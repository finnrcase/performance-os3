from fastapi.testclient import TestClient

from backend_new.main import app
from backend_new.routes import nutrition


def test_nutrition_logs_defaults_to_recent_bounded_query(monkeypatch):
    calls = {}
    nutrition._invalidate_nutrition_logs_cache()

    monkeypatch.setattr(
        nutrition,
        "ensure_jsonb_performance_indexes",
        lambda table: {"status": "ok", "table": table, "cached": True},
    )

    def fake_fetch(table, *, limit, date_field=None, since_date=None):
        calls["fetch"] = {
            "table": table,
            "limit": limit,
            "date_field": date_field,
            "since_date": since_date,
        }
        return [{"food_log_id": "one", "date": "2026-05-20"}]

    monkeypatch.setattr(nutrition, "fetch_json_rows", fake_fetch)

    response = TestClient(app).get("/api/nutrition/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["items"][0]["food_log_id"] == "one"
    assert payload["meta"]["mode"] == "recent"
    assert payload["meta"]["limit"] == 300
    assert calls["fetch"]["table"] == "food_logs"
    assert calls["fetch"]["date_field"] == "date"
    assert calls["fetch"]["limit"] == 300
    assert calls["fetch"]["since_date"]


def test_nutrition_logs_date_query_uses_exact_date(monkeypatch):
    calls = {}
    nutrition._invalidate_nutrition_logs_cache()

    monkeypatch.setattr(
        nutrition,
        "ensure_jsonb_performance_indexes",
        lambda table: {"status": "ok", "table": table, "cached": True},
    )

    def fake_fetch_for_value(table, field, value, *, limit):
        calls["fetch"] = {
            "table": table,
            "field": field,
            "value": value,
            "limit": limit,
        }
        return []

    monkeypatch.setattr(nutrition, "fetch_json_rows_for_value", fake_fetch_for_value)

    response = TestClient(app).get("/api/nutrition/logs?date=2026-05-20&limit=50")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["meta"]["mode"] == "date"
    assert payload["meta"]["date"] == "2026-05-20"
    assert calls["fetch"] == {
        "table": "food_logs",
        "field": "date",
        "value": "2026-05-20",
        "limit": 50,
    }


def test_nutrition_reorder_updates_food_and_marker_sequences(monkeypatch):
    nutrition._invalidate_nutrition_logs_cache()
    food_rows = {
        "food-1": {"food_log_id": "food-1", "date": "2026-05-28", "food_name": "Oats", "calories": 300, "logged_sequence": 1, "created_order": 1},
        "food-2": {"food_log_id": "food-2", "date": "2026-05-28", "food_name": "Shake", "calories": 220, "logged_sequence": 3, "created_order": 3},
    }
    marker_rows = {
        "marker-1": {"marker_id": "marker-1", "date": "2026-05-28", "workout_type": "Strength", "marker_sequence": 2, "created_order": 2},
    }
    updates = []

    def fake_fetch_for_value(table, field, value, *, limit):
        if table == "food_logs" and field == "food_log_id":
            return [food_rows[value]] if value in food_rows else []
        if table == "workout_markers" and field == "marker_id":
            return [marker_rows[value]] if value in marker_rows else []
        if table == "food_logs" and field == "date":
            return [row for row in food_rows.values() if row["date"] == value]
        if table == "workout_markers" and field == "date":
            return [row for row in marker_rows.values() if row["date"] == value]
        return []

    def fake_fetch_rows(table, *, limit, date_field=None, since_date=None):
        if table == "workout_markers":
            return list(marker_rows.values())
        return []

    def fake_upsert(table, key_field, key_value, data):
        updates.append((table, key_field, key_value, data.copy()))
        if table == "food_logs":
            food_rows[key_value] = data.copy()
        if table == "workout_markers":
            marker_rows[key_value] = data.copy()
        return data

    monkeypatch.setattr(nutrition, "fetch_json_rows_for_value", fake_fetch_for_value)
    monkeypatch.setattr(nutrition, "fetch_json_rows", fake_fetch_rows)
    monkeypatch.setattr(nutrition, "ensure_jsonb_table", lambda table: None)
    monkeypatch.setattr(nutrition, "upsert_json_row", fake_upsert)

    response = TestClient(app).patch(
        "/api/nutrition/reorder",
        json={
            "date": "2026-05-28",
            "ordered_items": [
                {"type": "food", "id": "food-2", "sequence": 1},
                {"type": "workout_marker", "id": "marker-1", "sequence": 2},
                {"type": "food", "id": "food-1", "sequence": 3},
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["food_updates"] == 2
    assert payload["marker_updates"] == 1
    assert food_rows["food-2"]["logged_sequence"] == 1
    assert marker_rows["marker-1"]["marker_sequence"] == 2
    assert food_rows["food-1"]["logged_sequence"] == 3
    assert len(updates) == 3


def test_nutrition_logs_returns_structured_error_without_raw_db_row(monkeypatch):
    nutrition._invalidate_nutrition_logs_cache()
    monkeypatch.setattr(
        nutrition,
        "ensure_jsonb_performance_indexes",
        lambda table: {"status": "ok", "table": table, "cached": True},
    )
    monkeypatch.setattr(
        nutrition,
        "fetch_json_rows",
        lambda *args, **kwargs: [{"_db_error": {"error_type": "QueryCanceled", "message": "statement timeout"}}],
    )

    response = TestClient(app).get("/api/nutrition/logs")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["items"] == []
    assert payload["error"]["error_type"] == "QueryCanceled"


def test_nutrition_logs_uses_short_memory_cache(monkeypatch):
    nutrition._invalidate_nutrition_logs_cache()
    calls = {"fetch": 0}

    monkeypatch.setattr(
        nutrition,
        "ensure_jsonb_performance_indexes",
        lambda table: {"status": "ok", "table": table, "cached": True},
    )

    def fake_fetch(*args, **kwargs):
        calls["fetch"] += 1
        return [{"food_log_id": "cached", "date": "2026-05-20"}]

    monkeypatch.setattr(nutrition, "fetch_json_rows", fake_fetch)

    client = TestClient(app)
    first = client.get("/api/nutrition/logs?days=90&limit=300").json()
    second = client.get("/api/nutrition/logs?days=90&limit=300").json()

    assert calls["fetch"] == 1
    assert first["meta"]["cache_hit"] is False
    assert second["meta"]["cache_hit"] is True
    assert second["items"][0]["food_log_id"] == "cached"
