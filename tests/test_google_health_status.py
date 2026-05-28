from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_new.main import app
from backend_new.routes.integrations import GOOGLE_HEALTH_EXPECTED_CALLBACK_URL, _google_health_status


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
                },
                "google_health_sync": {
                    "last_status": "ok",
                    "last_warning": "Missing optional sleep metric.",
                },
            }
        }
    )

    assert status == "Connected"
    assert metadata["token_status"] == "valid"
    assert metadata["last_status"] == "ok"
    assert metadata["last_warning"] == "Missing optional sleep metric."


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
