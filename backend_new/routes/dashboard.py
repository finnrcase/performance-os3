from __future__ import annotations

from collections import defaultdict
from datetime import date
import time
from typing import Any

from fastapi import APIRouter
import pandas as pd

from backend_new.db import fetch_dashboard_core_bundle
from backend_new.routes.goals import calculate_targets, fallback_goals
from backend_new.utils import utc_now_iso
from src.body_metrics import canonical_daily_bodyweights
from src.analytics.recovery_engine import calculate_recovery_score
from src.training_schedule import DEFAULT_RECURRING_SCHEDULE_PROFILE, planned_training_for_date, summarize_training_day


router = APIRouter(tags=["dashboard"])

REQUIRED_BLOCKS = {"load_core_bundle"}


def _today_iso() -> str:
    return date.today().isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _nutrition_value(item: dict[str, Any], field: str) -> float:
    aliases = {
        "protein": ("protein", "protein_g"),
        "carbs": ("carbs", "carbs_g"),
        "fat": ("fat", "fat_g"),
        "fiber": ("fiber", "fiber_g"),
    }
    for key in aliases.get(field, (field,)):
        if key in item:
            return _number(item.get(key), 0)
    return 0


def _totals(items: list[dict[str, Any]]) -> dict[str, int | float]:
    return {
        field: _round(sum(_nutrition_value(item, field) for item in items))
        for field in ("calories", "protein", "carbs", "fat", "fiber")
    }


