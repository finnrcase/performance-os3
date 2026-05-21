from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_new.main import app


client = TestClient(app)


def test_strava_auth_url_uses_required_scope_and_redirect_uri():
    with patch.dict(
        "os.environ",
        {
            "STRAVA_CLIENT_ID": "client-id",
            "STRAVA_CLIENT_SECRET": "client-secret",
            "STRAVA_REDIRECT_URI": "https://api.example.com/api/strava/callback",
        },
        clear=False,
    ), patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {}, "metadata": {}}):
        response = client.get("/api/integrations/strava/auth-url")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["scope"] == "read,activity:read_all"
    parsed = urlparse(payload["auth_url"])
    query = parse_qs(parsed.query)
    assert parsed.netloc == "www.strava.com"
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://api.example.com/api/strava/callback"]
    assert query["scope"] == ["read,activity:read_all"]


def test_strava_debug_reports_disconnected_without_exposing_credentials():
    with patch.dict(
        "os.environ",
        {
            "STRAVA_CLIENT_ID": "client-id",
            "STRAVA_CLIENT_SECRET": "client-secret",
            "STRAVA_REDIRECT_URI": "https://api.example.com/api/strava/callback",
            "STRAVA_ACCESS_TOKEN": "",
            "STRAVA_REFRESH_TOKEN": "",
        },
        clear=False,
    ), patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {}, "metadata": {}}):
        response = client.get("/api/debug/strava")

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id_configured"] is True
    assert payload["client_secret_configured"] is True
    assert payload["redirect_uri_configured"] is True
    assert payload["access_token_present"] is False
    assert payload["refresh_token_present"] is False
    assert payload["status"] == "disconnected"
    assert payload["next_action"] == "connect_strava"
    assert "client-secret" not in str(payload)


def test_strava_auth_url_can_use_saved_redirect_uri():
    stored = {
        "integrations": {
            "strava_client_id": "saved-client-id",
            "strava_client_secret": "saved-client-secret",
            "strava_redirect_uri": "https://saved.example.com/api/strava/callback",
        },
        "metadata": {},
    }
    with (
        patch.dict("os.environ", {"STRAVA_CLIENT_ID": "", "STRAVA_CLIENT_SECRET": "", "STRAVA_REDIRECT_URI": ""}, clear=False),
        patch("backend_new.routes.integrations.fetch_latest_document", return_value=stored),
    ):
        response = client.get("/api/integrations/strava/auth-url")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["redirect_uri"] == "https://saved.example.com/api/strava/callback"
    assert parse_qs(urlparse(payload["auth_url"]).query)["redirect_uri"] == ["https://saved.example.com/api/strava/callback"]


def test_strava_callback_exchanges_code_and_redirects_to_frontend():
    with patch("src.integrations.strava_client.exchange_strava_code", return_value={"status": "Connected", "athlete_id": "42"}) as exchange:
        response = client.get("/api/strava/callback?code=abc123", follow_redirects=False)

    assert response.status_code == 303
    assert "strava=connected" in response.headers["location"]
    exchange.assert_called_once_with("abc123")


def test_manual_strava_import_returns_counts_and_refreshes_summary_cache():
    result = {
        "imported_runs": 1,
        "updated_runs": 2,
        "skipped_duplicates": 2,
        "fetched_activities": 3,
        "latest_activity_date": "2026-05-20",
        "last_synced_at": "2026-05-20T12:00:00+00:00",
        "training_log": [1, 2, 3],
    }
    with (
        patch("src.integrations.strava_client.import_recent_runs", return_value=result) as importer,
        patch("backend_new.routes.training.load_recent_training_summary", return_value={"status": "ok"}) as cache,
    ):
        response = client.post("/api/training/import/strava", json={"per_page": 30})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["imported_runs"] == 1
    assert payload["updated_runs"] == 2
    assert payload["fetched_activities"] == 3
    assert payload["training_log_rows"] == 3
    importer.assert_called_once_with(per_page=30)
    cache.assert_called_once_with(force_refresh=True)


def test_manual_strava_import_returns_reconnect_required_cleanly():
    from src.integrations.strava_client import StravaReconnectRequired

    with patch("src.integrations.strava_client.import_recent_runs", side_effect=StravaReconnectRequired("Reconnect Strava.")):
        response = client.post("/api/training/import/strava", json={"per_page": 30})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "reconnect_required"
    assert payload["reconnect_required"] is True
    assert payload["imported_runs"] == 0
