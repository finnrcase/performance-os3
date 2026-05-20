from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.database import load_document, save_document
from backend.app.utils.helpers import to_float


router = APIRouter(tags=["goals"])


def fallback_goals() -> dict:
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


def fallback_targets(goals: dict | None = None) -> dict:
    bodyweight = to_float((goals or {}).get("current_bodyweight"), 180)
    calories = 2500
    protein = round(max(160, bodyweight))
    fat = 75
    carbs = round(max(200, (calories - protein * 4 - fat * 9) / 4))
    return {
        "target_calories": calories,
        "maintenance_calories": calories,
        "calorie_adjustment": 0,
        "protein_grams": protein,
        "carb_grams": carbs,
        "fat_grams": fat,
        "expected_weekly_weight_change": 0,
        "target_description": "Fallback target while advanced analytics are unavailable.",
        "timeline_status": "unknown",
        "timeline_warning": "",
    }


def goals_payload() -> dict:
    goals = load_document("user_goals", fallback_goals(), timeout_ms=750)
    if not goals:
        goals = fallback_goals()
    targets = load_document("nutrition_targets", fallback_targets(goals), timeout_ms=750) or fallback_targets(goals)
    return {
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "training_workload": {"status": "deferred", "summary": "Training workload is deferred in clean startup routes.", "current": {}},
        "weight_feedback": {"status": "deferred", "suggested_adjustment": "hold", "confidence": "low"},
        "adaptive_recommendation": {
            "confidence": "deferred",
            "reasoning": ["Advanced adaptive nutrition is not part of clean core startup."],
            "recommendedTargets": targets,
            "currentTarget": targets,
        },
        "recommendation_history": [],
        "lean_bulk_decision": {
            "status": "deferred",
            "message": "Lean-bulk analysis is deferred until v2 core endpoints are stable.",
            "recommended_target_calories": targets.get("target_calories"),
        },
        "debug": {
            "status": "ok",
            "mode": "clean_backend_lightweight",
            "counts": {},
        },
    }


@router.get("/api/goals")
def get_goals() -> dict:
    return goals_payload()


@router.post("/api/goals")
def update_goals(payload: dict) -> dict:
    current = load_document("user_goals", fallback_goals(), timeout_ms=750)
    save_document("user_goals", {**current, **payload}, timeout_ms=1000)
    return goals_payload()


@router.post("/api/goals/apply-suggested-macros")
def apply_suggested_macros() -> dict:
    goals = load_document("user_goals", fallback_goals(), timeout_ms=750)
    targets = load_document("nutrition_targets", fallback_targets(goals), timeout_ms=750) or fallback_targets(goals)
    save_document("nutrition_targets", targets, timeout_ms=1000)
    return {"status": "ok", "targets": targets}
