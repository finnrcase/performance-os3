from __future__ import annotations

from datetime import date, timedelta
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter

from backend_new.db import fetch_json_rows, fetch_json_rows_for_value, fetch_latest_document, insert_json_row, upsert_json_row
from backend_new.routes.dashboard import dashboard_core
from backend_new.routes.goals import calculate_targets, fallback_goals
from backend_new.routes.nutrition import _is_excluded, _nutrition_value, _round, _target_payload, _today_iso, _totals
from backend_new.utils import utc_now_iso


router = APIRouter(tags=["recommendations"])

RAW_TRAINING_DAYS = 180
SUMMARY_LIMIT = 500
RAW_ROW_LIMIT = 5000


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _since(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _clean_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and "_db_error" not in row]


def _frame(rows: list[dict[str, Any]]) -> Any:
    import pandas as pd

    return pd.DataFrame(_clean_rows(rows))


def _engine_goals(goals: dict[str, Any]) -> dict[str, Any]:
    goal_type = str(goals.get("goal_type") or "lean_bulk").replace("_", " ").strip()
    return {
        **goals,
        "goal_type": "Lean Bulk" if goal_type.lower() == "lean bulk" else goal_type.title(),
        "activity_level": str(goals.get("activity_level") or "Moderate").replace("_", " ").title(),
        "aggressiveness": str(goals.get("aggressiveness") or "Conservative").replace("_", " ").title(),
    }


def _current_targets(targets: dict[str, Any], goals: dict[str, Any]) -> dict[str, Any]:
    if not targets or "_db_error" in targets:
        return calculate_targets(goals)
    calculated = calculate_targets(goals)
    return {
        **calculated,
        **{key: value for key, value in targets.items() if value is not None and value != ""},
    }


def _target_from_payload(targets: dict[str, Any]) -> dict[str, Any]:
    return {
        "target_calories": targets.get("calories"),
        "protein_grams": targets.get("protein"),
        "carb_grams": targets.get("carbs"),
        "fat_grams": targets.get("fat"),
    }


