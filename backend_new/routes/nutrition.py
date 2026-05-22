from __future__ import annotations

from collections import defaultdict
from datetime import date
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend_new.db import (
    delete_json_row,
    fetch_json_rows,
    fetch_json_rows_for_value,
    fetch_latest_document,
    insert_json_row,
    update_json_rows_for_value,
    upsert_json_row,
)
from backend_new.utils import utc_now_iso


router = APIRouter(tags=["nutrition"])
logger = logging.getLogger(__name__)

TOTAL_FIELDS = ("calories", "protein", "carbs", "fat", "fiber")


def _today_iso() -> str:
    from datetime import date

    return date.today().isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed


def _round(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _is_excluded(item: dict[str, Any]) -> bool:
    return item.get("excluded_from_analytics") is True or str(item.get("excluded_from_analytics") or "").lower() == "true"


def _normalize_history_date(value: str) -> str:
    try:
        return date.fromisoformat(str(value or "").strip()[:10]).isoformat()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Date must be a valid YYYY-MM-DD value.") from exc


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
        start = date.fromisoformat(dates[0])
        end = date.fromisoformat(dates[-1])
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
    item["calories"] = _number(item.get("calories"), 0)
    item["protein"] = _number(item.get("protein", item.get("protein_g")), 0)
    item["carbs"] = _number(item.get("carbs", item.get("carbs_g")), 0)
    item["fat"] = _number(item.get("fat", item.get("fat_g")), 0)
    if "fiber" not in item and "fiber_g" in item:
        item["fiber"] = item.get("fiber_g")
    if "sugar" not in item and "sugar_g" in item:
        item["sugar"] = item.get("sugar_g")
    if "sodium" not in item and "sodium_mg" in item:
        item["sodium"] = item.get("sodium_mg")
    item.setdefault("source", "manual")
    item.setdefault("created_at", now)
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
def get_nutrition_logs(date: str | None = None, limit: int = 500) -> dict[str, Any]:
    items = fetch_json_rows_for_value("food_logs", "date", date, limit=limit) if date else fetch_json_rows("food_logs", limit=limit, date_field="date")
    return {"items": items}


@router.post("/api/nutrition/logs")
def post_nutrition_log(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("food_logs", _normalize_food_log(payload))
    return {"item": item}


@router.put("/api/nutrition/logs/{food_log_id}")
def put_nutrition_log(food_log_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = fetch_json_rows_for_value("food_logs", "food_log_id", food_log_id, limit=1)
    if not existing or "_db_error" in existing[0]:
        raise HTTPException(status_code=404, detail="Food log not found")
    item = upsert_json_row("food_logs", "food_log_id", food_log_id, _normalize_food_update(payload, food_log_id=food_log_id))
    return {"item": item}


@router.delete("/api/nutrition/logs/{food_log_id}")
def delete_nutrition_log(food_log_id: str) -> dict[str, Any]:
    result = delete_json_row("food_logs", "food_log_id", food_log_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result)
    return result


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
    return {"item": item}


@router.post("/api/food/analyze-text")
def analyze_food_text(payload: dict[str, Any]) -> dict[str, Any]:
    text = str((payload or {}).get("text") or "").strip()
    try:
        from src.ai.food_parser import analyze_food_text as analyze_text
        from src.ai.food_parser import openai_analyzer_config
        from src.ai.food_parser import get_openai_key_status
    except Exception as exc:
        logger.exception("AI food parser import failed.")
        return {
            "items": [],
            "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": None, "sugar_g": None, "sodium_mg": None},
            "warnings": [],
            "message": "AI food parsing is temporarily unavailable. You can still log foods manually.",
            "success": False,
            "error_code": "ai_parser_unavailable",
            "debug": {"backend_endpoint_reached": True, "openai_key_configured": False, "model": "unknown", "parsing_status": "import_error", "error_type": type(exc).__name__},
        }
    analyzer_config = openai_analyzer_config()
    if not get_openai_key_status():
        return {
            "items": [],
            "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": None, "sugar_g": None, "sodium_mg": None},
            "warnings": [],
            "message": "AI food parsing is not configured yet. You can still log foods manually.",
            "success": False,
            "error_code": "openai_not_configured",
            "debug": {**analyzer_config, "backend_endpoint_reached": True, "parsing_status": "not_configured"},
        }
    try:
        result = analyze_text(text)
        result["debug"] = {**analyzer_config, **(result.get("debug") if isinstance(result.get("debug"), dict) else {})}
        logger.info(
            "[food_analyze_text] model=%s fallback_model_used=%s success=%s error_code=%s items=%s",
            analyzer_config.get("model"),
            analyzer_config.get("fallback_model_used"),
            result.get("success"),
            result.get("error_code"),
            len(result.get("items") or []),
        )
        return result
    except Exception as exc:
        logger.exception("AI food parsing failed.")
        return {
            "items": [],
            "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": None, "sugar_g": None, "sodium_mg": None},
            "warnings": [],
            "message": "AI food parsing failed. You can still log foods manually.",
            "success": False,
            "error_code": "ai_parser_error",
            "debug": {**analyzer_config, "backend_endpoint_reached": True, "parsing_status": "error", "error_type": type(exc).__name__},
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
    shared = {
        "date": payload.get("date") or _today_iso(),
        "meal_type": payload.get("meal_type") or "Food",
        "source": "bulk_log",
    }
    items = [insert_json_row("food_logs", _normalize_food_log({**shared, **item})) for item in raw_items if isinstance(item, dict)]
    return {"status": "ok", "items": items, "created": len(items)}
