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


def _nutrition_summary(nutrition_df: pd.DataFrame | None) -> dict:
    nutrition = _dated_numeric_frame(nutrition_df, ["calories", "carbs", "protein", "fat"])
    if nutrition.empty:
        return {
            "recent_carbs_average": None,
            "recent_protein_average": None,
            "low_recent_carbs": False,
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
        "low_recent_carbs": bool(recent_carbs is not None and recent_carbs < 180),
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
    latest = windows.sort_values(["date", "workout_time"], kind="stable").iloc[-1]
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
        return {
            "status": "insufficient_data",
            "message": "Need more wearable history.",
            "run_recommendation": {
                "color": "Gray",
                "label": "Need more history",
                "reason": "Log at least 3 days of wearable metrics to start readiness guidance.",
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
                "label": "Normal",
                "reason": "Not enough wearable context to flag hydration stress.",
            },
            "signals": ["Need more wearable history."],
            "diagnostics": diagnostics,
        }

    wearable = daily.copy()
    wearable["activity_load"] = (
        pd.to_numeric(wearable.get("steps"), errors="coerce").fillna(0) / 1000
        + pd.to_numeric(wearable.get("active_minutes"), errors="coerce").fillna(0)
        + pd.to_numeric(wearable.get("workout_minutes"), errors="coerce").fillna(0)
        + pd.to_numeric(wearable.get("calories_burned"), errors="coerce").fillna(0) / 100
    )

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

    training = _training_load_summary(training_df)
    nutrition = _nutrition_summary(nutrition_df)
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
    if low_carbs_high_training:
        signals.append("Recent carbs are low while training load is high.")
    if recovery_training_decline:
        signals.append("Recovery score trend is declining during a high training-load window.")
    if post_workout["low"]:
        signals.append("Latest marked workout has under 30g post-workout protein logged.")
    if not signals:
        signals.append("No major readiness flags from current wearable trends.")

    if recovery_training_decline and elevated_hr_low_hrv:
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

    if recovery_training_decline:
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
            "reason": "Recent carb intake is low for the current training load.",
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
            "label": "Increase fluids/electrolytes",
            "reason": "Activity load or calorie burn is elevated relative to baseline.",
        }
    else:
        hydration_recommendation = {
            "label": "Normal",
            "reason": "No hydration stress signal from wearable trends.",
        }

    return {
        "status": "ok",
        "message": "Training readiness signals calculated from local wearable and performance data.",
        "run_recommendation": run_recommendation,
        "lift_recommendation": lift_recommendation,
        "fueling_recommendation": fueling_recommendation,
        "hydration_recommendation": hydration_recommendation,
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
        },
    }
