from backend_new.routes import training


def test_training_prs_missing_table_falls_back_without_crashing(monkeypatch):
    written = []

    monkeypatch.setattr(training, "count_rows", lambda table: {"status": "missing", "table": table, "count_estimate": 0})
    monkeypatch.setattr(training, "ensure_jsonb_table", lambda table: {"status": "ok", "table": table})
    monkeypatch.setattr(training, "upsert_json_row", lambda table, key_field, key_value, data: written.append((table, key_field, key_value, data)) or data)

    def fake_fetch(table, *, limit=500):
        if table == "exercise_prs":
            return [{"_db_error": {"message": "relation does not exist"}}]
        if table == "workout_logs":
            return [
                {"date": "2026-05-21", "exercise": "Bench Press", "weight": 185, "reps": 5, "source": "hevy", "workout_id": "push-1"},
                {"date": "2026-05-22", "exercise": "Bench Press", "weight": 195, "reps": 3, "source": "hevy", "workout_id": "push-2"},
                {"date": "2026-05-22", "exercise": "Running", "weight": 999, "reps": 1, "source": "strava", "workout_type": "Run"},
            ]
        return []

    monkeypatch.setattr(training, "fetch_latest_json_rows", fake_fetch)

    result = training.training_prs()

    assert result["status"] == "ok"
    assert result["source"] == "training_history_fallback"
    assert result["diagnostics"]["initial_table_status"] == "missing"
    assert result["diagnostics"]["skipped"]["cardio"] == 1
    assert result["items"] == [
        {
            "pr_id": "exercise-pr:bench-press",
            "exercise": "Bench Press",
            "weight": 195,
            "unit": "lb",
            "reps": 3,
            "estimated_1rm": 214.5,
            "date": "2026-05-22",
            "workout_id": "push-2",
            "workout_type": "",
            "source": "hevy",
            "record_source": "training_history_fallback",
            "updated_at": "",
        }
    ]
    assert written and written[0][0] == "exercise_prs"


def test_training_prs_uses_cached_table_with_diagnostics(monkeypatch):
    monkeypatch.setattr(training, "count_rows", lambda table: {"status": "ok", "table": table, "count_estimate": 1})
    monkeypatch.setattr(training, "ensure_jsonb_table", lambda table: {"status": "ok", "table": table})

    def fake_fetch(table, *, limit=500):
        assert table == "exercise_prs"
        return [
            {"pr_id": "exercise-pr:squat", "exercise": "Back Squat", "weight": 315, "reps": 2, "date": "2026-05-20", "source": "hevy"}
        ]

    monkeypatch.setattr(training, "fetch_latest_json_rows", fake_fetch)

    result = training.training_prs()

    assert result["status"] == "ok"
    assert result["source"] == "exercise_prs_table"
    assert result["diagnostics"]["source_reason"] == "exercise_prs table contained usable lifting PRs."
    assert result["items"][0]["exercise"] == "Back Squat"
