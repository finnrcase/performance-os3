from __future__ import annotations

from datetime import date, timedelta
import time

from fastapi import APIRouter

from backend_v2.db import load_dashboard_core_bundle
from backend_v2.routes.goals import fallback_goals, fallback_targets
from backend_v2.routes.nutrition import _totals
from backend_v2.routes.training import grouped_workout_history
from backend_v2.utils import to_float, today_iso, utc_now_iso

router = APIRouter(tags=["dashboard"])
REQUIRED_BLOCKS = {"load_nutrition", "load_training", "load_goals", "today_food_summary", "weight_summary", "latest_workout"}


def _target_macros(targets: dict) -> dict:
    return {"calories": round(to_float(targets.get("target_calories"), 2500)), "protein": round(to_float(targets.get("protein_grams"), 180)), "carbs": round(to_float(targets.get("carb_grams"), 275)), "fat": round(to_float(targets.get("fat_grams"), 75))}


def _left(actual: float, target: float | None) -> dict:
    if not target:
        return {"left": None, "over": None, "percent": 0}
    return {"left": max(float(target) - float(actual), 0), "over": max(float(actual) - float(target), 0), "percent": min(max(float(actual) / float(target) * 100, 0), 100)}


def _food_tile(nutrition: dict, targets: dict) -> dict:
    totals = nutrition.get("totals", {}) if isinstance(nutrition.get("totals"), dict) else {}
    macros = _target_macros(targets)
    calories = to_float(totals.get("calories"), 0)
    protein = to_float(totals.get("protein"), 0)
    carbs = to_float(totals.get("carbs"), 0)
    fat = to_float(totals.get("fat"), 0)
    return {"calories": {"eaten": calories, "target": macros["calories"], **_left(calories, macros["calories"])}, "protein": {"eaten": protein, "target": macros["protein"], **_left(protein, macros["protein"])}, "carbs": {"eaten": carbs, "target": macros["carbs"], **_left(carbs, macros["carbs"])}, "fat": {"eaten": fat, "target": macros["fat"], **_left(fat, macros["fat"])}, "has_targets": True, "has_food_logged": bool(nutrition.get("items"))}


def _weight_snapshot(rows: list[dict]) -> tuple[float | None, list[dict], dict]:
    cleaned = [row for row in rows if str(row.get("date") or "").strip() and row.get("bodyweight") not in {None, ""}]
    cleaned.sort(key=lambda row: str(row.get("date") or ""))
    if not cleaned:
        return None, [], {"today_weight": None, "latest_weight": None, "seven_day_average": None, "trend_label": "insufficient data", "history": [], "message": "Enter today's weight"}
    latest_weight = to_float(cleaned[-1].get("bodyweight"), 0)
    recent = cleaned[-7:]
    avg = round(sum(to_float(row.get("bodyweight"), 0) for row in recent) / len(recent), 1) if len(recent) >= 2 else None
    delta = to_float(recent[-1].get("bodyweight"), 0) - to_float(recent[0].get("bodyweight"), 0) if len(recent) >= 3 else 0
    trend = "gaining" if delta > 0.3 else "losing" if delta < -0.3 else "stable" if len(recent) >= 3 else "insufficient data"
    today = today_iso()
    today_rows = [row for row in cleaned if str(row.get("date")) == today]
    return latest_weight, cleaned[-30:], {"today_weight": to_float(today_rows[-1].get("bodyweight"), 0) if today_rows else None, "latest_weight": latest_weight, "seven_day_average": avg, "trend_label": trend, "history": cleaned[-14:], "message": "Today's weight logged" if today_rows else "Enter today's weight"}


