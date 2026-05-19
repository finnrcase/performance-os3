"""Local user goal storage and goal feasibility helpers."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pandas as pd

from src.analytics.training_workload import analyze_training_workload
from src.paths import processed_data_path
from src.storage import load_document, save_document

logger = logging.getLogger(__name__)
GOAL_TRAINING_WINDOW_DAYS = 90

USER_GOALS_PATH = processed_data_path("user_goals.json")

GOAL_TYPES = [
    "Lean Bulk",
    "Cut",
    "Maintain",
    "Recomposition",
    "Performance / Mile Time",
]
ACTIVITY_LEVELS = ["Low", "Moderate", "High", "Very High"]
AGGRESSIVENESS_LEVELS = ["Conservative", "Moderate", "Aggressive"]

DEFAULT_USER_GOALS = {
    "current_bodyweight": 180.0,
    "goal_bodyweight": 185.0,
    "timeline_weeks": 16,
    "goal_type": "Lean Bulk",
    "training_frequency_per_week": 4,
    "cardio_frequency_per_week": 2,
    "estimated_body_fat": None,
    "activity_level": "Moderate",
    "aggressiveness": "Conservative",
}


def _latest_bodyweight(body_metrics_df: pd.DataFrame | None, fallback: float) -> float:
    if body_metrics_df is None or body_metrics_df.empty:
        return float(fallback)
    df = body_metrics_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df["bodyweight"] = pd.to_numeric(df.get("bodyweight"), errors="coerce")
    df = df.dropna(subset=["date", "bodyweight"]).sort_values("date")
    return float(df.iloc[-1]["bodyweight"]) if not df.empty else float(fallback)


def _latest_body_fat(body_metrics_df: pd.DataFrame | None) -> float | None:
    if body_metrics_df is None or body_metrics_df.empty or "estimated_body_fat" not in body_metrics_df.columns:
        return None
    df = body_metrics_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df["estimated_body_fat"] = pd.to_numeric(df.get("estimated_body_fat"), errors="coerce")
    df = df.dropna(subset=["date", "estimated_body_fat"]).sort_values("date")
    return float(df.iloc[-1]["estimated_body_fat"]) if not df.empty else None


def build_automatic_goals(saved_goals: dict | None = None, body_metrics_df: pd.DataFrame | None = None, training_df: pd.DataFrame | None = None) -> dict:
    """Build the app's default conservative lean-bulk strategy from local logs."""
    started = time.perf_counter()
    saved = _coerce_goal_data(saved_goals)
    current_weight = _latest_bodyweight(body_metrics_df, saved["current_bodyweight"])
    analytics_training = _recent_training_window(training_df, GOAL_TRAINING_WINDOW_DAYS)
    logger.info("build_automatic_goals training rows input=%s window=%s", 0 if training_df is None else len(training_df), len(analytics_training))
    workload = analyze_training_workload(analytics_training, bodyweight=current_weight)["current"]
    has_training_history = not analytics_training.empty
    strength_source = float(workload.get("strength_workouts_per_week") or 0) if has_training_history else DEFAULT_USER_GOALS["training_frequency_per_week"]
    cardio_source = float(workload.get("runs_per_week") or 0) if has_training_history else DEFAULT_USER_GOALS["cardio_frequency_per_week"]
    strength_days = max(0, min(7, round(strength_source)))
    cardio_days = max(0, min(7, round(cardio_source)))
    total_training_days = strength_days + cardio_days
    activity_level = "Very High" if total_training_days >= 7 else "High" if total_training_days >= 5 else "Moderate" if total_training_days >= 3 else "Low"
    result = {
        **saved,
        "current_bodyweight": current_weight,
        "goal_bodyweight": round(current_weight * 1.03, 1),
        "timeline_weeks": 24,
        "goal_type": "Lean Bulk",
        "training_frequency_per_week": strength_days,
        "cardio_frequency_per_week": cardio_days,
        "estimated_body_fat": _latest_body_fat(body_metrics_df),
        "activity_level": activity_level,
        "aggressiveness": "Conservative",
    }
    logger.info("build_automatic_goals completed in %.1f ms", (time.perf_counter() - started) * 1000)
    return result


def _recent_training_window(training_df: pd.DataFrame | None, days: int) -> pd.DataFrame:
    if training_df is None or training_df.empty:
        return pd.DataFrame()
    df = training_df.copy()
    parsed_dates = pd.to_datetime(df.get("date"), errors="coerce")
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    return df[parsed_dates >= cutoff].copy()


