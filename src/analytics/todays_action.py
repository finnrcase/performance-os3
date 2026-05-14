"""Single daily action recommendation for the dashboard."""

from __future__ import annotations

import pandas as pd


def _latest_sleep_hours(sleep_df: pd.DataFrame) -> float | None:
    if sleep_df is None or sleep_df.empty:
        return None
    df = sleep_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return None
    if "durationMinutes" in df.columns:
        minutes = pd.to_numeric(df["durationMinutes"], errors="coerce").dropna()
        if not minutes.empty:
            return round(float(minutes.iloc[-1]) / 60, 2)
    if "sleep_hours" in df.columns:
        hours = pd.to_numeric(df["sleep_hours"], errors="coerce").dropna()
        if not hours.empty:
            return round(float(hours.iloc[-1]), 2)
    return None


def _nutrition_adherence_status(adherence: dict | None) -> str:
    if not adherence:
        return "missing"
    consistency = adherence.get("consistency_score")
    calorie_delta = adherence.get("average_calories_delta")
    try:
        consistency_value = float(consistency)
    except (TypeError, ValueError):
        consistency_value = 0
    try:
        delta_value = abs(float(calorie_delta))
    except (TypeError, ValueError):
        delta_value = 0
    if consistency_value >= 85 and delta_value <= 150:
        return "strong"
    if consistency_value >= 70 or delta_value <= 250:
        return "ok"
    return "off"


def generate_todays_action(
    workout_quality: dict,
    recovery_tile: dict,
    sleep_df: pd.DataFrame,
    weight_feedback: dict,
    nutrition_adherence: dict,
    training_workload: dict,
    adaptive_recommendation: dict,
) -> dict:
    """Return one compact action from the strongest current signal."""
    workout_status = str((workout_quality or {}).get("status") or "missing")
    workout_score = (workout_quality or {}).get("score")
    recovery_status = str((adaptive_recommendation or {}).get("signals", {}).get("recovery", {}).get("status") or "").lower()
    recovery_score = (recovery_tile or {}).get("latest_score")
    sleep_hours = _latest_sleep_hours(sleep_df)
    weight_status = str((weight_feedback or {}).get("status") or "").lower()
    adherence_status = _nutrition_adherence_status(nutrition_adherence)
    workload_current = (training_workload or {}).get("current", {})
    recovery_demand = str(workload_current.get("recovery_demand") or "").lower()
    running = (adaptive_recommendation or {}).get("signals", {}).get("runningLoad", {})
    training = (adaptive_recommendation or {}).get("signals", {}).get("trainingLoad", {})
    running_load = str(running.get("status") or "").lower()
    training_load = str(training.get("status") or "").lower()
    performance = str((adaptive_recommendation or {}).get("signals", {}).get("performance", {}).get("label") or "").lower()

    if recovery_status == "poor" or (sleep_hours is not None and sleep_hours < 6.25 and recovery_demand == "high"):
        return {
            "status": "recover",
            "color": "red",
            "headline": "Prioritize recovery",
            "reason": "Recovery is not keeping up with recent load, so sleep and load management matter more than pushing today.",
        }

    if recovery_status == "strained" and (training_load in {"high", "unusually high"} or running_load in {"high", "unusually high"}):
        return {
            "status": "caution",
            "color": "yellow",
            "headline": "Protect recovery",
            "reason": "Recovery is strained while training or running load is elevated.",
        }

    if workout_status == "missing":
        return {
            "status": "missing",
            "color": "gray",
            "headline": "Complete today's workout",
            "reason": "No Hevy or Strava session is logged yet today.",
        }

    if performance in {"declining", "fatigue/performance stagnation"} and recovery_status in {"strained", "poor"}:
        return {
            "status": "caution",
            "color": "yellow",
            "headline": "Add carbs around training",
            "reason": "Performance has dipped and recovery is strained, so keep support near the session before changing more.",
        }

    if weight_status in {"on track", "gaining in target range"} and adherence_status in {"strong", "ok"}:
        return {
            "status": "maintain",
            "color": "yellow",
            "headline": "Hold macros",
            "reason": "Weight gain and nutrition adherence are close enough to target.",
        }

    if workout_score is not None and float(workout_score) >= 8 and recovery_status in {"good", "normal", ""}:
        return {
            "status": "push",
            "color": "green",
            "headline": "Push today",
            "reason": "Workout quality is strong and recovery does not show a major limiter.",
        }

    if running_load in {"high", "unusually high"}:
        return {
            "status": "maintain",
            "color": "yellow",
            "headline": "Keep carbs available",
            "reason": "Running load is elevated, so keep fueling focused around training.",
        }

    if recovery_score is None and sleep_hours is None and workout_status in {"low_history", "scored"}:
        return {
            "status": "missing",
            "color": "gray",
            "headline": "Log recovery tonight",
            "reason": "Workout data is available, but sleep and recovery context are still missing.",
        }

    return {
        "status": "maintain",
        "color": "yellow",
        "headline": "Stay the course",
        "reason": "No single signal is strong enough to change the plan today.",
    }
