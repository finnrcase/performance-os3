"""Safe integration diagnostics for Performance OS."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from src.ai.food_parser import get_openai_key_status
from src.body_metrics import load_body_metrics
from src.config import load_settings
from src.integrations.hevy_client import HevyIntegrationError, fetch_recent_workouts, load_hevy_sync_state
from src.integrations.strava_client import (
    StravaIntegrationError,
    StravaReconnectRequired,
    get_strava_connection_status,
    get_strava_safe_token_metadata,
    load_strava_sync_state,
    refresh_strava_token_if_needed,
)
from src.integrations.withings_client import (
    WithingsIntegrationError,
    get_withings_connection_status,
    load_withings_sync_state,
    refresh_withings_token_if_needed,
)
from src.paths import PROJECT_ROOT
from src.storage import ALL_DATASET_TABLES, database_url, production_storage_warnings, use_database
from src.training import load_training_log


PRODUCTION_FRONTEND_URL = "https://performance-os-rho.vercel.app"
PRODUCTION_BACKEND_URL = "https://api-production-b3ff.up.railway.app"
EXPECTED_STRAVA_REDIRECT_URI = f"{PRODUCTION_BACKEND_URL}/api/strava/callback"
EXPECTED_WITHINGS_REDIRECT_URI = f"{PRODUCTION_BACKEND_URL}/api/withings/callback"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_dotenv_value(key: str) -> str:
    dotenv_path = PROJECT_ROOT / ".env"
    if not dotenv_path.exists():
        return ""
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _config_value(env_key: str, settings: dict | None = None, settings_key: str = "") -> str:
    settings_value = ""
    if settings is not None and settings_key:
        settings_value = str(settings.get("integrations", {}).get(settings_key, "") or "").strip()
    return os.getenv(env_key, "").strip() or _read_dotenv_value(env_key).strip() or settings_value


def _missing_env_vars(names: list[str]) -> list[str]:
    return [name for name in names if not _config_value(name)]


def _environment() -> str:
    explicit = os.getenv("ENVIRONMENT", "").strip().lower()
    if explicit in {"production", "prod"}:
        return "production"
    if explicit in {"local", "development", "dev"}:
        return "local"
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("VERCEL") or os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        return "production"
    if (PROJECT_ROOT / ".env").exists() or os.getenv("PYTEST_CURRENT_TEST"):
        return "local"
    return "unknown"


def _git_revision() -> str:
    for key in ["RAILWAY_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "COMMIT_SHA", "SOURCE_VERSION"]:
        value = os.getenv(key, "").strip()
        if value:
            return value
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _latest_date(df: pd.DataFrame, source_filter: str | None = None) -> str:
    if df.empty or "date" not in df.columns:
        return ""
    work = df.copy()
    if source_filter and "source" in work.columns:
        work = work[work["source"].fillna("").astype(str).str.lower() == source_filter]
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date")
    if work.empty:
        return ""
    return work.iloc[-1]["date"].date().isoformat()


def _component(
    *,
    configured: bool,
    status: str,
    message: str,
    required_env_vars: list[str] | None = None,
    missing_env_vars: list[str] | None = None,
    last_successful_sync: str = "",
    latest_record: str = "",
    reconnect_required: bool = False,
    user_action_required: bool = False,
    user_action_message: str = "",
    details: dict[str, Any] | None = None,
) -> dict:
    return {
        "configured": bool(configured),
        "status": status,
        "message": message,
        "required_env_vars": required_env_vars or [],
        "missing_env_vars": missing_env_vars or [],
        "last_successful_sync": last_successful_sync,
        "latest_record": latest_record,
        "reconnect_required": bool(reconnect_required),
        "user_action_required": bool(user_action_required),
        "user_action_message": user_action_message,
        "details": details or {},
    }


def _check_backend(environment: str) -> dict:
    return _component(
        configured=True,
        status="green",
        message="FastAPI app is alive.",
        details={
            "service": "performance-os-api",
            "environment": environment,
            "version": "0.1.0",
            "revision": _git_revision(),
        },
    )


def _check_database(environment: str, run_external_checks: bool = True) -> dict:
    required = ["DATABASE_URL"]
    missing = _missing_env_vars(required)
    if missing:
        production_warning = bool(production_storage_warnings()) or environment == "production"
        return _component(
            configured=False,
            status="red" if production_warning else "gray",
            message="DATABASE_URL is missing; backend is using local file storage.",
            required_env_vars=required,
            missing_env_vars=missing,
            user_action_required=production_warning,
            user_action_message="Add the Supabase Postgres connection string as DATABASE_URL in Railway backend env vars and redeploy." if production_warning else "",
            details={"storage": "local_files", "expected_tables": ALL_DATASET_TABLES},
        )
    if not run_external_checks:
        return _component(
            configured=True,
            status="yellow",
            message="DATABASE_URL is configured; live Postgres check was skipped.",
            required_env_vars=required,
            missing_env_vars=[],
            details={"storage": "postgres", "live_check": "skipped", "expected_tables": ALL_DATASET_TABLES},
        )

    try:
        import psycopg

        with psycopg.connect(database_url(), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    """
                )
                existing_tables = {str(row[0]) for row in cur.fetchall()}
    except Exception as exc:
        return _component(
            configured=True,
            status="red",
            message=f"DATABASE_URL exists, but the backend could not connect to Postgres: {exc}",
            required_env_vars=required,
            missing_env_vars=[],
            user_action_required=True,
            user_action_message="Check Supabase database availability, Railway DATABASE_URL, SSL/pooler settings, then redeploy Railway.",
            details={"storage": "postgres", "expected_tables": ALL_DATASET_TABLES},
        )

    missing_tables = sorted(set(ALL_DATASET_TABLES) - existing_tables)
    if missing_tables:
        return _component(
            configured=True,
            status="yellow",
            message="Postgres connection works, but some expected tables are missing.",
            required_env_vars=required,
            user_action_required=True,
            user_action_message="Run the backend once or execute the schema initialization so the missing JSONB tables are created.",
            details={"storage": "postgres", "missing_tables": missing_tables, "expected_tables": ALL_DATASET_TABLES},
        )
    return _component(
        configured=True,
        status="green",
        message="DATABASE_URL is configured, Postgres connection works, and expected tables exist.",
        required_env_vars=required,
        details={"storage": "postgres", "missing_tables": [], "expected_tables": ALL_DATASET_TABLES},
    )


