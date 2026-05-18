import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request as UrlRequest, urlopen

import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from src.config import INTEGRATION_FIELDS, fitbit_google_health_status, integration_status, load_settings, mask_secret, normalize_accent_color, save_settings
from src.ai.food_parser import get_openai_key_status
from src.body_metrics import load_body_metrics
from src.integrations.hevy_client import HEVY_API_BASE_URL, load_hevy_sync_state
from src.integrations.strava_client import (
    StravaIntegrationError,
    build_strava_auth_url,
    clear_strava_connection,
    exchange_strava_code,
    get_strava_connection_status,
    get_strava_safe_token_metadata,
    load_strava_sync_state,
    refresh_strava_token_if_needed,
)
from src.integrations.withings_client import (
    WITHINGS_MEASURE_URL,
    WITHINGS_REQUESTED_MEASTYPES,
    WithingsIntegrationError,
    WithingsReconnectRequired,
    get_withings_connection_status,
    load_withings_sync_state,
    refresh_withings_token_if_needed,
)
from src.integration_health import build_integration_status_report
from src.nutrition import load_nutrition_log
from src.recovery import load_recovery_log, load_sleep_entries
from src.storage import production_storage_warnings, use_database
from src.training import load_training_log


router = APIRouter(tags=["integrations"])
logger = logging.getLogger(__name__)
API_TEST_TIMEOUT_SECONDS = 8


@router.get("/status")
def status() -> dict:
    """Return placeholder route status."""
    return {"status": "placeholder", "module": "integrations"}


class SettingsPayload(BaseModel):
    integrations: dict[str, str] = Field(default_factory=dict)
    appearance: dict[str, str] = Field(default_factory=dict)


def _read_dotenv_value(key: str) -> str:
    """Read local .env config without returning secret values."""
    from pathlib import Path

    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
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


def _configured_from_env(key: str) -> bool:
    """Return whether a key exists in env or .env without exposing it."""
    import os

    return bool(os.getenv(key, "").strip() or _read_dotenv_value(key).strip())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _effective_config_value(settings: dict, settings_key: str, env_key: str) -> str:
    """Resolve a secret/config value without exposing where it came from."""
    return (
        os.getenv(env_key, "").strip()
        or _read_dotenv_value(env_key).strip()
        or str(settings.get("integrations", {}).get(settings_key, "") or "").strip()
    )


def _test_result(status: str, message: str, last_checked_at: str, **extra: object) -> dict:
    return {
        "status": status,
        "message": message,
        "lastCheckedAt": last_checked_at,
        **extra,
    }


def _hevy_probe(api_key: str) -> None:
    query = urlencode({"page": 1, "pageSize": 1})
    request = UrlRequest(
        f"{HEVY_API_BASE_URL}/v1/workouts?{query}",
        headers={"api-key": api_key, "Accept": "application/json"},
    )
    with urlopen(request, timeout=API_TEST_TIMEOUT_SECONDS) as response:
        payload = response.read().decode("utf-8")
    if payload:
        json.loads(payload)


def _test_hevy_connection(settings: dict) -> dict:
    checked_at = _now_iso()
    api_key = _effective_config_value(settings, "hevy_api_key", "HEVY_API_KEY")
    if not api_key:
        return _test_result("missing_api_key", "HEVY_API_KEY is not configured.", checked_at)
    try:
        _hevy_probe(api_key)
        return _test_result("connected", "Hevy API reachable.", checked_at)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return _test_result("invalid_api_key", "Hevy rejected the API key.", checked_at)
        if exc.code == 429:
            return _test_result("rate_limited", "Hevy rate limited the test request. Try again shortly.", checked_at)
        return _test_result("api_unreachable", f"Hevy test failed with HTTP {exc.code}.", checked_at)
    except (URLError, TimeoutError):
        return _test_result("api_unreachable", "Could not reach Hevy before the timeout.", checked_at)
    except (json.JSONDecodeError, OSError):
        return _test_result("api_unreachable", "Hevy returned an unreadable response.", checked_at)


