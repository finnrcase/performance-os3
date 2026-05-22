from backend_new.routes import training


def test_rebuild_summaries_writes_weekly_monthly_pr_and_muscle_caches(monkeypatch):
    written = []
    states = []

    monkeypatch.setattr(
        training,
        "_history_payload",
        lambda limit=200, days=365: {
            "items": [
                {
                    "date": "2026-05-20",
                    "workout_id": "push-1",
                    "workout_type": "Push",
                    "total_sets": 6,
                    "total_reps": 48,
                    "total_volume": 5400,
                    "duration_minutes": 55,
                    "muscle_groups": ["Chest", "Triceps"],
                    "details": [
                        {"exercise": "Bench Press", "muscle_group": "Chest", "sets": 3, "reps": 8, "weight": 185},
                        {"exercise": "Triceps Pushdown", "muscle_group": "Triceps", "sets": 3, "reps": 12, "weight": 70},
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(training, "upsert_json_row", lambda table, key_field, key_value, data: written.append((table, key_field, key_value, data)) or data)
    monkeypatch.setattr(training, "insert_json_row", lambda table, data: states.append((table, data)) or data)
    monkeypatch.setattr(training, "load_recent_training_summary", lambda force_refresh=False: {"status": "ok", "force_refresh": force_refresh})

    result = training.rebuild_summaries()

    tables = [item[0] for item in written]
    assert result["status"] == "ok"
    assert result["weekly_summaries"] == 1
    assert result["monthly_summaries"] == 1
    assert result["exercise_prs"] == 2
    assert result["muscle_group_periods"] == 4
    assert "weekly_training_summary" in tables
    assert "monthly_training_summary" in tables
    assert "exercise_prs" in tables
    assert "muscle_group_training_summary" in tables
    assert states[0][0] == "training_summary_state"
    assert result["core_training_summary"]["force_refresh"] is True
