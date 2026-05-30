import pandas as pd

import src.wearables as wearables
from src.wearables import (
    WEARABLE_METRIC_COLUMNS,
    add_wearable_metric_entry,
    calculate_training_readiness_signals,
    calculate_wearable_recovery_signals,
    heart_rate_cleaning_summary,
    load_wearable_metrics,
    normalize_wearable_metric_rows,
    save_wearable_metrics,
)


def test_load_wearable_metrics_handles_missing_csv(monkeypatch, tmp_path):
    monkeypatch.setattr(wearables, "WEARABLE_METRICS_PATH", tmp_path / "missing.csv")

    loaded = load_wearable_metrics()

    assert loaded.empty
    assert loaded.columns.tolist() == WEARABLE_METRIC_COLUMNS


def test_add_wearable_metric_entry_creates_csv_and_normalizes(monkeypatch, tmp_path):
    path = tmp_path / "wearable_metrics.csv"
    monkeypatch.setattr(wearables, "WEARABLE_METRICS_PATH", path)

    updated = add_wearable_metric_entry(
        date="2026-05-24",
        source="mock",
        sleep_hours="7.5",
        sleep_score=84,
        resting_hr=58,
        hrv=62,
        steps=9500,
        active_minutes=72,
        calories_burned=2600,
        workout_minutes=45,
    )

    assert path.exists()
    assert len(updated) == 1
    assert updated.iloc[0]["source"] == "mock"
    assert updated.iloc[0]["sleep_hours"] == 7.5
    assert str(updated.iloc[0]["metric_id"]).strip()
    assert str(updated.iloc[0]["created_at"]).strip()
    assert str(updated.iloc[0]["updated_at"]).strip()


def test_save_wearable_metrics_handles_missing_columns(monkeypatch, tmp_path):
    path = tmp_path / "wearable_metrics.csv"
    monkeypatch.setattr(wearables, "WEARABLE_METRICS_PATH", path)

    save_wearable_metrics(pd.DataFrame([{"date": "2026-05-24", "steps": "1000"}]))
    loaded = load_wearable_metrics()

    assert loaded.columns.tolist() == WEARABLE_METRIC_COLUMNS
    assert len(loaded) == 1
    assert loaded.iloc[0]["steps"] == 1000
    assert loaded.iloc[0]["source"] == "manual"


def test_provider_agnostic_wearable_normalization_adds_provider_and_raw_payload():
    normalized = normalize_wearable_metric_rows(
        [
            {
                "date": "2026-05-24",
                "source": "apple_health_export",
                "sleep_hours": "7.2",
                "raw_payload": {"source_file": "export.xml", "record_count": 4},
            }
        ],
        source="apple_health_export",
        provider="apple_health_export",
    )

    row = normalized.iloc[0]
    assert row["provider"] == "apple_health_export"
    assert row["sleep_hours"] == 7.2
    assert row["populated_metric_count"] == 1
    assert row["placeholder"] is False
    assert row["raw_payload"] == '{"record_count":4,"source_file":"export.xml"}'


def test_wearable_normalization_nulls_invalid_heart_rate_values():
    normalized = normalize_wearable_metric_rows(
        [
            {
                "date": "2026-05-24",
                "source": "google_health",
                "resting_hr": 0,
                "average_hr": 29,
                "max_hr": 221,
                "workout_average_hr": 140,
                "workout_max_hr": 185,
                "resting_hr_baseline": 0,
                "resting_hr_deviation": 8,
                "hrv": 0,
                "steps": 9000,
            }
        ],
        source="google_health",
    )

    row = normalized.iloc[0]
    assert row["resting_hr"] is None
    assert row["average_hr"] is None
    assert row["max_hr"] is None
    assert row["resting_hr_baseline"] is None
    assert row["resting_hr_deviation"] is None
    assert row["hrv"] is None
    assert row["workout_average_hr"] == 140
    assert row["workout_max_hr"] == 185
    assert row["populated_metric_count"] == 3


def test_heart_rate_cleaning_summary_counts_raw_invalid_and_clean_samples():
    summary = heart_rate_cleaning_summary(
        [
            {"resting_hr": 0, "average_hr": 29, "max_hr": 221},
            {"resting_hr": 58, "average_hr": 90, "max_hr": 170},
        ]
    )

    assert summary["raw_hr_samples_received"] == 6
    assert summary["invalid_hr_samples_dropped"] == 3
    assert summary["clean_hr_samples_used"] == 3
    assert summary["invalid_hr_samples_dropped_by_field"] == {"resting_hr": 1, "average_hr": 1, "max_hr": 1}


def test_calculate_wearable_recovery_signals_empty_and_missing_columns():
    empty_signals = calculate_wearable_recovery_signals(pd.DataFrame())
    partial_signals = calculate_wearable_recovery_signals(
        pd.DataFrame([{"date": "2026-05-24", "sleep_hours": 6.5}])
    )

    assert empty_signals["status"] == "empty"
    assert empty_signals["sleep"]["trend"] == "insufficient_data"
    assert partial_signals["status"] == "ok"
    assert partial_signals["latest"]["sleep_hours"] == 6.5
    assert "source" in partial_signals["diagnostics"]["missing_columns"]


