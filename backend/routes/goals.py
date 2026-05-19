"""Goals and nutrition target API routes."""

import copy
import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel
import pandas as pd

from src.analytics.food_history import get_finalized_nutrition_history
from src.analytics.training_workload import analyze_training_workload
from src.body_metrics import load_body_metrics
from src.goals import build_automatic_goals, load_user_goals, save_user_goals
from src.nutrition_targets import analyze_weight_trend, calculate_macro_targets, load_nutrition_targets, save_nutrition_targets
from src.optimization.adaptive_nutrition_engine import (
    append_nutrition_recommendation_history,
    build_adaptive_nutrition_recommendation,
    load_nutrition_recommendation_history,
)
from src.optimization.lean_bulk_engine import generate_lean_bulk_calorie_recommendation
from src.recovery import load_recovery_log, load_sleep_entries
from src.training import TRAINING_COLUMNS, load_recent_training_log, recent_training_window, training_raw_window_days


router = APIRouter(tags=["goals"])
logger = logging.getLogger(__name__)
GOALS_TRAINING_DAYS = 90
WORKLOAD_TRAINING_DAYS = 84
GOALS_CACHE_TTL_SECONDS = 60
_GOALS_RESPONSE_CACHE: dict[str, object] = {"expires_at": 0.0, "payload": None}


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


