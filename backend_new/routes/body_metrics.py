from __future__ import annotations

from datetime import date
import math
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend_new.db import (
    delete_json_row,
    fetch_json_rows,
    fetch_json_rows_for_value,
    insert_json_row,
    upsert_json_row,
)
from backend_new.utils import utc_now_iso
from src.body_metrics import canonical_bodyweight_debug, canonical_daily_bodyweights

router = APIRouter(tags=["body-metrics"])

NUMERIC_FIELDS = (
    "bodyweight",
    "waist",
    "estimated_body_fat",
    "body_fat_percent",
    "lean_mass",
    "fat_mass",
    "muscle_mass",
    "hydration",
    "bmi",
)


def _today_iso() -> str:
    return date.today().isoformat()


def _number_or_none(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _metric_id(item: dict[str, Any]) -> str:
    for field in ("body_metric_id", "id", "source_id"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return str(item.get("date") or uuid4())


def _is_excluded(item: dict[str, Any]) -> bool:
    return item.get("excluded_from_analytics") is True or str(item.get("excluded_from_analytics") or "").lower() in {"true", "1", "yes"}


def _normalize_metric(payload: dict[str, Any], *, body_metric_id: str | None = None, partial: bool = False) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload)
    item["body_metric_id"] = body_metric_id or str(item.get("body_metric_id") or item.get("id") or item.get("source_id") or uuid4())
    item["id"] = item["body_metric_id"]
    if not partial or "date" in item:
        item["date"] = str(item.get("date") or _today_iso())
    for field in NUMERIC_FIELDS:
        if field in item:
            item[field] = _number_or_none(item.get(field))
    body_fat = item.get("body_fat_percent")
    estimated = item.get("estimated_body_fat")
    if body_fat is None and estimated is not None:
        item["body_fat_percent"] = estimated
    if estimated is None and body_fat is not None:
        item["estimated_body_fat"] = body_fat
    item["source"] = str(item.get("source") or "manual")
    item.setdefault("source_id", "")
    item.setdefault("notes", "")
    item.setdefault("created_at", now)
    item["updated_at"] = now
    return item


def _public_metric(item: dict[str, Any]) -> dict[str, Any]:
    public = _normalize_metric(item, body_metric_id=_metric_id(item), partial=True)
    public.setdefault("date", str(item.get("date") or ""))
    public.setdefault("bodyweight", _number_or_none(item.get("bodyweight")))
    public.setdefault("waist", _number_or_none(item.get("waist")))
    public.setdefault("notes", str(item.get("notes") or ""))
    return public


def _sort_by_date(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda row: str(row.get("date") or ""))


def _canonical_public_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical = canonical_daily_bodyweights(rows)
    if canonical.empty:
        return []
    records = canonical.to_dict(orient="records")
    items = []
    for row in records:
        item = _public_metric(row)
        try:
            item["date"] = row["date"].date().isoformat()
        except Exception:
            item["date"] = str(row.get("date") or "")
        item["canonical_rule"] = "lowest_weight_per_day"
        items.append(item)
    return _sort_by_date(items)


def _find_metric(metric_id: str) -> dict[str, Any] | None:
    for field in ("body_metric_id", "id", "source_id"):
        rows = fetch_json_rows_for_value("body_metric_logs", field, metric_id, limit=1)
        if rows and "_db_error" not in rows[0]:
            return rows[0]
    return None


@router.get("/api/body-metrics")
def get_body_metrics(limit: int = 1000) -> dict[str, Any]:
    rows = fetch_json_rows("body_metric_logs", limit=limit, date_field="date")
    if rows and "_db_error" in rows[0]:
        return {"items": [], "status": "error", "error": rows[0]["_db_error"]}
    analytics_rows = [row for row in rows if not _is_excluded(row)]
    raw_items = _sort_by_date([_public_metric(row) for row in analytics_rows])
    canonical_items = _canonical_public_metrics(analytics_rows)
    return {
        "items": canonical_items,
        "canonical_items": canonical_items,
        "raw_items": raw_items,
        "excluded_raw_count": len(rows) - len(analytics_rows),
        "status": "ok",
        "debug": canonical_bodyweight_debug(rows),
    }


@router.post("/api/body-metrics")
def post_body_metric(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("body_metric_logs", _normalize_metric(payload))
    items = get_body_metrics()["items"]
    return {"item": _public_metric(item), "items": items, "status": "ok"}


@router.put("/api/body-metrics/{body_metric_id}")
def put_body_metric(body_metric_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = _find_metric(body_metric_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Body metric not found")
    key = "body_metric_id" if existing.get("body_metric_id") else "source_id" if existing.get("source_id") else "id"
    item = upsert_json_row("body_metric_logs", key, body_metric_id, _normalize_metric({**existing, **payload}, body_metric_id=body_metric_id, partial=True))
    return {"item": _public_metric(item), "status": "ok"}


@router.delete("/api/body-metrics/{body_metric_id}")
def delete_body_metric(body_metric_id: str) -> dict[str, Any]:
    deleted = 0
    errors = []
    for field in ("body_metric_id", "id", "source_id"):
        result = delete_json_row("body_metric_logs", field, body_metric_id)
        if result.get("status") == "error":
            errors.append(result)
        deleted += int(result.get("deleted") or 0)
        if deleted:
            break
    if errors and not deleted:
        raise HTTPException(status_code=500, detail=errors[0])
    return {"status": "ok", "deleted": deleted}