def _coerce_goal_data(data: dict | None) -> dict:
    """Return a stable goal dict with safe defaults."""
    goals = DEFAULT_USER_GOALS.copy()
    if data:
        goals.update(data)

    for key in [
        "current_bodyweight",
        "goal_bodyweight",
        "estimated_body_fat",
    ]:
        if goals.get(key) in ("", None):
            goals[key] = None if key == "estimated_body_fat" else DEFAULT_USER_GOALS[key]
        else:
            goals[key] = float(goals[key])

    for key in ["timeline_weeks", "training_frequency_per_week", "cardio_frequency_per_week"]:
        goals[key] = int(goals.get(key) or DEFAULT_USER_GOALS[key])

    if goals["goal_type"] not in GOAL_TYPES:
        goals["goal_type"] = DEFAULT_USER_GOALS["goal_type"]
    if goals["activity_level"] not in ACTIVITY_LEVELS:
        goals["activity_level"] = DEFAULT_USER_GOALS["activity_level"]
    if goals["aggressiveness"] not in AGGRESSIVENESS_LEVELS:
        goals["aggressiveness"] = DEFAULT_USER_GOALS["aggressiveness"]

    return goals


def load_user_goals() -> dict:
    """Load local user goals, returning defaults if no file exists yet."""
    return _coerce_goal_data(load_document("user_goals", USER_GOALS_PATH, DEFAULT_USER_GOALS))


def save_user_goals(goals: dict) -> dict:
    """Save local user goals and return the normalized saved shape."""
    normalized_goals = _coerce_goal_data(goals)
    return save_document("user_goals", USER_GOALS_PATH, normalized_goals)


def calculate_goal_feasibility(user_goals: dict) -> dict:
    """Estimate whether the user's requested timeline is conservative enough."""
    goals = _coerce_goal_data(user_goals)
    current_weight = float(goals["current_bodyweight"])
    goal_weight = float(goals["goal_bodyweight"])
    timeline_weeks = max(int(goals["timeline_weeks"]), 1)
    goal_type = goals["goal_type"]
    aggressiveness = goals["aggressiveness"]

    total_change = goal_weight - current_weight
    weekly_change = total_change / timeline_weeks
    weekly_change_pct = (weekly_change / current_weight) * 100 if current_weight > 0 else 0.0

    lean_bulk_caps = {
        "Conservative": 0.25,
        "Moderate": 0.5,
        "Aggressive": 0.5,
    }
    cut_caps = {
        "Conservative": 0.5,
        "Moderate": 0.75,
        "Aggressive": 1.0,
    }

    status = "Feasible"
    warning = "Timeline aligns with a conservative fitness-oriented pace."
    expected_direction = "stable"

    if goal_type == "Lean Bulk":
        expected_direction = "gain"
        max_rate = lean_bulk_caps[aggressiveness]
        if weekly_change_pct > max_rate:
            status = "Timeline may be too aggressive"
            warning = (
                f"This requires about {weekly_change_pct:.2f}% bodyweight gain per week. "
                "That may increase fat gain risk for a lean bulk."
            )
        elif weekly_change <= 0:
            status = "Goal mismatch"
            warning = "Lean bulk goals usually target a slow bodyweight increase."
    elif goal_type == "Cut":
        expected_direction = "loss"
        loss_rate_pct = abs(weekly_change_pct)
        max_rate = cut_caps[aggressiveness]
        if weekly_change >= 0:
            status = "Goal mismatch"
            warning = "Cutting goals usually target a gradual bodyweight decrease."
        elif loss_rate_pct > max_rate:
            status = "Timeline may be too aggressive"
            warning = (
                f"This requires about {loss_rate_pct:.2f}% bodyweight loss per week. "
                "A slower cut may better protect training performance and lean mass."
            )
    elif goal_type in ["Maintain", "Recomposition", "Performance / Mile Time"]:
        expected_direction = "stable"
        if abs(weekly_change_pct) > 0.25:
            status = "Timeline may distract from the stated goal"
            warning = (
                "This goal type usually works best with a stable or slowly changing bodyweight."
            )

    return {
        "status": status,
        "warning": warning,
        "total_change": round(total_change, 2),
        "weekly_change": round(weekly_change, 2),
        "weekly_change_pct": round(weekly_change_pct, 3),
        "expected_direction": expected_direction,
    }
