from __future__ import annotations

import time

from fastapi import APIRouter

from backend_v2.db import count_estimates, ping
from backend_v2.utils import timed, utc_now_iso

router = APIRouter(tags=["debug"])


@router.get("/api/debug/startup")
def debug_startup() -> dict:
    started = time.perf_counter()
    checks = []
    db_result, block = timed("db_ping", ping)
    checks.append(block)
    raw_counts = count_estimates(["nutrition_log", "training_log", "body_metrics", "user_settings", "user_goals", "nutrition_targets"])
    counts = {"nutrition": raw_counts.get("nutrition_log", 0), "training": raw_counts.get("training_log", 0), "body_metrics": raw_counts.get("body_metrics", 0), "settings_documents": raw_counts.get("user_settings", 0), "goal_documents": raw_counts.get("user_goals", 0), "target_documents": raw_counts.get("nutrition_targets", 0)}
    return {"status": "ok" if not any(check.get("status") == "error" for check in checks) else "degraded", "service": "performance-os-api-v2", "storage": (db_result or {}).get("storage", "postgres") if isinstance(db_result, dict) else "postgres", "db": db_result, "counts": counts, "checks": checks, "blocks": checks, "background_workers": False, "startup_syncs": False, "advanced_analytics_disabled": True, "duration_ms": round((time.perf_counter() - started) * 1000, 1), "generated_at": utc_now_iso()}
