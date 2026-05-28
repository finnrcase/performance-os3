from backend_new.routes.integrations import _google_health_status


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
