"""FastAPI backend for the production Performance OS frontend."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import date, datetime, timezone
import logging
import math
import os
import time
import traceback

import pandas as pd
from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from backend.routes import body_metrics, export as data_export, goals, integrations, nutrition, personal_records, recovery, training, withings
from backend.observability import capture_exception, capture_message, init_sentry
from backend.routes.utils import (
    ACCESS_COOKIE,
    SESSION_MAX_AGE_SECONDS,
    create_session_token,
    dataframe_records,
    require_authenticated_request,
    sanitize_sensitive_data,
)
from src.analytics.food_history import (
    calculate_calorie_adherence,
    get_finalized_nutrition_history,
    get_food_history_for_optimization,
)
from src.analytics.muscle_balance import analyze_muscle_balance
from src.analytics.personal_records import update_personal_records_from_logs
from src.analytics.personal_response_learning import generate_personal_response_learning
from src.analytics.recovery_engine import calculate_recovery_score as calculate_advanced_recovery_score
from src.analytics.strength_trends import calculate_strength_trend
from src.analytics.todays_action import generate_todays_action
from src.analytics.training_workload import analyze_training_workload
from src.analytics.weekly_report import generate_weekly_performance_report
from src.analytics.workout_quality import calculate_workout_quality
from src.body_metrics import BODY_METRICS_COLUMNS, load_body_metrics
from src.goals import build_automatic_goals, load_user_goals
from src.nutrition import NUTRITION_COLUMNS, NUTRITION_LOG_PATH, calculate_daily_totals, load_nutrition_log, load_recent_nutrition_log
from src.nutrition_targets import analyze_weight_trend, calculate_macro_targets, load_nutrition_targets
from src.optimization.adaptive_nutrition_engine import build_adaptive_nutrition_recommendation
from src.optimization.high_value_features import build_optimization_features
from src.optimization.lean_bulk_engine import generate_lean_bulk_calorie_recommendation
from src.optimization.performance_engine import generate_performance_recommendations
from src.optimization.run_readiness import generate_extra_run_readiness
from src.recovery import RECOVERY_COLUMNS, SLEEP_ENTRY_COLUMNS, load_recovery_log, load_sleep_entries
from src.training import TRAINING_COLUMNS, TRAINING_LOG_PATH, calculate_training_volume, load_recent_training_log, load_training_log, recent_training_window, training_raw_window_days
from src.training_schedule import is_run_row, is_strength_row, load_training_schedule_profile, summarize_training_day
from src.integrations.hevy_client import load_hevy_sync_state
from src.storage import count_dataframe_rows, debug_database_connection, ensure_database_schema, is_database_unavailable_error, production_storage_warnings, use_database


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)
logger = logging.getLogger(__name__)
init_sentry()

app = FastAPI(
    title="Performance OS API",
    version="0.1.0",
    description="Private API for Performance OS health, training, nutrition, recovery, body metrics, and integrations.",
)


def _cors_origins() -> list[str]:
    configured = ",".join(
        value
        for value in [
            os.getenv("CORS_ALLOW_ORIGINS", ""),
            os.getenv("FRONTEND_ORIGIN", ""),
            os.getenv("NEXT_PUBLIC_APP_URL", ""),
            f"https://{os.getenv('VERCEL_URL', '').strip()}" if os.getenv("VERCEL_URL", "").strip() else "",
        ]
        if value
    )
    origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "https://performance-os-rho.vercel.app",
    ]
    if configured:
        origins.extend(origin.strip() for origin in configured.split(",") if origin.strip())
    return origins

PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/auth/logout",
    "/api/strava/callback",
    "/api/integrations/strava/callback",
    "/api/withings/callback",
    "/api/hevy/webhook",
}


def _is_public_api_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in PUBLIC_API_PATHS


@app.middleware("http")
async def require_session_for_private_api(request: Request, call_next):
    """Fail closed for private API routes; OAuth callbacks/webhooks stay public."""
    path = request.url.path
    if request.method != "OPTIONS" and path.startswith("/api/") and not _is_public_api_path(path):
        try:
            require_authenticated_request(request)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return await call_next(request)


LOGGED_REQUEST_PATHS = {
    "/api/settings",
    "/api/goals",
    "/api/dashboard/core",
    "/api/debug/dashboard-core",
    "/api/dashboard",
    "/api/training/history",
    "/api/training/strength-trends",
}
LIVE_TRAINING_DAYS = training_raw_window_days()
LIVE_TRAINING_MAX_ROWS = 20000
CORE_TRAINING_DAYS = 90
CORE_TRAINING_MAX_ROWS = 5000
GOALS_TRAINING_DAYS = 90
WORKLOAD_TRAINING_DAYS = 84
CORE_BLOCK_TIMEOUT_MS = int(os.getenv("DASHBOARD_CORE_BLOCK_TIMEOUT_MS", "900"))
CORE_DB_STATEMENT_TIMEOUT_MS = int(os.getenv("DASHBOARD_CORE_DB_TIMEOUT_MS", "750"))
CORE_BLOCK_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("DASHBOARD_CORE_WORKERS", "4")), thread_name_prefix="dashboard-core")
CORE_REQUIRED_BLOCKS = {
    "dashboard_core",
    "load_nutrition",
    "load_training",
    "load_goals",
    "calculate_targets",
    "today_food_summary",
    "weight_summary",
    "lift_tile_core",
}


@app.middleware("http")
async def log_core_request_lifecycle(request: Request, call_next):
    """Log core startup route timing and surface transient DB failures as JSON."""
    path = request.url.path.rstrip("/") or "/"
    should_log = path in LOGGED_REQUEST_PATHS
    started = time.perf_counter()
    if should_log:
        logger.info("Request started: %s %s", request.method, path)
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        if is_database_unavailable_error(exc):
            logger.exception("Database unavailable during request: %s %s in %.1f ms", request.method, path, duration_ms)
            return JSONResponse(
                {
                    "detail": "Database unavailable",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "duration_ms": duration_ms,
                },
                status_code=503,
            )
        logger.exception("Unhandled request failure: %s %s in %.1f ms", request.method, path, duration_ms)
        capture_exception(
            exc,
            tags={"endpoint": path, "method": request.method, "kind": "unhandled_request_failure"},
            extra={"duration_ms": duration_ms},
        )
        raise
    if should_log:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info("Request completed: %s %s status=%s in %.1f ms", request.method, path, response.status_code, duration_ms)
        slow_threshold_ms = float(os.getenv("SLOW_ENDPOINT_SENTRY_THRESHOLD_MS", "5000"))
        if duration_ms >= slow_threshold_ms:
            capture_message(
                "Slow Performance OS endpoint",
                level="warning",
                tags={"endpoint": path, "method": request.method, "status_code": response.status_code},
                extra={"duration_ms": duration_ms, "threshold_ms": slow_threshold_ms},
            )
    return response


# Registered LAST so CORSMiddleware is the OUTERMOST middleware. Starlette
# applies the most-recently-added middleware outermost, so this guarantees that
# even an early-return response from require_session_for_private_api (e.g. a
# 401) travels back out through CORS and carries Access-Control-Allow-Origin.
# Without this, the browser blocks the 401 and fetch() surfaces it as a generic
# network/CORS failure instead of an authentication error.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.get("/health")
def health() -> dict:
    """Health check used by local development and deployment probes."""
    warnings = production_storage_warnings()
    environment = (
        "production"
        if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("VERCEL") or os.getenv("RENDER") or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
        else "local"
        if os.getenv("ENVIRONMENT", "").lower() in {"local", "development", "dev"} or (PROJECT_ROOT / ".env").exists()
        else "unknown"
    )
    return {
        "status": "ok" if not warnings else "warning",
        "service": "performance-os-api",
        "environment": environment,
        "version": app.version,
        "storage": "postgres" if use_database() else "local_files",
        "revision": (
            os.getenv("RAILWAY_GIT_COMMIT_SHA", "").strip()
            or os.getenv("VERCEL_GIT_COMMIT_SHA", "").strip()
            or os.getenv("GIT_COMMIT_SHA", "").strip()
            or os.getenv("COMMIT_SHA", "").strip()
            or os.getenv("SOURCE_VERSION", "").strip()
        ),
        "warnings": warnings,
    }


@app.get("/api/auth/session")
def auth_session() -> dict:
    """Return a lightweight success response after middleware validates auth."""
    return {"ok": True, "status": "authenticated"}


class AuthLoginPayload(BaseModel):
    password: str = ""


LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300"))
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_MAX_ATTEMPTS", "20"))
_LOGIN_FAILURES: dict[str, list[float]] = {}


def _production_like() -> bool:
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("VERCEL")
        or os.getenv("RENDER")
        or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
    )


def _session_cookie_options() -> dict:
    # Auth/session deployment contract:
    # - Railway backend must define SESSION_SECRET and APP_PASSWORD.
    # - Vercel/Next should proxy browser /api/* calls to BACKEND_API_URL or
    #   NEXT_PUBLIC_API_URL so the performance_os_access cookie remains usable.
    # Keep SameSite/Secure behavior conservative here; production cross-site
    # cookies require Secure + SameSite=None, local dev uses lax.
    production = _production_like()
    return {
        "httponly": True,
        "secure": production,
        "samesite": "none" if production else "lax",
        "path": "/",
        "max_age": SESSION_MAX_AGE_SECONDS,
    }


def _login_rate_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _recent_login_failures(key: str, now: float | None = None) -> list[float]:
    current = now or time.time()
    cutoff = current - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    attempts = [timestamp for timestamp in _LOGIN_FAILURES.get(key, []) if timestamp >= cutoff]
    if attempts:
        _LOGIN_FAILURES[key] = attempts
    else:
        _LOGIN_FAILURES.pop(key, None)
    return attempts


def _enforce_login_rate_limit(request: Request) -> str:
    key = _login_rate_key(request)
    if len(_recent_login_failures(key)) >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again shortly.",
        )
    return key


@app.post("/api/auth/login")
def auth_login(payload: AuthLoginPayload, response: Response, request: Request) -> dict:
    """Validate the private access password and issue the backend session cookie."""
    configured_password = os.getenv("APP_PASSWORD", "")
    session_secret = os.getenv("SESSION_SECRET", "")
    if not configured_password:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="APP_PASSWORD is not configured on the backend")
    if not session_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="SESSION_SECRET is not configured on the backend")
    rate_key = _enforce_login_rate_limit(request)
    if payload.password != configured_password:
        _LOGIN_FAILURES.setdefault(rate_key, []).append(time.time())
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    _LOGIN_FAILURES.pop(rate_key, None)
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=create_session_token(session_secret),
        **_session_cookie_options(),
    )
    return {"ok": True, "status": "authenticated"}


@app.post("/api/auth/logout")
def auth_logout(response: Response) -> dict:
    """Clear the backend session cookie."""
    response.delete_cookie(
        key=ACCESS_COOKIE,
        path="/",
        secure=_production_like(),
        samesite="none" if _production_like() else "lax",
    )
    return {"ok": True}


@app.on_event("startup")
def initialize_storage() -> None:
    """Initialize durable Postgres storage when DATABASE_URL is configured."""
    started = time.perf_counter()
    logger.info("Backend startup begin.")
    try:
        if use_database():
            ensure_database_schema()
        for warning in production_storage_warnings():
            logger.error(warning)
        logger.info("Backend startup complete in %.1f ms.", (time.perf_counter() - started) * 1000)
    except Exception:
        logger.exception("Backend startup storage initialization failed; API will stay up and report DB errors per request.")


@app.on_event("shutdown")
def log_shutdown() -> None:
    """Log ASGI shutdown; the platform provides the external stop reason."""
    CORE_BLOCK_EXECUTOR.shutdown(wait=False, cancel_futures=True)
    logger.warning("Backend shutdown signal received; no polling/background sync workers are running.")


@app.get("/api/debug/db")
def debug_db() -> dict:
    """Return a fresh Postgres SELECT 1 diagnostic."""
    return _public_json(debug_database_connection())


@app.get("/api/debug/startup")
def debug_startup() -> dict:
    """Return lightweight startup diagnostics without running advanced analytics."""
    started = time.perf_counter()
    blocks: list[dict] = []

    def measure(name: str, fn):
        block_started = time.perf_counter()
        try:
            value = fn()
            blocks.append({"name": name, "status": "ok", "duration_ms": round((time.perf_counter() - block_started) * 1000, 1)})
            return value
        except Exception as exc:
            blocks.append(
                {
                    "name": name,
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "duration_ms": round((time.perf_counter() - block_started) * 1000, 1),
                }
            )
            return None

    db = measure("db", debug_database_connection)
    training_rows_total = measure("count_training_rows_total", lambda: count_dataframe_rows("training_log", TRAINING_LOG_PATH))
    nutrition_rows_total = measure("count_nutrition_rows_total", lambda: count_dataframe_rows("nutrition_log", NUTRITION_LOG_PATH))
    nutrition_df = measure("load_recent_nutrition_log_2d", lambda: load_recent_nutrition_log(days=2, max_rows=500, statement_timeout_ms=CORE_DB_STATEMENT_TIMEOUT_MS))
    body_df = measure("load_body_metrics", load_body_metrics)
    recovery_df = measure("load_recovery_log", load_recovery_log)
    training_df = measure("load_recent_training_log_90d", lambda: load_recent_training_log(days=90, max_rows=10000))
    training_90d = measure("recent_training_window_90d", lambda: recent_training_window(training_df, days=90))
    goals_payload = measure(
        "build_automatic_goals",
        lambda: build_automatic_goals(
            load_user_goals(),
            body_metrics_df=body_df if isinstance(body_df, pd.DataFrame) else pd.DataFrame(columns=BODY_METRICS_COLUMNS),
            training_df=training_90d if isinstance(training_90d, pd.DataFrame) else pd.DataFrame(columns=TRAINING_COLUMNS),
        ),
    )
    failed = [block for block in blocks if block.get("status") == "error"]
    slow = sorted(blocks, key=lambda item: float(item.get("duration_ms") or 0), reverse=True)
    return _public_json(
        {
            "status": "ok" if not failed else "degraded",
            "storage": "postgres" if use_database() else "local_files",
            "db": db,
            "counts": {
                "training_rows_total": training_rows_total if isinstance(training_rows_total, int) else None,
                "training_rows_90d": len(training_90d) if isinstance(training_90d, pd.DataFrame) else None,
                "nutrition_rows_total": nutrition_rows_total if isinstance(nutrition_rows_total, int) else None,
                "nutrition_rows_recent": len(nutrition_df) if isinstance(nutrition_df, pd.DataFrame) else None,
                "body_metric_rows": len(body_df) if isinstance(body_df, pd.DataFrame) else None,
                "recovery_rows": len(recovery_df) if isinstance(recovery_df, pd.DataFrame) else None,
            },
            "goals_ok": isinstance(goals_payload, dict),
            "checks": blocks,
            "blocks": blocks,
            "likely_bottleneck": slow[0].get("name") if slow else None,
            "suggested_action": "Inspect the slowest check and keep startup on /api/dashboard/core plus /api/goals only.",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


def safe_block(name: str, dashboard_errors: list[dict], fallback, fn):
    start = time.perf_counter()
    logger.info("Dashboard block started: %s", name)
    try:
        value = fn()
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        dashboard_errors.append(
            {
                "block": name,
                "name": name,
                "status": "ok",
                "duration_ms": duration_ms,
            }
        )
        logger.info("Dashboard block completed: %s in %.1f ms", name, duration_ms)
        return value
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.exception("Dashboard block failed: %s", name)
        capture_exception(
            exc,
            tags={"dashboard_block": name, "endpoint": "/api/dashboard", "kind": "dashboard_block_failure"},
            extra={"duration_ms": duration_ms},
        )
        dashboard_errors.append(
            {
                "block": name,
                "name": name,
                "status": "error",
                "error_type": type(exc).__name__,
                "message": _exception_debug_message(exc),
                "duration_ms": duration_ms,
            }
        )
        try:
            return fallback() if callable(fallback) else fallback
        except Exception as fallback_exc:
            logger.exception("Dashboard fallback failed: %s", name)
            dashboard_errors.append(
                {
                    "block": f"{name}_fallback",
                    "name": f"{name}_fallback",
                    "status": "error",
                    "error_type": type(fallback_exc).__name__,
                    "message": _exception_debug_message(fallback_exc),
                    "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                }
            )
            return None


def _safe_dashboard_block(
    name: str,
    dashboard_errors: list[dict],
    dashboard_status: dict[str, bool],
    dashboard_timings_ms: dict[str, float],
    fallback,
    func,
):
    start_index = len(dashboard_errors)
    result = safe_block(name, dashboard_errors, fallback, func)
    block_record = next((entry for entry in dashboard_errors[start_index:] if entry.get("block") == name), None)
    dashboard_status[name] = block_record is not None and block_record.get("status") == "ok"
    dashboard_timings_ms[name] = float(block_record.get("duration_ms", 0.0)) if block_record else 0.0
    return result


def _safe_core_block(
    name: str,
    dashboard_errors: list[dict],
    dashboard_status: dict[str, bool],
    dashboard_timings_ms: dict[str, float],
    fallback,
    func,
    *,
    timeout_ms: int = CORE_BLOCK_TIMEOUT_MS,
):
    """Run one dashboard-core block with a hard request-facing timeout."""
    started = time.perf_counter()
    logger.info("Dashboard core block started: %s", name)
    future = CORE_BLOCK_EXECUTOR.submit(func)
    try:
        value = future.result(timeout=max(timeout_ms, 1) / 1000)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        record = {"block": name, "name": name, "status": "ok", "duration_ms": duration_ms}
        if isinstance(value, pd.DataFrame):
            record["rows"] = len(value)
            logger.info("Dashboard core block completed: %s rows=%s in %.1f ms", name, len(value), duration_ms)
        else:
            logger.info("Dashboard core block completed: %s in %.1f ms", name, duration_ms)
        dashboard_errors.append(record)
        dashboard_status[name] = True
        dashboard_timings_ms[name] = duration_ms
        return value
    except FutureTimeoutError:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        future.cancel()
        logger.warning("Dashboard core block timed out: %s after %.1f ms", name, duration_ms)
        capture_message(
            "Dashboard core block timed out",
            level="warning",
            tags={"dashboard_block": name, "endpoint": "/api/dashboard/core"},
            extra={"duration_ms": duration_ms, "timeout_ms": timeout_ms},
        )
        dashboard_errors.append(
            {
                "block": name,
                "name": name,
                "status": "timeout",
                "error_type": "TimeoutError",
                "message": f"{name} exceeded {timeout_ms}ms and was skipped.",
                "function": getattr(func, "__name__", repr(func)),
                "endpoint": "/api/dashboard/core",
                "duration_ms": duration_ms,
            }
        )
        dashboard_status[name] = False
        dashboard_timings_ms[name] = duration_ms
    except Exception as exc:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("Dashboard core block failed: %s", name)
        capture_exception(
            exc,
            tags={"dashboard_block": name, "endpoint": "/api/dashboard/core", "kind": "dashboard_core_block_failure"},
            extra={"duration_ms": duration_ms, "timeout_ms": timeout_ms},
        )
        dashboard_errors.append(
            {
                "block": name,
                "name": name,
                "status": "error",
                "error_type": type(exc).__name__,
                "message": _exception_debug_message(exc),
                "function": getattr(func, "__name__", repr(func)),
                "endpoint": "/api/dashboard/core",
                "trace_excerpt": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=4)),
                "duration_ms": duration_ms,
            }
        )
        dashboard_status[name] = False
        dashboard_timings_ms[name] = duration_ms
    try:
        return fallback() if callable(fallback) else fallback
    except Exception as fallback_exc:
        logger.exception("Dashboard core fallback failed: %s", name)
        dashboard_errors.append(
            {
                "block": f"{name}_fallback",
                "name": f"{name}_fallback",
                "status": "error",
                "error_type": type(fallback_exc).__name__,
                "message": _exception_debug_message(fallback_exc),
                "function": getattr(fallback, "__name__", repr(fallback)),
                "endpoint": "/api/dashboard/core",
                "trace_excerpt": "".join(traceback.format_exception(type(fallback_exc), fallback_exc, fallback_exc.__traceback__, limit=4)),
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
        return None


def _core_dataframe_block(
    name: str,
    loader,
    columns: list[str],
    dashboard_errors: list[dict],
    dashboard_status: dict[str, bool],
    dashboard_timings_ms: dict[str, float],
    *,
    timeout_ms: int = CORE_BLOCK_TIMEOUT_MS,
) -> pd.DataFrame:
    value = _safe_core_block(
        name,
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: pd.DataFrame(columns=columns),
        loader,
        timeout_ms=timeout_ms,
    )
    if isinstance(value, pd.DataFrame):
        return value
    return pd.DataFrame(columns=columns)


def _load_dashboard_frame(
    name: str,
    loader,
    columns: list[str],
    dashboard_errors: list[dict],
    dashboard_status: dict[str, bool],
    dashboard_timings_ms: dict[str, float],
) -> pd.DataFrame:
    fallback = lambda: pd.DataFrame(columns=columns)
    value = _safe_dashboard_block(name, dashboard_errors, dashboard_status, dashboard_timings_ms, fallback, loader)
    if isinstance(value, pd.DataFrame):
        logger.info("%s rows: %s", name, len(value))
        for entry in reversed(dashboard_errors):
            if entry.get("block") == name:
                entry["rows"] = len(value)
                break
        return value
    return fallback()


def _recent_training_for_analytics(days: int = LIVE_TRAINING_DAYS, max_rows: int = LIVE_TRAINING_MAX_ROWS) -> pd.DataFrame:
    started = time.perf_counter()
    training_df = load_recent_training_log(days=days, max_rows=max_rows)
    logger.info("load_recent_training_log(%sd) rows=%s took %.1f ms", days, len(training_df), (time.perf_counter() - started) * 1000)
    return training_df


def _recent_training_for_core() -> pd.DataFrame:
    started = time.perf_counter()
    training_df = load_recent_training_log(days=30, max_rows=500, statement_timeout_ms=CORE_DB_STATEMENT_TIMEOUT_MS)
    logger.info("dashboard_core load_recent_training_log rows=%s took %.1f ms", len(training_df), (time.perf_counter() - started) * 1000)
    return training_df


def _recent_nutrition_for_core() -> pd.DataFrame:
    started = time.perf_counter()
    nutrition_df = load_recent_nutrition_log(days=2, max_rows=500, statement_timeout_ms=CORE_DB_STATEMENT_TIMEOUT_MS)
    logger.info("dashboard_core load_recent_nutrition_log rows=%s took %.1f ms", len(nutrition_df), (time.perf_counter() - started) * 1000)
    return nutrition_df


def _training_window(training_df: pd.DataFrame, days: int) -> pd.DataFrame:
    if training_df.empty:
        return training_df
    df = training_df.copy()
    parsed_dates = pd.to_datetime(df.get("date"), errors="coerce")
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    return df[parsed_dates >= cutoff].copy()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.DataFrame):
        return dataframe_records(value)
    if isinstance(value, pd.Series):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is pd.NaT:
        return None
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        try:
            return _json_safe(value.tolist())
        except (TypeError, ValueError, AttributeError):
            pass
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError, AttributeError):
            pass
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _public_json(value):
    """Return JSON-safe API output with secret-like fields redacted."""
    return _json_safe(sanitize_sensitive_data(value))


def _exception_debug_message(exc: Exception) -> str:
    """Return an actionable exception message for diagnostic API payloads."""
    if isinstance(exc, SyntaxError):
        location = f"{exc.filename or 'unknown'}:{exc.lineno or '?'}"
        text = str(exc.text or "").strip()
        details = str(exc) or type(exc).__name__
        return f"{details} at {location}{f' near {text[:180]!r}' if text else ''}"
    return str(exc) or type(exc).__name__


def _target_number(targets: dict, key: str, default: float = 0.0) -> float:
    value = targets.get(key, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return default
    return parsed


def _dashboard_target_macros(targets: dict) -> dict:
    return {
        "calories": round(_target_number(targets, "target_calories", 2500)),
        "protein": round(_target_number(targets, "protein_grams", 180)),
        "carbs": round(_target_number(targets, "carb_grams", 275)),
        "fat": round(_target_number(targets, "fat_grams", 75)),
    }


def _fallback_goals() -> dict:
    return {
        "current_bodyweight": 180,
        "goal_bodyweight": 185,
        "timeline_weeks": 16,
        "goal_type": "lean_bulk",
        "training_frequency_per_week": 5,
        "cardio_frequency_per_week": 1,
        "estimated_body_fat": None,
        "activity_level": "moderate",
        "aggressiveness": "conservative",
    }


def _fallback_targets(goals: dict | None = None) -> dict:
    bodyweight = _target_number(goals or {}, "current_bodyweight", 180)
    calories = 2500
    protein = round(max(160, bodyweight))
    fat = 75
    carbs = round(max(200, (calories - protein * 4 - fat * 9) / 4))
    return {
        "target_calories": calories,
        "maintenance_calories": calories,
        "calorie_adjustment": 0,
        "protein_grams": protein,
        "carb_grams": carbs,
        "fat_grams": fat,
        "expected_weekly_weight_change": 0,
        "target_description": "Fallback target while advanced analytics are unavailable.",
        "timeline_status": "unknown",
        "timeline_warning": "",
    }


def _fallback_training_workload() -> dict:
    return {
        "status": "insufficient data",
        "summary": "Training workload analytics are unavailable.",
        "current": {"recovery_demand": "unknown"},
        "running": {"status": "insufficient data"},
    }


def _fallback_weight_feedback() -> dict:
    return {
        "status": "insufficient data",
        "weekly_change_pct": None,
        "weekly_change_lb": None,
        "suggested_adjustment": "hold",
        "reason": "Weight trend unavailable.",
        "window_used": "none",
        "confidence": "low",
        "calorie_adjustment": 0,
    }


def _fallback_workout_quality() -> dict:
    return {
        "status": "missing",
        "score": None,
        "score_label": "Unavailable",
        "confidence": "low",
        "color": "gray",
        "explanation": "Workout quality analytics are unavailable.",
        "comparison": None,
        "source": "none",
    }


def _fallback_nutrition_adherence() -> dict:
    return {
        "average_calories": None,
        "average_target_calories": None,
        "average_calories_delta": None,
        "average_protein": None,
        "average_target_protein": None,
        "average_protein_delta": None,
        "days_over_target": 0,
        "days_under_target": 0,
        "consistency_score": None,
        "logged_days": 0,
        "missing_days": 0,
        "confidence": "low",
        "data_quality_note": "Nutrition adherence unavailable.",
    }


def _fallback_todays_action() -> dict:
    return {
        "status": "maintain",
        "color": "gray",
        "headline": "Load core dashboard",
        "reason": "Advanced daily action analytics are unavailable, so keep the current plan stable.",
    }


def _fallback_weekly_report() -> dict:
    return {
        "status": "learning",
        "period_label": "Last 7 days",
        "summary": "Weekly analytics are unavailable, but core dashboard data is still loaded.",
        "rows": [],
        "best_trend": "Unavailable",
        "watch": "No advanced watch item available.",
        "recommendation": "Keep logging and refresh later.",
    }


def _fallback_personal_records() -> dict:
    return {"bench_press": None, "mile_time": None, "history": {"bench_press": [], "mile_time": []}}


def _fallback_performance_plan() -> dict:
    return {
        "recommendation_summary": "Advanced performance recommendations are unavailable.",
        "reasoning_explanation": "Core data loaded, but the recommendation engine failed gracefully.",
    }


def _fallback_lean_bulk_decision(targets: dict) -> dict:
    return {
        "recommendation": "maintain",
        "calorie_change": 0,
        "new_target_calories": _target_number(targets, "target_calories", 2500),
        "confidence": "low",
        "weekly_weight_change_pct": None,
        "fat_gain_risk_score": 0,
        "reasoning": ["Lean-bulk engine unavailable; holding targets."],
        "next_check_in_days": 7,
        "details": {
            "seven_day_avg_weight": None,
            "fourteen_day_avg_weight": None,
            "calorie_average": None,
            "protein_average": None,
            "protein_target": _target_number(targets, "protein_grams", 180),
            "training_trend": "unknown",
            "recovery_trend": "unknown",
            "target_weekly_gain_pct": None,
        },
    }


def _fallback_recovery_signal() -> dict:
    return {
        "status": "insufficient data",
        "confidence": "low",
        "score": None,
        "summary": "Recovery analytics are unavailable.",
        "nutrition_implication": "Hold nutrition targets.",
        "suggested_action": "Keep logging recovery.",
        "drivers": [],
        "metrics": {},
    }


def _fallback_performance_signal() -> dict:
    return {
        "label": "insufficient data",
        "confidence": "low",
        "summary": "Performance analytics are unavailable.",
        "recommendation": "Keep logging workouts.",
        "drivers": [],
        "muscle_group_drivers": [],
    }


def _fallback_adaptive_recommendation(targets: dict) -> dict:
    macros = _dashboard_target_macros(targets)
    return {
        "recommendedCalories": macros["calories"],
        "recommendedProtein": macros["protein"],
        "recommendedCarbs": macros["carbs"],
        "recommendedFat": macros["fat"],
        "caloriesTarget": macros["calories"],
        "proteinTarget": macros["protein"],
        "carbsTarget": macros["carbs"],
        "fatTarget": macros["fat"],
        "calorieAdjustment": 0,
        "macroChanges": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
        "confidence": "low",
        "dataQualityScore": 0,
        "reasoning": ["Adaptive nutrition unavailable; holding current targets."],
        "warnings": ["Advanced analytics failed, but core dashboard data is still available."],
        "missingDataWarnings": [],
        "strategy": "maintain",
        "currentTarget": macros,
        "recommendedTargets": targets,
        "signals": {
            "weight": {"status": "insufficient data", "confidence": "low", "reason": "Unavailable"},
            "performance": _fallback_performance_signal(),
            "recovery": _fallback_recovery_signal(),
            "trainingLoad": {"status": "insufficient data", "summary": "Training load unavailable."},
            "runningLoad": {"status": "insufficient data", "summary": "Running load unavailable."},
            "nutrition": {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None},
            "dataQuality": {
                "score": 0,
                "confidence": "low",
                "missingDataWarnings": ["Advanced adaptive calculation failed."],
            },
        },
    }


def _fallback_personal_learning() -> dict:
    return {
        "status": "insufficient data",
        "confidence": "low",
        "summary": "Personal response learning is unavailable.",
        "window": "none",
        "data_points": 0,
        "insights": [],
    }


def _fallback_optimization_features(targets: dict, personal_learning: dict | None = None) -> dict:
    macros = _dashboard_target_macros(targets)
    return {
        "day_type_macros": {
            "day_type": "baseline",
            "confidence": "low",
            "reason": "Advanced day-type macro analytics are unavailable.",
            "baseline_targets": macros,
            "adjusted_targets": macros,
            "delta": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
            "signals": [],
        },
        "plateau_detection": {
            "status": "insufficient data",
            "summary": "Plateau detection unavailable.",
            "top_alerts": [],
            "details": [],
        },
        "macro_adherence": {
            "weekly_score": None,
            "status": "insufficient data",
            "summary": "Macro adherence unavailable.",
            "components": {},
            "daily": [],
            "correlations": [],
        },
        "personal_baseline": {
            "status": (personal_learning or {}).get("status", "insufficient data"),
            "confidence": (personal_learning or {}).get("confidence", "low"),
            "summary": (personal_learning or {}).get("summary", "Personal baseline unavailable."),
            "dashboard_insight": None,
            "insights": [],
        },
    }


def _fallback_extra_run_readiness() -> dict:
    return {
        "status": "insufficient_data",
        "message": "Extra-run readiness unavailable.",
        "recommended_run": "No additional run recommended from fallback mode.",
        "reasoning": ["Advanced run-readiness analytics failed or lacked enough data."],
    }


def _failed_dashboard_blocks(blocks: list[dict]) -> list[dict]:
    return [block for block in blocks if block.get("status") in {"error", "timeout"}]


def _block_identifier(block: dict) -> str:
    return str(block.get("block") or block.get("name") or "")


def _required_core_failures(blocks: list[dict]) -> list[dict]:
    failed = _failed_dashboard_blocks(blocks)
    return [block for block in failed if _block_identifier(block) in CORE_REQUIRED_BLOCKS]


def _required_core_failure_names(blocks: list[dict]) -> list[str]:
    return [_block_identifier(block) for block in _required_core_failures(blocks)]


def _dashboard_status_label(blocks: list[dict]) -> str:
    return "degraded" if _failed_dashboard_blocks(blocks) else "ok"


def _dashboard_core_status_label(blocks: list[dict]) -> str:
    if _required_core_failures(blocks):
        return "failed"
    return "degraded" if _failed_dashboard_blocks(blocks) else "ok"


def _dashboard_likely_failure(blocks: list[dict]) -> str | None:
    failed = _failed_dashboard_blocks(blocks)
    if not failed:
        return None
    first = failed[0]
    message = first.get("message") or first.get("error_type") or "unknown error"
    return f"{first.get('block', 'dashboard')}: {message}"


def _dashboard_suggested_action(blocks: list[dict]) -> str:
    failed = _failed_dashboard_blocks(blocks)
    if not failed:
        return "No dashboard subsystem failures detected."
    failed_names = {str(block.get("block", "")) for block in failed}
    if any(name.startswith("load_") or name.endswith("_loaded") for name in failed_names):
        return "Check storage connectivity and schema first; a core data loader failed."
    return f"Inspect backend logs for {failed[0].get('block', 'the failing dashboard block')} and keep the app in degraded mode meanwhile."


def _safe_hevy_sync_debug() -> dict:
    try:
        state = load_hevy_sync_state()
    except Exception as exc:
        logger.warning("Hevy sync debug state unavailable: %s", exc)
        return {
            "status": "error",
            "last_sync_at": "",
            "last_event_cursor": "",
            "last_error": str(exc),
            "last_result": {},
            "safe_mode": True,
        }
    last_error = str(state.get("last_error", "") or "")
    last_sync_at = str(state.get("last_sync_at", "") or "")
    return {
        "status": "error" if last_error else "ok" if last_sync_at else "idle",
        "last_sync_at": last_sync_at,
        "last_event_cursor": str(state.get("last_event_cursor", "") or ""),
        "last_error": last_error,
        "last_result": state.get("last_result", {}) if isinstance(state.get("last_result", {}), dict) else {},
        "safe_mode": bool(state.get("safe_mode") or last_error),
    }


def _deferred_hevy_sync_debug() -> dict:
    return {
        "status": "deferred",
        "last_sync_at": "",
        "last_event_cursor": "",
        "last_error": "",
        "last_result": {},
        "safe_mode": True,
        "message": "Hevy sync state is deferred on dashboard core startup.",
    }


def _dashboard_debug_payload(payload: dict) -> dict:
    debug = payload.get("debug", {}) if isinstance(payload, dict) else {}
    blocks = debug.get("blocks") or []
    counts = payload.get("counts", {}) if isinstance(payload, dict) else {}
    status = debug.get("status", {})
    return {
        "status": debug.get("dashboard_status") or _dashboard_status_label(blocks),
        "storage": "postgres" if use_database() else "local_files",
        "counts": {
            "nutrition": counts.get("nutrition", 0),
            "training": counts.get("training", 0),
            "body_metrics": counts.get("body_metrics", 0),
            "recovery": counts.get("recovery", 0),
            "sleep": counts.get("sleep", 0),
        },
        "blocks": blocks,
        "likely_failure": _dashboard_likely_failure(blocks),
        "suggested_action": _dashboard_suggested_action(blocks),
        "hevy_sync": debug.get("hevy_sync") or _safe_hevy_sync_debug(),
        "generated_at": debug.get("generated_at"),
        "nutrition_loaded": bool(status.get("nutrition_loaded")),
        "training_loaded": bool(status.get("training_loaded")),
        "body_metrics_loaded": bool(status.get("body_metrics_loaded")),
        "recovery_loaded": bool(status.get("recovery_loaded")),
        "sleep_loaded": bool(status.get("sleep_loaded")),
        "adaptive_recommendation_ok": bool(status.get("adaptive_recommendation")),
        "weekly_report_ok": bool(status.get("weekly_report")),
        "optimization_features_ok": bool(status.get("optimization_features")),
        "personal_learning_ok": bool(status.get("personal_learning")),
        "workout_quality_ok": bool(status.get("workout_quality")),
        "run_readiness_ok": bool(status.get("run_readiness")),
        "muscle_balance_ok": bool(status.get("muscle_balance")),
        "legacy_status": status,
        "timings_ms": debug.get("timings_ms", {}),
        "errors": debug.get("errors", []),
    }


def _core_dashboard_fallback(exc: Exception, duration_ms: float) -> dict:
    today = pd.Timestamp.today().date().isoformat()
    goals = _fallback_goals()
    targets = _fallback_targets(goals)
    blocks = [
        {
            "block": "dashboard_core",
            "name": "dashboard_core",
            "status": "error",
            "error_type": type(exc).__name__,
            "message": _exception_debug_message(exc),
            "function": "_build_dashboard_core_payload",
            "endpoint": "/api/dashboard/core",
            "trace_excerpt": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=4)),
            "duration_ms": round(duration_ms, 1),
        }
    ]
    return {
        "date": today,
        "food": _food_dashboard_tile({"calories": 0, "protein": 0, "carbs": 0, "fat": 0}, targets),
        "weight": _weight_dashboard_tile(pd.DataFrame(columns=BODY_METRICS_COLUMNS), [], today),
        "lift_performance": _lift_performance_tile(pd.DataFrame(columns=TRAINING_COLUMNS), today),
        "workout_quality": _fallback_workout_quality(),
        "todays_action": _fallback_todays_action(),
        "weekly_report": _fallback_weekly_report(),
        "recovery": {**_recovery_dashboard_tile(pd.DataFrame(columns=RECOVERY_COLUMNS), None, today), "extra_run_readiness": _fallback_extra_run_readiness()},
        "prs": {"bench_press": None, "mile_time": None},
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "training_workload": _fallback_training_workload(),
        "nutrition_today": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
        "latest_bodyweight": None,
        "bodyweight_trend": [],
        "weight_feedback": _fallback_weight_feedback(),
        "latest_recovery": None,
        "recovery_trend": [],
        "latest_workout": None,
        "strength_trend_summary": {"label": "insufficient data", "exercise": "", "summary": "Dashboard core fallback loaded."},
        "muscle_balance_warning": None,
        "ai_insight_preview": None,
        "training_volume": [],
        "personal_records": _fallback_personal_records(),
        "lean_bulk_decision": _fallback_lean_bulk_decision(targets),
        "adaptive_recommendation": _fallback_adaptive_recommendation(targets),
        "personal_learning": _fallback_personal_learning(),
        "optimization": _fallback_optimization_features(targets),
        "recommendation": _fallback_performance_plan(),
        "counts": {"nutrition": 0, "body_metrics": 0, "recovery": 0, "sleep": 0, "training": 0},
        "errors": blocks,
        "ok": False,
        "core_ready": False,
        "debug": {
            "dashboard_status": "failed",
            "required_blocks": sorted(CORE_REQUIRED_BLOCKS),
            "required_blocks_failed": ["dashboard_core"],
            "errors": blocks,
            "blocks": blocks,
            "hevy_sync": _deferred_hevy_sync_debug(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": {"dashboard_core": False},
            "timings_ms": {"dashboard_core": round(duration_ms, 1)},
        },
    }


def _dashboard_context() -> dict:
    dashboard_errors: list[dict] = []
    dashboard_status: dict[str, bool] = {}
    dashboard_timings_ms: dict[str, float] = {}
    nutrition_df = _load_dashboard_frame("nutrition_loaded", load_nutrition_log, NUTRITION_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    body_metrics_df = _load_dashboard_frame("body_metrics_loaded", load_body_metrics, BODY_METRICS_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    recovery_df = _load_dashboard_frame("recovery_loaded", load_recovery_log, RECOVERY_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    sleep_df = _load_dashboard_frame("sleep_loaded", load_sleep_entries, SLEEP_ENTRY_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    training_df = _load_dashboard_frame("training_loaded", lambda: _recent_training_for_analytics(LIVE_TRAINING_DAYS, LIVE_TRAINING_MAX_ROWS), TRAINING_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    return {
        "errors": dashboard_errors,
        "status": dashboard_status,
        "timings_ms": dashboard_timings_ms,
        "nutrition_df": nutrition_df,
        "body_metrics_df": body_metrics_df,
        "recovery_df": recovery_df,
        "sleep_df": sleep_df,
        "training_df": training_df,
    }


def _bodyweight_snapshot(body_metrics_df: pd.DataFrame) -> tuple[float | None, list[dict]]:
    if body_metrics_df.empty:
        return None, []
    bodyweight_clean = body_metrics_df.copy()
    bodyweight_clean["date"] = pd.to_datetime(bodyweight_clean.get("date"), errors="coerce")
    bodyweight_clean["bodyweight"] = pd.to_numeric(bodyweight_clean.get("bodyweight"), errors="coerce")
    bodyweight_clean = bodyweight_clean.dropna(subset=["date", "bodyweight"]).sort_values("date")
    if bodyweight_clean.empty:
        return None, []
    latest = float(bodyweight_clean.iloc[-1]["bodyweight"])
    bodyweight_clean["date"] = bodyweight_clean["date"].dt.date.astype(str)
    return latest, dataframe_records(bodyweight_clean.tail(30))


def _latest_workout_snapshot(training_df: pd.DataFrame) -> dict | None:
    if training_df.empty:
        return None
    training_clean = training_df.copy()
    training_clean["date"] = pd.to_datetime(training_clean.get("date"), errors="coerce")
    training_clean = training_clean.dropna(subset=["date"])
    if training_clean.empty:
        return None
    return dataframe_records(training_clean.sort_values("date").tail(1))[0]


def _build_dashboard_core_payload() -> dict:
    """Return a fast startup dashboard payload without expensive analytics."""
    started = time.perf_counter()
    today = pd.Timestamp.today().date().isoformat()
    dashboard_errors: list[dict] = []
    dashboard_status: dict[str, bool] = {}
    dashboard_timings_ms: dict[str, float] = {}

    logger.info(
        "Dashboard core blocks configured: nutrition_recent=%sd/%s rows, training_recent=%sd/%s rows, block_timeout=%sms; advanced analytics disabled.",
        2,
        500,
        30,
        500,
        CORE_BLOCK_TIMEOUT_MS,
    )
    nutrition_df = _core_dataframe_block("load_nutrition", _recent_nutrition_for_core, NUTRITION_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    body_metrics_df = _core_dataframe_block("load_body_metrics", load_body_metrics, BODY_METRICS_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    training_df = _core_dataframe_block("load_training", _recent_training_for_core, TRAINING_COLUMNS, dashboard_errors, dashboard_status, dashboard_timings_ms)
    recovery_df = pd.DataFrame(columns=RECOVERY_COLUMNS)
    sleep_df = pd.DataFrame(columns=SLEEP_ENTRY_COLUMNS)
    dashboard_errors.append({"block": "load_recovery", "name": "load_recovery", "status": "skipped", "duration_ms": 0, "message": "Deferred outside dashboard core startup."})
    dashboard_errors.append({"block": "load_sleep", "name": "load_sleep", "status": "skipped", "duration_ms": 0, "message": "Deferred outside dashboard core startup."})
    dashboard_status["load_recovery"] = True
    dashboard_status["load_sleep"] = True
    dashboard_timings_ms["load_recovery"] = 0
    dashboard_timings_ms["load_sleep"] = 0

    goals = _safe_core_block(
        "load_goals",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_goals,
        lambda: build_automatic_goals(load_user_goals(), body_metrics_df=body_metrics_df, training_df=pd.DataFrame(columns=TRAINING_COLUMNS)),
        timeout_ms=700,
    )
    if not isinstance(goals, dict):
        goals = _fallback_goals()
    targets = _safe_core_block(
        "calculate_targets",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _fallback_targets(goals),
        lambda: load_nutrition_targets() or calculate_macro_targets(
            goals,
            nutrition_df=pd.DataFrame(columns=NUTRITION_COLUMNS),
            training_df=pd.DataFrame(columns=TRAINING_COLUMNS),
            recovery_df=pd.DataFrame(columns=RECOVERY_COLUMNS),
            body_metrics_df=body_metrics_df.tail(30) if isinstance(body_metrics_df, pd.DataFrame) else pd.DataFrame(columns=BODY_METRICS_COLUMNS),
            workload_data=_fallback_training_workload(),
        ),
        timeout_ms=700,
    )
    if not isinstance(targets, dict):
        targets = _fallback_targets(goals)
    nutrition_totals = _safe_core_block(
        "today_food_summary",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0},
        lambda: calculate_daily_totals(nutrition_df, today),
        timeout_ms=300,
    )
    latest_bodyweight, bodyweight_trend = _safe_core_block(
        "weight_summary",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: (None, []),
        lambda: _bodyweight_snapshot(body_metrics_df),
        timeout_ms=400,
    )
    latest_workout = _safe_core_block(
        "latest_workout",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: None,
        lambda: _latest_workout_snapshot(training_df),
        timeout_ms=300,
    )

    food_tile = _safe_core_block(
        "food_tile_core",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _food_dashboard_tile({"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}, targets),
        lambda: _food_dashboard_tile(nutrition_totals, targets),
        timeout_ms=300,
    )
    if not isinstance(food_tile, dict):
        food_tile = _food_dashboard_tile({"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}, targets)
    weight_tile = _safe_core_block(
        "weight_tile_core",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _weight_dashboard_tile(pd.DataFrame(columns=BODY_METRICS_COLUMNS), [], today),
        lambda: _weight_dashboard_tile(body_metrics_df, bodyweight_trend, today),
        timeout_ms=300,
    )
    if not isinstance(weight_tile, dict):
        weight_tile = _weight_dashboard_tile(pd.DataFrame(columns=BODY_METRICS_COLUMNS), [], today)
    lift_tile = _safe_core_block(
        "lift_tile_core",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _lift_performance_tile_core(pd.DataFrame(columns=TRAINING_COLUMNS), today),
        lambda: _lift_performance_tile_core(training_df, today),
        timeout_ms=400,
    )
    if not isinstance(lift_tile, dict):
        lift_tile = _lift_performance_tile_core(pd.DataFrame(columns=TRAINING_COLUMNS), today)
    latest_recovery = _safe_core_block(
        "recovery_summary",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: None,
        lambda: dataframe_records(recovery_df.sort_values("date").tail(1))[0] if not recovery_df.empty else None,
        timeout_ms=300,
    )
    recovery_tile = _safe_core_block(
        "recovery_tile_core",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: {**_recovery_dashboard_tile(pd.DataFrame(columns=RECOVERY_COLUMNS), None, today), "extra_run_readiness": _fallback_extra_run_readiness()},
        lambda: {**_recovery_dashboard_tile(recovery_df, latest_recovery, today), "extra_run_readiness": _fallback_extra_run_readiness()},
        timeout_ms=300,
    )
    counts = _safe_core_block(
        "counts",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: {"nutrition": 0, "body_metrics": 0, "recovery": 0, "sleep": 0, "training": 0},
        lambda: {
            "nutrition": len(nutrition_df),
            "body_metrics": len(body_metrics_df),
            "recovery": len(recovery_df),
            "sleep": len(sleep_df),
            "training": len(training_df),
        },
        timeout_ms=200,
    )
    if not isinstance(counts, dict):
        counts = {"nutrition": 0, "body_metrics": 0, "recovery": 0, "sleep": 0, "training": 0}

    required_blocks_failed = _required_core_failure_names(dashboard_errors)
    core_ready = not required_blocks_failed
    core_status = _dashboard_core_status_label(dashboard_errors)
    payload = {
        "ok": core_ready,
        "core_ready": core_ready,
        "date": today,
        "food": food_tile,
        "weight": weight_tile,
        "lift_performance": lift_tile,
        "workout_quality": _fallback_workout_quality(),
        "todays_action": _fallback_todays_action(),
        "weekly_report": _fallback_weekly_report(),
        "recovery": recovery_tile,
        "prs": {"bench_press": None, "mile_time": None},
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "training_workload": _fallback_training_workload(),
        "nutrition_today": nutrition_totals,
        "latest_bodyweight": latest_bodyweight,
        "bodyweight_trend": bodyweight_trend,
        "weight_feedback": _fallback_weight_feedback(),
        "latest_recovery": latest_recovery,
        "recovery_trend": [],
        "latest_workout": latest_workout,
        "strength_trend_summary": {"exercise": "", "label": "deferred", "summary": "Strength trends hydrate after startup."},
        "muscle_balance_warning": None,
        "ai_insight_preview": None,
        "training_volume": [],
        "personal_records": _fallback_personal_records(),
        "lean_bulk_decision": _fallback_lean_bulk_decision(targets),
        "adaptive_recommendation": _fallback_adaptive_recommendation(targets),
        "personal_learning": _fallback_personal_learning(),
        "optimization": _fallback_optimization_features(targets),
        "recommendation": _fallback_performance_plan(),
        "counts": counts,
        "errors": _failed_dashboard_blocks(dashboard_errors),
        "debug": {
            "dashboard_status": core_status,
            "mode": "core",
            "required_blocks": sorted(CORE_REQUIRED_BLOCKS),
            "required_blocks_failed": required_blocks_failed,
            "errors": _failed_dashboard_blocks(dashboard_errors),
            "blocks": dashboard_errors,
            "hevy_sync": _deferred_hevy_sync_debug(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": dashboard_status,
            "timings_ms": dashboard_timings_ms,
            "core_route": "/api/dashboard/core",
            "advanced_analytics_disabled": True,
            "total_duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }
    return payload


def _build_dashboard_payload() -> dict:
    """Return local-first dashboard data for the Next.js frontend."""
    context = _dashboard_context()
    dashboard_errors = context["errors"]
    dashboard_status = context["status"]
    dashboard_timings_ms = context["timings_ms"]
    nutrition_df = context["nutrition_df"]
    body_metrics_df = context["body_metrics_df"]
    recovery_df = context["recovery_df"]
    sleep_df = context["sleep_df"]
    training_df = context["training_df"]
    goals_training_df = _training_window(training_df, GOALS_TRAINING_DAYS)
    workload_training_df = _training_window(training_df, WORKLOAD_TRAINING_DAYS)
    logger.info("Dashboard training rows: loaded=%s goals_window=%s workload_window=%s", len(training_df), len(goals_training_df), len(workload_training_df))

    today = pd.Timestamp.today().date().isoformat()
    goals = _safe_dashboard_block(
        "goals",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_goals,
        lambda: build_automatic_goals(load_user_goals(), body_metrics_df=body_metrics_df, training_df=goals_training_df),
    )
    if not isinstance(goals, dict):
        goals = _fallback_goals()
    active_targets = _safe_dashboard_block(
        "active_targets",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: None,
        load_nutrition_targets,
    )
    training_workload = _safe_dashboard_block(
        "training_workload",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_training_workload,
        lambda: analyze_training_workload(workload_training_df, bodyweight=goals.get("current_bodyweight")),
    )
    if not isinstance(training_workload, dict):
        training_workload = _fallback_training_workload()
    base_targets = _safe_dashboard_block(
        "base_targets",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _fallback_targets(goals),
        lambda: calculate_macro_targets(
            goals,
            nutrition_df=nutrition_df,
            training_df=goals_training_df,
            recovery_df=recovery_df,
            body_metrics_df=body_metrics_df,
            workload_data=training_workload,
        ),
    )
    targets = active_targets or base_targets or _fallback_targets(goals)
    if not isinstance(targets, dict):
        targets = _fallback_targets(goals)
    daily_nutrition_summary = _safe_dashboard_block(
        "load_finalized_daily_nutrition_summary",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: pd.DataFrame(),
        lambda: get_finalized_nutrition_history(60),
    )
    if not isinstance(daily_nutrition_summary, pd.DataFrame):
        daily_nutrition_summary = pd.DataFrame()
    nutrition_for_optimization = _safe_dashboard_block(
        "food_history_optimization",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: daily_nutrition_summary,
        lambda: get_food_history_for_optimization(daily_nutrition_summary),
    )
    if not isinstance(nutrition_for_optimization, pd.DataFrame):
        nutrition_for_optimization = daily_nutrition_summary

    nutrition_totals = _safe_dashboard_block(
        "nutrition_today",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0},
        lambda: calculate_daily_totals(nutrition_df, today),
    )
    weight_feedback = _safe_dashboard_block(
        "weight_feedback",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_weight_feedback,
        lambda: analyze_weight_trend(body_metrics_df, goals),
    )
    if not isinstance(weight_feedback, dict):
        weight_feedback = _fallback_weight_feedback()

    latest_bodyweight = None
    bodyweight_trend = []

    def build_bodyweight_trend():
        if body_metrics_df.empty:
            return None, []
        bodyweight_clean = body_metrics_df.copy()
        bodyweight_clean["date"] = pd.to_datetime(bodyweight_clean.get("date"), errors="coerce")
        bodyweight_clean["bodyweight"] = pd.to_numeric(bodyweight_clean.get("bodyweight"), errors="coerce")
        bodyweight_clean = bodyweight_clean.dropna(subset=["date", "bodyweight"]).sort_values("date")
        if bodyweight_clean.empty:
            return None, []
        latest = float(bodyweight_clean.iloc[-1]["bodyweight"])
        bodyweight_clean["date"] = bodyweight_clean["date"].dt.date.astype(str)
        return latest, dataframe_records(bodyweight_clean.tail(30))

    latest_bodyweight, bodyweight_trend = _safe_dashboard_block(
        "bodyweight_trend",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: (None, []),
        build_bodyweight_trend,
    )

    latest_recovery = None
    recovery_trend = []

    def build_recovery_trend():
        if recovery_df.empty:
            return None, []
        recovery_analytics = calculate_advanced_recovery_score(
            recovery_df=recovery_df,
            training_df=training_df,
            nutrition_df=nutrition_df,
            target_calories=targets.get("target_calories"),
        )
        if recovery_analytics.empty:
            return None, []
        recovery_analytics["date"] = pd.to_datetime(recovery_analytics["date"], errors="coerce").dt.date.astype(str)
        return dataframe_records(recovery_analytics.tail(1))[0], dataframe_records(recovery_analytics.tail(30))

    latest_recovery, recovery_trend = _safe_dashboard_block(
        "recovery_engine",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: (None, []),
        build_recovery_trend,
    )

    latest_workout = None
    strength_trend_summary = {"label": "insufficient data", "exercise": "", "summary": "Log workouts to calculate strength trends."}
    muscle_balance_warning = None

    def build_training_snapshot():
        latest = None
        strength_summary = {"label": "insufficient data", "exercise": "", "summary": "Log workouts to calculate strength trends."}
        if training_df.empty:
            return latest, strength_summary
        training_clean = training_df.copy()
        training_clean["date"] = pd.to_datetime(training_clean.get("date"), errors="coerce")
        training_clean = training_clean.dropna(subset=["date"])
        if training_clean.empty:
            return latest, strength_summary
        latest = dataframe_records(training_clean.sort_values("date").tail(1))[0]
        exercises = training_clean.get("exercise", pd.Series("", index=training_clean.index)).fillna("").astype(str).str.strip()
        exercises = exercises[exercises != ""]
        if not exercises.empty:
            selected_exercise = exercises.value_counts().index[0]
            trend = calculate_strength_trend(training_clean, selected_exercise)
            strength_summary = {
                "exercise": selected_exercise,
                "label": trend.get("label", "insufficient data"),
                "summary": trend.get("summary", ""),
            }
        return latest, strength_summary

    latest_workout, strength_trend_summary = _safe_dashboard_block(
        "strength_trends",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: (None, {"label": "insufficient data", "exercise": "", "summary": "Log workouts to calculate strength trends."}),
        build_training_snapshot,
    )
    muscle_balance_warning = _safe_dashboard_block(
        "muscle_balance",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: None,
        lambda: (
            (lambda balance: balance["flags"][0] if balance.get("flags") else None)(
                analyze_muscle_balance(training_df, latest_recovery_score=latest_recovery.get("recovery_score") if latest_recovery else None)
            )
            if not training_df.empty
            else None
        ),
    )

    volume_df = _safe_dashboard_block(
        "training_volume",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: pd.DataFrame(),
        lambda: calculate_training_volume(training_df),
    )
    if not isinstance(volume_df, pd.DataFrame):
        volume_df = pd.DataFrame()
    performance_plan = _safe_dashboard_block(
        "performance_plan",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_performance_plan,
        lambda: generate_performance_recommendations(
            recovery_df=recovery_df,
            training_df=training_df,
            nutrition_df=nutrition_for_optimization,
            body_metrics_df=body_metrics_df,
            target_calories=targets.get("target_calories"),
            target_protein=targets.get("protein_grams"),
            goal=goals.get("goal_type"),
        ),
    )
    if not isinstance(performance_plan, dict):
        performance_plan = _fallback_performance_plan()
    personal_records_data = _safe_dashboard_block(
        "personal_records",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_personal_records,
        lambda: update_personal_records_from_logs(training_df),
    )
    if not isinstance(personal_records_data, dict):
        personal_records_data = _fallback_personal_records()
    lean_bulk_decision = _safe_dashboard_block(
        "lean_bulk_decision",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _fallback_lean_bulk_decision(targets),
        lambda: generate_lean_bulk_calorie_recommendation(
            body_metrics_df=body_metrics_df,
            nutrition_df=nutrition_for_optimization,
            training_df=training_df,
            recovery_df=recovery_df,
            user_goals=goals,
        ),
    )
    if not isinstance(lean_bulk_decision, dict):
        lean_bulk_decision = _fallback_lean_bulk_decision(targets)
    adaptive_recommendation = _safe_dashboard_block(
        "adaptive_recommendation",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _fallback_adaptive_recommendation(targets),
        lambda: build_adaptive_nutrition_recommendation(
            user_goals=goals,
            body_metrics_df=body_metrics_df,
            nutrition_df=daily_nutrition_summary,
            training_df=training_df,
            recovery_df=recovery_df,
            current_targets=targets,
            sleep_df=sleep_df,
            today=today,
        ),
    )
    if not isinstance(adaptive_recommendation, dict):
        adaptive_recommendation = _fallback_adaptive_recommendation(targets)
    personal_learning = _safe_dashboard_block(
        "personal_learning",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_personal_learning,
        lambda: generate_personal_response_learning(
            body_metrics_df=body_metrics_df,
            nutrition_df=daily_nutrition_summary,
            training_df=training_df,
            recovery_df=recovery_df,
            sleep_df=sleep_df,
            current_targets=targets,
        ),
    )
    if not isinstance(personal_learning, dict):
        personal_learning = _fallback_personal_learning()
    optimization_features = _safe_dashboard_block(
        "optimization_features",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _fallback_optimization_features(targets, personal_learning),
        lambda: build_optimization_features(
            nutrition_summary_df=daily_nutrition_summary,
            training_df=training_df,
            recovery_df=recovery_df,
            sleep_df=sleep_df,
            body_metrics_df=body_metrics_df,
            targets=targets,
            personal_learning=personal_learning,
            today=today,
        ),
    )
    if not isinstance(optimization_features, dict):
        optimization_features = _fallback_optimization_features(targets, personal_learning)
    adjusted_targets = (optimization_features.get("day_type_macros") or {}).get("adjusted_targets") or {}
    dashboard_targets = {
        **targets,
        "target_calories": adjusted_targets.get("calories", targets.get("target_calories")),
        "protein_grams": adjusted_targets.get("protein", targets.get("protein_grams")),
        "carb_grams": adjusted_targets.get("carbs", targets.get("carb_grams")),
        "fat_grams": adjusted_targets.get("fat", targets.get("fat_grams")),
    }
    food_tile = _safe_dashboard_block(
        "food_tile",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _food_dashboard_tile({"calories": 0, "protein": 0, "carbs": 0, "fat": 0}, dashboard_targets),
        lambda: _food_dashboard_tile(nutrition_totals, dashboard_targets),
    )
    if not isinstance(food_tile, dict):
        food_tile = _food_dashboard_tile({"calories": 0, "protein": 0, "carbs": 0, "fat": 0}, dashboard_targets)
    weight_tile = _safe_dashboard_block(
        "weight_tile",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _weight_dashboard_tile(pd.DataFrame(columns=BODY_METRICS_COLUMNS), [], today),
        lambda: _weight_dashboard_tile(body_metrics_df, bodyweight_trend, today),
    )
    if not isinstance(weight_tile, dict):
        weight_tile = _weight_dashboard_tile(pd.DataFrame(columns=BODY_METRICS_COLUMNS), [], today)
    recovery_tile = _safe_dashboard_block(
        "recovery_tile",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _recovery_dashboard_tile(pd.DataFrame(columns=RECOVERY_COLUMNS), None, today),
        lambda: _recovery_dashboard_tile(recovery_df, latest_recovery, today),
    )
    if not isinstance(recovery_tile, dict):
        recovery_tile = _recovery_dashboard_tile(pd.DataFrame(columns=RECOVERY_COLUMNS), None, today)
    recovery_tile["extra_run_readiness"] = _safe_dashboard_block(
        "run_readiness",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_extra_run_readiness,
        lambda: generate_extra_run_readiness(
            recovery_data=recovery_tile if recovery_tile.get("connected") else recovery_df,
            training_df=training_df,
            strava_df=training_df[training_df["source"].astype(str).str.lower() == "strava"] if not training_df.empty and "source" in training_df.columns else None,
            nutrition_summary=daily_nutrition_summary,
            user_goals=goals,
            today_date=today,
        ),
    )
    lift_tile = _safe_dashboard_block(
        "lift_performance_tile",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        lambda: _lift_performance_tile(pd.DataFrame(columns=TRAINING_COLUMNS), today),
        lambda: _lift_performance_tile(training_df, today),
    )
    if not isinstance(lift_tile, dict):
        lift_tile = _lift_performance_tile(pd.DataFrame(columns=TRAINING_COLUMNS), today)
    workout_quality = _safe_dashboard_block(
        "workout_quality",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_workout_quality,
        lambda: calculate_workout_quality(training_df, today),
    )
    if not isinstance(workout_quality, dict):
        workout_quality = _fallback_workout_quality()
    nutrition_adherence = _safe_dashboard_block(
        "nutrition_adherence",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_nutrition_adherence,
        lambda: calculate_calorie_adherence(daily_nutrition_summary),
    )
    if not isinstance(nutrition_adherence, dict):
        nutrition_adherence = _fallback_nutrition_adherence()
    todays_action = _safe_dashboard_block(
        "todays_action",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_todays_action,
        lambda: generate_todays_action(
            workout_quality=workout_quality,
            recovery_tile=recovery_tile,
            sleep_df=sleep_df,
            weight_feedback=weight_feedback,
            nutrition_adherence=nutrition_adherence,
            training_workload=training_workload,
            adaptive_recommendation=adaptive_recommendation,
        ),
    )
    if not isinstance(todays_action, dict):
        todays_action = _fallback_todays_action()
    weekly_report = _safe_dashboard_block(
        "weekly_report",
        dashboard_errors,
        dashboard_status,
        dashboard_timings_ms,
        _fallback_weekly_report,
        lambda: generate_weekly_performance_report(
            body_metrics_df=body_metrics_df,
            nutrition_df=daily_nutrition_summary,
            training_df=training_df,
            recovery_df=recovery_df,
            sleep_df=sleep_df,
            today=today,
        ),
    )
    if not isinstance(weekly_report, dict):
        weekly_report = _fallback_weekly_report()
    prs_tile = {
        "bench_press": personal_records_data.get("bench_press"),
        "mile_time": personal_records_data.get("mile_time"),
    }

    payload = {
        "date": today,
        "food": food_tile,
        "weight": weight_tile,
        "lift_performance": lift_tile,
        "workout_quality": workout_quality,
        "todays_action": todays_action,
        "weekly_report": weekly_report,
        "recovery": recovery_tile,
        "prs": prs_tile,
        "goals": goals,
        "targets": targets,
        "base_targets": base_targets,
        "training_workload": training_workload,
        "nutrition_today": nutrition_totals,
        "latest_bodyweight": latest_bodyweight,
        "bodyweight_trend": bodyweight_trend,
        "weight_feedback": weight_feedback,
        "latest_recovery": latest_recovery,
        "recovery_trend": recovery_trend,
        "latest_workout": latest_workout,
        "strength_trend_summary": strength_trend_summary,
        "muscle_balance_warning": muscle_balance_warning,
        "ai_insight_preview": "Run AI training analysis from the Training page." if len(training_df) else None,
        "training_volume": dataframe_records(volume_df),
        "personal_records": personal_records_data,
        "lean_bulk_decision": lean_bulk_decision,
        "adaptive_recommendation": adaptive_recommendation,
        "personal_learning": personal_learning,
        "optimization": optimization_features,
        "recommendation": performance_plan,
        "counts": {
            "nutrition": len(nutrition_df),
            "body_metrics": len(body_metrics_df),
            "recovery": len(recovery_df),
            "sleep": len(sleep_df),
            "training": len(training_df),
        },
        "errors": _failed_dashboard_blocks(dashboard_errors),
        "debug": {
            "dashboard_status": _dashboard_status_label(dashboard_errors),
            "errors": _failed_dashboard_blocks(dashboard_errors),
            "blocks": dashboard_errors,
            "hevy_sync": _safe_hevy_sync_debug(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": dashboard_status,
            "timings_ms": dashboard_timings_ms,
        },
    }
    return payload


@app.get("/api/dashboard/core")
def dashboard_core() -> dict:
    """Return the fast startup dashboard payload with no advanced analytics."""
    started = time.perf_counter()
    logger.info("Dashboard core request started.")
    try:
        payload = _build_dashboard_core_payload()
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("Dashboard core request fell back to core-safe payload.")
        payload = _core_dashboard_fallback(exc, elapsed_ms)
        payload.setdefault("debug", {})["mode"] = "core_fallback"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    payload.setdefault("debug", {})
    payload["debug"]["total_duration_ms"] = elapsed_ms
    status_label = payload.get("debug", {}).get("dashboard_status", "ok")
    logger.info("Dashboard core request completed in %.1f ms with status=%s", elapsed_ms, status_label)
    return _public_json(payload)


@app.get("/api/debug/dashboard-core")
def dashboard_core_debug() -> dict:
    """Return per-block dashboard-core diagnostics without running advanced analytics."""
    started = time.perf_counter()
    logger.info("Dashboard core debug request started.")
    try:
        payload = _build_dashboard_core_payload()
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("Dashboard core debug fell back to safe diagnostics.")
        payload = _core_dashboard_fallback(exc, elapsed_ms)
        payload.setdefault("debug", {})["mode"] = "core_debug_fallback"
    debug = payload.get("debug", {}) if isinstance(payload, dict) else {}
    blocks = debug.get("blocks") if isinstance(debug.get("blocks"), list) else []
    slow = sorted(blocks, key=lambda item: float(item.get("duration_ms") or 0), reverse=True)
    failed = _failed_dashboard_blocks(blocks)
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    return _public_json(
        {
            "status": debug.get("dashboard_status") or _dashboard_status_label(blocks),
            "storage": "postgres" if use_database() else "local_files",
            "counts": payload.get("counts", {}) if isinstance(payload, dict) else {},
            "blocks": blocks,
            "failed_blocks": failed,
            "likely_bottleneck": slow[0].get("block") if slow else None,
            "suggested_action": _dashboard_suggested_action(blocks),
            "duration_ms": duration_ms,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/api/dashboard")
def dashboard() -> dict:
    """Return dashboard data, degrading gracefully when advanced analytics fail."""
    started = time.perf_counter()
    logger.info("Dashboard request started.")
    try:
        payload = _build_dashboard_payload()
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("Dashboard request fell back to core payload.")
        payload = _core_dashboard_fallback(exc, elapsed_ms)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    payload.setdefault("debug", {})
    payload["debug"]["total_duration_ms"] = elapsed_ms
    status_label = payload.get("debug", {}).get("dashboard_status", "ok")
    failed_count = len(payload.get("debug", {}).get("errors", []))
    logger.info("Dashboard request completed in %.1f ms with status=%s failed_blocks=%s", elapsed_ms, status_label, failed_count)
    return _public_json(payload)


@app.get("/api/dashboard/debug")
def dashboard_debug() -> dict:
    """Return dashboard subsystem status without making the app fail hard."""
    started = time.perf_counter()
    logger.info("Dashboard debug request started.")
    try:
        payload = _build_dashboard_payload()
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("Dashboard debug request fell back to core diagnostics.")
        payload = _core_dashboard_fallback(exc, elapsed_ms)
    debug_payload = _dashboard_debug_payload(payload)
    debug_payload["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return _public_json(debug_payload)


@app.post("/api/recommendations/run")
def run_recommendations(date: str | None = None, finalize_day: bool = True) -> dict:
    """Explicitly finalize nutrition and run the heavier recommendation stack."""
    started = time.perf_counter()
    logger.info("Manual recommendation engine run started finalize_day=%s date=%s", finalize_day, date)
    finalized_summary = None
    if finalize_day:
        finalized_summary = nutrition.finalize_daily_nutrition_summary(date)
    try:
        payload = _build_dashboard_payload()
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception("Manual recommendation engine fell back to core payload.")
        payload = _core_dashboard_fallback(exc, elapsed_ms)
        payload.setdefault("debug", {})["mode"] = "recommendation_fallback"
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info("Manual recommendation engine run completed in %.1f ms", duration_ms)
    return _public_json(
        {
            "status": "ok",
            "message": "Recommendation engine completed from finalized daily nutrition summaries.",
            "finalized_summary": finalized_summary,
            "recommendation": payload.get("recommendation"),
            "adaptive_recommendation": payload.get("adaptive_recommendation"),
            "lean_bulk_decision": payload.get("lean_bulk_decision"),
            "optimization": payload.get("optimization"),
            "dashboard": payload,
            "duration_ms": duration_ms,
        }
    )


def _left(actual: float, target: float | None) -> dict:
    if not target:
        return {"left": None, "over": None, "percent": 0}
    return {
        "left": max(float(target) - float(actual), 0),
        "over": max(float(actual) - float(target), 0),
        "percent": min(max(float(actual) / float(target) * 100, 0), 100),
    }


def _food_dashboard_tile(nutrition_totals: dict, targets: dict) -> dict:
    calories = float(nutrition_totals.get("calories", 0) or 0)
    protein = float(nutrition_totals.get("protein", 0) or 0)
    carbs = float(nutrition_totals.get("carbs", 0) or 0)
    fat = float(nutrition_totals.get("fat", 0) or 0)
    target_calories = targets.get("target_calories")
    target_protein = targets.get("protein_grams")
    target_carbs = targets.get("carb_grams")
    target_fat = targets.get("fat_grams")
    return {
        "calories": {"eaten": calories, "target": target_calories, **_left(calories, target_calories)},
        "protein": {"eaten": protein, "target": target_protein, **_left(protein, target_protein)},
        "carbs": {"eaten": carbs, "target": target_carbs, **_left(carbs, target_carbs)},
        "fat": {"eaten": fat, "target": target_fat, **_left(fat, target_fat)},
        "has_targets": bool(target_calories and target_protein and target_carbs and target_fat),
        "has_food_logged": calories > 0 or protein > 0 or carbs > 0 or fat > 0,
    }


def _weight_dashboard_tile(body_metrics_df: pd.DataFrame, bodyweight_trend: list[dict], today: str) -> dict:
    if body_metrics_df.empty:
        return {
            "today_weight": None,
            "latest_weight": None,
            "seven_day_average": None,
            "trend_label": "insufficient data",
            "history": [],
            "message": "Enter today's weight",
        }
    df = body_metrics_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["bodyweight"] = pd.to_numeric(df["bodyweight"], errors="coerce")
    df = df.dropna(subset=["date", "bodyweight"]).sort_values("date")
    if df.empty:
        return {
            "today_weight": None,
            "latest_weight": None,
            "seven_day_average": None,
            "trend_label": "insufficient data",
            "history": [],
            "message": "Enter today's weight",
        }
    today_rows = df[df["date"].dt.date.astype(str) == today]
    recent = df.tail(7)
    seven_day_avg = round(float(recent["bodyweight"].mean()), 1) if len(recent) >= 2 else None
    trend_label = "insufficient data"
    if len(recent) >= 3:
        delta = float(recent["bodyweight"].iloc[-1] - recent["bodyweight"].iloc[0])
        if delta > 0.3:
            trend_label = "gaining"
        elif delta < -0.3:
            trend_label = "losing"
        else:
            trend_label = "stable"
    return {
        "today_weight": float(today_rows.iloc[-1]["bodyweight"]) if not today_rows.empty else None,
        "latest_weight": float(df.iloc[-1]["bodyweight"]),
        "seven_day_average": seven_day_avg,
        "trend_label": trend_label,
        "history": bodyweight_trend[-14:],
        "message": "Today's weight logged" if not today_rows.empty else "Enter today's weight",
    }


def _daily_training_rows(training_df: pd.DataFrame) -> pd.DataFrame:
    if training_df.empty:
        return pd.DataFrame()
    df = training_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return pd.DataFrame()
    profile = load_training_schedule_profile()
    df = df[df.apply(lambda row: is_strength_row(row, profile=profile), axis=1)].copy()
    if df.empty:
        return pd.DataFrame()
    for column in ["sets", "reps", "weight", "duration_minutes"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    grouped = (
        df.groupby(df["date"].dt.date)
        .agg(
            date=("date", "max"),
            workout_type=("workout_type", lambda values: ", ".join(sorted(set(str(value) for value in values if str(value))))),
            muscle_group=("muscle_group", lambda values: ", ".join(sorted(set(str(value) for value in values if str(value))))),
            total_volume=("volume", "sum"),
            total_sets=("sets", "sum"),
            duration_minutes=("duration_minutes", "max"),
        )
        .reset_index(drop=True)
        .sort_values("date")
    )
    grouped["weekday"] = grouped["date"].dt.day_name()
    return grouped


def _note_number(note: str, key: str) -> float:
    marker = f"{key}="
    if marker not in str(note):
        return 0.0
    raw = str(note).split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _today_run_summary(training_df: pd.DataFrame, today: str) -> dict | None:
    if training_df.empty:
        return None
    df = training_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return None
    for column in ["workout_type", "source", "notes", "duration_minutes"]:
        if column not in df.columns:
            df[column] = "" if column != "duration_minutes" else 0
    df["workout_type"] = df["workout_type"].fillna("").astype(str)
    df["source"] = df["source"].fillna("").astype(str)
    df["notes"] = df["notes"].fillna("").astype(str)
    df["duration_minutes"] = pd.to_numeric(df["duration_minutes"], errors="coerce").fillna(0)

    today_rows = df[df["date"].dt.date.astype(str) == today].copy()
    profile = load_training_schedule_profile()
    run_rows = today_rows[today_rows.apply(lambda row: is_run_row(row, profile=profile), axis=1)].copy()
    if run_rows.empty:
        return None

    run_rows["distance_miles"] = run_rows["notes"].apply(lambda note: _note_number(note, "distance_miles"))
    run_rows["calories_burned"] = run_rows["notes"].apply(lambda note: _note_number(note, "calories"))
    run_rows["average_heart_rate"] = run_rows["notes"].apply(lambda note: _note_number(note, "average_heartrate"))
    total_distance = float(run_rows["distance_miles"].sum())
    total_duration = float(run_rows["duration_minutes"].sum())
    if total_distance <= 0 and total_duration <= 0:
        return None
    average_pace = total_duration / total_distance if total_distance > 0 else None
    run_count = run_rows[["date", "workout_id"]].drop_duplicates().shape[0] if "workout_id" in run_rows.columns else len(run_rows)
    calories = float(run_rows["calories_burned"].sum())
    heart_rate_rows = run_rows[run_rows["average_heart_rate"] > 0]
    average_heart_rate = None
    if not heart_rate_rows.empty:
        duration_weights = heart_rate_rows["duration_minutes"].clip(lower=0)
        if float(duration_weights.sum()) > 0:
            average_heart_rate = float((heart_rate_rows["average_heart_rate"] * duration_weights).sum() / duration_weights.sum())
        else:
            average_heart_rate = float(heart_rate_rows["average_heart_rate"].mean())
    return {
        "run_count": int(run_count),
        "distance_miles": round(total_distance, 2),
        "duration_minutes": round(total_duration, 1),
        "average_pace_min_per_mile": round(average_pace, 2) if average_pace else None,
        "calories_burned": round(calories) if calories > 0 else None,
        "average_heart_rate": round(average_heart_rate) if average_heart_rate else None,
    }


def _lift_performance_tile(training_df: pd.DataFrame, today: str) -> dict:
    day_summary = summarize_training_day(training_df, today)
    daily = _daily_training_rows(training_df)
    run_summary = _today_run_summary(training_df, today)
    base_tile = {
        "planned_workout": day_summary["planned_workout"],
        "completed_workouts": day_summary["completed_workouts"],
        "completed_summary": day_summary["completed_summary"],
        "schedule_match": day_summary["schedule_match"],
        "match_label": day_summary["match_label"],
        "sources": day_summary["sources"],
        "has_run": day_summary["has_run"],
        "has_lift": day_summary["has_lift"],
        "cardio_indicator": day_summary["cardio_indicator"],
        "extra_run_added": day_summary["extra_run_added"],
        "recovery_status_relative_to_plan": day_summary["recovery_status_relative_to_plan"],
    }
    if daily.empty:
        return {
            **base_tile,
            "status": f"Today: {day_summary['planned_workout']}",
            "summary": f"Completed: {day_summary['completed_summary']}" if day_summary["completed_summary"] else "Workout not logged yet",
            "comparison": None,
            "today_volume": None,
            "percent_vs_average": None,
            "run_summary": run_summary,
        }
    today_dt = pd.to_datetime(today)
    today_rows = daily[daily["date"].dt.date.astype(str) == today]
    if today_rows.empty:
        return {
            **base_tile,
            "status": f"Today: {day_summary['planned_workout']}",
            "summary": f"Completed: {day_summary['completed_summary']}" if day_summary["completed_summary"] else "Workout not logged yet",
            "comparison": None,
            "today_volume": None,
            "percent_vs_average": None,
            "run_summary": run_summary,
        }
    today_row = today_rows.iloc[-1]
    previous = daily[daily["date"] < today_dt]
    same_weekday = previous[previous["weekday"] == today_row["weekday"]]
    similar = same_weekday
    if len(similar) < 2 and today_row["workout_type"]:
        similar = previous[previous["workout_type"] == today_row["workout_type"]]
    if len(similar) < 2 and today_row["muscle_group"]:
        similar = previous[previous["muscle_group"] == today_row["muscle_group"]]
    if similar.empty:
        return {
            **base_tile,
            "status": f"Today: {day_summary['planned_workout']}",
            "summary": f"Completed: {day_summary['completed_summary'] or today_row['workout_type'] or 'Workout'}",
            "comparison": None,
            "today_volume": round(float(today_row["total_volume"]), 0),
            "percent_vs_average": None,
            "run_summary": run_summary,
        }
    baseline = float(similar.tail(4)["total_volume"].mean())
    today_volume = float(today_row["total_volume"])
    percent = ((today_volume - baseline) / baseline * 100) if baseline > 0 else 0
    direction = "Stronger" if percent > 3 else "Lighter" if percent < -3 else "Similar"
    return {
        **base_tile,
        "status": f"Today: {day_summary['planned_workout']}",
        "summary": f"Completed: {day_summary['completed_summary'] or today_row['workout_type'] or 'Workout'} · {direction.lower()} than recent baseline",
        "comparison": f"{today_row['workout_type']} · {today_row['muscle_group']}",
        "today_volume": round(today_volume, 0),
        "percent_vs_average": round(percent, 1),
        "run_summary": run_summary,
    }


def _lift_performance_tile_core(training_df: pd.DataFrame, today: str) -> dict:
    """Return only the planned/completed training state needed for startup."""
    day_summary = summarize_training_day(training_df, today)
    run_summary = _today_run_summary(training_df, today)
    return {
        "planned_workout": day_summary["planned_workout"],
        "completed_workouts": day_summary["completed_workouts"],
        "completed_summary": day_summary["completed_summary"],
        "schedule_match": day_summary["schedule_match"],
        "match_label": day_summary["match_label"],
        "sources": day_summary["sources"],
        "has_run": day_summary["has_run"],
        "has_lift": day_summary["has_lift"],
        "cardio_indicator": day_summary["cardio_indicator"],
        "extra_run_added": day_summary["extra_run_added"],
        "recovery_status_relative_to_plan": day_summary["recovery_status_relative_to_plan"],
        "status": f"Today: {day_summary['planned_workout']}",
        "summary": f"Completed: {day_summary['completed_summary']}" if day_summary["completed_summary"] else "Workout not logged yet",
        "comparison": None,
        "today_volume": None,
        "percent_vs_average": None,
        "run_summary": run_summary,
    }


def _series(df: pd.DataFrame, column: str, output_key: str = "value") -> list[dict]:
    if column not in df.columns:
        return []
    values = pd.to_numeric(df[column], errors="coerce")
    series_df = df.loc[values.notna(), ["date"]].copy()
    series_df[output_key] = values[values.notna()].astype(float)
    series_df["date"] = series_df["date"].dt.date.astype(str)
    return dataframe_records(series_df.tail(30))


def _recovery_classification(score: float | None) -> str:
    if score is None:
        return "Sync pending"
    if score >= 80:
        return "Optimal"
    if score >= 60:
        return "Moderate"
    if score >= 40:
        return "Fatigued"
    return "High Risk"


def _recovery_dashboard_tile(recovery_df: pd.DataFrame, latest_recovery: dict | None, today: str) -> dict:
    """Return a wearable-first recovery dashboard shape.

    Manual recovery check-ins remain available elsewhere, but the dashboard tile
    is reserved for future Fitbit/Google Health style wearable ingestion.
    """
    empty_tile = {
        "connected": False,
        "source": "fitbit",
        "latest_score": None,
        "trend": [],
        "sleep": [],
        "hrv": [],
        "resting_hr": [],
        "status": "not_connected",
        "classification": "Not connected",
        "message": "Connect Fitbit/Google Health to enable recovery tracking.",
    }
    if recovery_df.empty:
        return empty_tile

    df = recovery_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return empty_tile

    source_col = "source" if "source" in df.columns else "data_source" if "data_source" in df.columns else None
    if not source_col:
        return empty_tile

    wearable_sources = {"fitbit", "google_health", "google_fit", "wearable", "withings"}
    source_values = df[source_col].fillna("").astype(str).str.lower().str.strip()
    wearable_df = df[source_values.isin(wearable_sources)].copy()
    if wearable_df.empty:
        return empty_tile

    score_column = next((column for column in ["recovery_score", "readiness_score", "score"] if column in wearable_df.columns), None)
    latest_score = None
    trend = []
    if score_column:
        score_values = pd.to_numeric(wearable_df[score_column], errors="coerce")
        if score_values.notna().any():
            latest_score = float(score_values.dropna().iloc[-1])
            trend = _series(wearable_df, score_column, "recovery_score")
    elif latest_recovery:
        latest_score = latest_recovery.get("recovery_score")

    latest_source = str(wearable_df[source_col].dropna().astype(str).iloc[-1] or "fitbit").lower()
    return {
        "connected": True,
        "source": latest_source,
        "latest_score": latest_score,
        "trend": trend,
        "sleep": _series(wearable_df, "sleep_hours", "sleep_hours"),
        "hrv": _series(wearable_df, "hrv", "hrv"),
        "resting_hr": _series(wearable_df, "resting_hr", "resting_hr"),
        "status": "connected" if latest_score is not None or len(wearable_df) else "sync_pending",
        "classification": _recovery_classification(float(latest_score) if latest_score is not None else None),
        "message": "Wearable recovery data synced.",
    }


app.include_router(nutrition.router)
app.include_router(training.router)
app.include_router(personal_records.router)
app.include_router(recovery.router)
app.include_router(body_metrics.router)
app.include_router(integrations.router)
app.include_router(withings.router)
app.include_router(goals.router)
app.include_router(data_export.router)
app.include_router(data_export.import_router)
