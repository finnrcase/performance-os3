from fastapi import APIRouter
from pydantic import BaseModel

from backend.routes.utils import dataframe_records
from src.recovery import add_recovery_entry, load_recovery_log, load_sleep_entries


router = APIRouter(tags=["recovery"])


@router.get("/status")
def status() -> dict:
    """Return placeholder route status."""
    return {"status": "placeholder", "module": "recovery"}


class RecoveryEntry(BaseModel):
    date: str
    sleep_hours: float
    sleep_quality: int
    fatigue: int
    soreness: int
    stress: int
    motivation: int
    resting_hr: float | None = None
    hrv: float | None = None
    notes: str = ""


@router.get("/api/recovery/logs")
def get_recovery_logs() -> dict:
    """Return saved recovery logs."""
    return {"items": dataframe_records(load_recovery_log())}


@router.get("/api/recovery/sleep")
def get_sleep_entries() -> dict:
    """Return future-ready sleep entries from wearable or manual local data."""
    return {"items": dataframe_records(load_sleep_entries())}


@router.post("/api/recovery/logs")
def add_recovery_log(entry: RecoveryEntry) -> dict:
    """Add a local recovery check-in."""
    recovery_df = add_recovery_entry(**entry.model_dump())
    return {"items": dataframe_records(recovery_df)}
