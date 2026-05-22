from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter

from backend_new.db import fetch_json_rows, insert_json_row
from backend_new.utils import app_today_iso, utc_now_iso

router = APIRouter(tags=["recovery"])


def _today_iso() -> str:
    return app_today_iso()


def _number_or_none(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any, default: float = 0.0) -> float:
    parsed = _number_or_none(value)
    return default if parsed is None else parsed


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _sort_by_date(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda row: str(row.get("date") or ""))


def _normalize_recovery(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload)
    item["recovery_log_id"] = str(item.get("recovery_log_id") or item.get("id") or uuid4())
    item["id"] = item["recovery_log_id"]
    item["date"] = str(item.get("date") or _today_iso())
    item["sleep_hours"] = _number(item.get("sleep_hours"), 0)
    item["sleep_quality"] = _integer(item.get("sleep_quality"), 0)
    item["fatigue"] = _integer(item.get("fatigue"), 0)
    item["soreness"] = _integer(item.get("soreness"), 0)
    item["stress"] = _integer(item.get("stress"), 0)
    item["motivation"] = _integer(item.get("motivation"), 0)
    item["resting_hr"] = _number_or_none(item.get("resting_hr"))
    item["hrv"] = _number_or_none(item.get("hrv"))
    item.setdefault("notes", "")
    item.setdefault("source", "manual")
    item.setdefault("created_at", now)
    item["updated_at"] = now
    return item


def _normalize_sleep(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload)
    item["id"] = str(item.get("id") or item.get("sleep_log_id") or uuid4())
    item["sleep_log_id"] = item["id"]
    item["userId"] = str(item.get("userId") or item.get("user_id") or "default")
    item["date"] = str(item.get("date") or _today_iso())
    item["sleepStart"] = str(item.get("sleepStart") or item.get("sleep_start") or "")
    item["sleepEnd"] = str(item.get("sleepEnd") or item.get("sleep_end") or "")
    for field in ("durationMinutes", "efficiencyPercent", "deepSleepMinutes", "remSleepMinutes", "lightSleepMinutes", "awakeMinutes", "restingHeartRate", "hrv"):
        if field in item:
            item[field] = _number_or_none(item.get(field))
    item["source"] = str(item.get("source") or "manual")
    item.setdefault("createdAt", item.get("created_at") or now)
    item.setdefault("updatedAt", now)
    item["created_at"] = item["createdAt"]
    item["updated_at"] = now
    return item


@router.get("/api/recovery/logs")
def get_recovery_logs(limit: int = 500) -> dict[str, Any]:
    rows = fetch_json_rows("recovery_logs", limit=limit, date_field="date")
    if rows and "_db_error" in rows[0]:
        return {"items": [], "status": "error", "error": rows[0]["_db_error"]}
    return {"items": _sort_by_date([_normalize_recovery(row) for row in rows]), "status": "ok"}


@router.post("/api/recovery/logs")
def post_recovery_log(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("recovery_logs", _normalize_recovery(payload))
    return {"item": _normalize_recovery(item), "items": get_recovery_logs()["items"], "status": "ok"}


@router.get("/api/recovery/sleep")
def get_sleep_entries(limit: int = 500) -> dict[str, Any]:
    rows = fetch_json_rows("sleep_logs", limit=limit, date_field="date")
    if rows and "_db_error" in rows[0]:
        return {"items": [], "status": "error", "error": rows[0]["_db_error"]}
    return {"items": _sort_by_date([_normalize_sleep(row) for row in rows]), "status": "ok"}


@router.post("/api/recovery/sleep")
def post_sleep_entry(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("sleep_logs", _normalize_sleep(payload))
    return {"item": _normalize_sleep(item), "items": get_sleep_entries()["items"], "status": "ok"}
