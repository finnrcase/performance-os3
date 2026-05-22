from backend_new.routes import body_metrics, dashboard, goals, nutrition, recovery, training


def test_dashboard_core_uses_tab_source_payloads(monkeypatch):
    today = "2026-05-21"
    requested_food_dates: list[str | None] = []

    monkeypatch.setattr(dashboard, "_today_iso", lambda: today)
    monkeypatch.setattr(
        dashboard,
        "fetch_dashboard_core_bundle",
        lambda *args, **kwargs: {
            "status": "ok",
            "food_rows": [{"date": today, "calories": 9999}],
            "body_rows": [{"date": today, "bodyweight": 999}],
            "recovery_rows": [],
            "sleep_rows": [],
            "training_summary": {"items": []},
            "targets": {"target_calories": 9999},
            "goals": {},
            "counts": {},
            "blocks": [],
            "warnings": [],
            "cache": {"status": "hit", "created_at": "2026-05-21T00:00:00+00:00", "ttl_seconds": 20},
            "duration_ms": 1,
        },
    )
    monkeypatch.setattr(
        nutrition,
        "get_nutrition_today",
        lambda date=None: requested_food_dates.append(date) or {
            "status": "ok",
            "date": today,
            "items": [{"date": today, "food_name": "real food", "calories": 321, "protein": 30, "carbs": 40, "fat": 9}],
            "totals": {"calories": 321, "protein": 30, "carbs": 40, "fat": 9, "fiber": 3},
        },
    )
    monkeypatch.setattr(
        goals,
        "get_goals",
        lambda: {
            "status": "ok",
            "goals": {"current_bodyweight": 180, "goal_type": "Lean Bulk"},
            "targets": {"target_calories": 2500, "protein_grams": 180, "carb_grams": 300, "fat_grams": 70, "updated_at": "goals-live"},
        },
    )
    monkeypatch.setattr(
        body_metrics,
        "get_body_metrics",
        lambda limit=5000: {
            "status": "ok",
            "canonical_items": [{"date": today, "bodyweight": 181.2}],
            "raw_items": [{"date": today, "bodyweight": 181.2}, {"date": today, "bodyweight": 183.0}],
        },
    )
    monkeypatch.setattr(
        training,
        "training_history",
        lambda limit=25, days=180: {
            "status": "ok",
            "items": [
                {
                    "date": today,
                    "workout_id": "lift-1",
                    "workout_type": "Push day",
                    "classification": "lift",
                    "exercise_names": ["Bench Press"],
                    "total_sets": 6,
                    "total_volume": 7200,
                    "duration_minutes": 55,
                    "source": "hevy",
                    "details": [],
                }
            ],
            "limit": limit,
            "days": days,
            "debug": {"raw_rows_read": 6, "read_limit": 1000, "duration_ms": 12},
        },
    )
    monkeypatch.setattr(recovery, "get_recovery_logs", lambda limit=500: {"status": "ok", "items": []})
    monkeypatch.setattr(recovery, "get_sleep_entries", lambda limit=500: {"status": "ok", "items": []})

    payload = dashboard.dashboard_core(date=today)

    assert payload["ok"] is True
    assert requested_food_dates == [today]
    assert payload["date"] == today
    assert payload["debug"]["dashboard_date_used"] == today
    assert payload["debug"]["app_local_date"] == today
    assert payload["nutrition_today"]["calories"] == 321
    assert payload["food"]["calories"]["target"] == 2500
    assert payload["latest_workout"]["workout_type"] == "Push day"
    assert payload["weight"]["latest_weight"] == 181.2
    assert payload["debug"]["sources"]["food"]["source"] == "/api/nutrition/today"
    assert payload["debug"]["sources"]["training"]["latest_workout_title"] == "Push day"
    assert payload["debug"]["sources"]["weight"]["raw_rows"] == 2
    assert payload["cache"]["source_versions"]["goals"] == "goals-live"