def _check_openai(run_external_checks: bool) -> dict:
    required = ["OPENAI_API_KEY"]
    env_key = _config_value("OPENAI_API_KEY")
    configured = bool(env_key or get_openai_key_status())
    missing = [] if configured else required
    if not configured:
        return _component(
            configured=False,
            status="gray",
            message="OPENAI_API_KEY is not configured on the backend.",
            required_env_vars=required,
            missing_env_vars=missing,
            user_action_required=True,
            user_action_message="Add OPENAI_API_KEY to Railway backend env vars and redeploy.",
            details={"food_parser_uses_backend_key": True},
        )
    if not env_key:
        return _component(
            configured=True,
            status="yellow",
            message="OpenAI key is saved in app settings, but OPENAI_API_KEY is not present as a backend env var.",
            required_env_vars=required,
            missing_env_vars=required,
            user_action_required=True,
            user_action_message="Move OPENAI_API_KEY into Railway backend env vars and redeploy so the secret is owned by the backend environment.",
            details={"food_parser_uses_backend_key": True},
        )
    if not run_external_checks:
        return _component(
            configured=True,
            status="yellow",
            message="OPENAI_API_KEY exists; live OpenAI check was skipped.",
            required_env_vars=required,
            details={"food_parser_uses_backend_key": True, "live_check": "skipped"},
        )
    try:
        from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

        client = OpenAI(api_key=env_key, timeout=5)
        client.models.list()
    except AuthenticationError as exc:
        return _component(
            configured=True,
            status="red",
            message="OPENAI_API_KEY exists, but OpenAI rejected it.",
            required_env_vars=required,
            user_action_required=True,
            user_action_message="Replace OPENAI_API_KEY in Railway with a valid key and redeploy.",
            details={"food_parser_uses_backend_key": True, "error": str(exc)},
        )
    except RateLimitError as exc:
        return _component(
            configured=True,
            status="yellow",
            message="OpenAI key exists, but the account is rate-limited or out of quota.",
            required_env_vars=required,
            user_action_required=True,
            user_action_message="Check OpenAI billing/quota, then retry the food parser.",
            details={"food_parser_uses_backend_key": True, "error": str(exc)},
        )
    except (APIConnectionError, APIStatusError, Exception) as exc:
        return _component(
            configured=True,
            status="yellow",
            message=f"OPENAI_API_KEY exists, but the lightweight OpenAI check failed: {exc}",
            required_env_vars=required,
            user_action_required=True,
            user_action_message="Check Railway networking and OpenAI account status, then retry.",
            details={"food_parser_uses_backend_key": True},
        )
    return _component(
        configured=True,
        status="green",
        message="OPENAI_API_KEY exists and a lightweight OpenAI API check succeeded.",
        required_env_vars=required,
        details={"food_parser_uses_backend_key": True},
    )


