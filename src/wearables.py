"""Local-first wearable metrics foundation.

This module intentionally does not connect to any live wearable APIs yet. It
provides a defensive CSV-backed layer that future Fitbit / Google Health
ingestion can write into without changing the existing recovery score.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
import json
from uuid import uuid4

import numpy as np
import pandas as pd

from src.paths import processed_data_path


WEARABLE_METRIC_COLUMNS = [
    "metric_id",
    "date",
    "source",
    "provider",
    "populated_metric_count",
    "placeholder",
    "sleep_hours",
    "sleep_score",
    "total_sleep_minutes",
    "rem_sleep_minutes",
    "deep_sleep_minutes",
    "light_sleep_minutes",
    "awake_minutes",
    "sleep_efficiency",
    "resting_hr",
    "resting_hr_baseline",
    "resting_hr_deviation",
    "hrv",
    "average_hr",
    "max_hr",
    "workout_average_hr",
    "workout_max_hr",
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "distance_miles",
    "calories_burned",
    "total_calories_burned",
    "active_calories_burned",
    "basal_calories_burned",
    "workout_minutes",
    "cardio_load",
    "breathing_rate",
    "spo2",
    "skin_temperature",
    "body_temperature",
    "raw_payload",
    "created_at",
    "updated_at",
]
WEARABLE_PROVIDER_IDS = {
    "manual",
    "mock",
    "google_health",
    "google_fit_legacy",
    "apple_health_export",
    "withings",
    "fitbit",
}
WEARABLE_NUMERIC_COLUMNS = [
    "sleep_hours",
    "sleep_score",
    "total_sleep_minutes",
    "rem_sleep_minutes",
    "deep_sleep_minutes",
    "light_sleep_minutes",
    "awake_minutes",
    "sleep_efficiency",
    "resting_hr",
    "resting_hr_baseline",
    "resting_hr_deviation",
    "hrv",
    "average_hr",
    "max_hr",
    "workout_average_hr",
    "workout_max_hr",
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "distance_miles",
    "calories_burned",
    "total_calories_burned",
    "active_calories_burned",
    "basal_calories_burned",
    "workout_minutes",
    "cardio_load",
    "breathing_rate",
    "spo2",
    "skin_temperature",
    "body_temperature",
]
WEARABLE_METRICS_PATH = processed_data_path("wearable_metrics.csv")
ACTIVITY_LOAD_COLUMNS = [
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "calories_burned",
    "workout_minutes",
    "cardio_load",
]


def _metric_value_present(value) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return True
    if pd.isna(parsed) or not np.isfinite(parsed):
        return False
    return parsed > 0


def _populated_metric_count(row: pd.Series | dict) -> int:
    return sum(1 for column in WEARABLE_NUMERIC_COLUMNS if _metric_value_present(row.get(column)))


def _empty_wearable_metrics() -> pd.DataFrame:
    return pd.DataFrame(columns=WEARABLE_METRIC_COLUMNS)


def _stable_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "nat"} else text


def _raw_payload_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return "" if value.strip().lower() in {"", "nan", "none", "<na>", "nat"} else value
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _normalize_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return _stable_text(value)
    return parsed.date().isoformat()


def _provider_from_source(source: str, provider: str | None = None) -> str:
    candidate = _stable_text(provider) or _stable_text(source) or "manual"
    return candidate


def normalize_wearable_metric_rows(
    wearable_df: pd.DataFrame | list[dict] | None,
    *,
    source: str = "manual",
    provider: str | None = None,
) -> pd.DataFrame:
    """Normalize any wearable provider payload into the wearable_metrics schema."""
    df = pd.DataFrame(wearable_df).copy() if wearable_df is not None else _empty_wearable_metrics()
    for column in WEARABLE_METRIC_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df = df[WEARABLE_METRIC_COLUMNS].copy()

    df["metric_id"] = df["metric_id"].fillna("").astype(str)
    missing_ids = df["metric_id"].str.strip().isin(["", "nan", "None", "<NA>"])
    if missing_ids.any():
        df.loc[missing_ids, "metric_id"] = [str(uuid4()) for _ in range(int(missing_ids.sum()))]

    df["date"] = df["date"].apply(_normalize_date)
    default_source = _stable_text(source) or "manual"
    df["source"] = df["source"].apply(lambda value: _stable_text(value) or default_source)
    df["provider"] = df.apply(
        lambda row: _provider_from_source(str(row.get("source") or default_source), _stable_text(row.get("provider")) or provider),
        axis=1,
    )
    for column in WEARABLE_NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["populated_metric_count"] = df.apply(_populated_metric_count, axis=1).astype(int)
    existing_placeholder = (
        df["placeholder"]
        .fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes", "placeholder"})
    )
    df["placeholder"] = existing_placeholder | (df["populated_metric_count"] <= 0)
    df["raw_payload"] = df["raw_payload"].apply(_raw_payload_text)
    for column in ["created_at", "updated_at"]:
        df[column] = df[column].fillna("").astype(str)

    df = df.sort_values(["date", "source", "created_at"], kind="stable").reset_index(drop=True)
    return df.astype(object).where(pd.notna(df), None)


def _normalize_wearable_metrics(wearable_df: pd.DataFrame | None) -> pd.DataFrame:
    return normalize_wearable_metric_rows(wearable_df)


def load_wearable_metrics() -> pd.DataFrame:
    """Load wearable metrics from the local CSV, returning a typed empty table if absent."""
    if not WEARABLE_METRICS_PATH.exists():
        return _empty_wearable_metrics()
    try:
        wearable_df = pd.read_csv(WEARABLE_METRICS_PATH)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return _empty_wearable_metrics()
    return _normalize_wearable_metrics(wearable_df)


def save_wearable_metrics(df: pd.DataFrame | None) -> None:
    """Save wearable metrics to local CSV with stable schema and defensive coercion."""
    WEARABLE_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _normalize_wearable_metrics(df).to_csv(WEARABLE_METRICS_PATH, index=False)


def add_wearable_metric_entry(
    date,
    source: str = "manual",
    provider: str | None = None,
    sleep_hours=None,
    sleep_score=None,
    resting_hr=None,
    hrv=None,
    steps=None,
    active_minutes=None,
    calories_burned=None,
    workout_minutes=None,
    metric_id: str | None = None,
) -> pd.DataFrame:
    """Append one wearable metric entry and return the updated metrics table."""
    now = datetime.now(timezone.utc).isoformat()
    entry = {
        "metric_id": str(metric_id or uuid4()),
        "date": _normalize_date(date),
        "source": str(source or "manual").strip() or "manual",
        "provider": _provider_from_source(str(source or "manual"), provider),
        "sleep_hours": sleep_hours,
        "sleep_score": sleep_score,
        "resting_hr": resting_hr,
        "hrv": hrv,
        "steps": steps,
        "active_minutes": active_minutes,
        "calories_burned": calories_burned,
        "workout_minutes": workout_minutes,
        "raw_payload": "",
        "created_at": now,
        "updated_at": now,
    }
    wearable_df = load_wearable_metrics()
    wearable_df = pd.concat([wearable_df, pd.DataFrame([entry])], ignore_index=True)
    wearable_df = _normalize_wearable_metrics(wearable_df)
    save_wearable_metrics(wearable_df)
    return wearable_df


def _aggregate_daily_metrics(wearable_df: pd.DataFrame | None) -> tuple[pd.DataFrame, dict]:
    raw = pd.DataFrame(wearable_df).copy() if wearable_df is not None else _empty_wearable_metrics()
    missing_columns = [column for column in WEARABLE_METRIC_COLUMNS if column not in raw.columns]
    df = _normalize_wearable_metrics(raw)
    diagnostics = {
        "rows": int(len(raw)),
        "valid_days": 0,
        "missing_columns": missing_columns,
        "placeholder_rows": 0,
        "valid_rows": 0,
        "message": "No wearable metrics available yet.",
        "connected_but_no_metrics": False,
    }
    if df.empty or "date" not in df.columns:
        return pd.DataFrame(), diagnostics

    df["_date_ts"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_date_ts"]).copy()
    if df.empty:
        return pd.DataFrame(), diagnostics

    df["populated_metric_count"] = pd.to_numeric(df["populated_metric_count"], errors="coerce").fillna(0).astype(int)
    placeholder_mask = df["placeholder"].fillna(False).astype(bool) | (df["populated_metric_count"] <= 0)
    diagnostics["placeholder_rows"] = int(placeholder_mask.sum())
    df = df.loc[~placeholder_mask].copy()
    diagnostics["valid_rows"] = int(len(df))
    if df.empty:
        diagnostics["connected_but_no_metrics"] = bool(len(raw))
        diagnostics["message"] = (
            "Connected, but no wearable metrics are available yet."
            if len(raw)
            else "No wearable metrics available yet."
        )
        return pd.DataFrame(), diagnostics

    sum_columns = {
        "steps",
        "active_minutes",
        "active_zone_minutes",
        "distance_meters",
        "distance_miles",
        "calories_burned",
        "total_calories_burned",
        "active_calories_burned",
        "basal_calories_burned",
        "workout_minutes",
        "cardio_load",
    }
    def sum_optional(series: pd.Series):
        return pd.to_numeric(series, errors="coerce").sum(min_count=1)

    def mean_optional(series: pd.Series):
        return pd.to_numeric(series, errors="coerce").mean()

    aggregations = {column: sum_optional if column in sum_columns else mean_optional for column in WEARABLE_NUMERIC_COLUMNS}
    daily = (
        df.groupby("_date_ts", as_index=False)
        .agg({column: aggregations[column] for column in WEARABLE_NUMERIC_COLUMNS})
        .sort_values("_date_ts", kind="stable")
        .reset_index(drop=True)
    )
    daily["date"] = daily["_date_ts"].dt.date.astype(str)
    daily = daily[["date", *WEARABLE_NUMERIC_COLUMNS]]
    return daily, {
        **diagnostics,
        "valid_days": int(len(daily)),
        "message": "Wearable metrics available.",
        "connected_but_no_metrics": False,
    }


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce")
    return pd.Series(pd.NA, index=frame.index, dtype="float64")


def _activity_load_series(frame: pd.DataFrame) -> pd.Series:
    components = pd.DataFrame({column: _numeric_series(frame, column) for column in ACTIVITY_LOAD_COLUMNS}, index=frame.index)
    has_any_activity = components.notna().any(axis=1)
    load = (
        components["steps"].fillna(0) / 1000
        + components["active_minutes"].fillna(0)
        + components["active_zone_minutes"].fillna(0) * 1.5
        + components["distance_meters"].fillna(0) / 1000
        + components["workout_minutes"].fillna(0)
        + components["cardio_load"].fillna(0)
        + components["calories_burned"].fillna(0) / 150
    )
    return load.where(has_any_activity, pd.NA)


def _rounded(value, digits: int = 1):
    if value is None:
        return None
    try:
        if pd.isna(value) or not np.isfinite(float(value)):
            return None
    except (TypeError, ValueError):
        return None
    return round(float(value), digits)


def _percent_change(current, previous):
    if current is None or previous is None:
        return None
    if not previous:
        return None
    return round((float(current) - float(previous)) / abs(float(previous)), 4)


def _trend_label(
    current,
    previous,
    *,
    higher_is_better: bool = True,
    stable_threshold: float = 0.05,
) -> str:
    pct_change = _percent_change(current, previous)
    if pct_change is None:
        return "insufficient_data"
    if abs(pct_change) < stable_threshold:
        return "stable"
    improving = pct_change > 0 if higher_is_better else pct_change < 0
    return "improving" if improving else "declining"


def _metric_trend(
    daily_df: pd.DataFrame,
    column: str,
    *,
    higher_is_better: bool = True,
    stable_threshold: float = 0.05,
) -> dict:
    if daily_df.empty or column not in daily_df.columns:
        return {
            "latest": None,
            "rolling_7_day_average": None,
            "recent_7_day_average": None,
            "previous_7_day_average": None,
            "change_vs_previous_7_days": None,
            "trend": "insufficient_data",
        }

    values = pd.to_numeric(daily_df[column], errors="coerce")
    valid = values.dropna()
    if valid.empty:
        return {
            "latest": None,
            "rolling_7_day_average": None,
            "recent_7_day_average": None,
            "previous_7_day_average": None,
            "change_vs_previous_7_days": None,
            "trend": "insufficient_data",
        }

    rolling = values.rolling(window=7, min_periods=1).mean().dropna()
    recent = valid.tail(7)
    previous = valid.iloc[-14:-7]
    recent_average = _rounded(recent.mean())
    previous_average = _rounded(previous.mean()) if not previous.empty else None
    return {
        "latest": _rounded(valid.iloc[-1]),
        "rolling_7_day_average": _rounded(rolling.iloc[-1]) if not rolling.empty else None,
        "recent_7_day_average": recent_average,
        "previous_7_day_average": previous_average,
        "change_vs_previous_7_days": _percent_change(recent_average, previous_average),
        "trend": _trend_label(
            recent_average,
            previous_average,
            higher_is_better=higher_is_better,
            stable_threshold=stable_threshold,
        ),
    }


def _activity_trend(daily_df: pd.DataFrame) -> dict:
    if daily_df.empty:
        return {
            "steps": _metric_trend(daily_df, "steps"),
            "active_minutes": _metric_trend(daily_df, "active_minutes"),
            "active_zone_minutes": _metric_trend(daily_df, "active_zone_minutes"),
            "distance_meters": _metric_trend(daily_df, "distance_meters"),
            "calories_burned": _metric_trend(daily_df, "calories_burned"),
            "workout_minutes": _metric_trend(daily_df, "workout_minutes"),
            "cardio_load": _metric_trend(daily_df, "cardio_load"),
            "activity_load": _metric_trend(daily_df, "activity_load"),
            "trend": "insufficient_data",
        }

    activity = daily_df.copy()
    for column in ACTIVITY_LOAD_COLUMNS:
        activity[column] = pd.to_numeric(activity.get(column), errors="coerce")
    activity["activity_load"] = _activity_load_series(activity)
    load_trend = _metric_trend(activity, "activity_load", higher_is_better=True, stable_threshold=0.08)
    return {
        "steps": _metric_trend(activity, "steps", higher_is_better=True, stable_threshold=0.08),
        "active_minutes": _metric_trend(activity, "active_minutes", higher_is_better=True, stable_threshold=0.08),
        "active_zone_minutes": _metric_trend(activity, "active_zone_minutes", higher_is_better=True, stable_threshold=0.08),
        "distance_meters": _metric_trend(activity, "distance_meters", higher_is_better=True, stable_threshold=0.08),
        "calories_burned": _metric_trend(activity, "calories_burned", higher_is_better=True, stable_threshold=0.08),
        "workout_minutes": _metric_trend(activity, "workout_minutes", higher_is_better=True, stable_threshold=0.08),
        "cardio_load": _metric_trend(activity, "cardio_load", higher_is_better=True, stable_threshold=0.08),
        "activity_load": load_trend,
        "trend": load_trend["trend"],
    }


def calculate_wearable_recovery_signals(wearable_df: pd.DataFrame | None) -> dict:
    """Calculate lightweight wearable recovery signals without changing recovery score.

    The return shape is intentionally structured and tolerant of missing data so
    future UI/API consumers can display an empty or partial state safely.
    """
    daily, diagnostics = _aggregate_daily_metrics(wearable_df)
    if daily.empty:
        message = str(diagnostics.get("message") or "No wearable metrics available yet.")
        return {
            "status": "empty",
            "message": message,
            "latest": {},
            "sleep": {
                "latest": None,
                "rolling_7_day_average": None,
                "recent_7_day_average": None,
                "previous_7_day_average": None,
                "change_vs_previous_7_days": None,
                "trend": "insufficient_data",
            },
            "resting_hr": {
                "latest": None,
                "rolling_7_day_average": None,
                "recent_7_day_average": None,
                "previous_7_day_average": None,
                "change_vs_previous_7_days": None,
                "trend": "insufficient_data",
            },
            "hrv": {
                "latest": None,
                "rolling_7_day_average": None,
                "recent_7_day_average": None,
                "previous_7_day_average": None,
                "change_vs_previous_7_days": None,
                "trend": "insufficient_data",
            },
            "sleep_stages": {
                "rem_sleep_minutes": None,
                "deep_sleep_minutes": None,
                "light_sleep_minutes": None,
                "awake_minutes": None,
                "sleep_efficiency": None,
            },
            "health": {
                "breathing_rate": None,
                "spo2": None,
                "skin_temperature": None,
                "body_temperature": None,
            },
            "activity": _activity_trend(daily),
            "flags": [message],
            "diagnostics": diagnostics,
        }

    latest_row = daily.iloc[-1].to_dict()
    latest = {"date": str(latest_row.get("date", ""))}
    for column in WEARABLE_NUMERIC_COLUMNS:
        latest[column] = _rounded(latest_row.get(column))

    sleep = _metric_trend(daily, "sleep_hours", higher_is_better=True)
    resting_hr = _metric_trend(daily, "resting_hr", higher_is_better=False)
    hrv = _metric_trend(daily, "hrv", higher_is_better=True)
    activity = _activity_trend(daily)
    sleep_stages = {
        "rem_sleep_minutes": _rounded(latest_row.get("rem_sleep_minutes")),
        "deep_sleep_minutes": _rounded(latest_row.get("deep_sleep_minutes")),
        "light_sleep_minutes": _rounded(latest_row.get("light_sleep_minutes")),
        "awake_minutes": _rounded(latest_row.get("awake_minutes")),
        "sleep_efficiency": _rounded(latest_row.get("sleep_efficiency")),
    }
    health = {
        "breathing_rate": _rounded(latest_row.get("breathing_rate")),
        "spo2": _rounded(latest_row.get("spo2")),
        "skin_temperature": _rounded(latest_row.get("skin_temperature")),
        "body_temperature": _rounded(latest_row.get("body_temperature")),
    }
    rhr_deviation = _rounded(latest_row.get("resting_hr_deviation"))

    flags = []
    if sleep["rolling_7_day_average"] is not None and sleep["rolling_7_day_average"] < 7:
        flags.append("Sleep average is below 7 hours.")
    if rhr_deviation is not None and rhr_deviation >= 5:
        flags.append("Resting HR is meaningfully above baseline.")
    if resting_hr["trend"] == "declining":
        flags.append("Resting HR is trending higher than baseline.")
    if hrv["trend"] == "declining":
        flags.append("HRV is trending lower than baseline.")
    if activity["trend"] == "improving" and (sleep["trend"] == "declining" or hrv["trend"] == "declining"):
        flags.append("Activity is rising while recovery markers are softening.")
    if health["spo2"] is not None and health["spo2"] < 94:
        flags.append("SpO2 is below the usual recovery range.")
    if health["breathing_rate"] is not None and health["breathing_rate"] >= 22:
        flags.append("Breathing rate is elevated.")
    if (
        health["skin_temperature"] is not None
        and abs(float(health["skin_temperature"])) <= 5
        and abs(float(health["skin_temperature"])) >= 1
    ):
        flags.append("Skin temperature is meaningfully different from baseline.")
    if health["body_temperature"] is not None and health["body_temperature"] >= 37.8:
        flags.append("Body temperature is elevated.")
    if not flags:
        flags.append("Wearable recovery signals are stable.")

    return {
        "status": "ok",
        "message": "Wearable recovery signals calculated from local metrics.",
        "latest": latest,
        "sleep": sleep,
        "resting_hr": resting_hr,
        "hrv": hrv,
        "sleep_stages": sleep_stages,
        "health": health,
        "activity": activity,
        "flags": flags,
        "diagnostics": diagnostics,
    }


def _empty_trend_metric() -> dict:
    return {
        "recent_average": None,
        "baseline_average": None,
        "change_vs_baseline": None,
        "sample_size": 0,
        "baseline_sample_size": 0,
    }


def _recent_vs_baseline(
    df: pd.DataFrame,
    column: str,
    *,
    recent_days: int = 3,
    baseline_days: int = 7,
) -> dict:
    if df.empty or column not in df.columns:
        return _empty_trend_metric()

    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return _empty_trend_metric()

    recent = values.tail(recent_days)
    previous_start = max(0, len(values) - recent_days - baseline_days)
    previous_end = max(0, len(values) - recent_days)
    baseline = values.iloc[previous_start:previous_end]
    recent_average = _rounded(recent.mean())
    baseline_average = _rounded(baseline.mean()) if not baseline.empty else None
    return {
        "recent_average": recent_average,
        "baseline_average": baseline_average,
        "change_vs_baseline": _percent_change(recent_average, baseline_average),
        "sample_size": int(len(recent)),
        "baseline_sample_size": int(len(baseline)),
    }


def _dated_numeric_frame(df: pd.DataFrame | None, numeric_columns: list[str]) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame(columns=["date", "_date_ts", *numeric_columns])
    prepared = pd.DataFrame(df).copy()
    prepared["_date_ts"] = pd.to_datetime(prepared["date"], errors="coerce")
    prepared = prepared.dropna(subset=["_date_ts"]).copy()
    if prepared.empty:
        return pd.DataFrame(columns=["date", "_date_ts", *numeric_columns])
    for column in numeric_columns:
        if column not in prepared.columns:
            prepared[column] = np.nan
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared["date"] = prepared["_date_ts"].dt.date.astype(str)
    return prepared.sort_values("_date_ts", kind="stable").reset_index(drop=True)


def _training_load_summary(training_df: pd.DataFrame | None) -> dict:
    training = _dated_numeric_frame(training_df, ["sets", "reps", "weight", "rpe", "duration_minutes"])
    if training.empty:
        return {
            "recent_volume": 0.0,
            "baseline_volume": None,
            "recent_duration_minutes": 0.0,
            "recent_hard_sets": 0.0,
            "high_training_load": False,
            "sample_size": 0,
        }

    training["volume"] = (
        training["sets"].fillna(0)
        * training["reps"].fillna(0)
        * training["weight"].fillna(0)
    )
    training["hard_sets"] = np.where(training["rpe"].fillna(0) >= 7, training["sets"].fillna(0), 0)
    daily = (
        training.groupby("_date_ts", as_index=False)
        .agg(
            volume=("volume", "sum"),
            duration_minutes=("duration_minutes", "sum"),
            hard_sets=("hard_sets", "sum"),
        )
        .sort_values("_date_ts", kind="stable")
        .reset_index(drop=True)
    )

    recent = daily.tail(7)
    baseline = daily.iloc[max(0, len(daily) - 14) : max(0, len(daily) - 7)]
    recent_volume = float(recent["volume"].sum()) if not recent.empty else 0.0
    baseline_volume = float(baseline["volume"].sum()) if not baseline.empty else None
    recent_duration = float(recent["duration_minutes"].sum()) if not recent.empty else 0.0
    recent_hard_sets = float(recent["hard_sets"].sum()) if not recent.empty else 0.0
    volume_above_baseline = baseline_volume is not None and baseline_volume > 0 and recent_volume > baseline_volume * 1.15
    high_training_load = bool(
        recent_volume >= 12000
        or recent_duration >= 240
        or recent_hard_sets >= 35
        or volume_above_baseline
    )
    return {
        "recent_volume": round(recent_volume, 1),
        "baseline_volume": _rounded(baseline_volume),
        "recent_duration_minutes": round(recent_duration, 1),
        "recent_hard_sets": round(recent_hard_sets, 1),
        "high_training_load": high_training_load,
        "sample_size": int(len(recent)),
    }


def _carb_threshold_for_training(training: dict | None = None, bodyweight_lb: float | None = None) -> float:
    try:
        bodyweight = float(bodyweight_lb or 180)
    except (TypeError, ValueError):
        bodyweight = 180
    training = training or {}
    recent_duration = float(training.get("recent_duration_minutes") or 0)
    recent_hard_sets = float(training.get("recent_hard_sets") or 0)
    high_load = bool(training.get("high_training_load"))
    grams_per_lb = 1.25 if high_load or recent_duration >= 240 or recent_hard_sets >= 35 else 1.05 if recent_duration >= 150 or recent_hard_sets >= 20 else 0.9
    return round(max(120.0, min(320.0, bodyweight * grams_per_lb)), 0)


def _nutrition_summary(nutrition_df: pd.DataFrame | None, training: dict | None = None) -> dict:
    nutrition = _dated_numeric_frame(nutrition_df, ["calories", "carbs", "protein", "fat"])
    carb_threshold = _carb_threshold_for_training(training)
    if nutrition.empty:
        return {
            "recent_carbs_average": None,
            "recent_protein_average": None,
            "low_recent_carbs": False,
            "carb_threshold": carb_threshold,
            "sample_size": 0,
        }

    daily = (
        nutrition.groupby("_date_ts", as_index=False)
        .agg(calories=("calories", "sum"), carbs=("carbs", "sum"), protein=("protein", "sum"), fat=("fat", "sum"))
        .sort_values("_date_ts", kind="stable")
        .reset_index(drop=True)
    )
    recent = daily.tail(3)
    recent_carbs = _rounded(recent["carbs"].mean()) if not recent.empty else None
    recent_protein = _rounded(recent["protein"].mean()) if not recent.empty else None
    return {
        "recent_carbs_average": recent_carbs,
        "recent_protein_average": recent_protein,
        "low_recent_carbs": bool(recent_carbs is not None and recent_carbs < carb_threshold),
        "carb_threshold": carb_threshold,
        "sample_size": int(len(recent)),
    }


def _recovery_decline_summary(recovery_df: pd.DataFrame | None) -> dict:
    recovery = _dated_numeric_frame(
        recovery_df,
        ["recovery_score", "sleep_hours", "sleep_quality", "fatigue", "soreness", "stress", "motivation"],
    )
    if recovery.empty:
        return {"declining": False, "latest": None, "previous": None, "sample_size": 0}

    if "recovery_score" not in recovery.columns or recovery["recovery_score"].dropna().empty:
        sleep_score = (recovery["sleep_hours"].clip(lower=0, upper=8) / 8).fillna(0)
        quality_score = (recovery["sleep_quality"].clip(lower=0, upper=10) / 10).fillna(0)
        fatigue_score = ((10 - recovery["fatigue"].clip(lower=0, upper=10)) / 10).fillna(0)
        soreness_score = ((10 - recovery["soreness"].clip(lower=0, upper=10)) / 10).fillna(0)
        stress_score = ((10 - recovery["stress"].clip(lower=0, upper=10)) / 10).fillna(0)
        motivation_score = (recovery["motivation"].clip(lower=0, upper=10) / 10).fillna(0)
        recovery["recovery_score"] = (
            sleep_score + quality_score + fatigue_score + soreness_score + stress_score + motivation_score
        ) / 6 * 100

    values = pd.to_numeric(recovery["recovery_score"], errors="coerce").dropna()
    if len(values) < 3:
        return {
            "declining": False,
            "latest": _rounded(values.iloc[-1]) if not values.empty else None,
            "previous": None,
            "sample_size": int(len(values)),
        }

    recent = values.tail(3).mean()
    previous = values.iloc[max(0, len(values) - 6) : max(0, len(values) - 3)].mean()
    declining = bool(not pd.isna(previous) and recent < previous - 5)
    return {
        "declining": declining,
        "latest": _rounded(recent),
        "previous": _rounded(previous),
        "sample_size": int(len(values.tail(6))),
    }


def _post_workout_protein_signal(
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    markers_df: pd.DataFrame | None,
) -> dict:
    if markers_df is None or markers_df.empty:
        return {"available": False, "post_workout_protein": None, "low": False}
    try:
        from src.workout_nutrition import calculate_workout_nutrition_windows

        windows = calculate_workout_nutrition_windows(nutrition_df, training_df, markers_df)
    except Exception:
        return {"available": False, "post_workout_protein": None, "low": False}
    if windows.empty or "post_workout_protein" not in windows.columns:
        return {"available": False, "post_workout_protein": None, "low": False}
    sort_columns = ["date", "marker_sequence"] if "marker_sequence" in windows.columns else ["date", "workout_time"]
    latest = windows.sort_values(sort_columns, kind="stable").iloc[-1]
    protein = pd.to_numeric(latest.get("post_workout_protein"), errors="coerce")
    if pd.isna(protein):
        return {"available": False, "post_workout_protein": None, "low": False}
    return {"available": True, "post_workout_protein": _rounded(protein), "low": bool(float(protein) < 30)}


def calculate_training_readiness_signals(
    wearable_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None = None,
    training_df: pd.DataFrame | None = None,
    nutrition_df: pd.DataFrame | None = None,
    markers_df: pd.DataFrame | None = None,
) -> dict:
    """Combine wearable, recovery, training, nutrition, and marker data into daily guidance.

    This is intentionally deterministic and additive: it does not modify the
    existing recovery score, nutrition totals, or training history.
    """
    daily, diagnostics = _aggregate_daily_metrics(wearable_df)
    valid_wearable_days = int(diagnostics.get("valid_days", 0))
    if valid_wearable_days < 3:
        message = str(diagnostics.get("message") or "Need more wearable history.")
        if valid_wearable_days > 0 or int(diagnostics.get("rows", 0) or 0) == 0:
            message = "Need more wearable history."
        return {
            "status": "insufficient_data",
            "message": message,
            "run_recommendation": {
                "color": "Gray",
                "label": "Need more history",
                "reason": message if diagnostics.get("connected_but_no_metrics") else "Log at least 3 days of wearable metrics to start readiness guidance.",
            },
            "lift_recommendation": {
                "label": "Need more history",
                "reason": "Wearable trend history is not available yet.",
            },
            "fueling_recommendation": {
                "label": "Normal fueling",
                "reason": "Not enough wearable context to adjust fueling guidance.",
            },
            "hydration_recommendation": {
                "label": "Normal hydration/electrolyte risk",
                "reason": "Not enough wearable context to flag hydration/electrolyte risk.",
            },
            "sickness_warning": {
                "status": "insufficient_data",
                "label": "Sickness pattern unavailable",
                "message": "No wearable vitals are available yet.",
                "disclaimer": "This is not a diagnosis.",
            },
            "signals": [message],
            "diagnostics": diagnostics,
        }

    wearable = daily.copy()
    wearable["activity_load"] = _activity_load_series(wearable)

    sleep_7_average = _rounded(pd.to_numeric(wearable["sleep_hours"], errors="coerce").dropna().tail(7).mean())
    resting_hr = _recent_vs_baseline(wearable, "resting_hr")
    hrv = _recent_vs_baseline(wearable, "hrv")
    activity = _recent_vs_baseline(wearable, "activity_load")
    steps = _recent_vs_baseline(wearable, "steps")

    resting_hr_high = bool(
        resting_hr["recent_average"] is not None
        and resting_hr["baseline_average"] is not None
        and resting_hr["baseline_sample_size"] >= 3
        and resting_hr["recent_average"] > resting_hr["baseline_average"] + 5
    )
    latest_row = wearable.iloc[-1].to_dict()
    latest_rhr_deviation = _rounded(latest_row.get("resting_hr_deviation"))
    if latest_rhr_deviation is not None and latest_rhr_deviation >= 5:
        resting_hr_high = True
    hrv_below_baseline = bool(
        hrv["recent_average"] is not None
        and hrv["baseline_average"] is not None
        and hrv["baseline_sample_size"] >= 3
        and hrv["recent_average"] < hrv["baseline_average"] * 0.95
    )
    elevated_hr_low_hrv = resting_hr_high and hrv_below_baseline
    sleep_low = bool(sleep_7_average is not None and sleep_7_average < 7)
    activity_high = bool(
        activity["recent_average"] is not None
        and activity["baseline_average"] is not None
        and activity["baseline_sample_size"] >= 3
        and activity["recent_average"] > activity["baseline_average"] * 1.25
    ) or bool(
        steps["recent_average"] is not None
        and steps["baseline_average"] is not None
        and steps["baseline_sample_size"] >= 3
        and steps["recent_average"] > steps["baseline_average"] + 3000
    )
    latest_spo2 = _rounded(latest_row.get("spo2"))
    latest_breathing_rate = _rounded(latest_row.get("breathing_rate"))
    latest_skin_temperature = _rounded(latest_row.get("skin_temperature"))
    latest_body_temperature = _rounded(latest_row.get("body_temperature"))
    low_spo2 = bool(latest_spo2 is not None and latest_spo2 < 94)
    elevated_breathing = bool(latest_breathing_rate is not None and latest_breathing_rate >= 22)
    skin_temp_delta_high = bool(
        latest_skin_temperature is not None
        and abs(float(latest_skin_temperature)) <= 5
        and abs(float(latest_skin_temperature)) >= 1
    )
    body_temp_high = bool(latest_body_temperature is not None and latest_body_temperature >= 37.8)
    sickness_warning = bool(low_spo2 or elevated_breathing or skin_temp_delta_high or body_temp_high)

    training = _training_load_summary(training_df)
    nutrition = _nutrition_summary(nutrition_df, training)
    recovery = _recovery_decline_summary(recovery_df)
    post_workout = _post_workout_protein_signal(nutrition_df, training_df, markers_df)
    high_training_load = bool(training["high_training_load"])
    low_carbs_high_training = bool(nutrition["low_recent_carbs"] and high_training_load)
    recovery_training_decline = bool(recovery["declining"] and high_training_load)

    signals = []
    if elevated_hr_low_hrv:
        signals.append("Resting HR is elevated while HRV is below baseline.")
    elif resting_hr_high:
        signals.append("Resting HR is running above baseline.")
    elif hrv_below_baseline:
        signals.append("HRV is below baseline.")
    if sleep_low:
        signals.append("7-day sleep average is below 7 hours.")
    if activity_high:
        signals.append("Recent steps/activity are unusually high; hidden fatigue is possible.")
    if sickness_warning:
        signals.append("Recovery health signals suggest possible sickness or unusual fatigue.")
    if low_carbs_high_training:
        signals.append(f"Recent carbs are below the current training-load threshold ({nutrition['carb_threshold']:.0f}g).")
    if recovery_training_decline:
        signals.append("Recovery score trend is declining during a high training-load window.")
    if post_workout["low"]:
        signals.append("Latest marked workout has under 30g post-workout protein logged.")
    if not signals:
        signals.append("No major readiness flags from current wearable trends.")

    if sickness_warning:
        run_recommendation = {
            "color": "Red",
            "label": "Skip run / recovery day",
            "reason": "Recovery health signals suggest avoiding added cardio stress today.",
        }
    elif recovery_training_decline and elevated_hr_low_hrv:
        run_recommendation = {
            "color": "Red",
            "label": "Skip run / recovery day",
            "reason": "Recovery is declining with high training load and wearable strain markers.",
        }
    elif elevated_hr_low_hrv or recovery_training_decline:
        run_recommendation = {
            "color": "Orange",
            "label": "Reduce intensity",
            "reason": "Wearable or recovery trends suggest avoiding hard aerobic work today.",
        }
    elif sleep_low or activity_high:
        run_recommendation = {
            "color": "Yellow",
            "label": "Easy run only",
            "reason": "Sleep or activity trend points to mild accumulated fatigue.",
        }
    else:
        run_recommendation = {
            "color": "Green",
            "label": "Run OK",
            "reason": "Wearable trends do not show a run-specific readiness concern.",
        }

    if sickness_warning:
        lift_recommendation = {
            "label": "Recovery day",
            "reason": "Health signals suggest backing off until recovery markers normalize.",
        }
    elif recovery_training_decline:
        lift_recommendation = {
            "label": "Deload suggested",
            "reason": "Recovery is declining while recent training load is high.",
        }
    elif elevated_hr_low_hrv:
        lift_recommendation = {
            "label": "Avoid max effort",
            "reason": "Elevated resting HR plus lower HRV argues against top-end attempts.",
        }
    elif sleep_low or activity_high:
        lift_recommendation = {
            "label": "Reduce volume",
            "reason": "Keep the session productive without adding too much fatigue.",
        }
    else:
        lift_recommendation = {
            "label": "Push normal",
            "reason": "No major wearable readiness flags for lifting intensity.",
        }

    if low_carbs_high_training:
        fueling_recommendation = {
            "label": "Increase carbs",
            "reason": f"Recent carb intake is below the current training-load threshold ({nutrition['carb_threshold']:.0f}g/day).",
        }
    elif post_workout["low"]:
        fueling_recommendation = {
            "label": "Post-workout protein reminder",
            "reason": "Latest marked workout has less than 30g post-workout protein logged.",
        }
    else:
        fueling_recommendation = {
            "label": "Normal fueling",
            "reason": "No low-carb or post-workout protein flag from current data.",
        }

    calorie_burn = _recent_vs_baseline(wearable, "calories_burned")
    high_burn = bool(
        calorie_burn["recent_average"] is not None
        and calorie_burn["baseline_average"] is not None
        and calorie_burn["baseline_sample_size"] >= 3
        and calorie_burn["recent_average"] > calorie_burn["baseline_average"] * 1.15
    )
    if activity_high or (resting_hr_high and high_burn):
        hydration_recommendation = {
            "label": "Elevated hydration/electrolyte risk",
            "reason": "Activity load or calorie burn is elevated relative to baseline.",
        }
    else:
        hydration_recommendation = {
            "label": "Normal hydration/electrolyte risk",
            "reason": "No hydration/electrolyte risk signal from wearable trends.",
        }

    return {
        "status": "ok",
        "message": "Training readiness signals calculated from local wearable and performance data.",
        "run_recommendation": run_recommendation,
        "lift_recommendation": lift_recommendation,
        "fueling_recommendation": fueling_recommendation,
        "hydration_recommendation": hydration_recommendation,
        "sickness_warning": {
            "status": "warning" if sickness_warning else "clear",
            "label": "Possible sickness / elevated recovery risk" if sickness_warning else "No sickness pattern detected",
            "message": "Consider reducing intensity today. Prioritize sleep, hydration, and easy movement." if sickness_warning else "No multi-signal sickness pattern from available wearable data.",
            "disclaimer": "This is not a diagnosis.",
        },
        "signals": signals,
        "diagnostics": {
            **diagnostics,
            "sleep_7_day_average": sleep_7_average,
            "resting_hr": resting_hr,
            "hrv": hrv,
            "activity": activity,
            "training": training,
            "nutrition": nutrition,
            "recovery": recovery,
            "post_workout": post_workout,
            "recovery_health": {
                "spo2": latest_spo2,
                "breathing_rate": latest_breathing_rate,
                "skin_temperature": latest_skin_temperature,
                "body_temperature": latest_body_temperature,
                "sickness_warning": sickness_warning,
                "resting_hr_deviation": latest_rhr_deviation,
            },
        },
    }