def _build_daily_summary(selected_date: str) -> dict[str, Any]:
    food_rows = [row for row in _clean_rows(fetch_json_rows_for_value("food_logs", "date", selected_date, limit=1000)) if not _is_excluded(row)]
    totals = _totals(food_rows)
    targets = _target_from_payload(_target_payload())
    total_calories = _nutrition_value(totals, "calories")
    total_protein = _nutrition_value(totals, "protein")
    total_carbs = _nutrition_value(totals, "carbs")
    total_fat = _nutrition_value(totals, "fat")
    target_calories = targets.get("target_calories")
    target_protein = targets.get("protein_grams")
    target_carbs = targets.get("carb_grams")
    target_fat = targets.get("fat_grams")
    return {
        "date": selected_date,
        "summary_id": f"nutrition-summary:{selected_date}",
        "finalized": True,
        "status": "finalized",
        "nutrition_logged": bool(food_rows),
        "logged_day": bool(food_rows),
        "items_count": len(food_rows),
        "total_calories": total_calories,
        "total_protein": total_protein,
        "total_carbs": total_carbs,
        "total_fat": total_fat,
        "fiber": totals.get("fiber"),
        "target_calories": target_calories,
        "target_protein": target_protein,
        "target_carbs": target_carbs,
        "target_fat": target_fat,
        "calories_delta": _round(total_calories - float(target_calories)) if target_calories else None,
        "protein_delta": _round(total_protein - float(target_protein)) if target_protein else None,
        "carbs_delta": _round(total_carbs - float(target_carbs)) if target_carbs else None,
        "fat_delta": _round(total_fat - float(target_fat)) if target_fat else None,
        "adherence_score": None,
        "notes": "Finalized from raw food logs. Missing days are not synthesized as zero.",
        "finalized_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }


def _finalize_day(selected_date: str) -> dict[str, Any]:
    summary = _build_daily_summary(selected_date)
    saved = upsert_json_row("daily_nutrition_summary", "date", selected_date, summary)
    return saved if isinstance(saved, dict) else summary


def _load_daily_summaries() -> list[dict[str, Any]]:
    summaries = _clean_rows(fetch_json_rows("daily_nutrition_summary", limit=SUMMARY_LIMIT, date_field="date"))
    finalized = [row for row in summaries if not _is_excluded(row) and (row.get("finalized") is True or str(row.get("status") or "") == "finalized")]
    finalized.sort(key=lambda row: str(row.get("date") or ""))
    return finalized


def _load_engine_inputs(selected_date: str, finalized_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    goals = _engine_goals({**fallback_goals(), **fetch_latest_document("user_goal_settings", {})})
    targets = _current_targets(fetch_latest_document("macro_targets", {}), goals)
    nutrition_rows = _load_daily_summaries()
    if finalized_summary and not any(str(row.get("date") or "") == selected_date for row in nutrition_rows):
        nutrition_rows.append(finalized_summary)
        nutrition_rows.sort(key=lambda row: str(row.get("date") or ""))
    return {
        "goals": goals,
        "targets": targets,
        "nutrition_rows": nutrition_rows,
        "training_rows": _clean_rows(fetch_json_rows("workout_logs", limit=RAW_ROW_LIMIT, date_field="date", since_date=_since(RAW_TRAINING_DAYS))),
        "weekly_training_summaries": _clean_rows(fetch_json_rows("weekly_training_summary", limit=SUMMARY_LIMIT, date_field="week_start")),
        "monthly_training_summaries": _clean_rows(fetch_json_rows("monthly_training_summary", limit=SUMMARY_LIMIT, date_field="month")),
        "body_rows": _clean_rows(fetch_json_rows("body_metric_logs", limit=1000, date_field="date", since_date=_since(RAW_TRAINING_DAYS))),
        "recovery_rows": _clean_rows(fetch_json_rows("recovery_logs", limit=1000, date_field="date", since_date=_since(RAW_TRAINING_DAYS))),
        "sleep_rows": _clean_rows(fetch_json_rows("sleep_logs", limit=1000, date_field="date", since_date=_since(RAW_TRAINING_DAYS))),
        "selected_date": selected_date,
    }


def _input_counts(inputs: dict[str, Any]) -> dict[str, int]:
    return {
        "finalized_daily_nutrition_summaries": len(inputs["nutrition_rows"]),
        "recent_raw_training_rows": len(inputs["training_rows"]),
        "weekly_training_summaries": len(inputs["weekly_training_summaries"]),
        "monthly_training_summaries": len(inputs["monthly_training_summaries"]),
        "body_metric_rows": len(inputs["body_rows"]),
        "recovery_rows": len(inputs["recovery_rows"]),
        "sleep_rows": len(inputs["sleep_rows"]),
    }


def _run_engine(inputs: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    from src.optimization.adaptive_nutrition_engine import build_adaptive_nutrition_recommendation
    from src.optimization.lean_bulk_engine import generate_lean_bulk_calorie_recommendation

    nutrition_df = _frame(inputs["nutrition_rows"])
    training_df = _frame(inputs["training_rows"])
    body_df = _frame(inputs["body_rows"])
    recovery_df = _frame(inputs["recovery_rows"])
    sleep_df = _frame(inputs["sleep_rows"])
    recommendation = build_adaptive_nutrition_recommendation(
        user_goals=inputs["goals"],
        body_metrics_df=body_df,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        current_targets=inputs["targets"],
        sleep_df=sleep_df,
        today=inputs["selected_date"],
    )
    lean_bulk = generate_lean_bulk_calorie_recommendation(
        body_metrics_df=body_df,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        user_goals=inputs["goals"],
    )
    return recommendation, lean_bulk


def _save_history(selected_date: str, recommendation: dict[str, Any], lean_bulk: dict[str, Any], input_counts: dict[str, int], trigger: str) -> dict[str, Any]:
    entry = {
        "recommendation_id": str(uuid4()),
        "date": selected_date,
        "trigger": trigger,
        "adaptive_recommendation": recommendation,
        "lean_bulk_decision": lean_bulk,
        "input_counts": input_counts,
        "created_at": utc_now_iso(),
    }
    return insert_json_row("nutrition_recommendation_history", entry)


def _dashboard_with_recommendation(recommendation: dict[str, Any], lean_bulk: dict[str, Any]) -> dict[str, Any]:
    dashboard = dashboard_core()
    dashboard["adaptive_recommendation"] = recommendation
    dashboard["lean_bulk_decision"] = lean_bulk
    dashboard["recommendation"] = {
        "recommendation_summary": recommendation.get("reasoning", ["Advanced recommendation refreshed."])[0],
        "reasoning_explanation": "Advanced recommendation loaded from explicit engine run.",
    }
    dashboard.setdefault("debug", {})["advanced_recommendation_loaded"] = True
    dashboard.setdefault("debug", {})["advanced_recommendation_runs_on_startup"] = False
    return dashboard


@router.post("/api/nutrition/finalize-day")
def finalize_nutrition_day(date: str | None = None) -> dict[str, Any]:
    selected_date = str(date or _today_iso())
    summary = _finalize_day(selected_date)
    return {
        "status": "ok",
        "message": "Daily nutrition summary finalized.",
        "summary": summary,
        "engine_ran": False,
    }


@router.post("/api/recommendations/run")
def run_recommendation_engine(date: str | None = None, finalize_day: bool = False, trigger: str = "manual") -> dict[str, Any]:
    started = time.perf_counter()
    selected_date = str(date or _today_iso())
    finalized_summary = _finalize_day(selected_date) if finalize_day else None
    inputs = _load_engine_inputs(selected_date, finalized_summary if isinstance(finalized_summary, dict) else None)
    input_counts = _input_counts(inputs)
    try:
        recommendation, lean_bulk = _run_engine(inputs)
        saved_history = _save_history(selected_date, recommendation, lean_bulk, input_counts, trigger)
        return {
            "status": "ok",
            "message": "Advanced recommendation engine completed.",
            "date": selected_date,
            "trigger": trigger,
            "finalized_summary": {"summary": finalized_summary} if finalized_summary else None,
            "adaptive_recommendation": recommendation,
            "lean_bulk_decision": lean_bulk,
            "dashboard": _dashboard_with_recommendation(recommendation, lean_bulk),
            "input_counts": input_counts,
            "history_entry": saved_history,
            "duration_ms": _duration_ms(started),
            "debug": {
                "runs_on_startup": False,
                "runs_after_food_write": False,
                "raw_training_days": RAW_TRAINING_DAYS,
                "full_hevy_scan": False,
                "external_api_calls": False,
            },
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": str(exc),
            "date": selected_date,
            "finalized_summary": {"summary": finalized_summary} if finalized_summary else None,
            "input_counts": input_counts,
            "duration_ms": _duration_ms(started),
            "debug": {
                "error_type": type(exc).__name__,
                "runs_on_startup": False,
                "runs_after_food_write": False,
                "external_api_calls": False,
            },
        }


@router.get("/api/recommendations/latest")
def latest_recommendation() -> dict[str, Any]:
    latest = fetch_latest_document("nutrition_recommendation_history", {})
    return {
        "status": "ok" if latest else "empty",
        "item": latest or None,
        "runs_on_startup": False,
    }
