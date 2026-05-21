from fastapi.testclient import TestClient

from backend_new.main import app
from backend_new.routes import training


def test_training_workout_date_move_updates_normalized_rows_and_cache(monkeypatch):
    calls = []

    def fake_move(table, workout_id, new_date, **kwargs):
        calls.append((table, workout_id, new_date, kwargs))
        if table == "workout_logs":
            return {
                "status": "ok",
                "table": table,
                "workout_id": workout_id,
                "old_date": "2026-05-16",
                "new_date": "2026-05-15",
                "updated_rows": 12,
            }
        return {
            "status": "ok",
            "table": table,
            "workout_id": workout_id,
            "old_date": "2026-05-16",
            "new_date": "2026-05-15",
            "updated_rows": 2,
        }

    monkeypatch.setattr(training, "move_workout_date_rows", fake_move)
    monkeypatch.setattr(training, "load_recent_training_summary", lambda force_refresh=False: {"status": "ok", "force_refresh": force_refresh})

    response = TestClient(app).post(
        "/api/training/workout-date",
        json={"workout_id": "hevy-123", "new_date": "2026-05-15"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["workout_id"] == "hevy-123"
    assert payload["old_date"] == "2026-05-16"
    assert payload["new_date"] == "2026-05-15"
    assert payload["updated_rows"] == 12
    assert payload["raw_updated_rows"] == 4
    assert payload["cache_summary"]["force_refresh"] is True
    assert calls[0] == ("workout_logs", "hevy-123", "2026-05-15", {"annotate_notes": True})
    assert calls[1][0] == "raw_hevy_workouts"
    assert calls[2][0] == "raw_hevy_sets"


def test_training_workout_date_move_returns_404_when_no_rows(monkeypatch):
    monkeypatch.setattr(
        training,
        "move_workout_date_rows",
        lambda *args, **kwargs: {"status": "ok", "old_date": "", "new_date": "2026-05-15", "updated_rows": 0},
    )

    response = TestClient(app).post(
        "/api/training/workout-date",
        json={"workout_id": "missing", "new_date": "2026-05-15"},
    )

    assert response.status_code == 404
    assert "No workout found" in response.json()["detail"]
