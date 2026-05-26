from backend_new.routes import body_metrics, dashboard, goals, nutrition, recovery, training


def _detail(exercise: str, weight: float, reps: int, set_number: int, muscle_group: str = "Back") -> dict:
    return {
        "exercise": exercise,
        "muscle_group": muscle_group,
        "sets": 1,
        "reps": reps,
        "weight": weight,
        "set_number": set_number,
        "source": "hevy",
    }


def _lift_item(date: str, workout_id: str, title: str, details: list[dict], *, total_volume: float | None = None) -> dict:
    return {
        "date": date,
        "workout_id": workout_id,
        "workout_type": title,
        "classification": "lift",
        "classification_label": "Lift",
        "total_sets": sum(int(row.get("sets") or 0) for row in details),
        "total_reps": sum(int(row.get("sets") or 0) * int(row.get("reps") or 0) for row in details),
        "total_volume": total_volume if total_volume is not None else sum(float(row.get("sets") or 0) * float(row.get("reps") or 0) * float(row.get("weight") or 0) for row in details),
        "duration_minutes": 74,
        "muscle_groups": sorted({row.get("muscle_group") for row in details if row.get("muscle_group")}),
        "details": details,
    }


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


def test_dashboard_core_does_not_use_yesterday_workout_as_today(monkeypatch):
    today = "2026-05-22"
    yesterday = "2026-05-21"

    monkeypatch.setattr(dashboard, "_today_iso", lambda: today)
    monkeypatch.setattr(
        dashboard,
        "fetch_dashboard_core_bundle",
        lambda *args, **kwargs: {
            "status": "ok",
            "food_rows": [],
            "body_rows": [],
            "recovery_rows": [],
            "sleep_rows": [],
            "training_summary": {
                "latest_workout": _lift_item(yesterday, "bundle-yesterday", "Pull day", [_detail("Cable Row", 120, 8, 1)]),
                "items": [_lift_item(yesterday, "bundle-yesterday", "Pull day", [_detail("Cable Row", 120, 8, 1)])],
            },
            "targets": {"target_calories": 2500},
            "goals": {},
            "counts": {},
            "blocks": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(nutrition, "get_nutrition_today", lambda date=None: {"status": "ok", "date": today, "items": [], "totals": {}})
    monkeypatch.setattr(nutrition, "get_nutrition_history", lambda limit=30: {"status": "ok", "items": [], "adherence": {}})
    monkeypatch.setattr(
        goals,
        "get_goals",
        lambda: {
            "status": "ok",
            "goals": {"current_bodyweight": 180, "goal_type": "Lean Bulk"},
            "targets": {"target_calories": 2500, "protein_grams": 180, "carb_grams": 300, "fat_grams": 70},
        },
    )
    monkeypatch.setattr(body_metrics, "get_body_metrics", lambda limit=5000: {"status": "ok", "canonical_items": [], "raw_items": []})
    monkeypatch.setattr(
        training,
        "training_history",
        lambda limit=25, days=180: {
            "status": "ok",
            "items": [_lift_item(yesterday, "lift-yesterday", "Pull day", [_detail("Cable Row", 120, 8, 1)])],
            "limit": limit,
            "days": days,
            "debug": {},
        },
    )
    monkeypatch.setattr(recovery, "get_recovery_logs", lambda limit=500: {"status": "ok", "items": []})
    monkeypatch.setattr(recovery, "get_sleep_entries", lambda limit=500: {"status": "ok", "items": []})
    monkeypatch.setattr(dashboard, "fetch_latest_document", lambda *args, **kwargs: {})

    payload = dashboard.dashboard_core(date=today)

    assert payload["date"] == today
    assert payload["latest_workout"] is None
    assert payload["lift_performance"]["status"] == "Workout not logged yet"
    assert payload["lift_performance"]["summary"] == "Workout not logged yet"
    assert payload["workout_quality"]["status"] == "empty"
    assert payload["workout_quality"]["summary"] == "No workout logged for this date."


def test_workout_quality_uses_latest_lift_not_newer_run():
    latest_pull = [
        _detail("Lat Pulldown (Cable)", 110, 10, 1, "Back"),
        _detail("Lat Pulldown (Cable)", 110, 10, 2, "Back"),
        _detail("Cable Row", 125, 8, 1, "Back"),
    ]
    prior_pull = [
        _detail("Lat Pulldown (Cable)", 100, 10, 1, "Back"),
        _detail("Lat Pulldown (Cable)", 100, 10, 2, "Back"),
        _detail("Cable Row", 115, 8, 1, "Back"),
    ]
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
        _lift_item("2026-05-21", "lift-1", "Pull day", latest_pull),
        _lift_item("2026-05-14", "lift-0", "Pull day", prior_pull),
    ]

    payload = dashboard._workout_quality_payload(items)

    assert payload["status"] == "ok"
    assert payload["date"] == "2026-05-21"
    assert payload["workout_id"] == "lift-1"
    assert payload["classification"] == "lift"
    assert payload["rating"] in {"Strong", "Excellent"}
    assert payload["score"] >= 75
    assert payload["total_sets"] == 3
    assert payload["total_reps"] == 28
    assert payload["total_volume"] == 3200
    assert payload["duration_minutes"] == 74
    assert payload["muscle_groups"] == ["Back"]
    assert payload["comparison_basis"] == "last_7_similar_workouts"
    assert payload["similar_workouts_used"] == 1
    assert payload["comparison"]["sample_size"] == 1
    assert payload["exercise_breakdown"][0]["sets_compared"] > 0
    assert payload["debug"]["matched_by"] == "normalized_split"
    assert payload["debug"]["source"] == "/api/training/history"


def test_dashboard_workout_quality_does_not_use_previous_day_when_active_date_has_no_workout():
    yesterday_pull = [
        _detail("Lat Pulldown (Cable)", 110, 10, 1, "Back"),
        _detail("Cable Row", 125, 8, 1, "Back"),
    ]
    prior_pull = [
        _detail("Lat Pulldown (Cable)", 100, 10, 1, "Back"),
        _detail("Cable Row", 115, 8, 1, "Back"),
    ]
    items = [
        _lift_item("2026-05-21", "lift-yesterday", "Pull day", yesterday_pull),
        _lift_item("2026-05-14", "lift-prior", "Pull day", prior_pull),
    ]

    payload = dashboard._workout_quality_payload(items, active_date="2026-05-22")

    assert payload["status"] == "empty"
    assert payload["date"] == "2026-05-22"
    assert payload["score"] is None
    assert payload["rating"] == "No workout logged"
    assert payload["summary"] == "No workout logged for this date."
    assert payload["debug"]["matched_date_count"] == 0


def test_dashboard_workout_quality_uses_selected_date_workout():
    selected_pull = [
        _detail("Lat Pulldown (Cable)", 110, 10, 1, "Back"),
        _detail("Cable Row", 125, 8, 1, "Back"),
    ]
    prior_pull = [
        _detail("Lat Pulldown (Cable)", 100, 10, 1, "Back"),
        _detail("Cable Row", 115, 8, 1, "Back"),
    ]
    newer_push = [
        _detail("Bench Press", 225, 5, 1, "Chest"),
        _detail("Incline Press", 185, 8, 1, "Chest"),
    ]
    items = [
        _lift_item("2026-05-22", "lift-newer", "Push day", newer_push, total_volume=2600),
        _lift_item("2026-05-21", "lift-selected", "Pull day", selected_pull),
        _lift_item("2026-05-14", "lift-prior", "Pull day", prior_pull),
    ]

    payload = dashboard._workout_quality_payload(items, active_date="2026-05-21")

    assert payload["status"] == "ok"
    assert payload["date"] == "2026-05-21"
    assert payload["workout_id"] == "lift-selected"
    assert payload["title"] == "Pull day"
    assert payload["debug"]["matched_date_count"] == 1


def test_workout_quality_scores_set_progression_against_last_7_matching_split():
    latest = _lift_item(
        "2026-05-21",
        "pull-today",
        "Pull day",
        [
            _detail("Lat Pulldown (Cable)", 106, 10, 1, "Back"),
            _detail("Lat Pulldown (Cable)", 106, 10, 2, "Back"),
            _detail("Cable Row", 126, 8, 1, "Back"),
            _detail("Cable Row", 126, 8, 2, "Back"),
        ],
    )
    prior_dates = ["2026-05-14", "2026-05-07", "2026-04-30", "2026-04-23", "2026-04-16", "2026-04-09", "2026-04-02", "2026-03-26"]
    prior_pulls = [
        _lift_item(
            day,
            f"pull-{index}",
            "Pull day",
            [
                _detail("Lat Pulldown (Cable)", 100, 10, 1, "Back"),
                _detail("Lat Pulldown (Cable)", 100, 10, 2, "Back"),
                _detail("Cable Row", 120, 8, 1, "Back"),
                _detail("Cable Row", 120, 8, 2, "Back"),
                _detail("Deadlift", 315, 5, 1, "Back"),
            ],
        )
        for index, day in enumerate(prior_dates)
    ]
    items = [
        latest,
        _lift_item("2026-05-20", "push-nearby", "Push day", [_detail("Bench Press", 225, 5, 1, "Chest")]),
        *prior_pulls,
    ]

    payload = dashboard._workout_quality_payload(items)

    assert payload["similar_workouts_used"] == 7
    assert payload["debug"]["matched_by"] == "normalized_split"
    assert payload["debug"]["match_label"] == "pull"
    assert payload["score"] >= 75
    assert payload["rating"] in {"Strong", "Excellent"}
    assert "Average set volume +6%" in payload["summary"]
    assert payload["exercise_breakdown"][0]["avg_set_volume_pct_change"] > 0
    assert all(item["exercise"] != "Deadlift" for item in payload["exercise_breakdown"])


def test_workout_quality_keeps_quad_and_hamstring_leg_days_separate():
    latest_hamstring = _lift_item(
        "2026-05-22",
        "ham-today",
        "Legs",
        [
            _detail("Romanian Deadlift", 235, 8, 1, "Hamstrings"),
            _detail("Romanian Deadlift", 235, 8, 2, "Hamstrings"),
            _detail("Lying Leg Curl", 100, 12, 1, "Hamstrings"),
        ],
    )
    prior_hamstring = _lift_item(
        "2026-05-15",
        "ham-prior",
        "Legs",
        [
            _detail("Romanian Deadlift", 225, 8, 1, "Hamstrings"),
            _detail("Romanian Deadlift", 225, 8, 2, "Hamstrings"),
            _detail("Lying Leg Curl", 95, 12, 1, "Hamstrings"),
        ],
    )
    prior_quad = _lift_item(
        "2026-05-19",
        "quad-prior",
        "Legs",
        [
            _detail("Pendulum Squat", 270, 8, 1, "Quads"),
            _detail("Pendulum Squat", 270, 8, 2, "Quads"),
            _detail("Leg Extension", 130, 12, 1, "Quads"),
        ],
    )

    payload = dashboard._workout_quality_payload([latest_hamstring, prior_quad, prior_hamstring])

    assert payload["split_type"] == "leg_day_hamstring"
    assert payload["debug"]["split_type"] == "leg_day_hamstring"
    assert payload["debug"]["match_label"] == "leg_day_hamstring"
    assert payload["similar_workouts_used"] == 1
    assert "Hamstring leg workout" in payload["summary"]
    assert all(item["exercise"] in {"Romanian Deadlift", "Lying Leg Curl"} for item in payload["exercise_breakdown"])


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