def _openai_probe(api_key: str) -> None:
    client = OpenAI(api_key=api_key, timeout=API_TEST_TIMEOUT_SECONDS, max_retries=0)
    # Listing models is an inexpensive auth/connectivity check; it does not run
    # a model generation.
    client.models.list()


def _test_openai_connection(settings: dict) -> dict:
    checked_at = _now_iso()
    api_key = _effective_config_value(settings, "openai_api_key", "OPENAI_API_KEY")
    if not api_key:
        return _test_result("missing_api_key", "OPENAI_API_KEY is not configured.", checked_at)
    try:
        _openai_probe(api_key)
        return _test_result("connected", "OpenAI API reachable.", checked_at)
    except AuthenticationError:
        return _test_result("invalid_api_key", "OpenAI rejected the API key.", checked_at)
    except RateLimitError:
        return _test_result("rate_limited", "OpenAI rate limited the test request. Check quota or try again shortly.", checked_at)
    except APIConnectionError:
        return _test_result("api_unreachable", "Could not reach OpenAI before the timeout.", checked_at)
    except APIStatusError as exc:
        if exc.status_code in {401, 403}:
            return _test_result("invalid_api_key", "OpenAI rejected the API key.", checked_at)
        if exc.status_code == 429:
            return _test_result("rate_limited", "OpenAI rate limited the test request. Check quota or try again shortly.", checked_at)
        return _test_result("api_unreachable", f"OpenAI test failed with HTTP {exc.status_code}.", checked_at)
    except Exception:
        logger.exception("OpenAI API connection test failed without exposing credentials.")
        return _test_result("api_unreachable", "OpenAI API test failed unexpectedly.", checked_at)


def _scope_set(scopes: str) -> set[str]:
    return {scope.strip().lower() for scope in re.split(r"[\s,]+", str(scopes or "")) if scope.strip()}


