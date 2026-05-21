from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend_new.db import fetch_latest_document, insert_json_row
from backend_new.utils import utc_now_iso
from src.nutrition_targets import analyze_weight_trend, calculate_macro_targets

router = APIRouter(tags=["goals"])


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


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


def _title_option(value: Any, fallback: str) -> str:
    normalized = str(value or fallback).replace("_", " ").strip().lower()
    known = {
        "lean bulk": "Lean Bulk",
        "fat loss": "Cut",
        "cut": "Cut",
        "maintenance": "Maintain",
        "maintain": "Maintain",
        "recomposition": "Recomposition",
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


def _canonical_goals(goals: dict[str, Any]) -> dict[str, Any]:
    return {
        **goals,
        "goal_type": _title_option(goals.get("goal_type"), "Lean Bulk"),
        "activity_level": _title_option(goals.get("activity_level"), "Moderate"),
        "aggressiveness": _title_option(goals.get("aggressiveness"), "Conservative"),
    }


def calculate_targets(goals: dict[str, Any]) -> dict[str, Any]:
    canonical = _canonical_goals({**fallback_goals(), **(goals or {})})
    targets = calculate_macro_targets(canonical)
    return {**targets, "updated_at": targets.get("updated_at") or utc_now_iso()}


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


def _simple_targets(goals: dict[str, Any], stored_targets: dict[str, Any]) -> dict[str, Any]:
    calculated = calculate_targets(goals)
    if not isinstance(stored_targets, dict) or "_db_error" in stored_targets:
        return calculated
    for field in TARGET_FIELDS:
        if field in stored_targets and stored_targets[field] not in {None, ""}:
            calculated[field] = stored_targets[field]
    return calculated


def _saved_goals() -> dict[str, Any]:
    stored = fetch_latest_document("user_goal_settings", fallback_goals())
    return {**fallback_goals(), **stored} if isinstance(stored, dict) else fallback_goals()


def goals_payload() -> dict[str, Any]:
    goals = _saved_goals()
    stored_targets = fetch_latest_document("macro_targets", {})
    targets = _simple_targets(goals, stored_targets)
    weight_feedback = analyze_weight_trend(None, _canonical_goals(goals))
    confidence = {
        "nutrition": "low",
        "body": "low",
        "training": "low",
        "recovery": "low",
        "overall": "low",
        "missing_data": ["Run the recommendation engine to refresh structured confidence."],
    }
    return {
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "training_workload": {
            "status": "deferred",
            "summary": "Training workload is not used in backend_new goals.",
            "current": {},
        },
        "weight_feedback": weight_feedback,
        "lean_bulk_decision": {
            "status": "deferred",
            "message": "Lean bulk analysis runs only from the explicit recommendation engine.",
            "recommended_target_calories": targets.get("target_calories"),
        },
        "adaptive_recommendation": {
            "confidence": confidence,
            "confidenceLevel": confidence["overall"],
            "reasoning": ["Goals use the shared canonical target framework. Run the recommendation engine for the next suggested update."],
            "recommendedTargets": targets,
            "currentTarget": targets,
        },
        "recommendation_history": [],
        "debug": {
            "status": "ok",
            "mode": "backend_new_lightweight",
            "analytics_called": False,
            "hevy_history_scanned": False,
        },
    }


@router.get("/api/goals")
def get_goals() -> dict[str, Any]:
    return goals_payload()


@router.put("/api/goals")
def put_goals(payload: dict[str, Any]) -> dict[str, Any]:
    goals = {**_saved_goals(), **payload, "updated_at": utc_now_iso()}
    targets = calculate_targets(goals)
    insert_json_row("user_goal_settings", goals)
    insert_json_row("macro_targets", targets)
    return goals_payload()


@router.post("/api/goals/apply-suggested-macros")
def apply_suggested_macros() -> dict[str, Any]:
    latest = fetch_latest_document("nutrition_recommendation_history", {})
    adaptive = latest.get("adaptive_recommendation") if isinstance(latest, dict) else None
    recommended = adaptive.get("recommendedTargets") if isinstance(adaptive, dict) else None
    targets = recommended if isinstance(recommended, dict) and recommended.get("target_calories") else calculate_targets(_saved_goals())
    saved = insert_json_row("macro_targets", {**targets, "updated_at": utc_now_iso()})
    return {
        "status": "ok",
        "message": "Canonical macro targets applied.",
        "source": "latest_recommendation" if recommended else "canonical_goals",
        "targets": saved if isinstance(saved, dict) and "_db_error" not in saved else targets,
    }