def test_invalid_hr_samples_do_not_skew_recovery_trends_or_readiness():
    rows = []
    for index in range(10):
        day = pd.Timestamp("2026-05-15") + pd.Timedelta(days=index)
        rows.append(
            {
                "metric_id": f"watch-off-{index}",
                "date": day.date().isoformat(),
                "source": "google_health",
                "sleep_hours": 7.5,
                "resting_hr": 0 if index >= 7 else 58,
                "average_hr": 0 if index >= 7 else 88,
                "max_hr": 0 if index >= 7 else 165,
                "steps": 8000,
                "active_minutes": 55,
            }
        )

    signals = calculate_wearable_recovery_signals(pd.DataFrame(rows))
    readiness = calculate_training_readiness_signals(pd.DataFrame(rows))

    assert signals["resting_hr"]["latest"] == 58
    assert signals["diagnostics"]["invalid_hr_samples_dropped"] == 9
    assert signals["diagnostics"]["clean_hr_samples_used"] == 21
    assert readiness["run_recommendation"]["label"] == "Run OK"
    assert not any("Resting HR is running above baseline" in signal for signal in readiness["signals"])


def test_calculate_wearable_recovery_signals_trends():
    rows = []
    for index in range(14):
        day = pd.Timestamp("2026-05-11") + pd.Timedelta(days=index)
        rows.append(
            {
                "metric_id": f"mock-{index}",
                "date": day.date().isoformat(),
                "source": "mock",
                "sleep_hours": 6.0 if index < 7 else 7.5,
                "resting_hr": 64 if index < 7 else 58,
                "hrv": 44 if index < 7 else 58,
                "steps": 5000 if index < 7 else 9000,
                "active_minutes": 35 if index < 7 else 70,
            }
        )

    signals = calculate_wearable_recovery_signals(pd.DataFrame(rows))

    assert signals["status"] == "ok"
    assert signals["sleep"]["rolling_7_day_average"] == 7.5
    assert signals["sleep"]["trend"] == "improving"
    assert signals["resting_hr"]["trend"] == "improving"
    assert signals["hrv"]["trend"] == "improving"
    assert signals["activity"]["trend"] == "improving"
    assert signals["diagnostics"]["valid_days"] == 14


def test_null_wearable_rows_do_not_become_zero_activity_or_calories():
    rows = [
        {
            "metric_id": f"google-empty-{index}",
            "date": (pd.Timestamp("2026-05-10") + pd.Timedelta(days=index)).date().isoformat(),
            "source": "google_health",
            "sleep_hours": None,
            "total_sleep_minutes": None,
            "steps": None,
            "active_minutes": None,
            "active_zone_minutes": None,
            "calories_burned": None,
            "total_calories_burned": None,
            "resting_hr": None,
            "hrv": None,
        }
        for index in range(4)
    ]

    signals = calculate_wearable_recovery_signals(pd.DataFrame(rows))
    readiness = calculate_training_readiness_signals(pd.DataFrame(rows))

    assert signals["activity"]["steps"]["latest"] is None
    assert signals["activity"]["calories_burned"]["latest"] is None
    assert signals["activity"]["activity_load"]["latest"] is None
    assert signals["status"] == "empty"
    assert signals["message"] == "Connected, but no wearable metrics are available yet."
    assert signals["diagnostics"]["placeholder_rows"] == 4
    assert signals["diagnostics"]["valid_days"] == 0
    assert readiness["status"] == "insufficient_data"
    assert readiness["message"] == "Connected, but no wearable metrics are available yet."
    assert readiness["run_recommendation"]["label"] == "Need more history"
    assert "Recent steps/activity are unusually high" not in readiness["signals"]


def test_empty_google_health_rows_do_not_create_run_ok_readiness():
    rows = [
        {
            "metric_id": f"google-empty-{index}",
            "date": (pd.Timestamp("2026-05-01") + pd.Timedelta(days=index)).date().isoformat(),
            "source": "google_health",
        }
        for index in range(14)
    ]

    readiness = calculate_training_readiness_signals(pd.DataFrame(rows))

    assert readiness["status"] == "insufficient_data"
    assert readiness["run_recommendation"]["label"] != "Run OK"
    assert readiness["diagnostics"]["placeholder_rows"] == 14
    assert readiness["diagnostics"]["valid_days"] == 0
    assert readiness["sickness_warning"]["status"] == "insufficient_data"


def test_training_readiness_needs_more_wearable_history():
    readiness = calculate_training_readiness_signals(pd.DataFrame())

    assert readiness["status"] == "insufficient_data"
    assert readiness["message"] == "Need more wearable history."
    assert readiness["run_recommendation"]["label"] == "Need more history"


