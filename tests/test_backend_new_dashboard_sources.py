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


def test_workout_quality_uses_latest_lift_not_newer_run():
    items = [
        {
            "date": "2026-05-22",
            "workout_id": "run-1",
            "workout_type": "Easy Run",
            "classification": "run",
            "total_sets": 0,
            "total_reps": 0,
            "total_volume": 0,
            "duration_minutes": 32,
            "muscle_groups": ["Cardio"],
        },
        {
            "date": "2026-05-21",
            "workout_id": "lift-1",
            "workout_type": "Pull day",
            "classification": "lift",
            "classification_label": "Lift",
            "total_sets": 20,
            "total_reps": 268,
            "total_volume": 22055,
            "duration_minutes": 74,
            "muscle_groups": ["Back", "Biceps"],
        },
        {
            "date": "2026-05-14",
            "workout_id": "lift-0",
            "workout_type": "Pull day",
            "classification": "lift",
            "total_sets": 19,
            "total_reps": 240,
            "total_volume": 21400,
            "duration_minutes": 70,
            "muscle_groups": ["Back", "Biceps"],
        },
    ]

    payload = dashboard._workout_quality_payload(items)

    assert payload["status"] == "ok"
    assert payload["date"] == "2026-05-21"
    assert payload["workout_id"] == "lift-1"
    assert payload["classification"] == "lift"
    assert payload["rating"] == "Solid"
    assert payload["total_sets"] == 20
    assert payload["total_reps"] == 268
    assert payload["total_volume"] == 22055
    assert payload["duration_minutes"] == 74
    assert payload["muscle_groups"] == ["Back", "Biceps"]
    assert payload["comparison"]["sample_size"] == 1
    assert payload["debug"]["source"] == "/api/training/history"


def test_workout_quality_empty_when_no_lift_exists():
    payload = dashboard._workout_quality_payload(
        [
            {
                "date": "2026-05-22",
                "workout_id": "run-1",
                "workout_type": "Easy Run",
                "classification": "run",
            }
        ]
    )

    assert payload["status"] == "empty"
    assert payload["rating"] == "No recent lift"
    assert payload["summary"] == "No recent lifting workout found."
    assert payload["debug"]["latest_lift_found"] is False


def test_optimization_signals_use_real_recent_data(monkeypatch):
    monkeypatch.setattr(dashboard, "fetch_latest_document", lambda *args, **kwargs: {})
    nutrition_rows = [
        {
            "date": f"2026-05-{day:02d}",
            "nutrition_logged": True,
            "logged_day": True,
            "finalized": True,
            "status": "finalized",
            "total_calories": 2480,
            "total_protein": 182,
            "total_carbs": 295,
            "total_fat": 72,
            "target_calories": 2500,
            "target_protein": 180,
            "target_carbs": 300,
            "target_fat": 70,
        }
        for day in range(12, 22)
    ]
    training_items = [
        {
            "date": f"2026-05-{day:02d}",
            "workout_id": f"lift-{day}",
            "workout_type": "Push day",
            "classification": "lift",
            "total_sets": 16,
            "total_reps": 120,
            "total_volume": 18000 + day,
            "duration_minutes": 60,
        }
        for day in range(10, 22, 2)
    ]
    training_rows = [
        {
            "date": item["date"],
            "workout_id": item["workout_id"],
            "workout_type": item["workout_type"],
            "exercise": "Bench Press",
            "muscle_group": "Chest",
            "sets": 4,
            "reps": 8,
            "weight": 185 + index,
            "source": "hevy",
        }
        for index, item in enumerate(training_items)
    ]
    body_rows = [{"date": f"2026-05-{day:02d}", "bodyweight": 180 + (day - 1) * 0.03} for day in range(1, 22)]

    payload = dashboard._optimization_signals_payload(
        nutrition_history_items=nutrition_rows,
        training_items=training_items,
        training_rows=training_rows,
        body_rows=body_rows,
        recovery_rows=[],
        sleep_rows=[],
        goals={"goal_type": "Lean Bulk"},
        targets={"target_calories": 2500, "protein_grams": 180, "carb_grams": 300, "fat_grams": 70},
        today="2026-05-22",
    )

    assert payload["debug"]["engine_ran"] is False
    assert payload["macro_adherence"]["weekly_score"] > 90
    assert payload["macro_adherence"]["missing_days"] == 4
    assert payload["macro_adherence"]["status"] == "on-target"
    assert payload["nutrition_recommendation"]["decision"] in {"hold", "increase", "decrease"}
    assert "deferred" not in payload["nutrition_recommendation"]["primary_reason"].lower()
    assert payload["plateau_watch"]["status"] in {"clear", "possible plateau", "insufficient data"}
    assert payload["personal_baseline"]["dashboard_insight"]["title"] in {"Building baseline", "Baseline confidence improving", "Baseline confidence strong"}
