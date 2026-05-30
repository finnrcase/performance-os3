from src.google_health_dashboard import build_google_health_dashboard_signals, merge_google_health_rows


def test_google_health_dashboard_flags_sickness_without_diagnosis():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {"date": "2026-05-24", "resting_hr": 55, "hrv": 70},
            {"date": "2026-05-25", "resting_hr": 55, "hrv": 70},
            {"date": "2026-05-26", "resting_hr": 55, "hrv": 70},
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": 5.8,
                "sleep_efficiency": 76,
                "resting_hr": 63,
                "resting_hr_baseline": 55,
                "hrv": 55,
                "spo2": 93,
                "active_minutes": 25,
            },
        ],
        recovery_rows=[{"date": "2026-05-27", "fatigue": 8, "sleep_quality": 4}],
        training_rows=[],
        nutrition_today={"calories": 2400},
        targets={"target_calories": 2700},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "ok"
    assert result["sickness_warning"]["status"] == "warning"
    assert "Possible sickness" in result["sickness_warning"]["label"]
    assert result["sickness_warning"]["disclaimer"] == "This is not a diagnosis."
    assert result["recovery_readiness"]["status"] == "learning_baseline"
    assert result["recovery_readiness"]["label"] == "Learning"
    assert result["recovery_readiness"]["provisional_score"] < 60


def test_google_health_calories_are_context_until_bodyweight_confirms():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": 7.5,
                "resting_hr": 55,
                "total_calories_burned": 2637,
                "active_minutes": 55,
            }
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2850},
        body_rows=[{"date": "2026-05-27", "bodyweight": 180}],
        today="2026-05-27",
    )

    assert result["calories_burned_vs_intake"]["status"] == "likely_near_maintenance"
    assert result["suggested_calorie_adjustment"]["adjustment"] == 0
    assert result["suggested_calorie_adjustment"]["confidence"] == "low"
    assert "bodyweight trend" in result["suggested_calorie_adjustment"]["message"]


def test_google_health_calorie_adjustment_waits_for_trend_confirmation():
    body_rows = [
        {"date": f"2026-05-{20 + index:02d}", "bodyweight": 180 - index * 0.15}
        for index in range(8)
    ]
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": 7.5,
                "resting_hr": 55,
                "total_calories_burned": 2900,
                "active_minutes": 75,
            }
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2500},
        targets={"target_calories": 2800},
        body_rows=body_rows,
        today="2026-05-27",
    )

    assert result["suggested_calorie_adjustment"]["confidence"] == "medium"
    assert result["suggested_calorie_adjustment"]["adjustment"] == 100


def test_google_health_missing_data_is_safe_empty_state():
    result = build_google_health_dashboard_signals(
        wearable_rows=[],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "insufficient_data"
    assert result["reason"] == "no_wearable_data_connected"
    assert "No wearable data connected" in result["message"]


def test_google_health_partial_malformed_values_do_not_produce_nan():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": {"bad": "shape"},
                "resting_hr": "nan",
                "total_calories_burned": "",
                "active_minutes": [],
            }
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": None},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "ok"
    assert result["sleep_quality"]["status"] == "insufficient_data"
    assert result["resting_hr_vs_baseline"]["status"] == "insufficient_data"
    assert result["calories_burned_vs_intake"]["status"] == "insufficient_data"
    assert result["debug"]["partial_data"] is True


def test_google_health_missing_heart_signals_lower_confidence_without_penalty():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": 8,
                "total_calories_burned": 2600,
                "active_minutes": 35,
                "steps": 8000,
            }
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "ok"
    assert result["resting_hr_vs_baseline"]["status"] == "insufficient_data"
    assert result["hrv"]["status"] == "insufficient_data"
    assert result["recovery_readiness"]["score"] is None
    assert result["recovery_readiness"]["provisional_score"] == 100
    assert result["recovery_readiness"]["label"] == "Learning"
    assert result["recovery_readiness"]["confidence"] == "learning"
    assert result["recovery_readiness"]["missing_heart_signals"] is True


def test_google_health_first_week_shows_learning_with_same_night_sleep_score():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-26",
                "source": "google_health",
                "sleep_hours": 7.1,
                "sleep_efficiency": 88,
                "rem_sleep_minutes": 82,
                "deep_sleep_minutes": 65,
                "resting_hr": 57,
                "hrv": 52,
                "steps": 8200,
            },
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": 7.8,
                "sleep_efficiency": 91,
                "rem_sleep_minutes": 96,
                "deep_sleep_minutes": 74,
                "awake_minutes": 28,
                "resting_hr": 56,
                "hrv": 55,
                "steps": 8700,
                "active_minutes": 48,
            },
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "ok"
    assert result["sleep_quality"]["score"] is not None
    assert result["sleep_quality"]["status"] == "early_data"
    assert result["sleep_quality"]["provisional"] is True
    assert result["sleep_quality"]["needed_nights"] == 5
    assert result["recovery_readiness"]["score"] is None
    assert result["recovery_readiness"]["provisional_score"] is not None
    assert result["recovery_readiness"]["label"] == "Learning"
    assert result["resting_hr_vs_baseline"]["baseline_label"] == "Learning baseline"
    assert result["hrv"]["baseline_label"] == "Learning baseline"


