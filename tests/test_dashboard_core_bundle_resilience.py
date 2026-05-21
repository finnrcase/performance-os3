from backend_new import db


def test_dashboard_core_bundle_fails_open_when_core_tables_are_missing(monkeypatch):
    monkeypatch.setattr(db, "database_url", lambda: "postgresql://example")
    monkeypatch.setattr(db, "existing_tables", lambda tables: set())
    monkeypatch.setattr(db, "cursor", lambda **kwargs: (_ for _ in ()).throw(AssertionError("missing tables must not be queried")))

    payload = db.fetch_dashboard_core_bundle("2026-05-21")

    assert payload["status"] == "ok"
    assert payload["food_rows"] == []
    assert payload["body_rows"] == []
    assert payload["recovery_rows"] == []
    assert payload["sleep_rows"] == []
    assert payload["counts"] == {"nutrition": 0, "body_metrics": 0, "training": 0, "recovery": 0, "sleep": 0}
    assert payload["warnings"]
    assert {warning["status"] for warning in payload["warnings"]} == {"warning"}
