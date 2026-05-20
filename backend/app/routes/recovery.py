from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter

from backend.app.core.database import insert_row, load_all_rows


router = APIRouter(tags=["recovery"])


@router.get("/api/recovery/logs")
def get_recovery_logs(limit: int = 180) -> dict:
    return {"items": load_all_rows("recovery_log", limit=limit, timeout_ms=1000)}


@router.post("/api/recovery/logs")
def create_recovery_log(payload: dict) -> dict:
    item = {**payload, "recovery_id": payload.get("recovery_id") or f"recovery_{uuid4().hex[:12]}"}
    return {"item": insert_row("recovery_log", item, timeout_ms=1000)}


@router.get("/api/recovery/sleep")
def get_sleep(limit: int = 180) -> dict:
    return {"items": load_all_rows("sleep_log", limit=limit, timeout_ms=1000)}


@router.post("/api/recovery/sleep")
def create_sleep(payload: dict) -> dict:
    item = {**payload, "sleep_id": payload.get("sleep_id") or f"sleep_{uuid4().hex[:12]}"}
    return {"item": insert_row("sleep_log", item, timeout_ms=1000)}

