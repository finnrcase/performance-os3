from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_new.main import app
from backend_new.routes.integrations import GOOGLE_HEALTH_EXPECTED_CALLBACK_URL, _google_health_access_token, _google_health_status


client = TestClient(app)


def test_google_health_status_connected_with_saved_refresh_token(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", "https://api.example.com/api/google-health/callback")

    status, metadata = _google_health_status(
        {
            "metadata": {
                "google_health_tokens": {
                    "access_token": "present",
                    "refresh_token": "present",
                    "expires_at": 1,
                    "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
                },
                "google_health_sync": {
                    "last_status": "ok",
                    "last_warning": "Optional heart rate summary unavailable from Google Health.",
                    "rows_saved": 14,
                    "optional_metric_warnings": ["Optional heart rate summary unavailable from Google Health."],
                    "required_metric_failures": [],
                },
            }
        }
    )

    assert status == "Connected"
    assert metadata["token_status"] == "valid"
    assert metadata["access_token_present"] is True
    assert metadata["refresh_token_present"] is True
    assert metadata["token_storage_source"] == "api_connections.latest.metadata.google_health_tokens"
    assert metadata["provider"] == "google_health"
    assert metadata["google_health_api_sync_available"] is True
    assert metadata["google_health_api_sync_label"] == "Google Health API sync available"
    assert metadata["google_fit_legacy_data_source_status"] == "not_found"
    assert metadata["last_status"] == "ok"
    assert metadata["last_warning"] == "Optional heart rate summary unavailable from Google Health."
    assert metadata["rows_saved"] == 14
    assert metadata["optional_metric_warnings"] == ["Optional heart rate summary unavailable from Google Health."]
    assert metadata["required_metric_failures"] == []


def test_google_health_status_reads_historical_token_state(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", "https://api.example.com/api/google-health/callback")
    old_settings = {
        "metadata": {
            "google_health_tokens": {
                "access_token": "old_access",
                "refresh_token": "old_refresh",
                "expires_at": 9999999999,
                "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            },
            "google_health_sync": {"connected_at": "2026-05-28T01:02:03Z"},
        }
    }

    with patch("backend_new.routes.integrations.fetch_json_rows", return_value=[old_settings]):
        status, metadata = _google_health_status({"metadata": {"google_health_tokens": {}, "google_health_sync": {}}})

    assert status == "Connected"
    assert metadata["access_token_present"] is True
    assert metadata["refresh_token_present"] is True
    assert metadata["token_storage_source"] == "api_connections.history[0].metadata.google_health_tokens"
    assert metadata["connected_at"] == "2026-05-28T01:02:03Z"


def test_google_health_access_token_migrates_historical_token_state(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", "https://api.example.com/api/google-health/callback")
    old_settings = {
        "metadata": {
            "google_health_tokens": {
                "access_token": "old_access",
                "refresh_token": "old_refresh",
                "expires_at": 9999999999,
                "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            },
            "google_health_sync": {"connected_at": "2026-05-28T01:02:03Z"},
        }
    }

    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {}, "metadata": {"google_health_tokens": {}, "google_health_sync": {}}}),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=[old_settings]),
        patch("backend_new.routes.integrations._save_google_health_tokens") as save_tokens,
    ):
        token = _google_health_access_token()

    assert token == "old_access"
    save_tokens.assert_called_once()
    assert save_tokens.call_args.args[0]["refresh_token"] == "old_refresh"


def test_google_health_access_token_missing_token_message_is_recoverable(monkeypatch):
    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {}, "metadata": {"google_health_tokens": {}, "google_health_sync": {}}}),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=[]),
        patch("backend_new.routes.integrations._save_google_health_sync_state") as save_sync,
    ):
        try:
            _google_health_access_token()
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("Expected missing Google Health token to raise.")

    assert message == "Google Health token not found. Reconnect Google Health."
    save_sync.assert_called_once()
    assert save_sync.call_args.args[0]["needs_reconnect"] is True