def _withings_probe(access_token: str) -> None:
    now = int(time.time())
    request = UrlRequest(
        WITHINGS_MEASURE_URL,
        data=urlencode(
            {
                "action": "getmeas",
                "category": 1,
                "meastypes": WITHINGS_REQUESTED_MEASTYPES,
                "startdate": now - 7 * 24 * 60 * 60,
                "enddate": now,
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=API_TEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    status = int(payload.get("status", 0) or 0)
    if status != 0:
        message = payload.get("error") or payload.get("body", {}).get("error") or f"Withings API returned status {status}."
        raise WithingsIntegrationError(str(message))


def _withings_layer(status: str, message: str) -> dict:
    return {"status": status, "message": message}


def _test_withings_connection(settings: dict) -> dict:
    checked_at = _now_iso()
    client_id = _effective_config_value(settings, "withings_client_id", "WITHINGS_CLIENT_ID")
    client_secret = _effective_config_value(settings, "withings_client_secret", "WITHINGS_CLIENT_SECRET")
    redirect_uri = os.getenv("WITHINGS_REDIRECT_URI", "").strip() or _read_dotenv_value("WITHINGS_REDIRECT_URI").strip()
    missing = [
        label
        for label, value in [
            ("WITHINGS_CLIENT_ID", client_id),
            ("WITHINGS_CLIENT_SECRET", client_secret),
            ("WITHINGS_REDIRECT_URI", redirect_uri),
        ]
        if not value
    ]
    layers = {
        "credentials": _withings_layer("configured", "Withings app credentials are configured."),
        "oauth": _withings_layer("not_connected", "User OAuth tokens have not been checked yet."),
        "scopes": _withings_layer("unknown", "Withings scopes have not been checked yet."),
    }
    if missing:
        layers["credentials"] = _withings_layer("missing", f"Missing {', '.join(missing)}.")
        return _test_result("missing_credentials", f"Missing Withings app credentials: {', '.join(missing)}.", checked_at, layers=layers)

    metadata = settings.get("metadata", {})
    tokens = metadata.get("withings_tokens", {})
    sync = metadata.get("withings_sync", {})
    access_token = str(tokens.get("access_token", "") or "")
    refresh_token = str(tokens.get("refresh_token", "") or "")
    expires_at = int(tokens.get("expires_at") or 0)
    scopes = _scope_set(str(tokens.get("scopes", "") or ""))

    if not access_token and not refresh_token:
        layers["oauth"] = _withings_layer("not_connected", "Withings app credentials are ready, but user OAuth is not connected.")
        return _test_result("ready_to_connect", "Withings credentials configured, user OAuth not connected.", checked_at, layers=layers)
    if sync.get("needs_reconnect"):
        layers["oauth"] = _withings_layer("needs_reconnect", "Saved Withings OAuth tokens require reconnection.")
        return _test_result("needs_reconnect", "Withings OAuth needs reconnecting.", checked_at, layers=layers)
    if not refresh_token:
        layers["oauth"] = _withings_layer("needs_reconnect", "Saved Withings token has no refresh token.")
        return _test_result("needs_reconnect", "Withings refresh token is missing. Reconnect Withings.", checked_at, layers=layers)
    if "user.metrics" not in scopes:
        layers["oauth"] = _withings_layer("connected", "Withings OAuth tokens exist.")
        layers["scopes"] = _withings_layer("missing", "Withings OAuth scope must include user.metrics for body metrics.")
        return _test_result("needs_reconnect", "Withings is connected without body metrics scope. Reconnect Withings.", checked_at, layers=layers)

    layers["scopes"] = _withings_layer("configured", "Withings body metrics scope is present.")
    try:
        if not access_token or expires_at <= int(time.time()) + 300:
            access_token = str(refresh_withings_token_if_needed(timeout_seconds=API_TEST_TIMEOUT_SECONDS) or "")
        layers["oauth"] = _withings_layer("connected", "Withings OAuth token is present and refreshable.")
        _withings_probe(access_token)
        return _test_result("connected", "Withings API reachable and body metrics access is working.", checked_at, layers=layers)
    except WithingsReconnectRequired:
        layers["oauth"] = _withings_layer("token_expired", "Withings token refresh failed.")
        return _test_result("token_expired", "Withings token expired. Reconnect Withings.", checked_at, layers=layers)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            layers["oauth"] = _withings_layer("needs_reconnect", "Withings rejected the saved access token.")
            return _test_result("needs_reconnect", "Withings rejected the saved token. Reconnect Withings.", checked_at, layers=layers)
        return _test_result("api_unreachable", f"Withings test failed with HTTP {exc.code}.", checked_at, layers=layers)
    except (URLError, TimeoutError):
        return _test_result("api_unreachable", "Could not reach Withings before the timeout.", checked_at, layers=layers)
    except WithingsIntegrationError as exc:
        message = str(exc)
        lowered = message.lower()
        if any(token in lowered for token in ["invalid", "expired", "unauthorized", "access_token", "refresh token"]):
            layers["oauth"] = _withings_layer("needs_reconnect", "Withings rejected the saved OAuth token.")
            return _test_result("needs_reconnect", "Withings OAuth token was rejected. Reconnect Withings.", checked_at, layers=layers)
        return _test_result("api_unreachable", f"Withings API test failed: {message}", checked_at, layers=layers)
    except (json.JSONDecodeError, OSError):
        return _test_result("api_unreachable", "Withings returned an unreadable response.", checked_at, layers=layers)


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


def _days_since(date_value: str) -> int | None:
    if not date_value:
        return None
    parsed = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(parsed):
        return None
    return int((pd.Timestamp.today().normalize() - parsed.normalize()).days)


def _freshness_detail(label: str, date_value: str) -> str:
    days = _days_since(date_value)
    if days is None:
        return f"No {label} data yet."
    if days == 0:
        return f"{label} data updated today."
    if days == 1:
        return f"{label} data updated yesterday."
    return f"{label} data updated {days} days ago."


def _masked_athlete_id(value: str) -> str:
    if not value:
        return ""
    return f"••••{value[-4:]}" if len(value) > 4 else "••••"


def _strava_redirect_uri(request: Request) -> str:
    configured = os.getenv("STRAVA_REDIRECT_URI", "").strip() or _read_dotenv_value("STRAVA_REDIRECT_URI").strip()
    if not configured:
        configured = str(request.url_for("strava_callback"))
    # Strava redirect URIs are case-sensitive. Normalize the callback path so a
    # mis-cased env var (e.g. /api/Strava/callback) still produces the valid
    # lowercase /api/strava/callback and passes Strava's redirect_uri check.
    return re.sub(r"/api/strava/callback", "/api/strava/callback", configured, flags=re.IGNORECASE)


def _frontend_return_url(request: Request, status: str, message: str = "") -> str:
    app_url = (
        os.getenv("NEXT_PUBLIC_APP_URL", "").strip().rstrip("/")
        or os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
        or _read_dotenv_value("NEXT_PUBLIC_APP_URL").strip().rstrip("/")
    )
    if not app_url:
        referer = request.headers.get("referer", "").strip()
        if referer:
            parsed = urlparse(referer)
            app_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if not app_url:
        app_url = str(request.base_url).rstrip("/")
    query = urlencode({"strava": status, "message": message})
    return f"{app_url}/?{query}"


def _strava_debug_status(settings: dict, latest_strava: str) -> dict:
    token_metadata = get_strava_safe_token_metadata()
    sync_state = load_strava_sync_state()
    return {
        "connected": token_metadata["connected"],
        "athlete_id": _masked_athlete_id(str(token_metadata.get("athlete_id", "") or "")),
        "token_expires_at": token_metadata["token_expires_at"],
        "token_status": token_metadata["token_status"],
        "scopes": str(token_metadata.get("scopes", "") or ""),
        "last_synced_at": sync_state.get("last_synced_at", ""),
        "latest_activity_date": sync_state.get("latest_activity_date", "") or latest_strava,
        "last_imported_count": sync_state.get("last_imported_count", 0),
        "last_updated_count": sync_state.get("last_updated_count", 0),
        "last_fetched_count": sync_state.get("last_fetched_count", 0),
        "last_error": sync_state.get("last_error", ""),
    }


def _safe_component(
    *,
    configured: bool,
    status: str,
    message: str,
    last_synced_at: str = "",
    latest_record: str = "",
    reconnect_required: bool = False,
) -> dict:
    return {
        "configured": bool(configured),
        "status": status,
        "message": message,
        "last_synced_at": last_synced_at,
        "latest_record": latest_record,
        "reconnect_required": bool(reconnect_required),
    }


def _integration_components(settings: dict) -> dict:
    training_df = load_training_log()
    latest_strava = _latest_date(training_df, "strava")
    latest_hevy = _latest_date(training_df, "hevy")
    hevy_state = load_hevy_sync_state()
    hevy_error = str(hevy_state.get("last_error", "") or "")
    hevy_last_sync = str(hevy_state.get("last_sync_at", "") or "")
    hevy_configured = bool(settings.get("integrations", {}).get("hevy_api_key")) or _configured_from_env("HEVY_API_KEY")

    strava_status = get_strava_connection_status()
    strava_debug = _strava_debug_status(settings, latest_strava)
    integrations = settings.get("integrations", {})
    strava_client_configured = bool(integrations.get("strava_client_id") and integrations.get("strava_client_secret")) or (_configured_from_env("STRAVA_CLIENT_ID") and _configured_from_env("STRAVA_CLIENT_SECRET"))
    if strava_status == "Connected":
        # Status only — report the stored token state. Tokens are refreshed
        # lazily when the user actually syncs, never on a status read.
        strava_token_expired = str(strava_debug.get("token_status", "") or "") == "expired"
        strava_component = _safe_component(
            configured=True,
            status="reconnect_required" if strava_token_expired else "ok",
            message=(
                "Strava access token has expired. It refreshes automatically on the next Strava sync, or reconnect now."
                if strava_token_expired
                else "Strava is connected. Tokens refresh automatically when you sync."
            ),
            last_synced_at=strava_debug["last_synced_at"],
            latest_record=strava_debug["latest_activity_date"],
            reconnect_required=strava_token_expired,
        )
    elif strava_status in {"Ready to connect", "Disconnected"}:
        strava_component = _safe_component(
            configured=strava_client_configured,
            status="reconnect_required",
            message="Strava client credentials are configured, but OAuth tokens are missing or invalid. Reconnect Strava.",
            last_synced_at=strava_debug["last_synced_at"],
            latest_record=strava_debug["latest_activity_date"],
            reconnect_required=True,
        )
    else:
        strava_component = _safe_component(
            configured=False,
            status="unconfigured",
            message="Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET on the Railway backend.",
            latest_record=latest_strava,
            reconnect_required=False,
        )

    database_warnings = production_storage_warnings()
    body_df = load_body_metrics()
    latest_weight = _latest_date(body_df)
    withings_status = get_withings_connection_status()
    withings_sync = load_withings_sync_state()
    withings_error = str(withings_sync.get("last_error", "") or "")
    withings_latest = str(withings_sync.get("latest_measure_date", "") or "") or latest_weight
    withings_last_sync = str(withings_sync.get("last_synced_at", "") or "")
    withings_client_configured = (
        bool(integrations.get("withings_client_id") and integrations.get("withings_client_secret"))
        or (_configured_from_env("WITHINGS_CLIENT_ID") and _configured_from_env("WITHINGS_CLIENT_SECRET"))
    )
    if withings_status == "Connected":
        # Status only — no external token refresh on a status read. The
        # Withings token is refreshed lazily inside the sync endpoint.
        withings_component = _safe_component(
            configured=True,
            status="error" if withings_error else "ok",
            message=withings_error or "Withings is connected. Tokens refresh automatically when you sync.",
            last_synced_at=withings_last_sync,
            latest_record=withings_latest,
            reconnect_required=False,
        )
    elif withings_status == "Ready to connect":
        withings_component = _safe_component(
            configured=withings_client_configured,
            status="reconnect_required",
            message="Withings client credentials are configured, but OAuth tokens are missing. Connect Withings.",
            last_synced_at=withings_last_sync,
            latest_record=withings_latest,
            reconnect_required=True,
        )
    else:
        withings_component = _safe_component(
            configured=False,
            status="unconfigured",
            message="Set WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET, and WITHINGS_REDIRECT_URI on the Railway backend.",
            latest_record=withings_latest,
            reconnect_required=False,
        )
    return {
        "backend": _safe_component(
            configured=True,
            status="ok",
            message="FastAPI backend is responding.",
        ),
        "database": _safe_component(
            configured=use_database(),
            status="ok" if use_database() else "error" if database_warnings else "unconfigured",
            message="DATABASE_URL is configured and Postgres storage is active." if use_database() else (database_warnings[0] if database_warnings else "DATABASE_URL is not configured; using local file storage."),
        ),
        "openai": _safe_component(
            configured=get_openai_key_status(),
            status="ok" if get_openai_key_status() else "unconfigured",
            message="OPENAI_API_KEY is configured on the backend." if get_openai_key_status() else "Set OPENAI_API_KEY on the Railway backend.",
        ),
        "strava": strava_component,
        "hevy": _safe_component(
            configured=hevy_configured,
            status="error" if hevy_error else "ok" if hevy_configured else "unconfigured",
            message=hevy_error or ("HEVY_API_KEY is configured on the backend." if hevy_configured else "Set HEVY_API_KEY on the Railway backend."),
            last_synced_at=hevy_last_sync,
            latest_record=latest_hevy,
            reconnect_required=False,
        ),
        "withings": withings_component,
    }


def _integration_health(settings: dict, statuses: dict[str, str]) -> list[dict]:
    training_df = load_training_log()
    body_df = load_body_metrics()
    nutrition_df = load_nutrition_log()
    recovery_df = load_recovery_log()
    sleep_df = load_sleep_entries()
    hevy_state = load_hevy_sync_state()
    hevy_last_sync = str(hevy_state.get("last_sync_at", "") or "")
    hevy_error = str(hevy_state.get("last_error", "") or "")
    hevy_configured = statuses.get("hevy_api_key") == "Configured"
    strava_status = statuses.get("strava", "Not configured")
    latest_strava = _latest_date(training_df, "strava")
    strava_debug = _strava_debug_status(settings, latest_strava)
    # Decide which button the Strava card shows: Sync when connected with a
    # usable token, Connect when credentials exist but OAuth never ran, and
    # Reconnect when the token is missing/expired.
    strava_token_status = str(strava_debug.get("token_status", "") or "")
    if strava_status == "Not configured":
        strava_action = ""
    elif strava_status == "Connected" and strava_token_status != "expired":
        strava_action = "strava_import"
    elif strava_status == "Ready to connect":
        strava_action = "strava_connect"
    else:
        strava_action = "strava_reconnect"
    latest_weight = _latest_date(body_df)
    latest_food = _latest_date(nutrition_df)
    latest_recovery = _latest_date(recovery_df) or _latest_date(sleep_df)
    storage_warnings = production_storage_warnings()
    withings_status = get_withings_connection_status()
    withings_sync = load_withings_sync_state()
    withings_error = str(withings_sync.get("last_error", "") or "")
    withings_latest = str(withings_sync.get("latest_measure_date", "") or "")
    withings_last_sync = str(withings_sync.get("last_synced_at", "") or "")

    cards = [
        {
            "id": "database",
            "title": "Database",
            "status": "connected" if use_database() else ("error" if storage_warnings else "warning"),
            "label": "Postgres connected" if use_database() else "Local file storage",
            "detail": storage_warnings[0] if storage_warnings else ("Data is using DATABASE_URL." if use_database() else "Fine for local dev; production should use DATABASE_URL."),
        },
        {
            "id": "hevy",
            "title": "Hevy",
            "status": "error" if hevy_error else "connected" if hevy_configured and hevy_last_sync else "warning",
            "label": "Connected" if hevy_configured else "Not configured",
            "detail": hevy_error or (f"Last sync: {hevy_last_sync}" if hevy_last_sync else "No Hevy sync has completed yet."),
            "last_synced_at": hevy_last_sync,
            "action": "hevy_sync" if hevy_configured else "",
        },
        {
            "id": "strava",
            "title": "Strava",
            "status": "error" if strava_debug["last_error"] else "connected" if strava_status == "Connected" and latest_strava else "warning",
            "label": strava_status,
            "detail": strava_debug["last_error"] or (_freshness_detail("Strava run", latest_strava) if strava_status == "Connected" else "OAuth is required before run sync works."),
            "last_synced_at": strava_debug["last_synced_at"] or latest_strava,
            "action": strava_action,
            "metadata": strava_debug,
        },
        {
            "id": "fitbit_google_health",
            "title": "Fitbit / Google Fit",
            "status": "connected" if statuses.get("fitbit_google_health") == "Connected" else "warning",
            "label": statuses.get("fitbit_google_health", "Not configured"),
            "detail": _freshness_detail("Recovery", latest_recovery) if latest_recovery else "Prepared, but wearable sync is not connected yet.",
        },
        {
            "id": "withings",
            "title": "Withings",
            "status": "error" if withings_error else "connected" if withings_status == "Connected" and withings_latest else "warning",
            "label": withings_status,
            "detail": withings_error or (_freshness_detail("Withings scale", withings_latest) if withings_latest else "Connect Withings, then sync scale measurements into body metrics."),
            "last_synced_at": withings_last_sync or withings_latest,
            "action": "withings_sync" if withings_status == "Connected" else "withings_connect" if withings_status == "Ready to connect" else "",
            "metadata": {
                "connected": withings_status == "Connected",
                "last_imported_count": withings_sync.get("last_imported_count", 0),
                "last_fetched_count": withings_sync.get("last_fetched_groups", 0),
                "latest_activity_date": withings_latest,
                "last_error": withings_error,
            },
        },
        {
            "id": "openai",
            "title": "OpenAI",
            "status": "connected" if statuses.get("openai_api_key") == "Configured" else "warning",
            "label": statuses.get("openai_api_key", "Not configured"),
            "detail": "Food parsing is available." if statuses.get("openai_api_key") == "Configured" else "Add OPENAI_API_KEY or save the key in settings.",
        },
        {
            "id": "bodyweight",
            "title": "Bodyweight",
            "status": "warning" if (_days_since(latest_weight) is None or (_days_since(latest_weight) or 0) > 5) else "connected",
            "label": "Fresh" if latest_weight and (_days_since(latest_weight) or 0) <= 5 else "Missing data",
            "detail": _freshness_detail("Bodyweight", latest_weight),
        },
        {
            "id": "food_logs",
            "title": "Food logs",
            "status": "warning" if (_days_since(latest_food) is None or (_days_since(latest_food) or 0) > 2) else "connected",
            "label": "Fresh" if latest_food and (_days_since(latest_food) or 0) <= 2 else "Missing recent food",
            "detail": _freshness_detail("Food", latest_food),
        },
    ]
    return cards


def _settings_response(settings: dict) -> dict:
    """Return settings with secrets masked for frontend display."""
    integrations = settings.get("integrations", {})
    appearance = settings.get("metadata", {}).get("appearance", {})
    masked = {
        key: mask_secret(integrations.get(key, ""))
        for key in INTEGRATION_FIELDS
    }
    openai_configured = get_openai_key_status()
    hevy_configured = bool(integrations.get("hevy_api_key")) or _configured_from_env("HEVY_API_KEY")
    statuses = {
        "hevy_api_key": "Configured" if hevy_configured else integration_status("hevy_api_key", settings),
        "strava": get_strava_connection_status(),
        "strava_client_id": "Configured" if _configured_from_env("STRAVA_CLIENT_ID") else integration_status("strava_client_id", settings),
        "strava_client_secret": "Configured" if _configured_from_env("STRAVA_CLIENT_SECRET") else integration_status("strava_client_secret", settings),
        "strava_redirect_uri": "Configured" if _configured_from_env("STRAVA_REDIRECT_URI") else "Auto from app URL",
        "fitbit_client_id": integration_status("fitbit_client_id", settings),
        "fitbit_client_secret": integration_status("fitbit_client_secret", settings),
        "fitbit_google_health": fitbit_google_health_status(settings),
        "withings_client_id": "Configured" if _configured_from_env("WITHINGS_CLIENT_ID") else integration_status("withings_client_id", settings),
        "withings_client_secret": "Configured" if _configured_from_env("WITHINGS_CLIENT_SECRET") else integration_status("withings_client_secret", settings),
        "withings": get_withings_connection_status(),
        "openai_api_key": "Configured" if openai_configured else "Not configured",
        "apple_health_export_file": integration_status("apple_health_export_file", settings),
    }
    return {
        "integrations": masked,
        "appearance": {"accent_color": normalize_accent_color(appearance.get("accent_color"))},
        "statuses": statuses,
        "health": _integration_health(settings, statuses),
        "services": _integration_components(settings),
    }


@router.get("/api/settings")
def get_settings() -> dict:
    """Return masked local settings."""
    return _settings_response(load_settings())


@router.put("/api/settings")
def update_settings(payload: SettingsPayload) -> dict:
    """Update local integration settings.

    Empty values and masked values preserve the existing secret, so the frontend
    never needs to display saved keys in plain text.
    """
    settings = load_settings()
    incoming = payload.integrations or {}
    for key in INTEGRATION_FIELDS:
        value = str(incoming.get(key, "")).strip()
        if value and not value.startswith("••"):
            settings["integrations"][key] = value
    if payload.appearance:
        settings.setdefault("metadata", {}).setdefault("appearance", {})["accent_color"] = normalize_accent_color(payload.appearance.get("accent_color"))
    save_settings(settings)
    return _settings_response(load_settings())


@router.get("/api/integrations/status")
def get_integration_statuses(external_checks: bool = Query(default=True)) -> dict:
    """Return a secret-safe integration diagnostics report plus legacy settings data."""
    settings = load_settings()
    response = _settings_response(settings)
    response.update(build_integration_status_report(settings=settings, run_external_checks=external_checks))
    return response


@router.get("/api/integrations/test")
def test_api_connections() -> dict:
    """Run explicit, timeout-bounded API connectivity checks for Settings."""
    settings = load_settings()
    checked_at = _now_iso()
    checks = {
        "hevy": _test_hevy_connection,
        "openai": _test_openai_connection,
        "withings": _test_withings_connection,
    }
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {name: executor.submit(check, settings) for name, check in checks.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result(timeout=API_TEST_TIMEOUT_SECONDS + 2)
            except FutureTimeout:
                results[name] = _test_result("api_unreachable", f"{name.title()} test timed out.", checked_at)
            except Exception:
                logger.exception("%s API connection test failed without exposing credentials.", name.title())
                results[name] = _test_result("api_unreachable", f"{name.title()} API test failed unexpectedly.", checked_at)
    return {"checkedAt": checked_at, **results}


@router.get("/api/integrations/strava/auth-url")
def get_strava_auth_url(request: Request, reconnect: bool = Query(default=False)) -> dict:
    """Return a Strava OAuth URL for the frontend Connect Strava button."""
    if reconnect:
        clear_strava_connection("Reconnect requested from Settings.", mark_error=False)
    redirect_uri = _strava_redirect_uri(request)
    production_like = os.getenv("VERCEL") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER") or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
    if production_like and "localhost" in redirect_uri:
        return {
            "status": "error",
            "message": "STRAVA_REDIRECT_URI is still localhost. Set it to your deployed backend callback URL.",
            "auth_url": "",
        }
    try:
        logger.info("Strava OAuth start requested with redirect_uri=%s", redirect_uri)
        auth_url = build_strava_auth_url(redirect_uri=redirect_uri, force_approval=reconnect)
    except StravaIntegrationError as exc:
        return {"status": "error", "message": str(exc), "auth_url": ""}
    return {"status": "ok", "auth_url": auth_url}


@router.get("/api/strava/callback", name="strava_callback")
@router.get("/api/integrations/strava/callback")
def strava_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """Exchange Strava OAuth callback code and store tokens locally."""
    if error:
        message = f"Strava authorization failed: {error}"
        logger.error("Strava OAuth callback failed: %s", error)
        return RedirectResponse(_frontend_return_url(request, "error", message), status_code=303)
    if not code:
        logger.error("Strava OAuth callback missing code.")
        return RedirectResponse(_frontend_return_url(request, "error", "Missing authorization code."), status_code=303)

    try:
        result = exchange_strava_code(code)
        logger.info("Strava OAuth callback connected athlete_id=%s", result.get("athlete_id", ""))
    except StravaIntegrationError as exc:
        logger.exception("Strava OAuth callback token exchange failed.")
        return RedirectResponse(_frontend_return_url(request, "error", str(exc)), status_code=303)

    return RedirectResponse(_frontend_return_url(request, "connected", "Strava connected."), status_code=303)


@router.post("/api/strava/refresh-token")
def refresh_strava_token() -> dict:
    try:
        refresh_strava_token_if_needed(force=True)
    except StravaIntegrationError as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "ok"}


@router.post("/api/integrations/strava/disconnect")
def disconnect_strava() -> dict:
    clear_strava_connection("Strava disconnected. Reconnect from Settings.")
    return _settings_response(load_settings())
