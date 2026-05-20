from __future__ import annotations

from collections import defaultdict
import os
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend_new.db import (
    delete_json_row,
    fetch_json_rows,
    fetch_json_rows_for_value,
    fetch_latest_document,
    insert_json_row,
    upsert_json_row,
)
from backend_new.utils import utc_now_iso


router = APIRouter(tags=["nutrition"])

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
        if isinstance(row, dict) and "_db_error" not in row and row.get("date")
    ]
    logs = fetch_json_rows("food_logs", limit=limit, date_field="date")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in logs:
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
        "adherence": {
            "average_calories": None,
            "average_target_calories": None,
            "average_calories_delta": None,
            "average_protein": None,
            "average_target_protein": None,
            "average_protein_delta": None,
            "days_over_target": 0,
            "days_under_target": 0,
            "consistency_score": None,
            "logged_days": len(items),
            "missing_days": 0,
            "confidence": "low",
            "data_quality_note": "Only logged days are returned; missing days are not synthesized as zero.",
        },
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
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return {
            "items": [],
            "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": None, "sugar_g": None, "sodium_mg": None},
            "warnings": ["OPENAI_API_KEY is not configured."],
            "message": "AI food parsing is unavailable because OPENAI_API_KEY is not configured. Manual food logging still works.",
            "success": False,
            "error_code": "openai_not_configured",
            "debug": {"ai_enabled": False},
        }
    return {
        "items": [],
        "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": None, "sugar_g": None, "sodium_mg": None},
        "warnings": ["AI parser is not enabled in backend_new yet."],
        "message": "AI food parsing is not enabled in backend_new yet. Manual food logging still works.",
        "success": False,
        "error_code": "ai_parser_disabled",
        "debug": {"ai_enabled": False, "text_length": len(str(payload.get("text") or ""))},
    }


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
