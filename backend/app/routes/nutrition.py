from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend.app.core.database import delete_row_by_data_id, insert_row, load_all_rows, load_rows_for_date, update_row_by_data_id
from backend.app.routes.goals import fallback_targets
from backend.app.core.database import load_document
from backend.app.schemas.constants import NUTRITION_TOTAL_FIELDS
from backend.app.utils.helpers import to_float, today_iso


router = APIRouter(tags=["nutrition"])


def _totals(items: list[dict]) -> dict:
    return {
        field: round(sum(to_float(item.get(field), 0.0) for item in items), 1)
        for field in NUTRITION_TOTAL_FIELDS
    }


def _target_payload(targets: dict | None) -> dict:
    targets = targets or {}
    return {
        "calories": targets.get("target_calories"),
        "protein": targets.get("protein_grams"),
        "carbs": targets.get("carb_grams"),
        "fat": targets.get("fat_grams"),
        "raw": targets,
    }


def nutrition_today_payload(date: str | None = None) -> dict:
    selected_date = str(date or today_iso())
    items = load_rows_for_date("nutrition_log", selected_date, limit=500, timeout_ms=1000)
    targets = load_document("nutrition_targets", fallback_targets(), timeout_ms=750) or fallback_targets()
    return {
        "date": selected_date,
        "items": items,
        "totals": _totals(items),
        "targets": _target_payload(targets),
        "debug": {
            "status": "ok",
            "mode": "clean_backend_lightweight",
            "item_count": len(items),
        },
    }


@router.get("/api/nutrition/today")
def get_nutrition_today(date: str | None = None) -> dict:
    return nutrition_today_payload(date)


@router.get("/api/nutrition/logs")
def get_nutrition_logs(date: str | None = None, limit: int = 500) -> dict:
    items = load_rows_for_date("nutrition_log", date, limit=limit, timeout_ms=1000) if date else load_all_rows("nutrition_log", limit=limit, timeout_ms=1000)
    return {"items": items}


@router.post("/api/nutrition/logs")
def create_nutrition_log(payload: dict) -> dict:
    item = {**payload, "food_log_id": payload.get("food_log_id") or f"food_{uuid4().hex[:12]}"}
    return {"item": insert_row("nutrition_log", item, timeout_ms=1000)}


@router.put("/api/nutrition/logs/{food_log_id}")
def update_nutrition_log(food_log_id: str, payload: dict) -> dict:
    item = update_row_by_data_id("nutrition_log", "food_log_id", food_log_id, payload, timeout_ms=1000)
    if item is None:
        raise HTTPException(status_code=404, detail="Nutrition log not found")
    return {"item": item}


@router.delete("/api/nutrition/logs/{food_log_id}")
def delete_nutrition_log(food_log_id: str) -> dict:
    return {"status": "ok", "deleted": delete_row_by_data_id("nutrition_log", "food_log_id", food_log_id, timeout_ms=1000)}


@router.get("/api/nutrition/history")
def get_nutrition_history(limit: int = 90) -> dict:
    return {"items": load_all_rows("daily_nutrition_summary", limit=limit, timeout_ms=1000), "adherence": {"status": "deferred"}}


@router.get("/api/nutrition/shortcuts")
def get_nutrition_shortcuts() -> dict:
    return {
        "shortcuts": load_all_rows("food_shortcut", limit=200, timeout_ms=1000),
        "frequent_foods": load_all_rows("frequent_food", limit=50, timeout_ms=1000),
        "meal_templates": load_all_rows("meal_template", limit=50, timeout_ms=1000),
    }


@router.post("/api/nutrition/shortcuts")
def create_nutrition_shortcut(payload: dict) -> dict:
    item = {**payload, "shortcut_id": payload.get("shortcut_id") or f"shortcut_{uuid4().hex[:12]}"}
    return {"item": insert_row("food_shortcut", item, timeout_ms=1000)}


@router.put("/api/nutrition/shortcuts/{shortcut_id}")
def update_nutrition_shortcut(shortcut_id: str, payload: dict) -> dict:
    item = update_row_by_data_id("food_shortcut", "shortcut_id", shortcut_id, payload, timeout_ms=1000)
    if item is None:
        raise HTTPException(status_code=404, detail="Shortcut not found")
    return {"item": item}


@router.delete("/api/nutrition/shortcuts/{shortcut_id}")
def delete_nutrition_shortcut(shortcut_id: str) -> dict:
    return {"status": "ok", "deleted": delete_row_by_data_id("food_shortcut", "shortcut_id", shortcut_id, timeout_ms=1000)}


@router.post("/api/nutrition/shortcuts/{shortcut_id}/log")
def log_nutrition_shortcut(shortcut_id: str, payload: dict | None = None) -> dict:
    data = dict(payload or {})
    item = {**data, "food_log_id": f"food_{uuid4().hex[:12]}", "source": "shortcut", "shortcut_id": shortcut_id}
    return {"item": insert_row("nutrition_log", item, timeout_ms=1000)}


@router.post("/api/nutrition/frequent-foods/{food_name}/log")
def log_frequent_food(food_name: str, payload: dict | None = None) -> dict:
    data = dict(payload or {})
    item = {**data, "food_log_id": f"food_{uuid4().hex[:12]}", "food": food_name, "source": "frequent_food"}
    return {"item": insert_row("nutrition_log", item, timeout_ms=1000)}


@router.post("/api/nutrition/meal-templates")
def create_meal_template(payload: dict) -> dict:
    item = {**payload, "template_name": payload.get("template_name") or payload.get("name") or f"template_{uuid4().hex[:8]}"}
    return {"item": insert_row("meal_template", item, timeout_ms=1000)}


@router.put("/api/nutrition/meal-templates/{template_name}")
def update_meal_template(template_name: str, payload: dict) -> dict:
    item = update_row_by_data_id("meal_template", "template_name", template_name, payload, timeout_ms=1000)
    return {"item": item or {**payload, "template_name": template_name}}


@router.post("/api/nutrition/meal-templates/{template_name}/log")
def log_meal_template(template_name: str, payload: dict | None = None) -> dict:
    data = dict(payload or {})
    item = {**data, "food_log_id": f"food_{uuid4().hex[:12]}", "source": "meal_template", "template_name": template_name}
    return {"item": insert_row("nutrition_log", item, timeout_ms=1000)}


@router.post("/api/nutrition/label-upload")
def upload_nutrition_label() -> dict:
    return {"status": "deferred", "message": "Label upload parsing is not enabled in the clean backend yet.", "items": []}


@router.post("/api/nutrition/ai/parse")
@router.post("/api/food/analyze-text")
def parse_food_text(payload: dict) -> dict:
    return {"status": "deferred", "text": payload.get("text", ""), "items": [], "message": "AI food parsing is disabled until explicitly re-enabled."}


@router.post("/api/food/log-bulk")
def log_food_bulk(payload: dict) -> dict:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    created = [insert_row("nutrition_log", {**item, "food_log_id": item.get("food_log_id") or f"food_{uuid4().hex[:12]}"}, timeout_ms=1000) for item in items if isinstance(item, dict)]
    return {"status": "ok", "items": created, "created": len(created)}