def test_training_readiness_reduces_intensity_from_wearable_and_recovery_strain():
    wearable_rows = []
    for index in range(10):
        day = pd.Timestamp("2026-05-15") + pd.Timedelta(days=index)
        recent = index >= 7
        wearable_rows.append(
            {
                "metric_id": f"strain-{index}",
                "date": day.date().isoformat(),
                "source": "mock",
                "sleep_hours": 6.4 if recent else 7.4,
                "resting_hr": 70 if recent else 60,
                "hrv": 40 if recent else 60,
                "steps": 13000 if recent else 7000,
                "active_minutes": 95 if recent else 45,
                "calories_burned": 3300 if recent else 2600,
            }
        )
    training_rows = []
    for index in range(7):
        day = pd.Timestamp("2026-05-18") + pd.Timedelta(days=index)
        training_rows.append(
            {
                "date": day.date().isoformat(),
                "sets": 10,
                "reps": 10,
                "weight": 100,
                "rpe": 8,
                "duration_minutes": 55,
            }
        )
    recovery_rows = [
        {"date": "2026-05-19", "recovery_score": 86},
        {"date": "2026-05-20", "recovery_score": 83},
        {"date": "2026-05-21", "recovery_score": 80},
        {"date": "2026-05-22", "recovery_score": 70},
        {"date": "2026-05-23", "recovery_score": 66},
        {"date": "2026-05-24", "recovery_score": 62},
    ]
    nutrition_rows = [
        {"date": "2026-05-22", "carbs": 120, "protein": 170, "calories": 2300},
        {"date": "2026-05-23", "carbs": 130, "protein": 160, "calories": 2350},
        {"date": "2026-05-24", "carbs": 125, "protein": 165, "calories": 2400},
        {
            "date": "2026-05-24",
            "carbs": 20,
            "protein": 20,
            "calories": 220,
            "created_at": "2026-05-24T13:00:00",
        },
    ]
    markers = pd.DataFrame(
        [
            {
                "marker_id": "marker-1",
                "date": "2026-05-24",
                "workout_time": "12:00",
                "workout_type": "Strength",
                "notes": "",
                "created_at": "2026-05-24T12:00:00",
            }
        ]
    )

    readiness = calculate_training_readiness_signals(
        wearable_df=pd.DataFrame(wearable_rows),
        recovery_df=pd.DataFrame(recovery_rows),
        training_df=pd.DataFrame(training_rows),
        nutrition_df=pd.DataFrame(nutrition_rows),
        markers_df=markers,
    )

    assert readiness["status"] == "ok"
    assert readiness["run_recommendation"]["color"] == "Red"
    assert readiness["run_recommendation"]["label"] == "Skip run / recovery day"
    assert readiness["lift_recommendation"]["label"] == "Deload suggested"
    assert readiness["fueling_recommendation"]["label"] == "Increase carbs"
    assert readiness["hydration_recommendation"]["label"] == "Elevated hydration/electrolyte risk"
    assert any("Resting HR is elevated" in signal for signal in readiness["signals"])


def test_training_readiness_stays_green_with_stable_wearables():
    wearable_rows = []
    for index in range(10):
        day = pd.Timestamp("2026-05-15") + pd.Timedelta(days=index)
        wearable_rows.append(
            {
                "metric_id": f"stable-{index}",
                "date": day.date().isoformat(),
                "source": "mock",
                "sleep_hours": 7.8,
                "resting_hr": 58,
                "hrv": 62,
                "steps": 8500,
                "active_minutes": 55,
                "calories_burned": 2700,
            }
        )

    readiness = calculate_training_readiness_signals(
        wearable_df=pd.DataFrame(wearable_rows),
        recovery_df=pd.DataFrame(),
        training_df=pd.DataFrame(),
        nutrition_df=pd.DataFrame(),
        markers_df=pd.DataFrame(),
    )

    assert readiness["run_recommendation"]["color"] == "Green"
    assert readiness["run_recommendation"]["label"] == "Run OK"
    assert readiness["lift_recommendation"]["label"] == "Push normal"


def test_training_readiness_uses_rhr_deviation_and_recovery_health_signals():
    wearable_rows = []
    for index in range(7):
        day = pd.Timestamp("2026-05-10") + pd.Timedelta(days=index)
        wearable_rows.append(
            {
                "metric_id": f"baseline-{index}",
                "date": day.date().isoformat(),
                "source": "google_health",
                "sleep_hours": 7.5,
                "resting_hr": 55,
                "resting_hr_deviation": 0,
                "hrv": 60,
                "steps": 6500,
                "active_minutes": 40,
            }
        )
    wearable_rows.append(
        {
            "metric_id": "health-risk",
            "date": "2026-05-17",
            "source": "google_health",
            "sleep_hours": 6.2,
            "resting_hr": 62,
            "resting_hr_deviation": 7,
            "hrv": 58,
            "steps": 7000,
            "active_minutes": 45,
            "spo2": 93,
        }
    )

    readiness = calculate_training_readiness_signals(pd.DataFrame(wearable_rows))

    assert readiness["run_recommendation"]["color"] == "Red"
    assert readiness["lift_recommendation"]["label"] == "Recovery day"
    assert readiness["diagnostics"]["recovery_health"]["sickness_warning"] is True
    assert any("possible sickness" in signal for signal in readiness["signals"])
