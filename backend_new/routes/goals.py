from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend_new.db import fetch_latest_document, insert_json_row
from backend_new.utils import utc_now_iso

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


def _activity_multiplier(activity_level: str) -> float:
    normalized = str(activity_level or "").strip().lower()
    if normalized in {"low", "light", "sedentary"}:
        return 14.0
    if normalized in {"high", "very_active", "very active"}:
        return 17.0
    return 15.5


def calculate_targets(goals: dict[str, Any]) -> dict[str, Any]:
    bodyweight = max(80.0, _to_float(goals.get("current_bodyweight"), 180.0))
    goal_type = str(goals.get("goal_type") or "lean_bulk").strip().lower()
    maintenance = round(bodyweight * _activity_multiplier(str(goals.get("activity_level") or "moderate")))
    if "cut" in goal_type or "fat_loss" in goal_type:
        adjustment = -250
        expected_change = -0.5
    elif "maintain" in goal_type:
        adjustment = 0
        expected_change = 0
    else:
        adjustment = 150
        expected_change = 0.25
    calories = max(1600, round(maintenance + adjustment))
    protein = round(min(max(bodyweight * 1.1, bodyweight), bodyweight * 1.2))
    fat = round(max(bodyweight * 0.3, 50))
    carbs = round(max(100, (calories - protein * 4 - fat * 9) / 4))
    return {
        "target_calories": calories,
        "maintenance_calories": maintenance,
        "calorie_adjustment": adjustment,
        "protein_grams": protein,
        "carb_grams": carbs,
        "fat_grams": fat,
        "expected_weekly_weight_change": expected_change,
        "target_description": "Simple conservative target from current bodyweight and goal type.",
        "timeline_status": "unknown",
        "timeline_warning": "",
        "updated_at": utc_now_iso(),
    }


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
    return {
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "training_workload": {
            "status": "deferred",
            "summary": "Training workload is not used in backend_new goals.",
            "current": {},
        },
        "weight_feedback": {
            "status": "deferred",
            "suggested_adjustment": "hold",
            "confidence": "low",
            "message": "Weight feedback is deferred until lightweight trend endpoints are enabled.",
        },
        "lean_bulk_decision": {
            "status": "deferred",
            "message": "Lean bulk analysis is deferred; using simple conservative targets.",
            "recommended_target_calories": targets.get("target_calories"),
        },
        "adaptive_recommendation": {
            "confidence": "deferred",
            "reasoning": ["Heavy adaptive analytics are disabled in backend_new."],
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
