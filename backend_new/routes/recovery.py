from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter
import pandas as pd

from backend_new.db import ensure_jsonb_table, fetch_json_rows, insert_json_row
from backend_new.utils import app_today_iso, json_safe, utc_now_iso
from src.wearables import calculate_training_readiness_signals, calculate_wearable_recovery_signals

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


def _valid_json_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and "_db_error" not in row]


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


def _normalize_wearable_metric(payload: dict[str, Any]) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload or {})
    item["metric_id"] = str(item.get("metric_id") or item.get("id") or uuid4())
    item["id"] = item["metric_id"]
    item["date"] = str(item.get("date") or _today_iso())[:10]
    item["source"] = str(item.get("source") or "manual").strip() or "manual"
    for field in [
        "sleep_hours",
        "sleep_score",
        "resting_hr",
        "hrv",
        "steps",
        "active_minutes",
        "calories_burned",
        "workout_minutes",
    ]:
        item[field] = _number_or_none(item.get(field))
    item.setdefault("created_at", now)
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


@router.get("/api/wearables/metrics")
def get_wearable_metrics(limit: int = 500) -> dict[str, Any]:
    ensure_jsonb_table("wearable_metrics")
    rows = fetch_json_rows("wearable_metrics", limit=limit, date_field="date")
    if rows and "_db_error" in rows[0]:
        return {"status": "error", "items": [], "message": "Wearable metrics are unavailable.", "diagnostics": rows[0]["_db_error"]}
    items = _sort_by_date([_normalize_wearable_metric(row) for row in _valid_json_rows(rows)])
    return {"status": "ok", "items": items, "source": "wearable_metrics", "diagnostics": {"rows": len(items), "storage": "jsonb"}}


@router.post("/api/wearables/metrics")
def post_wearable_metric(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("wearable_metrics", _normalize_wearable_metric(payload))
    if isinstance(item, dict) and "_db_error" in item:
        return {"status": "error", "item": _normalize_wearable_metric(payload), "items": [], "message": "Wearable metric could not be saved.", "diagnostics": item["_db_error"]}
    return {"status": "ok", "item": _normalize_wearable_metric(item), "items": get_wearable_metrics()["items"], "message": "Wearable metric saved."}


@router.get("/api/wearables/signals")
def get_wearable_signals(limit: int = 500) -> dict[str, Any]:
    metrics = get_wearable_metrics(limit=limit)
    try:
        signals = calculate_wearable_recovery_signals(pd.DataFrame(metrics.get("items") or []))
    except Exception as exc:
        return {"status": "error", "message": "Wearable recovery signals are unavailable.", "error": type(exc).__name__, "signals": {}}
    return json_safe(signals)


@router.get("/api/wearables/training-readiness")
def get_training_readiness_signals(limit: int = 500) -> dict[str, Any]:
    ensure_jsonb_table("workout_markers")
    metrics = get_wearable_metrics(limit=limit)
    recovery_rows = _valid_json_rows(fetch_json_rows("recovery_logs", limit=limit, date_field="date"))
    training_rows = _valid_json_rows(fetch_json_rows("workout_logs", limit=1000, date_field="date"))
    nutrition_rows = _valid_json_rows(fetch_json_rows("food_logs", limit=1000, date_field="date"))
    marker_rows = _valid_json_rows(fetch_json_rows("workout_markers", limit=limit, date_field="date"))
    try:
        signals = calculate_training_readiness_signals(
            pd.DataFrame(metrics.get("items") or []),
            pd.DataFrame(recovery_rows),
            pd.DataFrame(training_rows),
            pd.DataFrame(nutrition_rows),
            pd.DataFrame(marker_rows),
        )
    except Exception as exc:
        return {"status": "error", "message": "Training readiness signals are unavailable.", "error": type(exc).__name__, "signals": []}
    return json_safe(signals)
