from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_new.main import app


client = TestClient(app)


def test_fitbit_debug_status_is_safe_without_tokens():
    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {}, "metadata": {}}),
        patch("backend_new.routes.integrations.ensure_jsonb_table", return_value={"status": "ok"}),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=[]),
    ):
        response = client.get("/api/debug/fitbit")

    payload = response.json()
    assert response.status_code == 200
    assert payload["provider"] == "fitbit"
    assert payload["oauth"]["token_status"] == "missing"
    assert payload["data_freshness"]["status"] == "red"
    assert "secret" not in str(payload)


def test_fitbit_force_sync_reports_missing_access_token_without_leaking_secret():
    saved_sync = {}

    def capture_sync_state(updates):
        saved_sync.update(updates)
        return updates

    with (
        patch("backend_new.routes.integrations.fetch_latest_document", return_value={"integrations": {"fitbit_client_id": "id", "fitbit_client_secret": "secret"}, "metadata": {}}),
        patch("backend_new.routes.integrations.ensure_jsonb_table", return_value={"status": "ok"}),
        patch("backend_new.routes.integrations.fetch_json_rows", return_value=[]),
        patch("backend_new.routes.integrations._save_fitbit_sync_state", side_effect=capture_sync_state),
    ):
        response = client.post("/api/debug/fitbit/sync", json={"days": 7})

    payload = response.json()
    assert response.status_code == 200
    assert payload["status"] == "error"
    assert saved_sync["last_pipeline"]["fetched"]["status"] == "failed"
    assert saved_sync["last_status"] == "error"
    assert "secret" not in str(payload)
