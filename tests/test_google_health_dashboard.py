from src.google_health_dashboard import build_google_health_dashboard_signals


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
    assert result["recovery_readiness"]["status"] == "red"


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
    assert result["recovery_readiness"]["score"] == 100
    assert result["recovery_readiness"]["confidence"] == "low"
    assert result["recovery_readiness"]["missing_heart_signals"] is True
