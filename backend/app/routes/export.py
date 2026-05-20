from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.database import load_all_rows


router = APIRouter(tags=["export"])


@router.get("/api/export/daily-csv")
def export_daily_csv(date: str | None = None) -> dict:
    return {"status": "ok", "date": date, "items": load_all_rows("nutrition_log", limit=1000, timeout_ms=1000)}


@router.get("/api/export/full-backup")
def export_full_backup() -> dict:
    return {
        "status": "ok",
        "data": {
            "nutrition_logs": load_all_rows("nutrition_log", limit=5000, timeout_ms=1000),
            "workout_logs": load_all_rows("training_log", limit=5000, timeout_ms=1000),
            "body_metrics": load_all_rows("body_metrics", limit=2000, timeout_ms=1000),
            "recovery_logs": load_all_rows("recovery_log", limit=2000, timeout_ms=1000),
            "sleep_logs": load_all_rows("sleep_log", limit=2000, timeout_ms=1000),
        },
    }


@router.post("/api/import/full-backup")
def import_full_backup(dry_run: bool = True) -> dict:
    return {"status": "deferred", "dry_run": dry_run, "message": "Full backup import is disabled in the clean backend."}

