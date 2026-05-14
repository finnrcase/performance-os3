"""Goals and nutrition target API routes."""

from fastapi import APIRouter
from pydantic import BaseModel

from src.analytics.food_history import build_daily_nutrition_summary, save_daily_nutrition_summary
from src.analytics.training_workload import analyze_training_workload
from src.body_metrics import load_body_metrics
from src.goals import build_automatic_goals, load_user_goals, save_user_goals
from src.nutrition import load_nutrition_log
from src.nutrition_targets import analyze_weight_trend, calculate_macro_targets, load_nutrition_targets, save_nutrition_targets
from src.optimization.adaptive_nutrition_engine import (
    append_nutrition_recommendation_history,
    build_adaptive_nutrition_recommendation,
    load_nutrition_recommendation_history,
)
from src.optimization.lean_bulk_engine import generate_lean_bulk_calorie_recommendation
from src.recovery import load_recovery_log, load_sleep_entries
from src.training import load_training_log


router = APIRouter(tags=["goals"])


class GoalPayload(BaseModel):
    current_bodyweight: float
    goal_bodyweight: float
    timeline_weeks: int
    goal_type: str
    training_frequency_per_week: int
    cardio_frequency_per_week: int
    estimated_body_fat: float | None = None
    activity_level: str
    aggressiveness: str


def _goal_response(goals: dict) -> dict:
    body_metrics = load_body_metrics()
    nutrition_log = load_nutrition_log()
    training_log = load_training_log()
    recovery_log = load_recovery_log()
    sleep_log = load_sleep_entries()
    goals = build_automatic_goals(goals, body_metrics_df=body_metrics, training_df=training_log)
    active_targets = load_nutrition_targets()
    workload = analyze_training_workload(training_log, bodyweight=goals["current_bodyweight"])
    base_targets = calculate_macro_targets(
        goals,
        nutrition_df=nutrition_log,
        training_df=training_log,
        recovery_df=recovery_log,
        body_metrics_df=body_metrics,
        workload_data=workload,
    )
    targets = active_targets or base_targets
    if not active_targets:
        save_nutrition_targets(targets)
    nutrition_summary = build_daily_nutrition_summary(nutrition_log, targets)
    save_daily_nutrition_summary(nutrition_summary)
    adaptive_recommendation = build_adaptive_nutrition_recommendation(
        user_goals=goals,
        body_metrics_df=body_metrics,
        nutrition_df=nutrition_summary,
        training_df=training_log,
        recovery_df=recovery_log,
        current_targets=targets,
        sleep_df=sleep_log,
    )
    return {
        "goals": goals,
        "targets": targets,
        "base_targets": base_targets,
        "training_workload": workload,
        "weight_feedback": analyze_weight_trend(body_metrics, goals),
        "adaptive_recommendation": adaptive_recommendation,
        "recommendation_history": load_nutrition_recommendation_history(),
        "lean_bulk_decision": generate_lean_bulk_calorie_recommendation(
            body_metrics_df=body_metrics,
            nutrition_df=nutrition_summary,
            training_df=training_log,
            recovery_df=recovery_log,
            user_goals=goals,
        ),
    }


def _calculate_suggested_targets(goals: dict):
    body_metrics = load_body_metrics()
    nutrition_log = load_nutrition_log()
    training_log = load_training_log()
    recovery_log = load_recovery_log()
    sleep_log = load_sleep_entries()
    goals = build_automatic_goals(goals, body_metrics_df=body_metrics, training_df=training_log)
    active_targets = load_nutrition_targets()
    workload = analyze_training_workload(training_log, bodyweight=goals["current_bodyweight"])
    base_targets = calculate_macro_targets(
        goals,
        nutrition_df=nutrition_log,
        training_df=training_log,
        recovery_df=recovery_log,
        body_metrics_df=body_metrics,
        workload_data=workload,
    )
    current_targets = active_targets or base_targets
    nutrition_summary = build_daily_nutrition_summary(nutrition_log, current_targets)
    adaptive_recommendation = build_adaptive_nutrition_recommendation(
        user_goals=goals,
        body_metrics_df=body_metrics,
        nutrition_df=nutrition_summary,
        training_df=training_log,
        recovery_df=recovery_log,
        current_targets=current_targets,
        sleep_df=sleep_log,
    )
    recommended_targets = adaptive_recommendation["recommendedTargets"]
    nutrition_summary = build_daily_nutrition_summary(nutrition_log, recommended_targets)
    return recommended_targets, nutrition_summary, adaptive_recommendation


@router.get("/api/goals")
def get_goals() -> dict:
    """Return saved goals, calculated targets, and trend feedback."""
    return _goal_response(load_user_goals())


@router.post("/api/goals")
def update_goals(payload: GoalPayload) -> dict:
    """Save goals locally and return recalculated targets."""
    goals = save_user_goals(payload.model_dump())
    return _goal_response(goals)


@router.post("/api/goals/apply-suggested-macros")
def apply_suggested_macros() -> dict:
    """Persist the currently suggested macro targets as active daily targets."""
    goals = load_user_goals()
    previous_targets = load_nutrition_targets()
    targets, nutrition_summary, adaptive_recommendation = _calculate_suggested_targets(goals)
    save_nutrition_targets(targets)
    save_daily_nutrition_summary(nutrition_summary)
    append_nutrition_recommendation_history(
        {
            "source": "apply_suggested_macros",
            "previous_targets": previous_targets or adaptive_recommendation.get("currentTarget"),
            "applied_targets": targets,
            "calorieAdjustment": adaptive_recommendation.get("calorieAdjustment"),
            "macroAdjustment": adaptive_recommendation.get("macroAdjustment"),
            "dayType": adaptive_recommendation.get("dayType"),
            "confidence": adaptive_recommendation.get("confidence"),
            "dataQualityScore": adaptive_recommendation.get("dataQualityScore"),
            "reasoning": adaptive_recommendation.get("reasoning", []),
            "detectedTrends": adaptive_recommendation.get("detectedTrends", []),
            "missingDataWarnings": adaptive_recommendation.get("missingDataWarnings", []),
        }
    )
    return {
        "status": "ok",
        "message": "Suggested macros applied.",
        "targets": targets,
        "adaptive_recommendation": adaptive_recommendation,
    }