def test_google_health_status_reconnect_required_after_failed_sync(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", "https://api.example.com/api/google-health/callback")

    status, metadata = _google_health_status(
        {
            "metadata": {
                "google_health_tokens": {
                    "access_token": "",
                    "refresh_token": "present",
                    "expires_at": 1,
                },
                "google_health_sync": {
                    "needs_reconnect": True,
                    "last_status": "error",
                    "last_error": "Google Health token refresh failed.",
                },
            }
        }
    )

    assert status == "Reconnect required"
    assert metadata["token_status"] == "reconnect_required"
    assert metadata["last_status"] == "error"
    assert metadata["last_error"] == "Google Health token refresh failed."


def test_google_health_debug_endpoint_sanitizes_oauth_config(monkeypatch):
    client_id = "958682873913-example.apps.googleusercontent.com"
    secret = "super-secret-value"
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", client_id)
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", secret)
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", GOOGLE_HEALTH_EXPECTED_CALLBACK_URL)

    with patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {}, "metadata": {}}):
        response = client.get("/api/debug/google-health")

    payload = response.json()
    serialized = str(payload)
    assert response.status_code == 200
    assert payload["provider"] == "google_health"
    assert payload["client_id"]["present"] is True
    assert payload["client_id"]["looks_like_google_oauth_client"] is True
    assert payload["redirect_matches_expected"] is True
    assert secret not in serialized
    assert client_id not in serialized
    assert payload["oauth_provider"]["generated_authorize_url_preview"]


def test_google_health_connection_debug_reports_token_source(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", "https://api.example.com/api/google-health/callback")
    settings = {
        "integrations": {},
        "metadata": {
            "google_health_tokens": {
                "access_token": "secret-access-token-value",
                "refresh_token": "secret-refresh-token-value",
                "expires_at": 9999999999,
                "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            },
            "google_health_sync": {"connected_at": "2026-05-28T01:02:03Z"},
        },
    }

    with patch("backend_new.routes.integrations.fetch_latest_document", return_value=settings):
        response = client.get("/api/debug/google-health/connection")

    payload = response.json()
    assert response.status_code == 200
    assert payload["connected"] is True
    assert payload["access_token_present"] is True
    assert payload["refresh_token_present"] is True
    assert payload["token_storage_source"] == "api_connections.latest.metadata.google_health_tokens"
    assert payload["last_connection_timestamp"] == "2026-05-28T01:02:03Z"
    assert "secret-access-token-value" not in str(payload)
    assert "secret-refresh-token-value" not in str(payload)


def test_google_health_ingestion_debug_reports_endpoint_counts(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "client")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", "https://api.example.com/api/google-health/callback")
    settings = {
        "integrations": {},
        "metadata": {
            "google_health_tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": 9999999999,
                "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            },
            "google_health_sync": {
                "api_request_counts": {"total": 1, "google_health": 1, "google_fit_legacy": 0},
                "exact_endpoint_urls": ["https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp"],
                "raw_health_responses": {"steps": {"status": "ok", "point_count": 1, "populated_point_count": 1, "endpoint": "dailyRollUp"}},
                "normalization_audit": {
                    "steps": {
                        "provider": "google_health",
                        "source": "google_health",
                        "api_family": "google_health",
                        "endpoint": "dailyRollUp",
                        "endpoint_url": "https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints:dailyRollUp",
                        "raw_datapoint_count": 1,
                        "raw_populated_datapoint_count": 1,
                        "normalized_field_count": 1,
                        "dropped_field_count": 0,
                        "dropped_datapoint_count": 0,
                        "raw_sample": {"steps": {"countSum": "7000"}},
                    }
                },
            },
        },
    }
    rows = [{"date": "2026-05-28", "source": "google_health", "steps": 7000, "populated_metric_count": 1}]

    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value=settings),
        patch("backend_new.routes.integrations.ensure_jsonb_table", return_value=None),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=rows),
    ):
        response = client.get("/api/debug/google-health/ingestion?live=false")

    payload = response.json()
    assert response.status_code == 200
    assert payload["requests_sent_to_google_health_api"] == 1
    assert payload["requests_sent_to_fitness_api"] == 0
    assert payload["endpoint_results"][0]["datapoint_count"] == 1
    assert payload["endpoint_results"][0]["normalized_field_count"] == 1
    assert payload["endpoint_results"][0]["dropped_field_count"] == 0
    assert payload["where_data_disappears"] == "verified_ingestion"


def test_google_health_sources_debug_reports_empty_source_state(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "958682873913-example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", GOOGLE_HEALTH_EXPECTED_CALLBACK_URL)
    settings = {
        "integrations": {},
        "metadata": {
                "google_health_tokens": {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at": 9999999999,
                    "scopes": "https://www.googleapis.com/auth/fitness.activity.read",
            },
            "google_health_sync": {
                "last_status": "no_data",
                "empty_date_rows_count": 14,
                "populated_metric_counts_by_day": {"2026-05-28": 0},
            },
        },
    }

    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value=settings),
        patch("backend_new.routes.integrations._google_health_access_token", return_value="access"),
        patch("src.integrations.google_health_client.fetch_identity", return_value={"status": "ok", "identity": {"name": "users/me/identity"}}),
        patch("src.integrations.google_health_client.list_data_sources", return_value={"status": "ok", "data_sources": [], "data_type_names": [], "available_data_types": [], "data_source_count": 0}),
    ):
        response = client.get("/api/debug/google-health/sources")

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "warning"
    assert payload["connected"] is False
    assert payload["connected_status"] == "Reconnect required"
    assert payload["data_source_count"] == 0
    assert "steps" in payload["available_data_types"]
    assert "deprecated Google Fit/Fitness scopes" in payload["recommended_next_action"]
    assert payload["api_path"] == "google_health_v4"
    assert payload["google_health_api_sync_available"] is False
    assert payload["google_fit_legacy_data_source_status"] == "found"