def _check_strava(settings: dict, environment: str, run_external_checks: bool = True) -> dict:
    required = ["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REDIRECT_URI"]
    missing = _missing_env_vars(["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET"])
    redirect_uri = _config_value("STRAVA_REDIRECT_URI")
    if not redirect_uri:
        missing.append("STRAVA_REDIRECT_URI")
    token_storage = "postgres" if use_database() else "local_files"
    latest_strava = ""
    last_sync = ""
    token_metadata = {
        "connected": bool(_config_value("STRAVA_ACCESS_TOKEN") and _config_value("STRAVA_REFRESH_TOKEN")),
        "token_status": "configured" if _config_value("STRAVA_ACCESS_TOKEN") and _config_value("STRAVA_REFRESH_TOKEN") else "missing",
    }
    if run_external_checks:
        latest_strava = _latest_date(load_training_log(), "strava")
        sync_state = load_strava_sync_state()
        last_sync = str(sync_state.get("last_synced_at", "") or "")
        token_metadata = get_strava_safe_token_metadata()

    if missing:
        return _component(
            configured=False,
            status="gray",
            message="Strava OAuth client configuration is incomplete.",
            required_env_vars=required,
            missing_env_vars=sorted(set(missing)),
            latest_record=latest_strava,
            user_action_required=True,
            user_action_message="Add STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, and STRAVA_REDIRECT_URI to Railway backend env vars and redeploy.",
            details={"token_storage": token_storage, "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
        )

    if environment == "production" and redirect_uri != EXPECTED_STRAVA_REDIRECT_URI:
        return _component(
            configured=True,
            status="yellow",
            message="Strava credentials exist, but STRAVA_REDIRECT_URI does not match the Railway backend callback URL.",
            required_env_vars=required,
            latest_record=latest_strava,
            reconnect_required=True,
            user_action_required=True,
            user_action_message=f"Set STRAVA_REDIRECT_URI to {EXPECTED_STRAVA_REDIRECT_URI} in Railway, add api-production-b3ff.up.railway.app as the Strava callback domain, redeploy, then reconnect Strava.",
            details={"token_storage": token_storage, "configured_redirect_uri_matches_expected": False, "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
        )

    if not run_external_checks:
        token_configured = bool(_config_value("STRAVA_ACCESS_TOKEN") and _config_value("STRAVA_REFRESH_TOKEN"))
        return _component(
            configured=True,
            status="green" if token_configured else "yellow",
            message="Strava env vars are configured; token/storage checks were skipped." if token_configured else "Strava client credentials are configured; OAuth token check was skipped.",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_strava,
            reconnect_required=not token_configured,
            user_action_required=not token_configured,
            user_action_message="Reconnect Strava from Settings if OAuth tokens are missing." if not token_configured else "",
            details={"token_storage": token_storage, "token_status": token_metadata.get("token_status", "skipped"), "live_check": "skipped", "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
        )

    status = get_strava_connection_status()
    if status != "Connected" or not token_metadata.get("connected"):
        return _component(
            configured=True,
            status="yellow",
            message="Strava client credentials are configured, but OAuth tokens are missing or disconnected.",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_strava,
            reconnect_required=True,
            user_action_required=True,
            user_action_message="Reconnect Strava from the Settings page after confirming the Strava developer console callback domain.",
            details={"token_storage": token_storage, "token_status": token_metadata.get("token_status", "missing"), "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
        )
    try:
        refresh_strava_token_if_needed()
    except StravaReconnectRequired as exc:
        return _component(
            configured=True,
            status="yellow",
            message=str(exc),
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_strava,
            reconnect_required=True,
            user_action_required=True,
            user_action_message="Reconnect Strava from the Settings page.",
            details={"token_storage": token_storage, "token_status": "refresh_failed", "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
        )
    except StravaIntegrationError as exc:
        return _component(
            configured=True,
            status="red",
            message=f"Strava token refresh/status check failed: {exc}",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_strava,
            reconnect_required=True,
            user_action_required=True,
            user_action_message="Check STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET in Railway, redeploy, then reconnect Strava.",
            details={"token_storage": token_storage, "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
        )
    return _component(
        configured=True,
        status="green",
        message="Strava credentials and OAuth token refresh are working.",
        required_env_vars=required,
        last_successful_sync=last_sync,
        latest_record=latest_strava,
        details={"token_storage": token_storage, "token_status": "valid", "expected_redirect_uri": EXPECTED_STRAVA_REDIRECT_URI},
    )


def _check_hevy(run_external_checks: bool, settings: dict) -> dict:
    required = ["HEVY_API_KEY"]
    env_key = _config_value("HEVY_API_KEY")
    settings_key = str(settings.get("integrations", {}).get("hevy_api_key", "") or "").strip()
    configured = bool(env_key or settings_key)
    latest_hevy = ""
    last_sync = ""
    last_error = ""
    if run_external_checks:
        latest_hevy = _latest_date(load_training_log(), "hevy")
        state = load_hevy_sync_state()
        last_sync = str(state.get("last_sync_at", "") or "")
        last_error = str(state.get("last_error", "") or "")
    if not configured:
        return _component(
            configured=False,
            status="gray",
            message="HEVY_API_KEY is not configured.",
            required_env_vars=required,
            missing_env_vars=required,
            latest_record=latest_hevy,
            user_action_required=True,
            user_action_message="Add HEVY_API_KEY to Railway backend env vars and redeploy.",
        )
    if not env_key:
        return _component(
            configured=True,
            status="yellow",
            message="Hevy API key is saved in app settings, but HEVY_API_KEY is not present as a backend env var.",
            required_env_vars=required,
            missing_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_hevy,
            user_action_required=True,
            user_action_message="Move HEVY_API_KEY into Railway backend env vars and redeploy.",
        )
    if not run_external_checks:
        return _component(
            configured=True,
            status="green",
            message="HEVY_API_KEY is configured; live Hevy check was skipped.",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_hevy,
            details={"live_check": "skipped"},
        )
    if last_error:
        base_status = "yellow"
        base_message = f"HEVY_API_KEY exists, but the last sync reported an error: {last_error}"
    else:
        base_status = "green"
        base_message = "HEVY_API_KEY is configured."
    if run_external_checks:
        try:
            fetch_recent_workouts(api_key=env_key, page_size=1, pages=1, save_debug=False)
            base_status = "green"
            base_message = "HEVY_API_KEY exists and a lightweight Hevy API request succeeded."
        except HevyIntegrationError as exc:
            base_status = "red"
            base_message = f"HEVY_API_KEY exists, but Hevy rejected or failed the lightweight request: {exc}"
    return _component(
        configured=True,
        status=base_status,
        message=base_message,
        required_env_vars=required,
        last_successful_sync=last_sync,
        latest_record=latest_hevy,
        user_action_required=base_status == "red",
        user_action_message="Replace HEVY_API_KEY in Railway or check Hevy API availability, then redeploy Railway." if base_status == "red" else "",
    )


def _check_withings(environment: str, run_external_checks: bool = True) -> dict:
    required = ["WITHINGS_CLIENT_ID", "WITHINGS_CLIENT_SECRET", "WITHINGS_REDIRECT_URI"]
    missing = _missing_env_vars(required)
    redirect_uri = _config_value("WITHINGS_REDIRECT_URI")
    latest_weight = ""
    sync_state = {}
    last_sync = ""
    latest_withings = ""
    last_error = ""
    if run_external_checks:
        latest_weight = _latest_date(load_body_metrics())
        sync_state = load_withings_sync_state()
        last_sync = str(sync_state.get("last_synced_at", "") or "")
        latest_withings = str(sync_state.get("latest_measurement_date", "") or sync_state.get("latest_measure_date", "") or "") or latest_weight
        last_error = str(sync_state.get("last_error", "") or "")
    token_storage = "postgres" if use_database() else "local_files"
    route_details = {
        "connect_endpoint": "/api/withings/connect",
        "auth_url_endpoint": "/api/integrations/withings/auth-url",
        "callback_endpoint": "/api/withings/callback",
        "sync_endpoint": "/api/withings/sync",
        "refresh_path": "src.integrations.withings_client.refresh_withings_token_if_needed",
        "token_storage": token_storage,
        "expected_redirect_uri": EXPECTED_WITHINGS_REDIRECT_URI,
        "bmr_metabolic_rate_storage": "not_implemented",
        "bmr_metabolic_rate_usage": "not_used_in_adaptive_calorie_calculations",
    }
    if missing:
        return _component(
            configured=False,
            status="gray",
            message="Withings OAuth configuration is incomplete.",
            required_env_vars=required,
            missing_env_vars=missing,
            last_successful_sync=last_sync,
            latest_record=latest_withings,
            reconnect_required=True,
            user_action_required=True,
            user_action_message=f"Add WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET, and WITHINGS_REDIRECT_URI={EXPECTED_WITHINGS_REDIRECT_URI} to Railway backend env vars, redeploy, then reconnect Withings.",
            details=route_details,
        )
    if environment == "production" and redirect_uri != EXPECTED_WITHINGS_REDIRECT_URI:
        return _component(
            configured=True,
            status="yellow",
            message="redirect_mismatch: WITHINGS_REDIRECT_URI does not match the expected Railway backend callback URL.",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_withings,
            reconnect_required=True,
            user_action_required=True,
            user_action_message=f"Set WITHINGS_REDIRECT_URI to {EXPECTED_WITHINGS_REDIRECT_URI} in Railway and add that exact URL in the Withings developer console callback URLs, then redeploy and reconnect.",
            details={**route_details, "configured_redirect_uri_matches_expected": False},
        )
    if not run_external_checks:
        return _component(
            configured=True,
            status="yellow",
            message="Withings credentials are configured; OAuth token check was skipped.",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_withings,
            reconnect_required=True,
            user_action_required=False,
            details={**route_details, "live_check": "skipped"},
        )
    status = get_withings_connection_status()
    if status != "Connected":
        return _component(
            configured=True,
            status="yellow",
            message="Withings client credentials are configured, but OAuth tokens are missing.",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_withings,
            reconnect_required=True,
            user_action_required=True,
            user_action_message=f"Add {EXPECTED_WITHINGS_REDIRECT_URI} in the Withings developer console callback URLs, redeploy Railway if env vars changed, then connect Withings from Settings.",
            details=route_details,
        )
    try:
        refresh_withings_token_if_needed()
    except WithingsIntegrationError as exc:
        return _component(
            configured=True,
            status="red" if last_error else "yellow",
            message=f"Withings token refresh/status check failed: {exc}",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_withings,
            reconnect_required=True,
            user_action_required=True,
            user_action_message="Reconnect Withings from Settings. If it fails, verify the exact callback URL in the Withings developer console.",
            details=route_details,
        )
    if last_error:
        return _component(
            configured=True,
            status="red",
            message=f"Withings OAuth tokens refresh, but the last sync failed: {last_error}",
            required_env_vars=required,
            last_successful_sync=last_sync,
            latest_record=latest_withings,
            reconnect_required=bool(sync_state.get("needs_reconnect")),
            user_action_required=True,
            user_action_message="Retry Withings sync after confirming the Withings account has scale measurements and the OAuth app has user.metrics scope.",
            details=route_details,
        )
    return _component(
        configured=True,
        status="green" if latest_withings else "yellow",
        message="Withings credentials and refresh flow are working." if latest_withings else "Withings OAuth works, but no measurement sync has completed yet.",
        required_env_vars=required,
        last_successful_sync=last_sync,
        latest_record=latest_withings,
        user_action_required=not bool(latest_withings),
        user_action_message="Run Withings sync from Settings to import scale measurements." if not latest_withings else "",
        details=route_details,
    )


def _check_other_integrations(settings: dict) -> dict:
    integrations = settings.get("integrations", {})
    fitbit_client_id = _config_value("FITBIT_CLIENT_ID", settings, "fitbit_client_id")
    fitbit_client_secret = _config_value("FITBIT_CLIENT_SECRET", settings, "fitbit_client_secret")
    fitbit_configured = bool(fitbit_client_id and fitbit_client_secret)
    fitbit_missing = [name for name, value in [("FITBIT_CLIENT_ID", fitbit_client_id), ("FITBIT_CLIENT_SECRET", fitbit_client_secret)] if not value]
    usda_configured = bool(_config_value("USDA_FDC_API_KEY"))
    brave_configured = bool(_config_value("BRAVE_SEARCH_API_KEY"))
    serpapi_configured = bool(_config_value("SERPAPI_API_KEY"))
    return {
        "fitbit_google_health": _component(
            configured=fitbit_configured,
            status="yellow" if fitbit_configured else "gray",
            message="Fitbit / Google Fit OAuth ingestion is prepared but not fully implemented.",
            required_env_vars=["FITBIT_CLIENT_ID", "FITBIT_CLIENT_SECRET"],
            missing_env_vars=fitbit_missing,
            user_action_required=False,
        ),
        "usda_fdc": _component(
            configured=usda_configured,
            status="green" if usda_configured else "gray",
            message="USDA FoodData Central lookup key is configured." if usda_configured else "USDA_FDC_API_KEY is optional and not configured.",
            required_env_vars=["USDA_FDC_API_KEY"],
            missing_env_vars=[] if usda_configured else ["USDA_FDC_API_KEY"],
        ),
        "brave_search": _component(
            configured=brave_configured,
            status="green" if brave_configured else "gray",
            message="Brave Search key is configured for nutrition verification." if brave_configured else "BRAVE_SEARCH_API_KEY is optional and not configured.",
            required_env_vars=["BRAVE_SEARCH_API_KEY"],
            missing_env_vars=[] if brave_configured else ["BRAVE_SEARCH_API_KEY"],
        ),
        "serpapi": _component(
            configured=serpapi_configured,
            status="green" if serpapi_configured else "gray",
            message="SerpAPI key is configured for nutrition verification fallback." if serpapi_configured else "SERPAPI_API_KEY is optional and not configured.",
            required_env_vars=["SERPAPI_API_KEY"],
            missing_env_vars=[] if serpapi_configured else ["SERPAPI_API_KEY"],
        ),
    }


def _scan_frontend_source() -> dict:
    frontend_dir = PROJECT_ROOT / "frontend" / "src"
    source_files = list(frontend_dir.rglob("*.ts")) + list(frontend_dir.rglob("*.tsx"))
    direct_markers = ["api.openai.com", "www.strava.com/api", "api.hevyapp.com", "wbsapi.withings.net", "account.withings.com/oauth"]
    localhost_hits: list[str] = []
    direct_hits: list[str] = []
    hardcoded_backend_hits: list[str] = []
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        rel = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        if "localhost" in text or "127.0.0.1" in text:
            localhost_hits.append(rel)
        if PRODUCTION_BACKEND_URL in text:
            hardcoded_backend_hits.append(rel)
        if any(marker in text for marker in direct_markers):
            direct_hits.append(rel)
    required = ["NEXT_PUBLIC_API_URL"]
    api_configured = bool(_config_value("NEXT_PUBLIC_API_URL"))
    status = "green" if not direct_hits else "red"
    message = "Frontend API calls are centralized through the backend API base URL."
    user_action_required = False
    user_action_message = ""
    if direct_hits:
        message = "Frontend source contains direct external integration API calls."
        user_action_required = True
        user_action_message = "Remove direct frontend calls to OpenAI, Strava, Hevy, and Withings; route them through FastAPI."
    elif not api_configured:
        status = "yellow"
        message = "NEXT_PUBLIC_API_URL is not visible to this backend process; verify it in Vercel production env vars."
        user_action_required = True
        user_action_message = f"Set NEXT_PUBLIC_API_URL={PRODUCTION_BACKEND_URL} in Vercel and redeploy the frontend."
    return _component(
        configured=api_configured,
        status=status,
        message=message,
        required_env_vars=required,
        missing_env_vars=[] if api_configured else required,
        user_action_required=user_action_required,
        user_action_message=user_action_message,
        details={
            "expected_frontend_url": PRODUCTION_FRONTEND_URL,
            "expected_api_base_url": PRODUCTION_BACKEND_URL,
            "source_files_with_localhost_dev_fallbacks": sorted(localhost_hits),
            "source_files_with_hardcoded_backend_url": sorted(hardcoded_backend_hits),
            "source_files_with_direct_external_api_calls": sorted(direct_hits),
        },
    )


def _collect_required_actions(report: dict) -> list[str]:
    actions: list[str] = []
    for key, value in report.items():
        if key == "other_integrations" and isinstance(value, dict):
            for subkey, component in value.items():
                if component.get("user_action_required") and component.get("user_action_message"):
                    actions.append(f"{subkey}: {component['user_action_message']}")
            continue
        if isinstance(value, dict) and value.get("user_action_required") and value.get("user_action_message"):
            actions.append(f"{key}: {value['user_action_message']}")
    return actions


def _overall_status(report: dict) -> str:
    primary = [report.get(key, {}) for key in ["backend", "database", "openai", "strava", "hevy", "withings", "frontend"]]
    statuses = [item.get("status") for item in primary if isinstance(item, dict)]
    if "red" in statuses:
        return "error"
    if any(status in {"yellow", "gray"} for status in statuses):
        return "degraded"
    return "ok"


def build_integration_status_report(settings: dict | None = None, run_external_checks: bool = True) -> dict:
    """Build a secret-safe status report for local, production, and CLI diagnostics."""
    current_settings = settings or load_settings()
    environment = _environment()
    report: dict[str, Any] = {
        "environment": environment,
        "checked_at": _now_iso(),
    }
    report["backend"] = _check_backend(environment)
    report["database"] = _check_database(environment, run_external_checks)
    report["openai"] = _check_openai(run_external_checks)
    report["strava"] = _check_strava(current_settings, environment, run_external_checks)
    report["hevy"] = _check_hevy(run_external_checks, current_settings)
    report["withings"] = _check_withings(environment, run_external_checks)
    report["frontend"] = _scan_frontend_source()
    report["other_integrations"] = _check_other_integrations(current_settings)
    report["required_user_actions"] = _collect_required_actions(report)
    report["overall_status"] = _overall_status(report)
    return report


def fetch_remote_integration_status(base_url: str, timeout: int = 20) -> dict:
    """Fetch the deployed backend diagnostics endpoint without printing secrets."""
    target = f"{base_url.rstrip('/')}/api/integrations/status"
    request = Request(target, headers={"Accept": "application/json", "User-Agent": "PerformanceOSDiagnostics/0.1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Remote diagnostics failed with status {exc.code}: {body}") from exc
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f"Could not reach remote diagnostics endpoint: {exc}") from exc
