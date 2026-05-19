"""
Deterministic recovery analytics for Performance OS.

The engine combines subjective recovery check-ins with recent sleep debt,
fatigue/soreness accumulation, training stress, and calorie deficits. It does
not use AI or external services; every score is derived from local logs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.training_schedule import is_run_row, is_strength_row, load_training_schedule_profile


RECOVERY_ANALYTICS_COLUMNS = [
    "date",
    "recovery_score",
    "classification",
    "sleep_debt",
    "fatigue_load",
    "training_stress",
    "calorie_deficit",
    "explanation",
]

RECOVERY_SIGNAL_EMPTY = {
    "status": "insufficient data",
    "confidence": "low",
    "score": None,
    "summary": "Log recovery or connect wearable data to personalize nutrition recovery adjustments.",
    "nutrition_implication": "Keep nutrition targets stable until recovery data is available.",
    "suggested_action": "Log sleep, fatigue, soreness, HRV, or resting heart rate.",
    "drivers": [],
    "metrics": {},
}


def _empty_recovery_analytics() -> pd.DataFrame:
    """Return an empty analytics table with stable columns."""
    return pd.DataFrame(columns=RECOVERY_ANALYTICS_COLUMNS)


def _date_series(df: pd.DataFrame) -> pd.Series:
    """Safely extract normalized dates from any log with a date column."""
    if df.empty or "date" not in df.columns:
        return pd.Series(dtype="datetime64[ns]")
    return pd.to_datetime(df["date"], errors="coerce").dropna().dt.normalize()


def _analysis_dates(*frames: pd.DataFrame) -> pd.DataFrame:
    """Build a continuous date index spanning all available local logs."""
    dates = pd.concat([_date_series(frame) for frame in frames], ignore_index=True)
    if dates.empty:
        return pd.DataFrame(columns=["date"])

    date_range = pd.date_range(dates.min(), dates.max(), freq="D")
    return pd.DataFrame({"date": date_range})


def _daily_recovery(recovery_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse recovery check-ins to one row per day."""
    columns = [
        "sleep_hours",
        "sleep_quality",
        "fatigue",
        "soreness",
        "stress",
        "motivation",
    ]
    if recovery_df.empty:
        return pd.DataFrame(columns=["date", *columns])

    daily_df = recovery_df.copy()
    daily_df["date"] = pd.to_datetime(daily_df["date"], errors="coerce").dt.normalize()
    daily_df = daily_df.dropna(subset=["date"])

    for column in columns:
        daily_df[column] = pd.to_numeric(daily_df[column], errors="coerce")

    return daily_df.groupby("date", as_index=False)[columns].mean()


