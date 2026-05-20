from __future__ import annotations

from fastapi import APIRouter

from backend_v2.db import load_document, load_rows_for_date
from backend_v2.routes.goals import fallback_targets
from backend_v2.schemas import NUTRITION_TOTAL_FIELDS
from backend_v2.utils import to_float, today_iso

router = APIRouter(tags=["nutrition"])


def _totals(items: list[dict]) -> dict:
    return {field: round(sum(to_float(item.get(field), 0.0) for item in items), 1) for field in NUTRITION_TOTAL_FIELDS}


def _target_payload(targets: dict | None) -> dict:
    targets = targets or {}
    return {"calories": targets.get("target_calories"), "protein": targets.get("protein_grams"), "carbs": targets.get("carb_grams"), "fat": targets.get("fat_grams"), "raw": targets}


def nutrition_today_payload(date: str | None = None) -> dict:
    selected_date = str(date or today_iso())
    items = load_rows_for_date("nutrition_log", selected_date, limit=500, timeout_ms=1000)
    targets = load_document("nutrition_targets", fallback_targets(), timeout_ms=750) or fallback_targets()
    return {"date": selected_date, "items": items, "totals": _totals(items), "targets": _target_payload(targets), "debug": {"status": "ok", "mode": "backend_v2_lightweight", "item_count": len(items)}}


@router.get("/api/nutrition/today")
def get_nutrition_today(date: str | None = None) -> dict:
    return nutrition_today_payload(date)