def test_google_health_readiness_merges_same_day_metric_rows():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "metric_id": "google_health:2026-05-27",
                "sleep_hours": 8,
                "total_sleep_minutes": 480,
                "sleep_efficiency": 92,
            },
            {
                "date": "2026-05-27",
                "source": "google_health",
                "metric_id": "google_health:2026-05-27-heart",
                "resting_hr": 62,
                "resting_hr_baseline": 55,
                "hrv": 35,
                "breathing_rate": 16,
                "spo2": 98,
            },
            {
                "date": "2026-05-27",
                "source": "google_health",
                "metric_id": "google_health:2026-05-27-activity",
                "steps": 9200,
                "active_minutes": 60,
                "active_zone_minutes": 20,
            },
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "ok"
    assert result["sleep_quality"]["duration_hours"] == 8
    assert result["resting_hr_vs_baseline"]["status"] == "early_data"
    assert result["resting_hr_vs_baseline"]["baseline_label"] == "Learning baseline"
    assert result["activity_load"]["steps"] == 9200
    assert result["recovery_readiness"]["missing_heart_signals"] is False
    assert result["debug"]["fields_used"]["active_zone_minutes"] == 20


def test_google_health_zero_sensor_values_are_unavailable_not_real_metrics():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "sleep_hours": 0,
                "total_sleep_minutes": 0,
                "rem_sleep_minutes": 0,
                "deep_sleep_minutes": 0,
                "resting_hr": 0,
                "resting_hr_baseline": 0,
                "hrv": 0,
                "steps": 0,
                "active_minutes": 0,
                "active_zone_minutes": 0,
                "total_calories_burned": 0,
            }
        ],
        recovery_rows=[],
        training_rows=[{"date": "2026-05-27", "sets": 40, "rpe": 8, "duration_minutes": 300}],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "insufficient_data"
    assert result["reason"] == "connected_no_wearable_metrics"
    assert result["message"] == "Connected, but no wearable metrics are available yet."
    assert result["debug"]["placeholder_rows_ignored"] == 1


def test_google_health_dashboard_treats_out_of_range_hr_as_insufficient_clean_data():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "resting_hr": 0,
                "resting_hr_baseline": 250,
                "average_hr": 29,
                "max_hr": 221,
                "steps": 8000,
                "active_minutes": 45,
            }
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "ok"
    assert result["resting_hr_vs_baseline"]["status"] == "insufficient_data"
    assert result["resting_hr_vs_baseline"]["message"] == "insufficient clean HR data"
    assert result["recovery_readiness"]["missing_heart_signals"] is True
    assert result["debug"]["clean_hr_diagnostics"]["invalid_hr_samples_dropped"] == 3
    assert "resting_hr" in result["debug"]["missing_fields"]


def test_google_health_dashboard_merges_split_google_health_tables():
    merged = merge_google_health_rows(
        wearable_rows=[{"date": "2026-05-27", "source": "google_health", "metric_id": "google_health:2026-05-27"}],
        sleep_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "total_sleep_time": 7.5,
                "total_sleep_minutes": 450,
                "rem_sleep_minutes": 90,
                "deep_sleep_minutes": 70,
                "sleep_efficiency": 88,
            }
        ],
        activity_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "steps": 9200,
                "active_minutes": 52,
                "active_zone_minutes": 18,
                "total_calories_burned": 2637,
            }
        ],
        heart_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "resting_hr": 54,
            }
        ],
    )
    result = build_google_health_dashboard_signals(
        wearable_rows=merged,
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["sleep_quality"]["duration_hours"] == 7.5
    assert result["sleep_quality"]["rem_minutes"] == 90
    assert result["activity_load"]["steps"] == 9200
    assert result["calories_burned_vs_intake"]["calories_burned"] == 2637
    assert result["resting_hr_vs_baseline"]["resting_hr"] == 54
    assert "google_health_sleep" in result["debug"]["source_tables"]
    assert result["debug"]["fields_used"]["total_calories_burned"] == 2637


def test_google_health_dashboard_ignores_empty_placeholder_rows():
    result = build_google_health_dashboard_signals(
        wearable_rows=[
            {
                "date": "2026-05-27",
                "source": "google_health",
                "metric_id": "google_health:2026-05-27",
                "sleep_hours": None,
                "steps": None,
                "calories_burned": None,
                "resting_hr": None,
                "hrv": None,
            }
        ],
        recovery_rows=[],
        training_rows=[],
        nutrition_today={"calories": 2600},
        targets={"target_calories": 2800},
        body_rows=[],
        today="2026-05-27",
    )

    assert result["status"] == "insufficient_data"
    assert result["reason"] == "connected_no_wearable_metrics"
    assert result["message"] == "Connected, but no wearable metrics are available yet."
    assert result["debug"]["placeholder_rows_ignored"] == 1
