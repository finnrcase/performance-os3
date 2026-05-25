"""Local-first wearable metrics foundation.

This module intentionally does not connect to any live wearable APIs yet. It
provides a defensive CSV-backed layer that future Fitbit / Google Health
ingestion can write into without changing the existing recovery score.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timezone
from uuid import uuid4

import numpy as np
import pandas as pd

from src.paths import processed_data_path


WEARABLE_METRIC_COLUMNS = [
    "metric_id",
    "date",
    "source",
    "sleep_hours",
    "sleep_score",
    "resting_hr",
    "hrv",
    "steps",
    "active_minutes",
    "calories_burned",
    "workout_minutes",
    "created_at",
    "updated_at",
]
WEARABLE_NUMERIC_COLUMNS = [
    "sleep_hours",
    "sleep_score",
    "resting_hr",
    "hrv",
    "steps",
    "active_minutes",
    "calories_burned",
    "workout_minutes",
]
WEARABLE_METRICS_PATH = processed_data_path("wearable_metrics.csv")


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


def _normalize_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return _stable_text(value)
    return parsed.date().isoformat()


def _normalize_wearable_metrics(wearable_df: pd.DataFrame | None) -> pd.DataFrame:
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
    df["source"] = df["source"].fillna("manual").astype(str).str.strip().replace("", "manual")
    for column in WEARABLE_NUMERIC_COLUMNS:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["created_at", "updated_at"]:
        df[column] = df[column].fillna("").astype(str)

    return df.sort_values(["date", "source", "created_at"], kind="stable").reset_index(drop=True)


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
        "sleep_hours": sleep_hours,
        "sleep_score": sleep_score,
        "resting_hr": resting_hr,
        "hrv": hrv,
        "steps": steps,
        "active_minutes": active_minutes,
        "calories_burned": calories_burned,
        "workout_minutes": workout_minutes,
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
    if df.empty or "date" not in df.columns:
        return pd.DataFrame(), {"rows": int(len(raw)), "valid_days": 0, "missing_columns": missing_columns}

    df["_date_ts"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_date_ts"]).copy()
    if df.empty:
        return pd.DataFrame(), {"rows": int(len(raw)), "valid_days": 0, "missing_columns": missing_columns}

    aggregations = {
        "sleep_hours": "mean",
        "sleep_score": "mean",
        "resting_hr": "mean",
        "hrv": "mean",
        "steps": "sum",
        "active_minutes": "sum",
        "calories_burned": "sum",
        "workout_minutes": "sum",
    }
    daily = (
        df.groupby("_date_ts", as_index=False)
        .agg({column: aggregations[column] for column in WEARABLE_NUMERIC_COLUMNS})
        .sort_values("_date_ts", kind="stable")
        .reset_index(drop=True)
    )
    daily["date"] = daily["_date_ts"].dt.date.astype(str)
    daily = daily[["date", *WEARABLE_NUMERIC_COLUMNS]]
    return daily, {
        "rows": int(len(raw)),
        "valid_days": int(len(daily)),
        "missing_columns": missing_columns,
    }


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
            "calories_burned": _metric_trend(daily_df, "calories_burned"),
            "workout_minutes": _metric_trend(daily_df, "workout_minutes"),
            "activity_load": _metric_trend(daily_df, "activity_load"),
            "trend": "insufficient_data",
        }

    activity = daily_df.copy()
    for column in ["steps", "active_minutes", "calories_burned", "workout_minutes"]:
        activity[column] = pd.to_numeric(activity.get(column), errors="coerce")
    activity["activity_load"] = (
        activity["steps"].fillna(0) / 1000
        + activity["active_minutes"].fillna(0)
        + activity["workout_minutes"].fillna(0)
        + activity["calories_burned"].fillna(0) / 100
    )
    load_trend = _metric_trend(activity, "activity_load", higher_is_better=True, stable_threshold=0.08)
    return {
        "steps": _metric_trend(activity, "steps", higher_is_better=True, stable_threshold=0.08),
        "active_minutes": _metric_trend(activity, "active_minutes", higher_is_better=True, stable_threshold=0.08),
        "calories_burned": _metric_trend(activity, "calories_burned", higher_is_better=True, stable_threshold=0.08),
        "workout_minutes": _metric_trend(activity, "workout_minutes", higher_is_better=True, stable_threshold=0.08),
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
        return {
            "status": "empty",
            "message": "No wearable metrics available yet.",
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
            "activity": _activity_trend(daily),
            "flags": ["No wearable data yet."],
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

    flags = []
    if sleep["rolling_7_day_average"] is not None and sleep["rolling_7_day_average"] < 7:
        flags.append("Sleep average is below 7 hours.")
    if resting_hr["trend"] == "declining":
        flags.append("Resting HR is trending higher than baseline.")
    if hrv["trend"] == "declining":
        flags.append("HRV is trending lower than baseline.")
    if activity["trend"] == "improving" and (sleep["trend"] == "declining" or hrv["trend"] == "declining"):
        flags.append("Activity is rising while recovery markers are softening.")
    if not flags:
        flags.append("Wearable recovery signals are stable.")

    return {
        "status": "ok",
        "message": "Wearable recovery signals calculated from local metrics.",
        "latest": latest,
        "sleep": sleep,
        "resting_hr": resting_hr,
        "hrv": hrv,
        "activity": activity,
        "flags": flags,
        "diagnostics": diagnostics,
    }