def dashboard_core_payload() -> dict:
    started = time.perf_counter()
    today = today_iso()
    blocks = []
    bundle_error = None
    bundle_started = time.perf_counter()
    try:
        bundle = load_dashboard_core_bundle(today=today, training_cutoff=(date.today() - timedelta(days=30)).isoformat(), body_cutoff=(date.today() - timedelta(days=90)).isoformat(), training_limit=500, body_limit=200, food_limit=500, timeout_ms=1500)
        blocks.append({"block": "load_core_bundle", "name": "load_core_bundle", "status": "ok", "duration_ms": round((time.perf_counter() - bundle_started) * 1000, 1)})
    except Exception as exc:
        bundle_error = exc
        bundle = {}
        blocks.append({"block": "load_core_bundle", "name": "load_core_bundle", "status": "error", "error_type": type(exc).__name__, "message": str(exc), "duration_ms": round((time.perf_counter() - bundle_started) * 1000, 1)})
    nutrition_rows = bundle.get("nutrition_rows") if isinstance(bundle.get("nutrition_rows"), list) else []
    training_rows = bundle.get("training_rows") if isinstance(bundle.get("training_rows"), list) else []
    body_rows = bundle.get("body_rows") if isinstance(bundle.get("body_rows"), list) else []
    goals = bundle.get("goals") if isinstance(bundle.get("goals"), dict) and bundle.get("goals") else fallback_goals()
    targets = bundle.get("targets") if isinstance(bundle.get("targets"), dict) and bundle.get("targets") else fallback_targets(goals)
    status = "error" if bundle_error else "ok"
    err = {"error_type": type(bundle_error).__name__, "message": str(bundle_error)} if bundle_error else {}
    blocks.extend([{"block": "load_nutrition", "name": "load_nutrition", "status": status, "duration_ms": 0, "rows": len(nutrition_rows), **err}, {"block": "load_training", "name": "load_training", "status": status, "duration_ms": 0, "rows": len(training_rows), **err}, {"block": "load_body_metrics", "name": "load_body_metrics", "status": status, "duration_ms": 0, "rows": len(body_rows), **err}, {"block": "load_goals", "name": "load_goals", "status": status, "duration_ms": 0, **err}])
    nutrition = {"date": today, "items": nutrition_rows, "totals": _totals(nutrition_rows), "targets": targets}
    latest_bodyweight, bodyweight_trend, weight_tile = _weight_snapshot(body_rows)
    latest_workout = grouped_workout_history(training_rows)[0] if training_rows else None
    blocks.extend([{"block": "today_food_summary", "name": "today_food_summary", "status": "ok", "duration_ms": 0, "rows": len(nutrition_rows)}, {"block": "weight_summary", "name": "weight_summary", "status": "ok", "duration_ms": 0, "rows": len(body_rows)}, {"block": "latest_workout", "name": "latest_workout", "status": "ok", "duration_ms": 0, "rows": len(training_rows)}])
    failed = [block for block in blocks if block.get("status") == "error"]
    required_failed = [block.get("block") for block in failed if block.get("block") in REQUIRED_BLOCKS]
    core_ready = not required_failed
    total_duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return {"ok": core_ready, "core_ready": core_ready, "date": today, "food": _food_tile(nutrition, targets), "weight": weight_tile, "lift_performance": {"status": f"Latest: {latest_workout.get('workout_type')}" if latest_workout else "Workout not logged yet", "summary": latest_workout.get("workout_type") if latest_workout else "Workout not logged yet", "comparison": None, "today_volume": latest_workout.get("total_volume") if latest_workout and latest_workout.get("date") == today else None, "percent_vs_average": None, "run_summary": None}, "goals": goals, "targets": targets, "base_targets": targets, "training_workload": {"status": "deferred", "summary": "Training workload is deferred in backend_v2 core."}, "nutrition_today": nutrition.get("totals", {}), "latest_bodyweight": latest_bodyweight, "bodyweight_trend": bodyweight_trend, "weight_feedback": {"status": "deferred", "suggested_adjustment": "hold", "confidence": "low"}, "latest_workout": latest_workout, "workout_quality": {"status": "missing", "score": None, "confidence": "low"}, "todays_action": {"status": "maintain", "headline": "Load core dashboard"}, "weekly_report": {"status": "deferred", "rows": []}, "recovery": {"connected": False, "status": "deferred", "message": "Recovery is deferred in backend_v2 core."}, "prs": {"bench_press": None, "mile_time": None}, "latest_recovery": None, "recovery_trend": [], "strength_trend_summary": {"exercise": "", "label": "deferred", "summary": "Strength trends are deferred."}, "muscle_balance_warning": None, "ai_insight_preview": None, "training_volume": [], "personal_records": {"bench_press": None, "mile_time": None, "history": {"bench_press": [], "mile_time": []}}, "lean_bulk_decision": {"status": "deferred", "recommended_target_calories": targets.get("target_calories")}, "adaptive_recommendation": {"confidence": "deferred", "recommendedTargets": targets, "currentTarget": targets}, "personal_learning": {"status": "deferred", "insights": []}, "optimization": {"status": "deferred"}, "recommendation": {"recommendation_summary": "Advanced recommendations are deferred in backend_v2."}, "counts": {"nutrition": len(nutrition_rows), "training": len(training_rows), "body_metrics": len(body_rows), "recovery": 0, "sleep": 0, "nutrition_rows_estimate": bundle.get("nutrition_rows_estimate", 0), "training_rows_estimate": bundle.get("training_rows_estimate", 0), "body_metric_rows_estimate": bundle.get("body_metric_rows_estimate", 0)}, "errors": failed, "debug": {"dashboard_status": "ok" if core_ready else "failed", "mode": "backend_v2_core", "required_blocks": sorted(REQUIRED_BLOCKS), "required_blocks_failed": required_failed, "errors": failed, "blocks": blocks, "generated_at": utc_now_iso(), "timings_ms": {str(block.get("block")): block.get("duration_ms", 0) for block in blocks}, "core_route": "/api/dashboard/core", "advanced_analytics_disabled": True, "background_workers": False, "startup_syncs": False, "total_duration_ms": total_duration_ms}}


@router.get("/api/dashboard/core")
def get_dashboard_core() -> dict:
    try:
        return dashboard_core_payload()
    except Exception as exc:
        return {"ok": False, "core_ready": False, "debug": {"dashboard_status": "failed", "required_blocks_failed": ["dashboard_core"], "errors": [{"block": "dashboard_core", "status": "error", "error_type": type(exc).__name__, "message": str(exc)}]}}