def _simple_targets(goals: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    calculated = calculate_targets(goals)
    if not isinstance(targets, dict) or "_db_error" in targets:
        return calculated
    for field in (
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
    ):
        if field in targets and targets[field] not in {None, ""}:
            calculated[field] = targets[field]
    return calculated


def _progress(actual: float, target: float | None) -> dict[str, Any]:
    if not target:
        return {"left": None, "over": None, "percent": 0}
    left = max(float(target) - float(actual), 0)
    over = max(float(actual) - float(target), 0)
    return {"left": _round(left), "over": _round(over), "percent": round(min(max(float(actual) / float(target) * 100, 0), 100), 1)}


def _food_tile(totals: dict[str, Any], targets: dict[str, Any], *, has_food: bool) -> dict[str, Any]:
    macro_targets = {
        "calories": targets.get("target_calories"),
        "protein": targets.get("protein_grams"),
        "carbs": targets.get("carb_grams"),
        "fat": targets.get("fat_grams"),
    }
    return {
        key: {
            "eaten": _number(totals.get(key), 0),
            "target": macro_targets[key],
            **_progress(_number(totals.get(key), 0), macro_targets[key]),
        }
        for key in ("calories", "protein", "carbs", "fat")
    } | {
        "has_targets": any(value for value in macro_targets.values()),
        "has_food_logged": has_food,
    }


def _weight_tile(rows: list[dict[str, Any]], today: str) -> tuple[float | None, list[dict[str, Any]], dict[str, Any]]:
    canonical = canonical_daily_bodyweights(rows)
    usable = []
    for row in canonical.to_dict(orient="records") if not canonical.empty else []:
        item = dict(row)
        try:
            item["date"] = row["date"].date().isoformat()
        except Exception:
            item["date"] = str(row.get("date") or "")
        usable.append(item)
    if not usable:
        tile = {
            "today_weight": None,
            "latest_weight": None,
            "seven_day_average": None,
            "trend_label": "insufficient data",
            "history": [],
            "message": "Enter today's weight",
            "canonical_rule": "lowest_weight_per_day",
        }
        return None, [], tile
    latest = _round(_number(usable[-1].get("bodyweight"), 0))
    recent = usable[-7:]
    average = _round(sum(_number(row.get("bodyweight"), 0) for row in recent) / len(recent)) if len(recent) >= 2 else None
    delta = _number(recent[-1].get("bodyweight"), 0) - _number(recent[0].get("bodyweight"), 0) if len(recent) >= 3 else 0
    trend = "gaining" if delta > 0.3 else "losing" if delta < -0.3 else "stable" if len(recent) >= 3 else "insufficient data"
    today_rows = [row for row in usable if str(row.get("date")) == today]
    tile = {
        "today_weight": _round(_number(today_rows[-1].get("bodyweight"), 0)) if today_rows else None,
        "latest_weight": latest,
        "seven_day_average": average,
        "trend_label": trend,
        "history": usable[-14:],
        "message": "Today's weight logged" if today_rows else "Enter today's weight",
        "canonical_rule": "lowest_weight_per_day",
    }
    return latest, usable[-30:], tile


def _volume(row: dict[str, Any]) -> float:
    return _number(row.get("sets"), 0) * _number(row.get("reps"), 0) * _number(row.get("weight"), 0)


def _latest_workout(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        workout_date = str(row.get("date") or "")
        if not workout_date:
            continue
        workout_id = str(row.get("workout_id") or row.get("hevy_workout_id") or f"{workout_date}:unknown")
        grouped[(workout_date, workout_id)].append(row)
    if not grouped:
        return None
    workout_date, workout_id = sorted(grouped.keys(), reverse=True)[0]
    workout_rows = grouped[(workout_date, workout_id)]
    exercises = list(dict.fromkeys(str(row.get("exercise") or "").strip() for row in workout_rows if str(row.get("exercise") or "").strip()))
    title = ""
    for row in workout_rows:
        notes = str(row.get("notes") or "")
        if "workout_title=" in notes:
            title = notes.split("workout_title=", 1)[1].split("|", 1)[0].strip()
            break
    title = title or str(workout_rows[0].get("workout_type") or "Workout")
    return {
        "date": workout_date,
        "workout_id": workout_id,
        "workout_type": title,
        "exercise_names": exercises,
        "total_sets": int(sum(max(0, int(_number(row.get("sets"), 0))) for row in workout_rows)),
        "total_volume": _round(sum(_volume(row) for row in workout_rows)),
        "duration_minutes": _round(max([_number(row.get("duration_minutes"), 0) for row in workout_rows] or [0])),
        "source": ", ".join(sorted({str(row.get("source") or "manual") for row in workout_rows})),
    }


def _training_rows_from_history(history_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in history_items:
        details = item.get("details") if isinstance(item.get("details"), list) else []
        if details:
            rows.extend(dict(row) for row in details if isinstance(row, dict))
            continue
        rows.append(
            {
                "date": item.get("date"),
                "workout_id": item.get("workout_id"),
                "workout_type": item.get("workout_type"),
                "sets": item.get("total_sets"),
                "reps": 1,
                "weight": item.get("total_volume"),
                "duration_minutes": item.get("duration_minutes"),
                "source": item.get("source"),
            }
        )
    return rows


def _latest_from_training_history(history_items: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not history_items:
        return None
    latest = dict(history_items[0])
    return {
        "date": latest.get("date"),
        "workout_id": latest.get("workout_id"),
        "workout_type": latest.get("workout_type") or "Workout",
        "classification": latest.get("classification"),
        "classification_debug": latest.get("classification_debug"),
        "exercise_names": latest.get("exercise_names") or [],
        "total_sets": latest.get("total_sets", 0),
        "total_volume": latest.get("total_volume", 0),
        "duration_minutes": latest.get("duration_minutes", 0),
        "source": latest.get("source") or "manual",
    }


def _lift_performance_payload(
    *,
    today: str,
    latest_workout: dict[str, Any] | None,
    training_items: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    planned = planned_training_for_date(today, profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)
    day_summary = {
        "planned": planned,
        "planned_workout": planned["display_label"],
        "completed_workouts": [],
        "completed_summary": "",
        "has_lift": False,
        "has_run": False,
        "sources": [],
        "schedule_match": "missed",
        "match_label": "Workout not logged yet",
        "cardio_indicator": "Planned run/cardio" if planned["is_run_day"] else None,
        "extra_run_added": False,
        "recovery_status_relative_to_plan": "Plan pending",
    }
    today_items = [item for item in training_items if str(item.get("date") or "") == today]
    completed_workouts = list(
        dict.fromkeys(
            str(item.get("workout_type") or item.get("classification_label") or "Workout").strip()
            for item in today_items
            if str(item.get("workout_type") or item.get("classification_label") or "").strip()
        )
    )
    if completed_workouts:
        planned_label = str((day_summary.get("planned") or {}).get("label") or "").lower()
        completed_text = " ".join(completed_workouts).lower()
        has_lift = any(str(item.get("classification") or "") in {"lift", "lift_cardio"} for item in today_items)
        has_run = any(str(item.get("classification") or "") in {"run", "cardio", "lift_cardio"} for item in today_items)
        schedule_match = "matched" if planned_label and planned_label in completed_text else "different"
        day_summary = {
            **day_summary,
            "completed_workouts": completed_workouts,
            "completed_summary": " + ".join(completed_workouts),
            "has_lift": has_lift,
            "has_run": has_run,
            "sources": sorted({str(item.get("source") or "manual").capitalize() for item in today_items if item.get("source")}),
            "schedule_match": schedule_match,
            "match_label": "Matched schedule" if schedule_match == "matched" else "Different from planned",
            "cardio_indicator": "Run/cardio logged" if has_run else None,
            "extra_run_added": bool(has_run and has_lift),
            "recovery_status_relative_to_plan": "On plan" if schedule_match == "matched" else "Different from planned",
        }
    elif training_rows:
        training_df = pd.DataFrame(training_rows)
        day_summary = summarize_training_day(training_df, today, profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)
    completed_summary = str(day_summary.get("completed_summary") or "")
    summary = completed_summary or (latest_workout.get("workout_type") if latest_workout else "Workout not logged yet")
    today_workout = latest_workout if latest_workout and latest_workout.get("date") == today else None
    return {
        "status": f"Latest: {latest_workout.get('workout_type')}" if latest_workout else "Workout not logged yet",
        "summary": summary,
        "comparison": None,
        "today_volume": today_workout.get("total_volume") if today_workout else None,
        "percent_vs_average": None,
        "planned_workout": day_summary.get("planned_workout", "Training"),
        "completed_workouts": day_summary.get("completed_workouts", []),
        "completed_summary": completed_summary,
        "schedule_match": day_summary.get("schedule_match", "missed"),
        "match_label": day_summary.get("match_label", "Workout not logged yet"),
        "sources": day_summary.get("sources", []),
        "has_run": bool(day_summary.get("has_run")),
        "has_lift": bool(day_summary.get("has_lift")),
        "cardio_indicator": day_summary.get("cardio_indicator"),
        "extra_run_added": bool(day_summary.get("extra_run_added")),
        "recovery_status_relative_to_plan": day_summary.get("recovery_status_relative_to_plan"),
    }


def _recovery_payload(recovery_rows: list[dict[str, Any]], sleep_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    recovery_df = pd.DataFrame(recovery_rows)
    sleep_df = pd.DataFrame(sleep_rows)
    try:
        analytics = calculate_recovery_score(recovery_df) if recovery_rows else pd.DataFrame()
    except Exception:
        analytics = pd.DataFrame()

    trend: list[dict[str, Any]] = []
    latest_recovery = None
    if not analytics.empty:
        analytics = analytics.sort_values("date")
        for row in analytics.tail(14).to_dict(orient="records"):
            item = {
                "date": str(row.get("date"))[:10],
                "recovery_score": _round(_number(row.get("recovery_score"), 0)),
                "classification": str(row.get("classification") or "unknown"),
            }
            trend.append(item)
        latest = analytics.iloc[-1].to_dict()
        latest_recovery = {
            "recovery_score": _round(_number(latest.get("recovery_score"), 0)),
            "classification": str(latest.get("classification") or "unknown"),
            "explanation": str(latest.get("explanation") or latest.get("reason") or ""),
        }
    elif recovery_rows:
        latest_row = sorted(recovery_rows, key=lambda row: str(row.get("date") or ""))[-1]
        score = max(
            0,
            min(
                100,
                100
                - _number(latest_row.get("fatigue"), 0) * 7
                - _number(latest_row.get("soreness"), 0) * 4
                - _number(latest_row.get("stress"), 0) * 4
                + _number(latest_row.get("motivation"), 0) * 3,
            ),
        )
        latest_recovery = {"recovery_score": _round(score), "classification": "manual", "explanation": "Manual recovery check-in."}
        trend = [{"date": str(row.get("date") or ""), "recovery_score": _round(score), "classification": "manual"} for row in recovery_rows[-14:]]

    sleep_trend = []
    for row in sorted(sleep_rows, key=lambda item: str(item.get("date") or ""))[-14:]:
        hours = _number(row.get("sleep_hours"), 0)
        if not hours:
            hours = _number(row.get("durationMinutes"), 0) / 60
        if hours:
            sleep_trend.append({"date": str(row.get("date") or ""), "sleep_hours": _round(hours)})
    if not sleep_trend:
        for row in sorted(recovery_rows, key=lambda item: str(item.get("date") or ""))[-14:]:
            hours = _number(row.get("sleep_hours"), 0)
            if hours:
                sleep_trend.append({"date": str(row.get("date") or ""), "sleep_hours": _round(hours)})

    hrv = [
        {"date": str(row.get("date") or ""), "hrv": _round(_number(row.get("hrv"), 0))}
        for row in sorted(recovery_rows, key=lambda item: str(item.get("date") or ""))[-14:]
        if row.get("hrv") not in {None, ""}
    ]
    resting_hr = [
        {"date": str(row.get("date") or ""), "resting_hr": _round(_number(row.get("resting_hr"), row.get("restingHeartRate") or 0))}
        for row in sorted([*recovery_rows, *sleep_rows], key=lambda item: str(item.get("date") or ""))[-14:]
        if row.get("resting_hr") not in {None, ""} or row.get("restingHeartRate") not in {None, ""}
    ]
    connected = bool(recovery_rows or sleep_rows)
    latest_score = latest_recovery.get("recovery_score") if latest_recovery else None
    classification = latest_recovery.get("classification") if latest_recovery else "unknown"
    message = "Recovery data loaded from saved check-ins." if connected else "No recovery or sleep entries yet."
    payload = {
        "connected": connected,
        "source": "manual" if recovery_rows else "sleep" if sleep_rows else "none",
        "latest_score": latest_score,
        "trend": trend,
        "sleep": sleep_trend,
        "hrv": hrv,
        "resting_hr": resting_hr,
        "status": "ready" if connected else "missing",
        "classification": classification,
        "message": message,
        "extra_run_readiness": {
            "status": "insufficient_data" if not connected else "green" if _number(latest_score, 0) >= 70 else "yellow" if _number(latest_score, 0) >= 50 else "red",
            "message": "Recovery looks usable for normal training." if connected and _number(latest_score, 0) >= 70 else "Use recovery page check-ins to guide extra running." if connected else "Log recovery data for run readiness.",
            "recommended_run": "Optional easy run" if connected and _number(latest_score, 0) >= 70 else "Keep it easy" if connected else "Need recovery data",
            "reasoning": [message],
        },
    }
    return payload, latest_recovery, trend


def _target_macros(targets: dict[str, Any]) -> dict[str, int | float]:
    return {
        "calories": _round(_number(targets.get("target_calories"), 0)),
        "protein": _round(_number(targets.get("protein_grams"), 0)),
        "carbs": _round(_number(targets.get("carb_grams"), 0)),
        "fat": _round(_number(targets.get("fat_grams"), 0)),
    }


def _lean_bulk_placeholder(targets: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation": "maintain",
        "calorie_change": 0,
        "new_target_calories": _round(_number(targets.get("target_calories"), 0)),
        "confidence": "low",
        "weekly_weight_change_pct": None,
        "fat_gain_risk_score": 0,
        "reasoning": ["Lean bulk analysis is deferred in dashboard core."],
        "next_check_in_days": 7,
        "details": {
            "seven_day_avg_weight": None,
            "fourteen_day_avg_weight": None,
            "calorie_average": None,
            "protein_average": None,
            "protein_target": targets.get("protein_grams"),
            "training_trend": "Need data",
            "recovery_trend": "Need data",
            "recovery_average": None,
            "target_weekly_gain_pct": targets.get("expected_weekly_weight_change"),
            "calorie_target_delta_average": None,
            "protein_consistency": None,
            "days_over_calorie_target": None,
            "days_under_calorie_target": None,
            "key_lift_trends": {},
            "performance_signal": {
                "label": "deferred",
                "confidence": "low",
                "summary": "Performance analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
                "muscle_group_drivers": [],
            },
            "recovery_signal": {
                "status": "deferred",
                "label": "Need data",
                "confidence": "low",
                "summary": "Recovery analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
            },
        },
    }


def _adaptive_placeholder(targets: dict[str, Any]) -> dict[str, Any]:
    macros = _target_macros(targets)
    return {
        "recommendedCalories": macros["calories"],
        "recommendedProtein": macros["protein"],
        "recommendedCarbs": macros["carbs"],
        "recommendedFat": macros["fat"],
        "caloriesTarget": macros["calories"],
        "proteinTarget": macros["protein"],
        "carbsTarget": macros["carbs"],
        "fatTarget": macros["fat"],
        "calorieAdjustment": 0,
        "macroAdjustment": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
        "macroChanges": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
        "dayType": "standard",
        "dayTypeAdjustment": {
            "type": "standard",
            "reason": "Adaptive analytics are disabled in dashboard core.",
            "calorie_delta": 0,
            "carb_delta": 0,
            "fat_delta": 0,
            "confidence": "low",
            "applied_delta": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
            "adjusted_targets": macros,
        },
        "carbTimingRecommendation": "",
        "confidence": "low",
        "dataQualityScore": 0,
        "reasoning": ["Adaptive analytics are disabled in dashboard core."],
        "warnings": [],
        "detectedTrends": [],
        "missingDataWarnings": [],
        "nextReviewDate": "",
        "strategy": "deferred",
        "currentTarget": macros,
        "recommendedTargets": targets,
        "baselineRecommendedTargets": targets,
        "dayTypeAdjustedTargets": targets,
        "signals": {
            "weight": {
                "status": "insufficient_data",
                "weekly_change_pct": None,
                "weekly_change_lb": None,
                "calorie_adjustment": 0,
                "confidence": "low",
                "reason": "Need bodyweight trend.",
            },
            "bodyComposition": {
                "status": "insufficient_data",
                "lean_gain_quality": "unknown",
                "latest_bodyweight": None,
                "latest_body_fat_percent": None,
                "latest_lean_mass": None,
                "latest_fat_mass": None,
                "weight_7_day_average": None,
                "weight_14_day_average": None,
                "weight_28_day_average": None,
                "weight_gain_rate_lb_per_week": None,
                "weight_gain_rate_pct_per_week": None,
                "lean_mass_trend_7": None,
                "lean_mass_trend_14": None,
                "lean_mass_trend_28": None,
                "fat_mass_trend_7": None,
                "fat_mass_trend_14": None,
                "fat_mass_trend_28": None,
                "body_fat_percent_trend_14": None,
                "body_fat_percent_trend_28": None,
                "data_points": 0,
                "body_fat_data_points": 0,
            },
            "performance": {
                "label": "deferred",
                "confidence": "low",
                "summary": "Performance analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
                "muscle_group_drivers": [],
            },
            "recovery": {
                "status": "deferred",
                "label": "Need data",
                "confidence": "low",
                "summary": "Recovery analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
            },
            "trainingLoad": {"status": "deferred", "summary": "Training load analytics are deferred.", "hard_sets_per_week": 0, "weekly_training_minutes": 0},
            "runningLoad": {"status": "deferred", "summary": "Running load analytics are deferred.", "runs_per_week": 0, "weekly_mileage": 0, "interference_risk": "unknown"},
            "nutrition": {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None},
            "dataQuality": {"score": 0, "confidence": "low", "missingDataWarnings": []},
            "historicalLearning": {"detectedTrends": []},
        },
    }


def _fallback_payload(today: str, blocks: list[dict[str, Any]], *, started: float) -> dict[str, Any]:
    failed = [block for block in blocks if block.get("status") == "error"]
    return {
        "ok": False,
        "core_ready": False,
        "date": today,
        "food": {},
        "weight": {},
        "goals": {},
        "targets": {},
        "nutrition_today": {},
        "latest_workout": None,
        "counts": {},
        "debug": {
            "dashboard_status": "failed",
            "blocks": blocks,
            "errors": failed,
            "required_blocks": sorted(REQUIRED_BLOCKS),
            "required_blocks_failed": [block.get("block") for block in failed if block.get("block") in REQUIRED_BLOCKS],
            "generated_at": utc_now_iso(),
            "total_duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }


@router.get("/api/dashboard/core")
def dashboard_core() -> dict[str, Any]:
    started = time.perf_counter()
    today = _today_iso()
    bundle = fetch_dashboard_core_bundle(today, body_limit=1000, food_limit=500, recovery_limit=500, sleep_limit=500, include_training_summary=True)
    bundle_status = str(bundle.get("status") or "")
    bundle_ready = bundle_status in {"ok", "not_configured"}
    blocks = [
        {
            "block": "load_core_bundle",
            "name": "load_core_bundle",
            "status": "ok" if bundle_ready else "error",
            "duration_ms": bundle.get("duration_ms", 0),
            "message": bundle.get("message", "") or ("DATABASE_URL is not configured; using empty local shell data." if bundle_status == "not_configured" else ""),
            "error_type": bundle.get("error_type"),
        }
    ]
    if isinstance(bundle.get("blocks"), list):
        blocks.extend(bundle.get("blocks") or [])
    if not bundle_ready:
        return _fallback_payload(today, blocks, started=started)

    food_rows = bundle.get("food_rows") if isinstance(bundle.get("food_rows"), list) else []
    body_rows = bundle.get("body_rows") if isinstance(bundle.get("body_rows"), list) else []
    recovery_rows = bundle.get("recovery_rows") if isinstance(bundle.get("recovery_rows"), list) else []
    sleep_rows = bundle.get("sleep_rows") if isinstance(bundle.get("sleep_rows"), list) else []
    training_summary = bundle.get("training_summary") if isinstance(bundle.get("training_summary"), dict) else {}
    training_items = training_summary.get("items") if isinstance(training_summary.get("items"), list) else []
    training_rows = _training_rows_from_history(training_items)
    goals = {**fallback_goals(), **(bundle.get("goals") if isinstance(bundle.get("goals"), dict) else {})}
    targets = _simple_targets(goals, bundle.get("targets") if isinstance(bundle.get("targets"), dict) else {})
    nutrition_today = _totals(food_rows)
    latest_bodyweight, bodyweight_trend, weight = _weight_tile(body_rows, today)
    latest_workout = _latest_from_training_history(training_items)
    if latest_workout is None and isinstance(training_summary.get("latest_workout"), dict):
        latest_workout = training_summary.get("latest_workout")
    if latest_workout is None:
        latest_workout = _latest_workout(training_rows)
    training_status = str(training_summary.get("status") or "ok")
    training_available = training_status in {"ok", "not_configured", "not_loaded"}
    recovery, latest_recovery, recovery_trend = _recovery_payload(recovery_rows, sleep_rows)
    counts = {**(bundle.get("counts") if isinstance(bundle.get("counts"), dict) else {})}
    adaptive_recommendation = _adaptive_placeholder(targets)
    lean_bulk_decision = _lean_bulk_placeholder(targets)
    lift_performance = _lift_performance_payload(today=today, latest_workout=latest_workout, training_items=training_items, training_rows=training_rows)
    total_duration_ms = round((time.perf_counter() - started) * 1000, 1)
    blocks.extend(
        [
            {"block": "today_food_summary", "name": "today_food_summary", "status": "ok", "rows": len(food_rows), "duration_ms": 0},
            {"block": "weight_summary", "name": "weight_summary", "status": "ok", "rows": len(body_rows), "duration_ms": 0},
            {"block": "recovery_summary", "name": "recovery_summary", "status": "ok", "rows": len(recovery_rows), "sleep_rows": len(sleep_rows), "duration_ms": 0},
            {
                "block": "load_training",
                "name": "load_training",
                "status": "ok" if training_available else "degraded",
                "rows": training_summary.get("recent_rows", len(training_rows)),
                "total_rows": training_summary.get("total_rows", counts.get("training", 0)),
                "duration_ms": training_summary.get("duration_ms", 0),
                "source": training_summary.get("source", "training_cache_metadata"),
                "message": training_summary.get("message", ""),
                "full_raw_hevy_scan": False,
            },
            {
                "block": "latest_workout",
                "name": "latest_workout",
                "status": "ok",
                "rows": len(training_rows),
                "duration_ms": 0,
            },
        ]
    )
    training_unavailable = not training_available and not latest_workout
    training_summary_text = "Training summary temporarily unavailable" if training_unavailable else latest_workout.get("workout_type") if latest_workout else "Workout not logged yet"
    return {
        "ok": True,
        "core_ready": True,
        "date": today,
        "food": _food_tile(nutrition_today, targets, has_food=bool(food_rows)),
        "weight": weight,
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "nutrition_today": nutrition_today,
        "latest_bodyweight": latest_bodyweight,
        "bodyweight_trend": bodyweight_trend,
        "latest_workout": latest_workout,
        "lift_performance": lift_performance,
        "workout_quality": {"status": "missing", "score": None, "score_label": "No score", "confidence": "low", "color": "gray", "explanation": "Workout quality is deferred in dashboard core.", "comparison": None, "source": "backend_new_core"},
        "todays_action": {"status": "maintain", "color": "gray", "headline": "Keep logging", "reason": "Lightweight dashboard core loaded."},
        "recovery": recovery,
        "prs": {"bench_press": None, "mile_time": None},
        "latest_recovery": latest_recovery,
        "recovery_trend": recovery_trend,
        "strength_trend_summary": {"exercise": "", "label": "deferred", "summary": "Strength trends are deferred."},
        "muscle_balance_warning": None,
        "ai_insight_preview": None,
        "training_volume": [],
        "personal_records": {"bench_press": None, "mile_time": None, "history": {"bench_press": [], "mile_time": []}},
        "lean_bulk_decision": lean_bulk_decision,
        "adaptive_recommendation": adaptive_recommendation,
        "personal_learning": {"status": "deferred", "confidence": "low", "summary": "Personal learning is deferred.", "window": "", "data_points": 0, "insights": []},
        "weekly_report": {"status": "deferred", "period_label": "Deferred", "summary": "Weekly report is deferred.", "rows": [], "best_trend": "", "watch": "", "recommendation": ""},
        "optimization": {
            "day_type_macros": {
                "day_type": "standard",
                "confidence": "low",
                "reason": "Optimization is deferred in dashboard core.",
                "baseline_targets": {"calories": targets.get("target_calories"), "protein": targets.get("protein_grams"), "carbs": targets.get("carb_grams"), "fat": targets.get("fat_grams")},
                "adjusted_targets": {"calories": targets.get("target_calories"), "protein": targets.get("protein_grams"), "carbs": targets.get("carb_grams"), "fat": targets.get("fat_grams")},
                "delta": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
                "signals": [],
            },
            "plateau_detection": {"status": "deferred", "summary": "Plateau detection is deferred.", "top_alerts": [], "details": []},
            "macro_adherence": {"weekly_score": None, "status": "deferred", "summary": "Macro adherence is deferred.", "components": {}, "daily": [], "correlations": []},
            "personal_baseline": {"status": "deferred", "confidence": "low", "summary": "Personal baseline is deferred.", "dashboard_insight": None, "insights": []},
        },
        "recommendation": {"recommendation_summary": "Advanced recommendations are deferred.", "reasoning_explanation": ""},
        "counts": counts,
        "errors": [],
        "debug": {
            "dashboard_status": "ok",
            "blocks": blocks,
            "warnings": bundle.get("warnings", []) if isinstance(bundle.get("warnings"), list) else [],
            "errors": [],
            "required_blocks": sorted(REQUIRED_BLOCKS),
            "required_blocks_failed": [],
            "generated_at": utc_now_iso(),
            "total_duration_ms": total_duration_ms,
            "training_read_limit": training_summary.get("max_core_training_rows", 0),
            "training_core_limit": training_summary.get("limit_workouts", 0),
            "training_core_days": training_summary.get("days", 90),
            "training_recent_rows": training_summary.get("recent_rows", len(training_rows)),
            "training_total_rows": counts.get("training", training_summary.get("total_rows", 0)),
            "training_summary_source": training_summary.get("source", "training_cache_metadata"),
            "full_training_history_scanned": False,
            "external_api_checks": False,
            "syncs": False,
        },
    }