def test_google_health_raw_debug_groups_metric_counts(monkeypatch):
    settings = {
        "integrations": {},
        "metadata": {
            "google_health_tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": 9999999999,
                "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            },
            "google_health_sync": {
                "last_status": "ok",
                "latest_record": "2026-05-28",
                "raw_health_responses": {
                    "sleep": {"status": "ok", "point_count": 1, "populated_point_count": 1, "endpoint": "reconcile"},
                    "steps": {"status": "ok", "point_count": 1, "populated_point_count": 1, "endpoint": "dailyRollUp"},
                    "daily-heart-rate-variability": {"status": "ok", "point_count": 0, "populated_point_count": 0, "endpoint": "reconcile"},
                },
            },
        },
    }
    rows = [{"date": "2026-05-28", "source": "google_health", "sleep_hours": 7.5, "steps": 8123}]

    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value=settings),
        patch("backend_new.routes.integrations.ensure_jsonb_table", return_value=None),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=rows),
        patch("src.integrations.google_health_client.fetch_identity", return_value={"status": "ok", "identity": {"name": "users/me/identity"}}),
    ):
        response = client.get("/api/debug/google-health/raw")

    payload = response.json()
    assert response.status_code == 200
    assert payload["raw_response_counts_by_metric"]["sleep"]["point_count"] == 1
    assert payload["raw_response_counts_by_metric"]["steps"]["populated_point_count"] == 1
    assert payload["populated_fields_by_day"]["2026-05-28"]["fields_populated_count"] == 2
    assert payload["last_successful_populated_metric_date"] == "2026-05-28"


def test_wearables_provider_status_includes_google_diagnostic(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", "958682873913-example.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", GOOGLE_HEALTH_EXPECTED_CALLBACK_URL)
    settings = {
        "integrations": {},
        "metadata": {
            "google_health_tokens": {
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_at": 9999999999,
                "scopes": "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
            },
            "google_health_sync": {
                "last_status": "no_data",
                "empty_date_rows_count": 0,
                "raw_health_responses": {},
            },
        },
    }

    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value=settings),
        patch("backend_new.routes.integrations._google_health_access_token", return_value="access"),
        patch("backend_new.routes.integrations.ensure_jsonb_table", return_value=None),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=[]),
        patch("src.integrations.google_health_client.fetch_identity", return_value={"status": "ok", "identity": {"name": "users/me/identity"}}),
        patch("src.integrations.google_health_client.list_data_sources", return_value={"status": "ok", "data_sources": [], "data_type_names": [], "available_data_types": [], "data_source_count": 0}),
        patch("backend_new.routes.integrations._fitbit_debug_payload", return_value={"connection_status": "Disconnected", "connected": False, "oauth": {"token_status": "missing", "granted_scopes": []}, "sync": {}, "data_freshness": {}}),
    ):
        response = client.get("/api/debug/wearables/provider-status")

    payload = response.json()
    assert response.status_code == 200
    assert payload["providers"]["google_health"]["diagnostic"]["category"] == "no_backend_readable_sources"
    assert payload["normalized_contract"]["table"] == "wearable_metrics"
    assert payload["normalized_contract"]["dashboard_reads_provider_tables"] is False
    assert "apple_health_export" in payload["providers"]
    assert "withings" in payload["providers"]
    assert payload["diagnostic_matrix"]["C_no_backend_readable_sources"] is True


def test_google_health_client_id_leading_equals_is_normalized(monkeypatch):
    from src.integrations.google_health_client import get_auth_url

    client_id = "958682873913-example.apps.googleusercontent.com"
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_ID", f"={client_id}")
    monkeypatch.setenv("GOOGLE_HEALTH_CLIENT_SECRET", "=secret")
    monkeypatch.setenv("GOOGLE_HEALTH_REDIRECT_URI", GOOGLE_HEALTH_EXPECTED_CALLBACK_URL)

    result = get_auth_url({}, redirect_uri=GOOGLE_HEALTH_EXPECTED_CALLBACK_URL)

    assert result["status"] == "ok"
    assert "client_id=958682873913-example.apps.googleusercontent.com" in result["auth_url"]
    assert "client_id=%3D" not in result["auth_url"]
