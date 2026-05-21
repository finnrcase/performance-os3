from fastapi.testclient import TestClient

from backend_new.main import app
from backend_new.routes import nutrition


def test_nutrition_history_exclude_marks_logs_and_summary(monkeypatch):
    updates = []

    def fake_update(table, field, value, patch):
        updates.append((table, field, value, patch))
        return {"status": "ok", "updated_rows": 3 if table == "food_logs" else 1}

    monkeypatch.setattr(nutrition, "update_json_rows_for_value", fake_update)
    monkeypatch.setattr(nutrition, "upsert_json_row", lambda *args, **kwargs: {"date": "2026-05-18"})

    response = TestClient(app).post("/api/nutrition/history/2026-05-18/exclude", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["date"] == "2026-05-18"
    assert payload["rule"] == "excluded_from_analytics"
    assert payload["updated_rows"] == 4
    assert updates[0][0] == "food_logs"
    assert updates[1][0] == "daily_nutrition_summary"
    assert updates[0][3]["excluded_from_analytics"] is True


def test_nutrition_history_filters_excluded_days(monkeypatch):
    def fake_fetch(table, *args, **kwargs):
        if table == "daily_nutrition_summary":
            return [
                {"date": "2026-05-18", "total_calories": 1000, "excluded_from_analytics": True},
                {"date": "2026-05-17", "total_calories": 2400, "finalized": True},
            ]
        if table == "food_logs":
            return [
                {"date": "2026-05-18", "food_name": "Incomplete", "calories": 1000, "excluded_from_analytics": True},
                {"date": "2026-05-16", "food_name": "Complete", "calories": 2200, "protein": 180, "carbs": 250, "fat": 70},
            ]
        return []

    monkeypatch.setattr(nutrition, "fetch_json_rows", fake_fetch)

    response = TestClient(app).get("/api/nutrition/history")

    assert response.status_code == 200
    dates = [item["date"] for item in response.json()["items"]]
    assert "2026-05-18" not in dates
    assert dates == ["2026-05-17", "2026-05-16"]
