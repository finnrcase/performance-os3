from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(tags=["recommendations"])


@router.post("/api/recommendations/run")
def run_recommendations(date: str | None = None, finalize_day: bool = False) -> dict:
    return {"status": "deferred", "date": date, "finalize_day": finalize_day, "recommendation_summary": "Recommendations are deferred in the clean backend."}


@router.put("/api/personal-records/bench")
def update_bench_record(payload: dict) -> dict:
    return {"status": "ok", "item": payload}


@router.put("/api/personal-records/mile")
def update_mile_record(payload: dict) -> dict:
    return {"status": "ok", "item": payload}


@router.post("/api/personal-records/recalculate")
def recalculate_personal_records() -> dict:
    return {"status": "deferred", "personal_records": {"bench_press": None, "mile_time": None}}

