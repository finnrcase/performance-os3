from __future__ import annotations

from fastapi import APIRouter, Query, Request

from backend_new.config import SERVICE_NAME, environment, storage_name
from backend_new.db import SUPPORTED_JSONB_TABLES, count_rows_many, fetch_json_rows, fetch_latest_document, insert_json_row, ping
from backend_new.routes.body_metrics import body_metric_freshness_debug
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
    body_metric_freshness = body_metric_freshness_debug(body_rows)
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
        "freshness": body_metric_freshness,
        **body_metric_freshness,
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


@router.get("/api/debug/calorie-engine")
def debug_calorie_engine() -> dict:
    """Show whether wearable burn is actually driving the calorie target."""
    import pandas as pd

    from backend_new.services.recommendation_service import saved_goals, canonical_goals
    from src.nutrition_targets import estimate_adaptive_maintenance_calories

    def _df(table: str, limit: int) -> pd.DataFrame:
        rows = fetch_json_rows(table, limit=limit, date_field="date")
        clean = [row for row in rows if isinstance(row, dict) and "_db_error" not in row]
        return pd.DataFrame(clean) if clean else pd.DataFrame()

    wearable_df = _df("wearable_metrics", 400)
    nutrition_df = _df("food_logs", 2000)
    body_df = _df("body_metric_logs", 400)
    goals = canonical_goals(saved_goals())
    adaptive = estimate_adaptive_maintenance_calories(
        goals,
        nutrition_df=nutrition_df if not nutrition_df.empty else None,
        body_metrics_df=body_df if not body_df.empty else None,
        wearable_df=wearable_df if not wearable_df.empty else None,
    )
    provider = adaptive["wearable_provider"]
    connected = bool(provider and provider != "none")
    included = adaptive["wearable_included_in_target"]
    return {
        "fitbit_google_health_connected": connected,
        "provider": provider,
        "latest_wearable_row_date": adaptive["last_wearable_sync_date"],
        "average_wearable_burn": adaptive["wearable_average_burn"],
        "wearable_days_used": adaptive["wearable_days_used"],
        "wearable_burn_included_in_target": included,
        "why": adaptive["reason_for_calorie_change"],
        "adaptive_maintenance_calories": adaptive["adaptive_maintenance_calories"],
        "profile_estimated_maintenance": adaptive["profile_estimated_maintenance"],
        "observed_tdee_from_weight_and_intake": adaptive["observed_tdee_from_weight_and_intake"],
        "nutrition_days_used": adaptive["nutrition_days_used"],
        "weigh_in_days_used": adaptive["weigh_in_days_used"],
        "calorie_engine_confidence": adaptive["calorie_engine_confidence"],
        "data_sources_used": adaptive["data_sources_used"],
        "generated_at": utc_now_iso(),
    }


@router.get("/api/debug/openai")
def debug_openai() -> dict:
    try:
        from src.ai.food_parser import test_openai_connection

        result = test_openai_connection()
        try:
            settings = fetch_latest_document("api_connections", {"integrations": {}, "metadata": {}})
            if not isinstance(settings, dict):
                settings = {"integrations": {}, "metadata": {}}
            metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
            safe_result = {key: value for key, value in result.items() if "token" not in key.lower() and "key" not in key.lower()}
            metadata["openai_last_test"] = safe_result
            metadata["openai_last_test_at"] = utc_now_iso()
            settings["metadata"] = metadata
            insert_json_row("api_connections", settings)
        except Exception:
            pass
        return result
    except Exception as exc:
        return {
            "configured": False,
            "client_initialized": False,
            "test_status": "error",
            "response_ms": 0,
            "error_type": type(exc).__name__,
            "message": str(exc) or "OpenAI debug check failed before the client could be initialized.",
            "model": "",
            "api_key_source": "unknown",
            "checked_at": utc_now_iso(),
        }
