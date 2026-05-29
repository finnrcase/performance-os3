from __future__ import annotations

from collections import defaultdict
import copy
from datetime import date as date_cls, timedelta
import logging
import threading
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend_new.db import (
    delete_json_row,
    ensure_jsonb_table,
    ensure_jsonb_performance_indexes,
    fetch_json_rows,
    fetch_json_rows_for_value,
    fetch_latest_document,
    insert_json_row,
    update_json_rows_for_value,
    upsert_json_row,
)
from backend_new.utils import app_today_iso, utc_now_iso


router = APIRouter(tags=["nutrition"])
logger = logging.getLogger(__name__)

TOTAL_FIELDS = ("calories", "protein", "carbs", "fat", "fiber")
FOOD_AI_EMPTY_TOTALS = {
    "calories": 0,
    "protein_g": 0,
    "carbs_g": 0,
    "fat_g": 0,
    "fiber_g": None,
    "sugar_g": None,
    "sodium_mg": None,
}
NUTRITION_LOGS_CACHE_TTL_SECONDS = 15
_nutrition_logs_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_nutrition_logs_cache_lock = threading.RLock()


def _cached_nutrition_logs(cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
    now = time.monotonic()
    with _nutrition_logs_cache_lock:
        entry = _nutrition_logs_cache.get(cache_key)
        if not entry:
            return None
        cached_at, payload = entry
        if now - cached_at > NUTRITION_LOGS_CACHE_TTL_SECONDS:
            _nutrition_logs_cache.pop(cache_key, None)
            return None
        cached_payload = copy.deepcopy(payload)
        cached_payload["meta"] = {**(cached_payload.get("meta") or {}), "cache": "memory", "cache_hit": True}
        return cached_payload


def _cache_nutrition_logs(cache_key: tuple[Any, ...], payload: dict[str, Any]) -> None:
    if payload.get("status") != "ok":
        return
    with _nutrition_logs_cache_lock:
        _nutrition_logs_cache[cache_key] = (time.monotonic(), copy.deepcopy(payload))


def _invalidate_nutrition_logs_cache() -> None:
    with _nutrition_logs_cache_lock:
        _nutrition_logs_cache.clear()


def _food_ai_item_to_api(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize parser internals or API-shaped items to the Food tab draft shape."""
    quantity_value = item.get("quantity")
    if not isinstance(quantity_value, (int, float)):
        quantity_value = item.get("quantity_value")
    return {
        "name": item.get("name") or item.get("food_name") or item.get("display_name") or "",
        "display_name": item.get("display_name") or item.get("name") or item.get("food_name") or "",
        "normalized_name": item.get("normalized_name") or "",
        "original_text": item.get("original_text") or item.get("food_name") or item.get("name") or "",
        "quantity": quantity_value,
        "unit": item.get("unit") or "",
        "serving_description": item.get("serving_description") or item.get("quantity") or "",
        "calories": item.get("calories", 0),
        "protein_g": item.get("protein_g", item.get("protein", 0)),
        "carbs_g": item.get("carbs_g", item.get("carbs", 0)),
        "fat_g": item.get("fat_g", item.get("fat", 0)),
        "fiber_g": item.get("fiber_g", item.get("fiber")),
        "sugar_g": item.get("sugar_g", item.get("sugar")),
        "sodium_mg": item.get("sodium_mg", item.get("sodium")),
        "confidence": item.get("confidence") or "medium",
        "confidence_score": item.get("confidence_score"),
        "source": item.get("source") or "openai_estimate",
        "source_id": item.get("source_id") or None,
        "source_url": item.get("source_url") or None,
        "assumptions": item.get("assumptions") if isinstance(item.get("assumptions"), list) else [],
        "needs_review": bool(item.get("needs_review", item.get("verification_needed", True))),
        "needs_confirmation": bool(item.get("needs_confirmation", item.get("needs_review", item.get("verification_needed", True)))),
    }


def _food_ai_totals(items: list[dict[str, Any]], provided: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(provided, dict) and provided:
        return {
            "calories": provided.get("calories", 0),
            "protein_g": provided.get("protein_g", provided.get("protein", 0)),
            "carbs_g": provided.get("carbs_g", provided.get("carbs", 0)),
            "fat_g": provided.get("fat_g", provided.get("fat", 0)),
            "fiber_g": provided.get("fiber_g", provided.get("fiber")),
            "sugar_g": provided.get("sugar_g", provided.get("sugar")),
            "sodium_mg": provided.get("sodium_mg", provided.get("sodium")),
        }
    totals = {
        "calories": round(sum(float(item.get("calories") or 0) for item in items), 1),
        "protein_g": round(sum(float(item.get("protein_g") or 0) for item in items), 1),
        "carbs_g": round(sum(float(item.get("carbs_g") or 0) for item in items), 1),
        "fat_g": round(sum(float(item.get("fat_g") or 0) for item in items), 1),
    }
    for key in ["fiber_g", "sugar_g", "sodium_mg"]:
        values = [item.get(key) for item in items if item.get(key) is not None]
        totals[key] = round(sum(float(value or 0) for value in values), 1) if values else None
    return totals


def _food_ai_response(
    result: dict[str, Any],
    analyzer_config: dict[str, Any],
    steps: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    raw_items = result.get("items") if isinstance(result.get("items"), list) else result.get("foods")
    items = [_food_ai_item_to_api(item) for item in raw_items] if isinstance(raw_items, list) else []
    totals = _food_ai_totals(items, result.get("totals") if isinstance(result.get("totals"), dict) else result.get("total"))
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    success = bool(result.get("success")) and bool(items)
    parser_source = str(result.get("source") or debug.get("parser_source") or "")
    parser_cached = bool(result.get("cached", debug.get("parser_cached", False)))
    parser_meta = result.get("parser") if isinstance(result.get("parser"), dict) else debug.get("parser") if isinstance(debug.get("parser"), dict) else {}
    external_lookup_status = str(result.get("external_lookup_status") or debug.get("external_lookup_status") or "skipped")
    openai_called = bool(parser_meta.get("default_model_used") or parser_meta.get("escalated") or (parser_source == "openai" and not parser_cached))
    merged_steps = {
        **steps,
        "parser_returned": True,
        "openai_called": openai_called,
        "model_used": parser_meta.get("final_model") or parser_meta.get("model_used") or analyzer_config.get("model"),
        "default_model_used": bool(parser_meta.get("default_model_used", openai_called)),
        "escalated": bool(parser_meta.get("escalated", False)),
        "escalation_reason": parser_meta.get("escalation_reason", ""),
        "estimated_input_tokens": parser_meta.get("estimated_input_tokens", 0),
        "estimated_output_tokens": parser_meta.get("estimated_output_tokens", 0),
        "estimated_cost_usd": parser_meta.get("estimated_cost_usd", 0),
        "parser_source": parser_source,
        "external_lookup_status": external_lookup_status,
        "raw_items_count": len(raw_items) if isinstance(raw_items, list) else 0,
        "normalized_items_count": len(items),
        "json_parse_success": bool(success),
        "returned_items": len(items),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    response = {
        **result,
        "status": "ok" if success else "error",
        "items": items,
        "foods": items,
        "totals": totals,
        "total": totals,
        "warnings": result.get("warnings") if isinstance(result.get("warnings"), list) else [],
        "parser": parser_meta,
        "parser_source": parser_source,
        "external_lookup_status": external_lookup_status,
        "success": success,
        "message": result.get("message") or ("Parsed food text. Review before saving." if success else "AI food parsing failed."),
        "error_code": result.get("error_code"),
        "debug": {
            **analyzer_config,
            **debug,
            "backend_endpoint_reached": True,
            "parser_source": parser_source,
            "parser_cached": parser_cached,
            "parser": parser_meta,
            "external_lookup_status": external_lookup_status,
            "openai_called": openai_called,
            "escalated": bool(parser_meta.get("escalated", False)),
            "escalation_reason": parser_meta.get("escalation_reason", ""),
            "final_model": parser_meta.get("final_model") or parser_meta.get("model_used") or analyzer_config.get("model"),
            "estimated_input_tokens": parser_meta.get("estimated_input_tokens", 0),
            "estimated_output_tokens": parser_meta.get("estimated_output_tokens", 0),
            "estimated_cost_usd": parser_meta.get("estimated_cost_usd", 0),
            "failed_step": debug.get("failed_step") or (None if success else debug.get("parsing_status") or "parse"),
            "duration_ms": merged_steps["duration_ms"],
        },
        "steps": merged_steps,
    }
    return response


def _food_ai_error_response(
    *,
    analyzer_config: dict[str, Any] | None = None,
    steps: dict[str, Any] | None = None,
    started: float | None = None,
    message: str,
    error_code: str,
    failed_step: str,
    exc: Exception | None = None,
) -> dict[str, Any]:
    elapsed = round((time.perf_counter() - started) * 1000, 1) if started else 0
    error_type = type(exc).__name__ if exc else error_code
    return {
        "status": "error",
        "items": [],
        "foods": [],
        "totals": FOOD_AI_EMPTY_TOTALS,
        "total": FOOD_AI_EMPTY_TOTALS,
        "warnings": [],
        "message": message,
        "success": False,
        "error_code": error_code,
        "debug": {
            **(analyzer_config or {}),
            "backend_endpoint_reached": True,
            "parsing_status": "error",
            "parser_source": "",
            "external_lookup_status": "skipped",
            "openai_called": False,
            "failed_step": failed_step,
            "error_type": error_type,
            "message": message,
            "duration_ms": elapsed,
        },
        "steps": {
            **(steps or {}),
            "openai_called": False,
            "external_lookup_status": "skipped",
            "failed_step": failed_step,
            "error_type": error_type,
            "duration_ms": elapsed,
        },
    }


def _today_iso() -> str:
    return app_today_iso()


def _valid_json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and "_db_error" not in row]


def _order_number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _next_log_sequence(selected_date: str) -> int:
    """Return the next same-day divider sequence across foods and markers."""
    max_sequence = 0.0
    for table, fields in (
        ("food_logs", ("logged_sequence", "created_order")),
        ("workout_markers", ("marker_sequence", "created_order")),
    ):
        rows = _valid_json_rows(fetch_json_rows_for_value(table, "date", str(selected_date)[:10], limit=5000))
        for row in rows:
            for field in fields:
                value = _order_number(row.get(field))
                if value is not None:
                    max_sequence = max(max_sequence, value)
                    break
    return int(max_sequence) + 1


def _ensure_food_log_sequence(item: dict[str, Any]) -> dict[str, Any]:
    if _order_number(item.get("logged_sequence")) is None and _order_number(item.get("created_order")) is None:
        item["logged_sequence"] = _next_log_sequence(str(item.get("date") or _today_iso()))
    elif _order_number(item.get("logged_sequence")) is None:
        item["logged_sequence"] = item.get("created_order")
    elif _order_number(item.get("created_order")) is None:
        item["created_order"] = item.get("logged_sequence")
    item["created_order"] = item.get("created_order", item.get("logged_sequence"))
    return item


def _normalize_workout_marker(payload: dict[str, Any], *, assign_sequence: bool = False) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload or {})
    item["marker_id"] = str(item.get("marker_id") or item.get("id") or uuid4())
    item["date"] = str(item.get("date") or _today_iso())[:10]
    if assign_sequence and _order_number(item.get("marker_sequence")) is None and _order_number(item.get("created_order")) is None:
        item["marker_sequence"] = _next_log_sequence(item["date"])
    elif _order_number(item.get("marker_sequence")) is None:
        item["marker_sequence"] = item.get("created_order")
    elif _order_number(item.get("created_order")) is None:
        item["created_order"] = item.get("marker_sequence")
    if "marker_sequence" in item or "created_order" in item:
        item["created_order"] = item.get("created_order", item.get("marker_sequence"))
    workout_time = str(item.get("workout_time") or item.get("time") or "").strip()
    item["workout_time"] = workout_time[:5] if workout_time else ""
    item["workout_type"] = str(item.get("workout_type") or item.get("type") or "Strength").strip() or "Strength"
    item["notes"] = str(item.get("notes") or "")
    item.setdefault("created_at", now)
    item["updated_at"] = now
    return item


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _round(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _macro_calories(protein: Any, carbs: Any, fat: Any) -> int | float:
    return _round((_number(protein, 0) * 4) + (_number(carbs, 0) * 4) + (_number(fat, 0) * 9))


def _is_excluded(item: dict[str, Any]) -> bool:
    return item.get("excluded_from_analytics") is True or str(item.get("excluded_from_analytics") or "").lower() == "true"


def _normalize_history_date(value: str) -> str:
    try:
        return date_cls.fromisoformat(str(value or "").strip()[:10]).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be a valid YYYY-MM-DD value.") from exc


def _bounded_route_limit(limit: int | str | None, *, default: int = 300, max_limit: int = 1000) -> int:
    try:
        value = int(limit or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, max_limit))


def _bounded_days(days: int | str | None, *, default: int = 90, max_days: int = 366) -> int:
    try:
        value = int(days or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, max_days))


def _nutrition_value(item: dict[str, Any], field: str) -> float:
    aliases = {
        "protein": ("protein", "protein_g"),
        "carbs": ("carbs", "carbs_g"),
        "fat": ("fat", "fat_g"),
        "fiber": ("fiber", "fiber_g"),
    }
    for key in aliases.get(field, (field,)):
        if key in item:
            return _number(item.get(key), 0.0)
    return 0.0


def _totals(items: list[dict[str, Any]]) -> dict[str, int | float]:
    return {field: _round(sum(_nutrition_value(item, field) for item in items)) for field in TOTAL_FIELDS}


def _target_payload() -> dict[str, Any]:
    targets = fetch_latest_document("macro_targets", {})
    return {
        "calories": targets.get("target_calories"),
        "protein": targets.get("protein_grams"),
        "carbs": targets.get("carb_grams"),
        "fat": targets.get("fat_grams"),
    }


def _target_summary_payload() -> dict[str, Any]:
    targets = _target_payload()
    return {
        "target_calories": targets.get("calories"),
        "target_protein": targets.get("protein"),
        "target_carbs": targets.get("carbs"),
        "target_fat": targets.get("fat"),
    }


def _adherence_score(totals: dict[str, Any], targets: dict[str, Any], *, logged: bool) -> int | None:
    if not logged:
        return None
    scores: list[float] = []
    total_calories = _number(totals.get("calories"), 0)
    total_protein = _number(totals.get("protein"), 0)
    target_calories = _number(targets.get("target_calories"), 0)
    target_protein = _number(targets.get("target_protein"), 0)
    if target_calories > 0:
        scores.append(max(0.0, 100.0 - (abs(total_calories - target_calories) / target_calories * 100.0)))
    if target_protein > 0:
        scores.append(min(100.0, max(0.0, total_protein / target_protein * 100.0)))
    if not scores:
        return None
    return int(round(sum(scores) / len(scores)))


def _daily_summary_from_logs(selected_date: str, *, finalized: bool) -> dict[str, Any]:
    food_rows = [
        row
        for row in fetch_json_rows_for_value("food_logs", "date", selected_date, limit=1000)
        if isinstance(row, dict) and "_db_error" not in row and not _is_excluded(row)
    ]
    totals = _totals(food_rows)
    targets = _target_summary_payload()
    logged = bool(food_rows)
    target_calories = targets.get("target_calories")
    target_protein = targets.get("target_protein")
    target_carbs = targets.get("target_carbs")
    target_fat = targets.get("target_fat")
    total_calories = _nutrition_value(totals, "calories")
    total_protein = _nutrition_value(totals, "protein")
    total_carbs = _nutrition_value(totals, "carbs")
    total_fat = _nutrition_value(totals, "fat")
    now = utc_now_iso()
    return {
        "date": selected_date,
        "summary_id": f"nutrition-summary:{selected_date}",
        "finalized": finalized,
        "status": "finalized" if finalized else "draft",
        "nutrition_logged": logged,
        "logged_day": logged,
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
        "adherence_score": _adherence_score(totals, targets, logged=logged),
        "confidence": "medium" if logged and target_calories else "low",
        "confidence_factors": {
            "logged_items": len(food_rows),
            "targets_present": bool(target_calories and target_protein),
            "missing_days_are_zero": False,
        },
        "notes": "Finalized from raw food logs. Missing days are not synthesized as zero.",
        "finalized_at": now if finalized else None,
        "updated_at": now,
    }


def _history_adherence(items: list[dict[str, Any]]) -> dict[str, Any]:
    logged = [item for item in items if item.get("nutrition_logged") or item.get("logged_day")]
    calories = [_number(item.get("total_calories"), 0) for item in logged if item.get("total_calories") is not None]
    protein = [_number(item.get("total_protein"), 0) for item in logged if item.get("total_protein") is not None]
    target_calories = [_number(item.get("target_calories"), 0) for item in logged if _number(item.get("target_calories"), 0) > 0]
    target_protein = [_number(item.get("target_protein"), 0) for item in logged if _number(item.get("target_protein"), 0) > 0]
    scores = [_number(item.get("adherence_score"), 0) for item in logged if item.get("adherence_score") is not None]
    dates = sorted({str(item.get("date") or "")[:10] for item in logged if item.get("date")})
    missing_days = 0
    if len(dates) >= 2:
        start = date_cls.fromisoformat(dates[0])
        end = date_cls.fromisoformat(dates[-1])
        missing_days = max(0, (end - start).days + 1 - len(dates))
    confidence = "high" if len(logged) >= 14 and missing_days <= 1 else "medium" if len(logged) >= 7 and missing_days <= 3 else "low"
    avg_calories = round(sum(calories) / len(calories), 1) if calories else None
    avg_target_calories = round(sum(target_calories) / len(target_calories), 1) if target_calories else None
    avg_protein = round(sum(protein) / len(protein), 1) if protein else None
    avg_target_protein = round(sum(target_protein) / len(target_protein), 1) if target_protein else None
    return {
        "average_calories": avg_calories,
        "average_target_calories": avg_target_calories,
        "average_calories_delta": _round((avg_calories or 0) - avg_target_calories) if avg_calories is not None and avg_target_calories else None,
        "average_protein": avg_protein,
        "average_target_protein": avg_target_protein,
        "average_protein_delta": _round((avg_protein or 0) - avg_target_protein) if avg_protein is not None and avg_target_protein else None,
        "days_over_target": sum(1 for item in logged if item.get("calories_delta") is not None and _number(item.get("calories_delta"), 0) > 0),
        "days_under_target": sum(1 for item in logged if item.get("calories_delta") is not None and _number(item.get("calories_delta"), 0) < 0),
        "consistency_score": int(round(sum(scores) / len(scores))) if scores else None,
        "logged_days": len(logged),
        "missing_days": missing_days,
        "confidence": confidence,
        "data_quality_note": "Only logged/finalized days are included; missing days lower confidence and are not counted as zero.",
    }


def _normalize_food_log(payload: dict[str, Any], *, food_log_id: str | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload)
    item["food_log_id"] = food_log_id or str(item.get("food_log_id") or uuid4())
    item["date"] = str(item.get("date") or _today_iso())
    item["meal_type"] = str(item.get("meal_type") or "Food")
    item["food_name"] = str(item.get("food_name") or item.get("name") or "Food").strip() or "Food"
    item["protein"] = _number(item.get("protein", item.get("protein_g")), 0)
    item["carbs"] = _number(item.get("carbs", item.get("carbs_g")), 0)
    item["fat"] = _number(item.get("fat", item.get("fat_g")), 0)
    item["calories"] = _number(item.get("calories"), 0)
    if item["calories"] <= 0 and (item["protein"] > 0 or item["carbs"] > 0 or item["fat"] > 0):
        item["calories"] = _macro_calories(item["protein"], item["carbs"], item["fat"])
    if "fiber" not in item and "fiber_g" in item:
        item["fiber"] = item.get("fiber_g")
    if "sugar" not in item and "sugar_g" in item:
        item["sugar"] = item.get("sugar_g")
    if "sodium" not in item and "sodium_mg" in item:
        item["sodium"] = item.get("sodium_mg")
    item.setdefault("source", "manual")
    item.setdefault("created_at", now)
    _ensure_food_log_sequence(item)
    item["updated_at"] = now
    return item


def _normalize_food_update(payload: dict[str, Any], *, food_log_id: str) -> dict[str, Any]:
    item = dict(payload)
    item["food_log_id"] = food_log_id
    if "name" in item and "food_name" not in item:
        item["food_name"] = item.pop("name")
    for target, aliases in {
        "protein": ("protein_g",),
        "carbs": ("carbs_g",),
        "fat": ("fat_g",),
        "fiber": ("fiber_g",),
        "sugar": ("sugar_g",),
        "sodium": ("sodium_mg",),
    }.items():
        for alias in aliases:
            if alias in item and target not in item:
                item[target] = item.pop(alias)
    for field in ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium", "potassium"):
        if field in item and item[field] is not None:
            item[field] = _number(item[field], 0)
    item["updated_at"] = utc_now_iso()
    return item


def _normalize_shortcut(payload: dict[str, Any], *, shortcut_id: str | None = None) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload)
    item["shortcut_id"] = shortcut_id or str(item.get("shortcut_id") or uuid4())
    item["shortcut_name"] = str(item.get("shortcut_name") or item.get("food_name") or item.get("name") or "Food").strip() or "Food"
    item["calories"] = _number(item.get("calories"), 0)
    item["protein"] = _number(item.get("protein", item.get("protein_g")), 0)
    item["carbs"] = _number(item.get("carbs", item.get("carbs_g")), 0)
    item["fat"] = _number(item.get("fat", item.get("fat_g")), 0)
    item.setdefault("fiber", None)
    item.setdefault("sodium", None)
    item.setdefault("potassium", None)
    item.setdefault("notes", "")
    item.setdefault("source", "manual")
    item.setdefault("created_at", now)
    item["updated_at"] = now
    return item


def _shortcut_to_log(shortcut: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(payload or {})
    return _normalize_food_log(
        {
            "date": payload.get("date") or _today_iso(),
            "meal_type": payload.get("meal_type") or shortcut.get("default_meal_type") or "Food",
            "food_name": shortcut.get("shortcut_name") or shortcut.get("food_name") or "Food",
            "iconType": shortcut.get("iconType") or shortcut.get("icon_type"),
            "calories": shortcut.get("calories", 0),
            "protein": shortcut.get("protein", 0),
            "carbs": shortcut.get("carbs", 0),
            "fat": shortcut.get("fat", 0),
            "fiber": shortcut.get("fiber"),
            "sodium": shortcut.get("sodium"),
            "potassium": shortcut.get("potassium"),
            "serving_size_grams": shortcut.get("serving_size_grams"),
            "grams_consumed": shortcut.get("default_grams_consumed"),
            "source": "shortcut",
            "source_id": shortcut.get("shortcut_id"),
        }
    )


def _find_shortcut(shortcut_id: str) -> dict[str, Any] | None:
    rows = fetch_json_rows_for_value("food_shortcuts", "shortcut_id", shortcut_id, limit=1)
    return rows[0] if rows and "_db_error" not in rows[0] else None


@router.get("/api/nutrition/today")
def get_nutrition_today(date: str | None = None) -> dict[str, Any]:
    selected_date = str(date or _today_iso())
    items = fetch_json_rows_for_value("food_logs", "date", selected_date, limit=500)
    return {
        "date": selected_date,
        "items": items,
        "totals": _totals(items),
        "targets": _target_payload(),
        "finalized": False,
        "status": "ok",
    }


@router.get("/api/nutrition/logs")
def get_nutrition_logs(
    date: str | None = None,
    limit: int = 300,
    days: int = 90,
    since_date: str | None = None,
) -> dict[str, Any]:
    bounded_limit = _bounded_route_limit(limit)
    if date:
        selected_date = _normalize_history_date(date)
        query_meta = {"mode": "date", "date": selected_date}
        cache_key: tuple[Any, ...] = ("date", selected_date, bounded_limit)
    else:
        bounded_window_days = _bounded_days(days)
        cutoff = _normalize_history_date(since_date) if since_date else (date_cls.fromisoformat(app_today_iso()) - timedelta(days=bounded_window_days)).isoformat()
        query_meta = {"mode": "recent", "days": bounded_window_days, "since_date": cutoff}
        cache_key = ("recent", cutoff, bounded_limit)
    cached = _cached_nutrition_logs(cache_key)
    if cached is not None:
        return cached
    index_result = ensure_jsonb_performance_indexes("food_logs")
    if date:
        items = fetch_json_rows_for_value("food_logs", "date", query_meta["date"], limit=bounded_limit)
    else:
        items = fetch_json_rows("food_logs", limit=bounded_limit, date_field="date", since_date=query_meta["since_date"])
    if items and isinstance(items[0], dict) and "_db_error" in items[0]:
        logger.warning("[nutrition_logs] query failed meta=%s error=%s", query_meta, items[0].get("_db_error"))
        return {
            "status": "error",
            "items": [],
            "error": items[0].get("_db_error"),
            "meta": {**query_meta, "limit": bounded_limit, "returned": 0, "index_status": index_result.get("status")},
        }
    response = {
        "status": "ok",
        "items": items,
        "meta": {
            **query_meta,
            "limit": bounded_limit,
            "returned": len(items),
            "index_status": index_result.get("status"),
            "index_cached": index_result.get("cached"),
            "cache": "miss",
            "cache_hit": False,
        },
    }
    _cache_nutrition_logs(cache_key, response)
    return response


@router.post("/api/nutrition/logs")
def post_nutrition_log(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("food_logs", _normalize_food_log(payload))
    _invalidate_nutrition_logs_cache()
    return {"item": item}


@router.put("/api/nutrition/logs/{food_log_id}")
def put_nutrition_log(food_log_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = fetch_json_rows_for_value("food_logs", "food_log_id", food_log_id, limit=1)
    if not existing or "_db_error" in existing[0]:
        raise HTTPException(status_code=404, detail="Food log not found")
    item = upsert_json_row("food_logs", "food_log_id", food_log_id, _normalize_food_update(payload, food_log_id=food_log_id))
    _invalidate_nutrition_logs_cache()
    return {"item": item}


@router.delete("/api/nutrition/logs/{food_log_id}")
def delete_nutrition_log(food_log_id: str) -> dict[str, Any]:
    result = delete_json_row("food_logs", "food_log_id", food_log_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result)
    _invalidate_nutrition_logs_cache()
    return result


@router.patch("/api/nutrition/reorder")
def patch_nutrition_timeline_order(payload: dict[str, Any]) -> dict[str, Any]:
    selected_date = _normalize_history_date(str(payload.get("date") or _today_iso()))
    raw_items = payload.get("ordered_items")
    if not isinstance(raw_items, list) or not raw_items:
        raise HTTPException(status_code=400, detail="ordered_items must include at least one food or workout marker.")

    validated: list[tuple[str, str, float, dict[str, Any]]] = []
    errors: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_items, start=1):
        if not isinstance(raw_item, dict):
            errors.append({"index": index - 1, "message": "Timeline item must be an object."})
            continue
        item_type = str(raw_item.get("type") or raw_item.get("item_type") or "").strip().lower()
        if item_type in {"marker", "workout"}:
            item_type = "workout_marker"
        item_id = str(raw_item.get("id") or raw_item.get("item_id") or "").strip()
        sequence = _order_number(raw_item.get("sequence")) or float(index)
        if item_type not in {"food", "workout_marker"}:
            errors.append({"index": index - 1, "message": "Timeline item type must be food or workout_marker."})
            continue
        if not item_id:
            errors.append({"index": index - 1, "message": "Timeline item id is required."})
            continue

        table = "food_logs" if item_type == "food" else "workout_markers"
        key_field = "food_log_id" if item_type == "food" else "marker_id"
        existing_rows = _valid_json_rows(fetch_json_rows_for_value(table, key_field, item_id, limit=1))
        if not existing_rows:
            errors.append({"index": index - 1, "message": f"{item_type} item was not found.", "id": item_id})
            continue
        existing = existing_rows[0]
        existing_date = str(existing.get("date") or "")[:10]
        if existing_date != selected_date:
            errors.append({"index": index - 1, "message": "Timeline item does not belong to the selected date.", "id": item_id, "date": existing_date})
            continue
        validated.append((item_type, item_id, sequence, existing))

    if errors:
        raise HTTPException(status_code=400, detail={"message": "Food timeline order could not be saved.", "errors": errors})

    now = utc_now_iso()
    updated_food = 0
    updated_markers = 0
    for item_type, item_id, sequence, existing in validated:
        item = dict(existing)
        item["created_order"] = sequence
        item["updated_at"] = now
        if item_type == "food":
            item["logged_sequence"] = sequence
            saved = upsert_json_row("food_logs", "food_log_id", item_id, item)
            updated_food += 1
        else:
            item["marker_sequence"] = sequence
            saved = upsert_json_row("workout_markers", "marker_id", item_id, item)
            updated_markers += 1
        if isinstance(saved, dict) and "_db_error" in saved:
            raise HTTPException(status_code=500, detail={"message": "Food timeline order could not be saved.", "diagnostics": saved["_db_error"]})

    _invalidate_nutrition_logs_cache()
    today_payload = get_nutrition_today(selected_date)
    markers = [
        marker
        for marker in get_workout_markers()["items"]
        if str(marker.get("date") or "")[:10] == selected_date
    ]
    return {
        "status": "ok",
        "date": selected_date,
        "updated_rows": len(validated),
        "food_updates": updated_food,
        "marker_updates": updated_markers,
        "items": today_payload.get("items", []),
        "markers": markers,
        "message": "Food timeline order saved.",
    }


@router.get("/api/nutrition/history")
def get_nutrition_history(limit: int = 500) -> dict[str, Any]:
    finalized = [
        row
        for row in fetch_json_rows("daily_nutrition_summary", limit=limit, date_field="date")
        if isinstance(row, dict) and "_db_error" not in row and row.get("date") and not _is_excluded(row)
    ]
    logs = fetch_json_rows("food_logs", limit=limit, date_field="date")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in logs:
        if _is_excluded(item):
            continue
        item_date = str(item.get("date") or "")
        if item_date:
            grouped[item_date].append(item)
    finalized_dates = {str(row.get("date")) for row in finalized}
    items = list(finalized)
    for day, day_items in grouped.items():
        if day in finalized_dates:
            continue
        totals = _totals(day_items)
        items.append(
            {
                "date": day,
                "total_calories": totals["calories"],
                "total_protein": totals["protein"],
                "total_carbs": totals["carbs"],
                "total_fat": totals["fat"],
                "fiber": totals["fiber"],
                "sodium": None,
                "potassium": None,
                "magnesium": None,
                "calcium": None,
                "iron": None,
                "zinc": None,
                "vitamin_d": None,
                "omega_3": None,
                "target_calories": None,
                "target_protein": None,
                "target_carbs": None,
                "target_fat": None,
                "calories_delta": None,
                "protein_delta": None,
                "carbs_delta": None,
                "fat_delta": None,
                "adherence_score": None,
                "nutrition_logged": True,
                "logged_day": True,
                "finalized": False,
                "notes": "Raw log summary. Missing days are omitted.",
            }
        )
    items.sort(key=lambda row: row["date"], reverse=True)
    return {
        "items": items,
        "adherence": _history_adherence(items),
    }


@router.post("/api/nutrition/finalize-day")
def finalize_nutrition_day(payload: dict[str, Any] | None = None, date: str | None = None) -> dict[str, Any]:
    raw_date = date or (payload or {}).get("date") or _today_iso()
    selected_date = _normalize_history_date(str(raw_date))
    summary = _daily_summary_from_logs(selected_date, finalized=True)
    if not summary.get("nutrition_logged"):
        return {
            "status": "skipped",
            "date": selected_date,
            "summary": {**summary, "finalized": False, "status": "missing"},
            "message": "No food logs exist for this date, so no zero-calorie summary was created.",
        }
    saved = upsert_json_row("daily_nutrition_summary", "date", selected_date, summary)
    if isinstance(saved, dict) and saved.get("_db_error"):
        raise HTTPException(status_code=500, detail=saved["_db_error"])
    return {"status": "ok", "date": selected_date, "summary": saved}


@router.post("/api/nutrition/history/{history_date}/finalize")
def finalize_nutrition_history_day(history_date: str) -> dict[str, Any]:
    return finalize_nutrition_day({"date": history_date})


@router.post("/api/nutrition/history/{history_date}/exclude")
def exclude_nutrition_history_day(history_date: str) -> dict[str, Any]:
    selected_date = _normalize_history_date(history_date)
    now = utc_now_iso()
    patch = {
        "date": selected_date,
        "excluded_from_analytics": True,
        "excluded_at": now,
        "exclusion_reason": "User excluded incomplete nutrition day from analytics.",
        "updated_at": now,
    }
    logs_result = update_json_rows_for_value("food_logs", "date", selected_date, patch)
    summary_result = update_json_rows_for_value("daily_nutrition_summary", "date", selected_date, patch)
    if logs_result.get("status") == "error" or summary_result.get("status") == "error":
        raise HTTPException(status_code=500, detail={"food_logs": logs_result, "daily_nutrition_summary": summary_result})
    marker = upsert_json_row(
        "daily_nutrition_summary",
        "date",
        selected_date,
        {
            **patch,
            "summary_id": f"nutrition-excluded:{selected_date}",
            "status": "excluded",
            "finalized": False,
            "nutrition_logged": False,
            "logged_day": False,
            "notes": "Excluded from analytics by user; raw food logs remain stored.",
        },
    )
    _invalidate_nutrition_logs_cache()
    return {
        "status": "ok",
        "date": selected_date,
        "rule": "excluded_from_analytics",
        "updated_rows": int(logs_result.get("updated_rows") or 0) + int(summary_result.get("updated_rows") or 0),
        "food_log_rows_updated": int(logs_result.get("updated_rows") or 0),
        "summary_rows_updated": int(summary_result.get("updated_rows") or 0),
        "marker_saved": not bool(isinstance(marker, dict) and marker.get("_db_error")),
        "message": f"Nutrition day {selected_date} excluded from analytics.",
    }


@router.get("/api/nutrition/shortcuts")
def get_nutrition_shortcuts() -> dict[str, Any]:
    return {
        "items": fetch_json_rows("food_shortcuts", limit=500),
        "frequent_foods": [],
        "meal_templates": [],
    }


@router.post("/api/nutrition/shortcuts")
def post_nutrition_shortcut(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("food_shortcuts", _normalize_shortcut(payload))
    return {"item": item}


@router.put("/api/nutrition/shortcuts/{shortcut_id}")
def put_nutrition_shortcut(shortcut_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    item = upsert_json_row("food_shortcuts", "shortcut_id", shortcut_id, _normalize_shortcut(payload, shortcut_id=shortcut_id))
    return {"item": item}


@router.delete("/api/nutrition/shortcuts/{shortcut_id}")
def delete_nutrition_shortcut(shortcut_id: str) -> dict[str, Any]:
    result = delete_json_row("food_shortcuts", "shortcut_id", shortcut_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result)
    return result


@router.post("/api/nutrition/shortcuts/{shortcut_id}/log")
def log_nutrition_shortcut(shortcut_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    shortcut = _find_shortcut(shortcut_id)
    if not shortcut:
        raise HTTPException(status_code=404, detail="Shortcut not found")
    item = insert_json_row("food_logs", _shortcut_to_log(shortcut, payload))
    _invalidate_nutrition_logs_cache()
    return {"item": item}


@router.post("/api/food/analyze-text")
def analyze_food_text(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    text = str((payload or {}).get("text") or "").strip()
    force_openai = bool((payload or {}).get("force_openai", False))
    steps: dict[str, Any] = {"route_entered": True, "text_length": len(text), "force_openai": force_openai}
    logger.info("[food_ai] route_entered endpoint=/api/food/analyze-text")
    logger.info("[food_ai] text_length=%s", len(text))
    try:
        from src.ai.food_parser import analyze_food_text as analyze_text
        from src.ai.food_parser import openai_analyzer_config
        from src.ai.food_parser import get_openai_key_status
    except Exception as exc:
        logger.exception("[food_ai] failed step=import_parser error_type=%s message=%s", type(exc).__name__, exc)
        return _food_ai_error_response(
            steps=steps,
            started=started,
            message="AI food parsing is temporarily unavailable. You can still log foods manually.",
            error_code="ai_parser_unavailable",
            failed_step="import_parser",
            exc=exc,
        )
    analyzer_config = openai_analyzer_config()
    steps["openai_configured"] = bool(analyzer_config.get("openai_key_configured"))
    steps["model"] = analyzer_config.get("model")
    logger.info("[food_ai] openai_configured=%s", steps["openai_configured"])
    logger.info("[food_ai] model=%s", analyzer_config.get("model"))
    if not get_openai_key_status():
        logger.warning("[food_ai] config_check warning=missing OpenAI key; saved-food/parser fallback path will still run")
    try:
        logger.info("[food_ai] parser_request_start")
        logger.info("[food_ai] pre_openai_step=saved_food_then_openai")
        result = analyze_text(text, force_openai=force_openai)
        response = _food_ai_response(result, analyzer_config, steps, started)
        logger.info(
            "[food_ai] parser_success model=%s fallback_model_used=%s success=%s error_code=%s",
            analyzer_config.get("model"),
            analyzer_config.get("fallback_model_used"),
            response.get("success"),
            response.get("error_code"),
        )
        logger.info("[food_ai] json_parse_success=%s", bool(response.get("success")))
        logger.info("[food_ai] returned_items=%s", len(response.get("items") or []))
        return response
    except Exception as exc:
        logger.exception("[food_ai] failed step=analyze_text error_type=%s message=%s", type(exc).__name__, exc)
        return _food_ai_error_response(
            analyzer_config=analyzer_config,
            steps=steps,
            started=started,
            message=f"AI parser failed at analyze_text: {exc}",
            error_code="ai_parser_error",
            failed_step="analyze_text",
            exc=exc,
        )


@router.post("/api/debug/food-parser-test")
def debug_food_parser_test(payload: dict[str, Any]) -> dict[str, Any]:
    text = str((payload or {}).get("text") or "").strip() or "banana and protein shake"
    request_body = {"text": text}
    route_payload = {**request_body, "force_openai": True}
    result = analyze_food_text(route_payload)
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    steps = result.get("steps") if isinstance(result.get("steps"), dict) else {}
    items = result.get("items") if isinstance(result.get("items"), list) else []
    foods = result.get("foods") if isinstance(result.get("foods"), list) else items
    diagnostic = {
        "endpoint_called": "/api/food/analyze-text",
        "request_body_received": request_body,
        "diagnostic_force_openai": True,
        "openai_called": bool(steps.get("openai_called") or debug.get("openai_called")),
        "model_used": steps.get("model_used") or debug.get("model") or "",
        "parser_source": result.get("parser_source") or debug.get("parser_source") or result.get("source") or "",
        "external_lookup_status": result.get("external_lookup_status") or debug.get("external_lookup_status") or "skipped",
        "raw_items_count": int(steps.get("raw_items_count") or len(foods)),
        "normalized_items_count": int(steps.get("normalized_items_count") or len(items)),
        "response_shape": {
            "keys": sorted(str(key) for key in result.keys()),
            "has_items": isinstance(result.get("items"), list),
            "has_foods": isinstance(result.get("foods"), list),
            "has_totals": isinstance(result.get("totals"), dict),
            "has_total": isinstance(result.get("total"), dict),
            "status": result.get("status") or ("ok" if result.get("success") else "error"),
        },
        "frontend_received_items": False,
        "log_insert_attempted": False,
        "log_insert_success": False,
    }
    return {
        "status": result.get("status") or ("ok" if result.get("success") else "error"),
        "openai_connected": bool(debug.get("openai_key_configured")) and result.get("status") == "ok",
        **diagnostic,
        "items": items,
        "foods": foods,
        "totals": result.get("totals") or FOOD_AI_EMPTY_TOTALS,
        "raw_model_excerpt": "",
        "steps": steps,
        "debug": debug,
        "message": result.get("message") or "",
        "error_code": result.get("error_code"),
    }


@router.post("/api/nutrition/label-upload")
async def upload_nutrition_label(file: UploadFile = File(...)) -> dict[str, Any]:
    content_type = str(file.content_type or "").lower()
    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
        return {
            "status": "unsupported_file_type",
            "message": "AI nutrition label extraction supports PNG, JPG, JPEG, or WebP images. You can still enter the label manually.",
            "items": [],
            "path": file.filename or "nutrition-label",
        }
    image_bytes = await file.read()
    if not image_bytes:
        return {"status": "error", "message": "The uploaded label image was empty.", "items": [], "path": file.filename or "nutrition-label"}
    if len(image_bytes) > 8 * 1024 * 1024:
        return {"status": "error", "message": "The uploaded label image is too large. Use an image under 8 MB.", "items": [], "path": file.filename or "nutrition-label"}
    try:
        from src.ai.food_parser import analyze_food_label_image
        from src.ai.food_parser import openai_analyzer_config
        from src.ai.food_parser import get_openai_key_status
    except Exception as exc:
        logger.exception("AI food label analyzer import failed.")
        return {"status": "error", "message": "AI label extraction is temporarily unavailable. You can still enter the label manually.", "items": [], "path": file.filename or "nutrition-label", "debug": {"error_type": type(exc).__name__}}
    analyzer_config = openai_analyzer_config()
    if not get_openai_key_status():
        return {
            "status": "openai_not_configured",
            "message": "AI label extraction is not configured yet. You can still enter the label manually.",
            "items": [],
            "path": file.filename or "nutrition-label",
            "debug": {**analyzer_config, "backend_endpoint_reached": True, "parsing_status": "not_configured"},
        }
    try:
        result = analyze_food_label_image(image_bytes, content_type, context=file.filename or "")
        logger.info(
            "[nutrition_label_upload] model=%s fallback_model_used=%s success=%s items=%s",
            analyzer_config.get("model"),
            analyzer_config.get("fallback_model_used"),
            result.get("success"),
            len(result.get("items") or []),
        )
        return {
            "status": "ok" if result.get("success") else "needs_review",
            "message": result.get("message") or "Nutrition label analyzed. Review before saving.",
            "items": result.get("items", []),
            "totals": result.get("totals", {}),
            "warnings": result.get("warnings", []),
            "path": file.filename or "nutrition-label",
            "debug": {**analyzer_config, **(result.get("debug") if isinstance(result.get("debug"), dict) else {})},
        }
    except Exception as exc:
        logger.exception("AI food label extraction failed.")
        return {"status": "error", "message": "AI label extraction failed. You can still enter the label manually.", "items": [], "path": file.filename or "nutrition-label", "debug": {**analyzer_config, "backend_endpoint_reached": True, "parsing_status": "error", "error_type": type(exc).__name__}}


@router.post("/api/food/log-bulk")
def log_food_bulk(payload: dict[str, Any]) -> dict[str, Any]:
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else []
    if not raw_items:
        raise HTTPException(status_code=400, detail={"message": "No parsed food items were provided to save.", "code": "empty_food_bulk"})
    shared = {
        "date": payload.get("date") or _today_iso(),
        "meal_type": payload.get("meal_type") or "Food",
        "source": "bulk_log",
    }
    items = []
    errors = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            errors.append({"index": index, "message": "Parsed food item was not an object."})
            continue
        inserted = insert_json_row("food_logs", _normalize_food_log({**shared, **item}))
        if isinstance(inserted, dict) and inserted.get("status") == "error":
            errors.append({"index": index, "message": inserted.get("message") or "Database insert failed.", "detail": inserted})
            continue
        items.append(inserted)
    if errors:
        if items:
            _invalidate_nutrition_logs_cache()
        raise HTTPException(status_code=500, detail={"message": "Some parsed food items could not be saved.", "code": "food_bulk_insert_failed", "errors": errors, "created": len(items)})
    _invalidate_nutrition_logs_cache()
    return {"status": "ok", "items": items, "created": len(items), "requested": len(raw_items)}


@router.get("/api/workout-markers")
def get_workout_markers(limit: int = 500) -> dict[str, Any]:
    ensure_jsonb_table("workout_markers")
    rows = fetch_json_rows("workout_markers", limit=limit, date_field="date")
    if rows and "_db_error" in rows[0]:
        return {"status": "error", "items": [], "message": "Workout markers are unavailable.", "diagnostics": rows[0]["_db_error"]}
    items = sorted(
        [_normalize_workout_marker(row) for row in _valid_json_rows(rows)],
        key=lambda row: (str(row.get("date") or ""), _order_number(row.get("marker_sequence")) or _order_number(row.get("created_order")) or -1, str(row.get("created_at") or "")),
        reverse=True,
    )
    return {
        "status": "ok",
        "items": items,
        "source": "workout_markers",
        "diagnostics": {"rows": len(items), "storage": "jsonb"},
    }


@router.post("/api/workout-markers")
def post_workout_marker(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_workout_marker(payload, assign_sequence=True)
    item = insert_json_row("workout_markers", normalized)
    if isinstance(item, dict) and "_db_error" in item:
        return {"status": "error", "item": normalized, "items": [], "message": "Workout marker could not be saved.", "diagnostics": item["_db_error"]}
    items = get_workout_markers()["items"]
    return {"status": "ok", "item": _normalize_workout_marker(item), "items": items, "message": "Workout marker saved."}
