from fastapi.testclient import TestClient

from backend_v2 import db
from backend_v2.main import app
from backend_v2.routes import dashboard_core, goals, nutrition, settings, training


def test_health_uses_v2_service_name(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "performance-os-api-v2",
        "storage": "postgres",
    }


def test_core_routes_return_frontend_safe_shapes(monkeypatch):
    monkeypatch.setattr(goals, "load_document", lambda key, default=None, timeout_ms=None: default or {})
    monkeypatch.setattr(nutrition, "load_document", lambda key, default=None, timeout_ms=None: default or {})
    monkeypatch.setattr(nutrition, "load_rows_for_date", lambda *args, **kwargs: [])
    monkeypatch.setattr(settings, "load_document", lambda key, default=None, timeout_ms=None: default or {})
    monkeypatch.setattr(training, "load_recent_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        dashboard_core,
        "load_dashboard_core_bundle",
        lambda **kwargs: {
            "goals": {},
            "targets": {},
            "nutrition_rows": [],
            "training_rows": [],
            "body_rows": [],
            "nutrition_rows_estimate": 0,
            "training_rows_estimate": 0,
            "body_metric_rows_estimate": 0,
        },
    )
    client = TestClient(app)

    assert client.get("/api/settings").status_code == 200
    assert client.get("/api/goals").json()["debug"]["status"] == "ok"
    assert client.get("/api/nutrition/today").json()["totals"]["calories"] == 0
    assert client.get("/api/training/history").json()["limit"] == 25

    payload = client.get("/api/dashboard/core").json()
    assert payload["ok"] is True
    assert payload["core_ready"] is True
    assert payload["debug"]["advanced_analytics_disabled"] is True
    assert payload["debug"]["background_workers"] is False


def test_db_statement_timeout_uses_set_config(monkeypatch):
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params=None):
            calls.append((" ".join(str(sql).split()), params))

    class FakeConnection:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

    monkeypatch.setattr(db, "_connect", lambda: FakeConnection())

    with db.cursor(timeout_ms=999999):
        pass

    assert calls == [("SELECT set_config('statement_timeout', %s, true)", ("120000ms",))]
    assert "SET LOCAL" not in calls[0][0]
