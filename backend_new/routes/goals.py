from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend_new.db import fetch_latest_document, insert_json_row
from backend_new.services.recommendation_service import (
    calculate_targets,
    canonical_goals,
    current_targets,
    fallback_goals as service_fallback_goals,
    lightweight_recommendation_preview,
    saved_goals,
    title_option,
)
from backend_new.utils import utc_now_iso
from src.nutrition_targets import analyze_weight_trend

router = APIRouter(tags=["goals"])


def fallback_goals() -> dict[str, Any]:
    return service_fallback_goals()


def _title_option(value: Any, fallback: str) -> str:
    return title_option(value, fallback)


def _canonical_goals(goals: dict[str, Any]) -> dict[str, Any]:
    return canonical_goals(goals)


def _simple_targets(goals: dict[str, Any], stored_targets: dict[str, Any]) -> dict[str, Any]:
    return current_targets(goals, stored_targets)


def _saved_goals() -> dict[str, Any]:
    return saved_goals()


def goals_payload() -> dict[str, Any]:
    goals = _saved_goals()
    targets = current_targets(goals)
    weight_feedback = analyze_weight_trend(None, _canonical_goals(goals))
    preview = lightweight_recommendation_preview(goals, targets)
    confidence = preview["confidence"]
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
            **preview,
            "confidence": confidence,
            "confidenceLevel": confidence["overall"],
            "reasoning": ["Goals use the shared canonical target framework. Run the recommendation engine for the next suggested update."],
            "recommendedTargets": targets,
            "currentTarget": targets,
        },
        "adaptive_recommendation_preview": preview,
        "recommendation_trace": preview["recommendation_trace"],
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
