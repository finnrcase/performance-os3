from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend_new.db import fetch_json_rows, fetch_latest_document
from backend_new.utils import utc_now_iso
from src.nutrition_targets import calculate_macro_targets

logger = logging.getLogger(__name__)


def _rows_to_df(table: str, limit: int = 400) -> pd.DataFrame:
    """Load recent JSONB rows from Postgres into a DataFrame for the calorie engine.

    Returns an empty DataFrame on any error so target calculation never breaks
    on a transient DB issue (the engine then degrades to the profile estimate).
    """
    try:
        rows = fetch_json_rows(table, limit=limit, date_field="date")
        clean = [row for row in rows if isinstance(row, dict) and "_db_error" not in row]
        return pd.DataFrame(clean) if clean else pd.DataFrame()
    except Exception:
        logger.exception("Failed to load %s for the calorie engine.", table)
        return pd.DataFrame()


TARGET_FIELDS = {
    "target_calories",
    "maintenance_calories",
    "calorie_adjustment",
    "protein_grams",
    "carb_grams",
    "fat_grams",
    "expected_weekly_weight_change",
    "target_description",
    "timeline_status",
    "timeline_warning",
    "updated_at",
}


def fallback_goals() -> dict[str, Any]:
    return {
        "current_bodyweight": 180,
        "goal_bodyweight": 185,
        "timeline_weeks": 16,
        "goal_type": "lean_bulk",
        "training_frequency_per_week": 5,
        "cardio_frequency_per_week": 1,
        "estimated_body_fat": None,
        "activity_level": "moderate",
        "aggressiveness": "conservative",
    }


def title_option(value: Any, fallback: str) -> str:
    normalized = str(value or fallback).replace("_", " ").strip().lower()
    known = {
        "lean bulk": "Lean Bulk",
        "fat loss": "Cut",
        "cut": "Cut",
        "maintenance": "Maintain",
        "maintain": "Maintain",
        "recomposition": "Recomposition",
        "recomp": "Recomposition",
        "performance / mile time": "Performance / Mile Time",
        "performance": "Performance / Mile Time",
        "low": "Low",
        "light": "Low",
        "moderate": "Moderate",
        "high": "High",
        "very high": "Very High",
        "very active": "Very High",
        "conservative": "Conservative",
        "aggressive": "Aggressive",
    }
    return known.get(normalized, normalized.title() or fallback)


def canonical_goals(goals: dict[str, Any] | None) -> dict[str, Any]:
    merged = {**fallback_goals(), **(goals or {})}
    return {
        **merged,
        "goal_type": title_option(merged.get("goal_type"), "Lean Bulk"),
        "activity_level": title_option(merged.get("activity_level"), "Moderate"),
        "aggressiveness": title_option(merged.get("aggressiveness"), "Conservative"),
    }


def goal_family(goals: dict[str, Any] | None) -> str:
    normalized = str((goals or {}).get("goal_type") or "lean_bulk").replace("_", " ").strip().lower()
    if normalized in {"lean bulk", "bulk", "gain", "gain weight"}:
        return "lean_bulk"
    if normalized in {"cut", "fat loss", "lose weight", "weight loss"}:
        return "cut"
    if normalized in {"recomposition", "recomp", "body recomposition"}:
        return "recomp"
    if normalized in {"maintenance", "maintain", "hold"}:
        return "maintenance"
    return "performance" if "performance" in normalized else "maintenance"


def calculate_targets(goals: dict[str, Any] | None) -> dict[str, Any]:
    # Feed the adaptive calorie engine the production data it needs: wearable
    # energy burn (Fitbit/Google Health), logged nutrition, and weigh-ins all
    # live in Postgres JSONB tables, not the local CSVs that src.wearables reads.
    wearable_df = _rows_to_df("wearable_metrics")
    nutrition_df = _rows_to_df("food_logs", limit=2000)
    body_metrics_df = _rows_to_df("body_metric_logs")
    targets = calculate_macro_targets(
        canonical_goals(goals),
        nutrition_df=nutrition_df if not nutrition_df.empty else None,
        body_metrics_df=body_metrics_df if not body_metrics_df.empty else None,
        wearable_df=wearable_df if not wearable_df.empty else None,
    )
    return {**targets, "updated_at": targets.get("updated_at") or utc_now_iso()}


def saved_goals() -> dict[str, Any]:
    stored = fetch_latest_document("user_goal_settings", fallback_goals())
    return {**fallback_goals(), **stored} if isinstance(stored, dict) else fallback_goals()


def current_targets(goals: dict[str, Any] | None = None, stored_targets: dict[str, Any] | None = None) -> dict[str, Any]:
    calculated = calculate_targets(goals or saved_goals())
    targets = stored_targets if stored_targets is not None else fetch_latest_document("macro_targets", {})
    if not isinstance(targets, dict) or "_db_error" in targets:
        return calculated
    for field in TARGET_FIELDS:
        if field in targets and targets[field] not in {None, ""}:
            calculated[field] = targets[field]
    return calculated


def lightweight_recommendation_preview(goals: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    family = goal_family(goals)
    target_range = targets.get("target_weekly_change_range") or {}
    confidence = {
        "nutrition": "low",
        "body": "low",
        "training": "low",
        "recovery": "low",
        "overall": "low",
        "missing_data": ["Run the recommendation engine to refresh structured confidence."],
    }
    states = {
        "body_comp_state": "insufficient_data",
        "nutrition_state": "insufficient_data",
        "training_state": "insufficient_data",
        "recovery_state": "insufficient_data",
        "decision": "hold",
        "goal_type": family,
    }
    trace = {
        **states,
        "calorie_change": 0,
        "main_reasons": [
            "Goals uses saved/canonical targets only; the manual recommendation engine computes full adaptive changes.",
        ],
        "thresholds": {
            "weekly_weight_change_pct": targets.get("weekly_weight_change_pct"),
            "target_weekly_change_pct_range": [target_range.get("low"), target_range.get("high")],
            "fat_mass_trend_lb_per_week": None,
            "fat_gain_risk_threshold": 0.25,
            "lean_mass_trend_lb_per_week": None,
            "lean_gain_threshold": 0.08,
            "actual_avg_calories": None,
            "target_calories": targets.get("target_calories"),
        },
        "what_would_change_decision": [
            "Finalized nutrition, canonical weigh-ins, recent Hevy data, and recovery logs are required before changing targets.",
        ],
    }
    return {
        "confidence": confidence,
        "confidenceLevel": confidence["overall"],
        "states": states,
        "recommendation_trace": trace,
        "reasoning": trace["main_reasons"],
        "recommendedTargets": targets,
        "currentTarget": targets,
        "runs_on_startup": False,
        "mode": "lightweight_preview",
    }

