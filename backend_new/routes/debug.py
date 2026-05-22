from __future__ import annotations

from fastapi import APIRouter, Query, Request

from backend_new.config import SERVICE_NAME, environment, storage_name
from backend_new.db import SUPPORTED_JSONB_TABLES, count_rows_many, fetch_json_rows, ping
from backend_new.utils import env_presence, timed, utc_now_iso
from src.body_metrics import canonical_bodyweight_debug


router = APIRouter(tags=["debug"])

DEBUG_ENV_VARS = [
    "APP_ENV",
    "ENVIRONMENT",
    "DATABASE_URL",
    "CORS_ALLOW_ORIGINS",
    "FRONTEND_ORIGIN",
    "NEXT_PUBLIC_APP_URL",
    "VERCEL_URL",
    "OPENAI_API_KEY",
    "HEVY_API_KEY",
    "STRAVA_CLIENT_ID",
    "STRAVA_CLIENT_SECRET",
    "WITHINGS_CLIENT_ID",
    "WITHINGS_CLIENT_SECRET",
    "APP_PASSWORD",
    "SESSION_SECRET",
]


def _route_list(request: Request) -> list[dict]:
    routes = []
    for route in request.app.routes:
        path = getattr(route, "path", "")
        methods = sorted(method for method in getattr(route, "methods", []) if method not in {"HEAD", "OPTIONS"})
        if path and methods:
            routes.append({"path": path, "methods": methods})
    return sorted(routes, key=lambda item: (item["path"], ",".join(item["methods"])))


@router.get("/api/debug/startup")
def debug_startup(request: Request, full: bool = Query(default=False)) -> dict:
    db_result, db_check = timed("db_ping", ping)
    row_counts = count_rows_many(SUPPORTED_JSONB_TABLES)
    body_rows = fetch_json_rows("body_metric_logs", limit=5000 if full else 1000, date_field="date")
    body_rows = [row for row in body_rows if isinstance(row, dict) and "_db_error" not in row]
    body_metric_debug = canonical_bodyweight_debug(body_rows)
    raw_withings_rows = sum(
        1
        for row in body_rows
        if "withings" in str(row.get("source", "") or "").lower()
        or "source=withings" in str(row.get("notes", "") or "").lower()
    )
    body_metrics_summary = {
        "raw_body_metric_rows": body_metric_debug.get("raw_body_metric_rows", 0),
        "canonical_daily_weight_rows": body_metric_debug.get("canonical_daily_weight_rows", 0),
        "withings_measurement_groups": raw_withings_rows,
        "earliest_weight_date": body_metric_debug.get("date_min", ""),
        "latest_weight_date": body_metric_debug.get("date_max", ""),
        "dates_with_multiple_weighins": body_metric_debug.get("dates_with_multiple_weighins", 0),
        "rule": "lowest_weight_per_day",
    }
    count_checks = [
        {
            "name": f"count_rows:{table}",
            "status": result.get("status", "unknown"),
            "duration_ms": result.get("duration_ms", 0),
        }
        for table, result in row_counts.items()
    ]
    checks = [db_check, *count_checks]
    return {
        "status": "ok" if all(check["status"] in {"ok", "not_configured"} for check in checks) and db_check["status"] == "ok" else "degraded",
        "service": SERVICE_NAME,
        "environment": environment(),
        "storage": storage_name(),
        "database": db_result,
        "row_counts": row_counts,
        "body_metrics_debug": body_metric_debug,
        "body_metrics": body_metrics_summary,
        "full": full,
        "checks": checks,
        "env": env_presence(DEBUG_ENV_VARS),
        "routes": _route_list(request),
        "background_workers": False,
        "startup_syncs": False,
        "integration_syncs_on_startup": False,
        "generated_at": utc_now_iso(),
    }