def _safe_goal_block(name: str, fallback, fn, debug: list[dict]):
    started = time.perf_counter()
    try:
        value = fn()
        debug.append({"name": name, "status": "ok", "duration_ms": round((time.perf_counter() - started) * 1000, 1)})
        return value
    except Exception as exc:
        logger.exception("[goals] %s failed", name)
        debug.append(
            {
                "name": name,
                "status": "error",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        return fallback() if callable(fallback) else fallback


def _fallback_targets(goals: dict) -> dict:
    calories = int(round(float(goals.get("target_calories") or goals.get("calories") or 2500)))
    bodyweight = float(goals.get("current_bodyweight") or 180)
    protein = int(round(max(150, bodyweight)))
    fat = int(round(max(55, calories * 0.25 / 9)))
    carbs = int(round(max(0, (calories - protein * 4 - fat * 9) / 4)))
    return {
        "target_calories": calories,
        "protein_grams": protein,
        "carb_grams": carbs,
        "fat_grams": fat,
        "macro_calories": int(protein * 4 + carbs * 4 + fat * 9),
        "calorie_macro_delta": int(protein * 4 + carbs * 4 + fat * 9 - calories),
        "strategy": "fallback",
        "target_description": "Safe fallback targets loaded because goal analytics were unavailable.",
    }


def _goal_response(goals: dict, *, include_training: bool = False) -> dict:
    started = time.perf_counter()
    debug: list[dict] = []
    warnings: list[str] = []
    logger.info("[goals] response started include_training=%s", include_training)

    body_metrics = _safe_goal_block("load_body_metrics", lambda: pd.DataFrame(), load_body_metrics, debug)
    nutrition_summary = _safe_goal_block("load_finalized_nutrition_summary", lambda: pd.DataFrame(), lambda: get_finalized_nutrition_history(60), debug)
    active_targets = _safe_goal_block("load_nutrition_targets", lambda: None, load_nutrition_targets, debug)

    training_log = pd.DataFrame(columns=TRAINING_COLUMNS)
    workload_training = pd.DataFrame(columns=TRAINING_COLUMNS)
    if include_training:
        training_log = _safe_goal_block(
            f"load_recent_training_log_{GOALS_TRAINING_DAYS}d",
            lambda: pd.DataFrame(columns=TRAINING_COLUMNS),
            lambda: load_recent_training_log(days=GOALS_TRAINING_DAYS, max_rows=10000),
            debug,
        )
        training_log = recent_training_window(training_log, GOALS_TRAINING_DAYS)
        workload_training = recent_training_window(training_log, WORKLOAD_TRAINING_DAYS)
    else:
        warnings.append("Training-derived goal personalization skipped on startup for fast load.")
        debug.append({"name": "load_training_log", "status": "skipped", "duration_ms": 0, "rows": 0})

    goals = _safe_goal_block(
        "build_automatic_goals",
        goals,
        lambda: build_automatic_goals(goals, body_metrics_df=body_metrics, training_df=training_log),
        debug,
    )
    workload = _safe_goal_block(
        "analyze_training_workload",
        lambda: {"current": {}},
        lambda: analyze_training_workload(workload_training, bodyweight=goals.get("current_bodyweight", 180)),
        debug,
    )
    if active_targets:
        base_targets = active_targets
        debug.append({"name": "calculate_macro_targets", "status": "skipped", "duration_ms": 0, "reason": "using saved active targets"})
    else:
        base_targets = _safe_goal_block(
            "calculate_macro_targets",
            lambda: _fallback_targets(goals),
            lambda: calculate_macro_targets(
                goals,
                nutrition_df=nutrition_summary,
                training_df=training_log,
                recovery_df=None,
                body_metrics_df=body_metrics,
                workload_data=workload,
            ),
            debug,
        )
    targets = active_targets or base_targets
    if not active_targets:
        _safe_goal_block("save_nutrition_targets", lambda: None, lambda: save_nutrition_targets(targets), debug)
    response = {
        "goals": goals,
        "targets": targets,
        "base_targets": base_targets,
        "training_workload": workload,
        "weight_feedback": _safe_goal_block("analyze_weight_trend", lambda: {}, lambda: analyze_weight_trend(body_metrics, goals), debug),
        "adaptive_recommendation": {
            "confidence": "deferred",
            "reasoning": ["Advanced adaptive nutrition hydrates from the dashboard after startup."],
            "recommendedTargets": targets,
            "currentTarget": targets,
        },
        "recommendation_history": [],
        "lean_bulk_decision": {
            "status": "deferred",
            "message": "Lean-bulk decision analysis is deferred until after startup.",
            "recommended_target_calories": targets.get("target_calories"),
        },
        "debug": {
            "status": "degraded" if any(item.get("status") == "error" for item in debug) else "ok",
            "warnings": warnings,
            "checks": debug,
            "counts": {
                "nutrition_rows": len(nutrition_summary) if isinstance(nutrition_summary, pd.DataFrame) else 0,
                "body_metric_rows": len(body_metrics) if isinstance(body_metrics, pd.DataFrame) else 0,
                "training_rows": len(training_log) if isinstance(training_log, pd.DataFrame) else 0,
            },
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }
    logger.info("[goals] response completed in %.1f ms checks=%s", (time.perf_counter() - started) * 1000, debug)
    return response


def _calculate_suggested_targets(goals: dict):
    body_metrics = load_body_metrics()
    nutrition_summary = get_finalized_nutrition_history(60)
    training_log = load_recent_training_log(days=training_raw_window_days(), max_rows=20000)
    recovery_log = load_recovery_log()
    sleep_log = load_sleep_entries()
    goals = build_automatic_goals(goals, body_metrics_df=body_metrics, training_df=training_log)
    active_targets = load_nutrition_targets()
    workload = analyze_training_workload(training_log, bodyweight=goals["current_bodyweight"])
    base_targets = calculate_macro_targets(
        goals,
        nutrition_df=nutrition_summary,
        training_df=training_log,
        recovery_df=recovery_log,
        body_metrics_df=body_metrics,
        workload_data=workload,
    )
    current_targets = active_targets or base_targets
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
    return recommended_targets, nutrition_summary, adaptive_recommendation


@router.get("/api/goals")
def get_goals() -> dict:
    """Return saved goals, calculated targets, and trend feedback."""
    now = time.monotonic()
    cached = _GOALS_RESPONSE_CACHE.get("payload")
    if cached is not None and now < float(_GOALS_RESPONSE_CACHE.get("expires_at") or 0):
        logger.info("Goals response served from cache.")
        return copy.deepcopy(cached)
    response = _goal_response(load_user_goals(), include_training=False)
    _GOALS_RESPONSE_CACHE["payload"] = copy.deepcopy(response)
    _GOALS_RESPONSE_CACHE["expires_at"] = now + GOALS_CACHE_TTL_SECONDS
    return response


@router.post("/api/goals")
def update_goals(payload: GoalPayload) -> dict:
    """Save goals locally and return recalculated targets."""
    _GOALS_RESPONSE_CACHE["payload"] = None
    _GOALS_RESPONSE_CACHE["expires_at"] = 0.0
    goals = save_user_goals(payload.model_dump())
    return _goal_response(goals, include_training=False)


@router.post("/api/goals/apply-suggested-macros")
def apply_suggested_macros() -> dict:
    """Persist the currently suggested macro targets as active daily targets."""
    _GOALS_RESPONSE_CACHE["payload"] = None
    _GOALS_RESPONSE_CACHE["expires_at"] = 0.0
    goals = load_user_goals()
    previous_targets = load_nutrition_targets()
    targets, nutrition_summary, adaptive_recommendation = _calculate_suggested_targets(goals)
    save_nutrition_targets(targets)
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
