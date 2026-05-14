from fastapi import APIRouter
from pydantic import BaseModel

from src.analytics.personal_records import (
    add_manual_pr,
    load_personal_records,
    update_personal_records_from_logs,
)
from src.training import load_training_log


router = APIRouter(tags=["personal-records"])


class ManualPersonalRecord(BaseModel):
    record_type: str
    value: float
    date: str
    reps: int = 1
    notes: str = ""


class BenchPersonalRecord(BaseModel):
    weight: float
    reps: int = 1
    date: str
    notes: str = ""


class MilePersonalRecord(BaseModel):
    minutes: int = 0
    seconds: int = 0
    date: str
    notes: str = ""


@router.get("/api/personal-records")
def get_personal_records() -> dict:
    """Return saved PRs after checking whether logs clearly beat them."""
    return update_personal_records_from_logs(load_training_log())


@router.post("/api/personal-records/manual")
def add_manual_personal_record(payload: ManualPersonalRecord) -> dict:
    """Add a manual bench or mile PR fallback."""
    return add_manual_pr(
        record_type=payload.record_type,
        value=payload.value,
        date=payload.date,
        reps=payload.reps,
        source="manual",
        notes=payload.notes,
    )


@router.put("/api/personal-records/bench")
def update_bench_personal_record(payload: BenchPersonalRecord) -> dict:
    """Manually override the bench press PR."""
    return add_manual_pr(
        record_type="bench_press",
        value=payload.weight,
        date=payload.date,
        reps=payload.reps,
        source="manual",
        notes=payload.notes,
    )


@router.put("/api/personal-records/mile")
def update_mile_personal_record(payload: MilePersonalRecord) -> dict:
    """Manually override the mile PR."""
    total_seconds = max(int(payload.minutes or 0), 0) * 60 + max(int(payload.seconds or 0), 0)
    return add_manual_pr(
        record_type="mile_time",
        value=total_seconds,
        date=payload.date,
        source="manual",
        notes=payload.notes,
    )


@router.post("/api/personal-records/recalculate")
def recalculate_personal_records() -> dict:
    """Recalculate PRs from local logs, overriding manual PRs if logs beat them."""
    return update_personal_records_from_logs(load_training_log(), force=True)
