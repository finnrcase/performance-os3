import pandas as pd

import src.wearables as wearables
from src.wearables import (
    WEARABLE_METRIC_COLUMNS,
    add_wearable_metric_entry,
    calculate_wearable_recovery_signals,
    load_wearable_metrics,
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