def _daily_nutrition(nutrition_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse nutrition entries to daily calories."""
    if nutrition_df.empty:
        return pd.DataFrame(columns=["date", "calories"])

    daily_df = nutrition_df.copy()
    daily_df["date"] = pd.to_datetime(daily_df["date"], errors="coerce").dt.normalize()
    daily_df = daily_df.dropna(subset=["date"])
    daily_df["calories"] = pd.to_numeric(daily_df["calories"], errors="coerce").fillna(0)

    return daily_df.groupby("date", as_index=False)["calories"].sum()


def _daily_training(training_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse training entries to daily load components."""
    if training_df.empty:
        return pd.DataFrame(columns=["date", "volume", "duration_minutes", "avg_rpe", "run_load"])

    daily_df = training_df.copy()
    daily_df["date"] = pd.to_datetime(daily_df["date"], errors="coerce").dt.normalize()
    daily_df = daily_df.dropna(subset=["date"])

    for column in ["sets", "reps", "weight", "duration_minutes", "rpe"]:
        if column not in daily_df.columns:
            daily_df[column] = 0
        daily_df[column] = pd.to_numeric(daily_df[column], errors="coerce").fillna(0)
    if "notes" not in daily_df.columns:
        daily_df["notes"] = ""
    if "workout_type" not in daily_df.columns:
        daily_df["workout_type"] = ""
    profile = load_training_schedule_profile()
    daily_df["is_strength"] = daily_df.apply(lambda row: is_strength_row(row, profile=profile), axis=1)
    daily_df["is_run"] = daily_df.apply(lambda row: is_run_row(row, profile=profile), axis=1)

    daily_df["volume"] = np.where(
        daily_df["is_strength"],
        daily_df["sets"] * daily_df["reps"] * daily_df["weight"],
        0,
    )
    daily_df["run_load"] = daily_df["notes"].fillna("").astype(str).apply(_extract_run_load)
    missing_run_load = daily_df["is_run"] & (daily_df["run_load"] <= 0)
    daily_df.loc[missing_run_load, "run_load"] = daily_df.loc[missing_run_load].apply(
        lambda row: (_note_number(row["notes"], "distance_miles") * 10) + (float(row["duration_minutes"] or 0) * 0.45),
        axis=1,
    )

    return (
        daily_df.groupby("date", as_index=False)
        .agg(
            volume=("volume", "sum"),
            duration_minutes=("duration_minutes", "sum"),
            avg_rpe=("rpe", "mean"),
            run_load=("run_load", "sum"),
        )
        .fillna(0)
    )


def _extract_run_load(note: str) -> float:
    """Extract Strava estimated run load from local training notes."""
    marker = "estimated_run_load="
    if marker not in note:
        return 0.0
    raw = note.split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _note_number(note: str, key: str) -> float:
    marker = f"{key}="
    if marker not in str(note):
        return 0.0
    raw = str(note).split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def calculate_sleep_debt(recovery_df: pd.DataFrame, target_sleep_hours=8.0, window=7) -> pd.DataFrame:
    """Calculate rolling sleep debt over the recent window."""
    daily_df = _daily_recovery(recovery_df)
    if daily_df.empty:
        return pd.DataFrame(columns=["date", "sleep_debt"])

    daily_df["sleep_shortfall"] = (target_sleep_hours - daily_df["sleep_hours"]).clip(lower=0)
    daily_df["sleep_debt"] = (
        daily_df["sleep_shortfall"]
        .rolling(window=window, min_periods=1)
        .sum()
        .round(2)
    )

    return daily_df[["date", "sleep_debt"]]


def calculate_fatigue_load(recovery_df: pd.DataFrame, window=3) -> pd.DataFrame:
    """Calculate rolling subjective fatigue and soreness load."""
    daily_df = _daily_recovery(recovery_df)
    if daily_df.empty:
        return pd.DataFrame(columns=["date", "fatigue_load"])

    daily_df["fatigue_load"] = (
        daily_df[["fatigue", "soreness"]]
        .mean(axis=1)
        .rolling(window=window, min_periods=1)
        .mean()
        .round(2)
    )

    return daily_df[["date", "fatigue_load"]]


def calculate_training_stress(training_df: pd.DataFrame, window=7) -> pd.DataFrame:
    """Calculate rolling training stress from volume, duration, and RPE."""
    daily_df = _daily_training(training_df)
    if daily_df.empty:
        return pd.DataFrame(columns=["date", "training_stress"])

    # Volume is scaled down so very large strength totals stay in a readable range.
    daily_df["daily_stress"] = (
        (daily_df["volume"] / 1000)
        + (daily_df["duration_minutes"] / 30)
        + daily_df["avg_rpe"].clip(lower=0)
        + (daily_df["run_load"] / 10)
    )
    daily_df["training_stress"] = (
        daily_df["daily_stress"].rolling(window=window, min_periods=1).sum().round(2)
    )

    return daily_df[["date", "training_stress"]]


def classify_recovery(score: float) -> str:
    """Classify a 0-100 recovery score."""
    if score >= 80:
        return "Optimal"
    if score >= 65:
        return "Moderate"
    if score >= 45:
        return "Fatigued"
    return "High Risk"


def _base_readiness(row: pd.Series) -> float:
    """Score same-day subjective readiness before rolling penalties."""
    sleep_score = min(float(row.get("sleep_hours", 0) or 0) / 8, 1) * 20
    sleep_quality_score = (float(row.get("sleep_quality", 5) or 5) / 10) * 15
    motivation_score = (float(row.get("motivation", 5) or 5) / 10) * 15
    fatigue_score = ((11 - float(row.get("fatigue", 5) or 5)) / 10) * 18
    soreness_score = ((11 - float(row.get("soreness", 5) or 5)) / 10) * 16
    stress_score = ((11 - float(row.get("stress", 5) or 5)) / 10) * 16
    return sleep_score + sleep_quality_score + motivation_score + fatigue_score + soreness_score + stress_score


def _calorie_deficit(nutrition_df: pd.DataFrame, target_calories: float) -> pd.DataFrame:
    """Calculate daily calorie deficit against the recovery target."""
    daily_df = _daily_nutrition(nutrition_df)
    if daily_df.empty:
        return pd.DataFrame(columns=["date", "calorie_deficit"])

    daily_df["calorie_deficit"] = (float(target_calories) - daily_df["calories"]).clip(lower=0)
    return daily_df[["date", "calorie_deficit"]]


def _build_explanation(row: pd.Series, previous_score: float | None) -> str:
    """Explain the largest contributors to the current score."""
    reasons = []
    if previous_score is not None:
        delta = row["recovery_score"] - previous_score
        direction = "up" if delta >= 0 else "down"
        reasons.append(f"Score moved {direction} {abs(delta):.1f} points from the prior entry.")

    if row["sleep_debt"] >= 8:
        reasons.append(f"High rolling sleep debt ({row['sleep_debt']:.1f} hours) reduced readiness.")
    elif row["sleep_debt"] <= 2:
        reasons.append("Sleep debt is low, which supports recovery.")

    if row["fatigue_load"] >= 7:
        reasons.append(f"Fatigue and soreness are accumulating ({row['fatigue_load']:.1f}/10).")
    elif row["fatigue_load"] <= 4:
        reasons.append("Subjective fatigue and soreness are controlled.")

    if row["training_stress"] >= 35:
        reasons.append(f"Recent training stress is elevated ({row['training_stress']:.1f}).")
    elif row["training_stress"] <= 12:
        reasons.append("Recent training stress is manageable.")

    if row["calorie_deficit"] >= 500:
        reasons.append(f"Large calorie deficit ({row['calorie_deficit']:.0f}) adds a recovery penalty.")
    elif row["calorie_deficit"] == 0:
        reasons.append("Calories are not creating an added recovery penalty.")

    return " ".join(reasons) if reasons else "Not enough recent context to explain movement yet."


def calculate_recovery_score(
    recovery_df: pd.DataFrame,
    training_df: pd.DataFrame | None = None,
    nutrition_df: pd.DataFrame | None = None,
    target_calories=2850,
) -> pd.DataFrame:
    """Calculate advanced daily recovery scores and explanations."""
    training_df = training_df if training_df is not None else pd.DataFrame()
    nutrition_df = nutrition_df if nutrition_df is not None else pd.DataFrame()
    dates_df = _analysis_dates(recovery_df, training_df, nutrition_df)
    if dates_df.empty:
        return _empty_recovery_analytics()

    analytics_df = dates_df.merge(_daily_recovery(recovery_df), on="date", how="left")
    analytics_df = analytics_df.merge(calculate_sleep_debt(recovery_df), on="date", how="left")
    analytics_df = analytics_df.merge(calculate_fatigue_load(recovery_df), on="date", how="left")
    analytics_df = analytics_df.merge(calculate_training_stress(training_df), on="date", how="left")
    analytics_df = analytics_df.merge(_calorie_deficit(nutrition_df, target_calories), on="date", how="left")

    for column in ["sleep_quality", "fatigue", "soreness", "stress", "motivation"]:
        analytics_df[column] = analytics_df[column].fillna(5)
    analytics_df["sleep_hours"] = analytics_df["sleep_hours"].fillna(7)
    analytics_df["sleep_debt"] = analytics_df["sleep_debt"].ffill().fillna(0)
    analytics_df["fatigue_load"] = analytics_df["fatigue_load"].ffill().fillna(5)
    analytics_df["training_stress"] = analytics_df["training_stress"].fillna(0)
    analytics_df["calorie_deficit"] = analytics_df["calorie_deficit"].fillna(0)

    analytics_df["base_readiness"] = analytics_df.apply(_base_readiness, axis=1)
    analytics_df["recovery_score"] = (
        analytics_df["base_readiness"]
        - (analytics_df["sleep_debt"] * 2.2).clip(upper=25)
        - ((analytics_df["fatigue_load"] - 5).clip(lower=0) * 5)
        - (analytics_df["training_stress"] * 0.7).clip(upper=20)
        - (analytics_df["calorie_deficit"] / 100).clip(upper=15)
    ).clip(lower=0, upper=100).round(1)
    analytics_df["classification"] = analytics_df["recovery_score"].apply(classify_recovery)

    explanations = []
    previous_score = None
    for _, row in analytics_df.iterrows():
        explanations.append(_build_explanation(row, previous_score))
        previous_score = row["recovery_score"]
    analytics_df["explanation"] = explanations
    analytics_df["date"] = analytics_df["date"].dt.date.astype(str)

    return analytics_df[RECOVERY_ANALYTICS_COLUMNS]


def _numeric_series(df: pd.DataFrame, column: str) -> pd.Series:
    if df.empty or column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").dropna()


def _trend_delta(df: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    values = _numeric_series(df.sort_values("date"), column)
    if len(values) < 7:
        return None, round(float(values.tail(min(7, len(values))).mean()), 2) if len(values) else None
    recent = values.tail(7)
    previous = values.iloc[-14:-7] if len(values) >= 14 else values.iloc[:-7]
    if previous.empty:
        return None, round(float(recent.mean()), 2)
    return round(float(recent.mean() - previous.mean()), 2), round(float(recent.mean()), 2)


def _add_driver(drivers: list[dict], name: str, severity: str, detail: str, value=None) -> None:
    drivers.append({"name": name, "severity": severity, "detail": detail, "value": value})


def _status_from_score(score: float | None) -> str:
    if score is None:
        return "insufficient data"
    if score >= 80:
        return "good"
    if score >= 65:
        return "normal"
    if score >= 45:
        return "strained"
    return "poor"


def analyze_recovery_signal(
    recovery_df: pd.DataFrame,
    training_df: pd.DataFrame | None = None,
    nutrition_df: pd.DataFrame | None = None,
    target_calories=2850,
    performance_signal: dict | None = None,
    workload_data: dict | None = None,
) -> dict:
    """Return a nutrition-facing recovery/readiness signal with explainable drivers."""
    if recovery_df is None or recovery_df.empty:
        return dict(RECOVERY_SIGNAL_EMPTY)

    df = recovery_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return dict(RECOVERY_SIGNAL_EMPTY)

    training_df = training_df if training_df is not None else pd.DataFrame()
    nutrition_df = nutrition_df if nutrition_df is not None else pd.DataFrame()
    if not nutrition_df.empty and "calories" not in nutrition_df.columns and "total_calories" in nutrition_df.columns:
        nutrition_df = nutrition_df.copy()
        nutrition_df["calories"] = nutrition_df["total_calories"]

    analytics = calculate_recovery_score(
        recovery_df=df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        target_calories=target_calories,
    )

    latest_score = None
    metrics = {}
    drivers: list[dict] = []
    if not analytics.empty:
        latest = analytics.sort_values("date").iloc[-1]
        latest_score = float(latest["recovery_score"])
        metrics.update(
            {
                "sleep_debt": float(latest["sleep_debt"]),
                "fatigue_load": float(latest["fatigue_load"]),
                "training_stress": float(latest["training_stress"]),
                "calorie_deficit": float(latest["calorie_deficit"]),
            }
        )
        if latest["sleep_debt"] >= 8:
            _add_driver(drivers, "Sleep debt", "poor", f"Rolling sleep debt is {latest['sleep_debt']:.1f} hours.", round(float(latest["sleep_debt"]), 1))
        elif latest["sleep_debt"] >= 4:
            _add_driver(drivers, "Sleep debt", "strained", f"Sleep debt is building at {latest['sleep_debt']:.1f} hours.", round(float(latest["sleep_debt"]), 1))
        if latest["fatigue_load"] >= 7:
            _add_driver(drivers, "Fatigue and soreness", "poor", f"Subjective fatigue/soreness load is {latest['fatigue_load']:.1f}/10.", round(float(latest["fatigue_load"]), 1))
        elif latest["fatigue_load"] >= 6:
            _add_driver(drivers, "Fatigue and soreness", "strained", f"Subjective fatigue/soreness load is elevated at {latest['fatigue_load']:.1f}/10.", round(float(latest["fatigue_load"]), 1))
        if latest["training_stress"] >= 35:
            _add_driver(drivers, "Training load", "strained", f"Recent training stress is elevated at {latest['training_stress']:.1f}.", round(float(latest["training_stress"]), 1))

    sleep_delta, sleep_avg = _trend_delta(df, "sleep_hours")
    if sleep_avg is not None:
        metrics["sleep_7_day_avg"] = sleep_avg
        if sleep_avg < 6.5:
            _add_driver(drivers, "Sleep duration", "poor", f"Sleep is averaging {sleep_avg:.1f} hours recently.", sleep_avg)
        elif sleep_avg < 7:
            _add_driver(drivers, "Sleep duration", "strained", f"Sleep is averaging {sleep_avg:.1f} hours recently.", sleep_avg)
    if sleep_delta is not None and sleep_delta <= -0.5:
        _add_driver(drivers, "Sleep trend", "strained", f"Sleep is down {abs(sleep_delta):.1f} hours versus the prior window.", sleep_delta)

    hrv_delta, hrv_avg = _trend_delta(df, "hrv")
    if hrv_avg is not None:
        metrics["hrv_7_day_avg"] = hrv_avg
        hrv_values = _numeric_series(df, "hrv")
        baseline = float(hrv_values.iloc[:-7].mean()) if len(hrv_values) >= 14 else None
        if baseline and hrv_avg < baseline * 0.85:
            _add_driver(drivers, "HRV", "poor", f"HRV is more than 15% below baseline ({hrv_avg:.1f} vs {baseline:.1f}).", hrv_avg)
        elif baseline and hrv_avg < baseline * 0.95:
            _add_driver(drivers, "HRV", "strained", f"HRV is below baseline ({hrv_avg:.1f} vs {baseline:.1f}).", hrv_avg)

    rhr_delta, rhr_avg = _trend_delta(df, "resting_hr")
    if rhr_avg is not None:
        metrics["resting_hr_7_day_avg"] = rhr_avg
        rhr_values = _numeric_series(df, "resting_hr")
        baseline = float(rhr_values.iloc[:-7].mean()) if len(rhr_values) >= 14 else None
        if baseline and rhr_avg > baseline + 6:
            _add_driver(drivers, "Resting heart rate", "poor", f"Resting HR is {rhr_avg:.0f} bpm, over 6 bpm above baseline.", rhr_avg)
        elif baseline and rhr_avg > baseline + 3:
            _add_driver(drivers, "Resting heart rate", "strained", f"Resting HR is {rhr_avg:.0f} bpm, above baseline.", rhr_avg)

    performance_label = str((performance_signal or {}).get("label") or "insufficient data")
    if performance_label in {"declining", "fatigue/performance stagnation"}:
        _add_driver(drivers, "Workout performance", "strained", f"Hevy performance is {performance_label}.", performance_label)

    workload_current = (workload_data or {}).get("current", {})
    if str(workload_current.get("recovery_demand") or "") == "high":
        _add_driver(drivers, "Training/running demand", "strained", "Recent Hevy/Strava workload is creating high recovery demand.", "high")

    status = _status_from_score(latest_score)
    poor_count = sum(driver["severity"] == "poor" for driver in drivers)
    strained_count = sum(driver["severity"] == "strained" for driver in drivers)
    if poor_count >= 2:
        status = "poor"
    elif status not in {"poor"} and (poor_count == 1 or strained_count >= 2):
        status = "strained"
    elif status == "insufficient data" and drivers:
        status = "strained"

    data_points = int(len(df))
    confidence = "high" if data_points >= 14 else "medium" if data_points >= 7 else "low"
    if latest_score is None and not drivers:
        confidence = "low"

    if status == "good":
        summary = "Recovery looks good and should support normal training."
        implication = "No recovery-driven macro increase is needed."
        action = "Maintain macros unless bodyweight trend moves outside target."
    elif status == "normal":
        summary = "Recovery is normal with no major nutrition red flags."
        implication = "Keep targets steady and keep carbs placed around harder sessions."
        action = "Maintain current nutrition plan."
    elif status == "strained":
        summary = "Recovery is strained; watch sleep, soreness, and recent workload."
        implication = "Use carbs around training and avoid aggressive calorie cuts."
        action = "Prioritize sleep and manage accessory/cardio volume."
    elif status == "poor":
        summary = "Recovery is poor enough to influence nutrition recommendations."
        implication = "If weight gain is slow or performance is dropping, a small carb-focused increase may help; if weight gain is fast, address recovery load first."
        action = "Prioritize sleep/recovery and review high-volume accessories or extra cardio."
    else:
        summary = RECOVERY_SIGNAL_EMPTY["summary"]
        implication = RECOVERY_SIGNAL_EMPTY["nutrition_implication"]
        action = RECOVERY_SIGNAL_EMPTY["suggested_action"]

    severity_rank = {"poor": 0, "strained": 1, "normal": 2, "good": 3}
    drivers = sorted(drivers, key=lambda item: (severity_rank.get(item["severity"], 9), item["name"]))[:6]
    return {
        "status": status,
        "confidence": confidence,
        "score": round(latest_score, 1) if latest_score is not None else None,
        "summary": summary,
        "nutrition_implication": implication,
        "suggested_action": action,
        "drivers": drivers,
        "metrics": metrics,
    }
