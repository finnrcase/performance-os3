from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from backend_new.db import ensure_jsonb_table, fetch_json_rows, fetch_latest_document, insert_json_row, ping, upsert_json_row
from backend_new.routes.body_metrics import withings_body_metric_sync_response
from backend_new.routes.settings import settings_payload
from backend_new.utils import app_today_iso, utc_now_iso

router = APIRouter(tags=["integrations"])
logger = logging.getLogger(__name__)

WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_SCOPES = "user.metrics"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_SCOPES = "read,activity:read_all"
GOOGLE_HEALTH_EXPECTED_CALLBACK_URL = "https://performance-os-git-main-finnrcases-projects.vercel.app/api/google-health/callback"

SECRET_MARKER = "••••"


def _production_like() -> bool:
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("VERCEL")
        or os.getenv("RENDER")
        or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
        or os.getenv("APP_ENV", "").lower() in {"production", "prod"}
    )


def _withings_redirect_uri(request: Request) -> str:
    configured = os.getenv("WITHINGS_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return str(request.url_for("withings_callback"))


def _redirect_uri_error(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or ""
    if not redirect_uri:
        return "WITHINGS_REDIRECT_URI is not configured and the backend could not derive a callback URL."
    if _production_like() and host in {"localhost", "127.0.0.1", "::1"}:
        return "WITHINGS_REDIRECT_URI is still localhost. Set it to your deployed callback URL."
    return ""


def _frontend_return_url(request: Request, provider: str, status: str, message: str = "") -> str:
    app_url = (
        os.getenv("NEXT_PUBLIC_APP_URL", "").strip().rstrip("/")
        or os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    )
    if not app_url:
        referer = request.headers.get("referer", "").strip()
        if referer:
            parsed = urlparse(referer)
            app_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if not app_url:
        app_url = str(request.base_url).rstrip("/")
    return f"{app_url}/?{urlencode({'page': 'settings', provider: status, 'message': message})}"


def _withings_error(message: str) -> dict:
    return {
        "status": "error",
        "message": message,
        "imported_measurements": 0,
        "fetched_groups": 0,
        "latest_measure_date": "",
        "last_synced_at": "",
    }


def _withings_sync_response(result: dict[str, Any], *, items_limit: int) -> dict[str, Any]:
    return withings_body_metric_sync_response(result, items_limit=items_limit)


def _settings_document() -> dict:
    stored = fetch_latest_document("api_connections", {"integrations": {}, "metadata": {}})
    if not isinstance(stored, dict):
        return {"integrations": {}, "metadata": {}}
    stored.setdefault("integrations", {})
    stored.setdefault("metadata", {})
    return stored


def _metadata(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    current = settings if isinstance(settings, dict) else _settings_document()
    metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    return metadata


def _integrations(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    current = settings if isinstance(settings, dict) else _settings_document()
    integrations = current.get("integrations") if isinstance(current.get("integrations"), dict) else {}
    return integrations


def _env_or_saved(settings: dict[str, Any], env_name: str, integration_field: str = "") -> str:
    saved = _integrations(settings).get(integration_field or env_name.lower(), "") if integration_field else ""
    return os.getenv(env_name, "").strip() or str(saved or "").strip()


def _mask_present(value: object) -> str:
    return SECRET_MARKER if str(value or "").strip() else ""


def _secret_preview(value: object, *, head: int = 8, tail: int = 6) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= head + tail + 3:
        return f"{text[:2]}...{text[-2:]}" if len(text) > 4 else "present"
    return f"{text[:head]}...{text[-tail:]}"


def _runtime_service() -> dict[str, Any]:
    if os.getenv("VERCEL"):
        service = "vercel"
    elif os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME"):
        service = "railway"
    elif os.getenv("RENDER"):
        service = "render"
    else:
        service = "local_or_unknown"
    return {
        "service": service,
        "environment": os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("VERCEL_ENV") or os.getenv("RENDER_SERVICE_TYPE") or os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "local",
        "vercel": bool(os.getenv("VERCEL")),
        "railway": bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_SERVICE_NAME")),
        "render": bool(os.getenv("RENDER")),
    }


def _save_settings_document(settings: dict[str, Any]) -> dict[str, Any]:
    payload = dict(settings or {})
    payload["settings_key"] = "primary"
    payload["updated_at"] = utc_now_iso()
    return upsert_json_row("api_connections", "settings_key", "primary", payload)


def _component(
    *,
    configured: bool,
    status: str,
    message: str,
    required_env_vars: list[str] | None = None,
    latest_record: str = "",
    last_successful_sync: str = "",
    reconnect_required: bool = False,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required = required_env_vars or []
    return {
        "configured": configured,
        "status": status,
        "message": message,
        "required_env_vars": required,
        "missing_env_vars": [name for name in required if not os.getenv(name, "").strip()],
        "latest_record": latest_record,
        "last_successful_sync": last_successful_sync,
        "reconnect_required": reconnect_required,
        "user_action_required": status in {"red", "yellow"} and bool(required),
        "user_action_message": "Configure missing environment variables or reconnect this integration." if status in {"red", "yellow"} else "",
        "details": details or {},
    }


def _test_result(status: str, message: str) -> dict[str, Any]:
    return {"status": status, "message": message, "lastCheckedAt": utc_now_iso(), "layers": {}}


def _strava_tokens(settings: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(settings)
    integrations = _integrations(settings)
    saved = metadata.get("strava_tokens") if isinstance(metadata.get("strava_tokens"), dict) else {}
    try:
        expires_at = int(
            os.getenv("STRAVA_EXPIRES_AT", "")
            or os.getenv("STRAVA_TOKEN_EXPIRES_AT", "")
            or integrations.get("strava_expires_at")
            or saved.get("expires_at")
            or 0
        )
    except ValueError:
        expires_at = 0
    return {
        "access_token": os.getenv("STRAVA_ACCESS_TOKEN", "").strip() or str(integrations.get("strava_access_token") or saved.get("access_token") or "").strip(),
        "refresh_token": os.getenv("STRAVA_REFRESH_TOKEN", "").strip() or str(integrations.get("strava_refresh_token") or saved.get("refresh_token") or "").strip(),
        "expires_at": expires_at,
        "athlete_id": os.getenv("STRAVA_ATHLETE_ID", "").strip() or str(integrations.get("strava_athlete_id") or saved.get("athlete_id") or "").strip(),
        "scopes": os.getenv("STRAVA_SCOPES", "").strip() or str(integrations.get("strava_scopes") or saved.get("scopes") or "").strip() or STRAVA_SCOPES,
    }


def _strava_storage_keys_found(settings: dict[str, Any]) -> list[str]:
    integrations = _integrations(settings)
    metadata = _metadata(settings)
    tokens = metadata.get("strava_tokens") if isinstance(metadata.get("strava_tokens"), dict) else {}
    keys = [
        key
        for key in (
            "strava_access_token",
            "strava_refresh_token",
            "strava_expires_at",
            "strava_athlete_id",
            "strava_connected_at",
        )
        if str(integrations.get(key) or "").strip()
    ]
    keys.extend(
        f"metadata.strava_tokens.{key}"
        for key in ("access_token", "refresh_token", "expires_at", "athlete_id")
        if str(tokens.get(key) or "").strip()
    )
    return sorted(dict.fromkeys(keys))


def _strava_sync(settings: dict[str, Any]) -> dict[str, Any]:
    sync = _metadata(settings).get("strava_sync")
    return sync if isinstance(sync, dict) else {}


def _strava_credentials(settings: dict[str, Any] | None = None) -> tuple[str, str]:
    current = settings if isinstance(settings, dict) else _settings_document()
    client_id = _env_or_saved(current, "STRAVA_CLIENT_ID", "strava_client_id")
    client_secret = _env_or_saved(current, "STRAVA_CLIENT_SECRET", "strava_client_secret")
    return client_id, client_secret


def _strava_status(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tokens = _strava_tokens(settings)
    sync = _strava_sync(settings)
    client_id, client_secret = _strava_credentials(settings)
    access_token_present = bool(tokens.get("access_token"))
    refresh_token_present = bool(tokens.get("refresh_token"))
    connected = refresh_token_present
    expires_at = int(tokens.get("expires_at") or 0)
    access_expired = bool(access_token_present and expires_at and expires_at <= int(time.time()))
    needs_reconnect = bool(sync.get("needs_reconnect"))
    if not (client_id and client_secret):
        status = "Not configured"
    elif needs_reconnect:
        status = "Reconnect required"
    elif connected:
        status = "Connected"
    elif client_id and client_secret:
        status = "Disconnected"
    else:
        status = "Not configured"
    if needs_reconnect:
        token_status = "reconnect_required"
    elif refresh_token_present and access_expired:
        token_status = "access_expired_refresh_available"
    elif refresh_token_present and access_token_present:
        token_status = "valid"
    elif refresh_token_present:
        token_status = "refresh_available"
    else:
        token_status = "missing"
    return status, {
        "connected": connected and not needs_reconnect,
        "access_token_present": access_token_present,
        "refresh_token_present": refresh_token_present,
        "athlete_id": str(tokens.get("athlete_id") or ""),
        "expires_at": expires_at or None,
        "token_status": token_status,
        "scopes": str(tokens.get("scopes") or ""),
        "last_imported_count": sync.get("last_imported_count", 0),
        "last_updated_count": sync.get("last_updated_count", 0),
        "last_fetched_count": sync.get("last_fetched_count", 0),
        "latest_activity_date": sync.get("latest_activity_date", ""),
        "last_error": sync.get("last_error", ""),
        "last_synced_at": sync.get("last_synced_at", ""),
        "needs_reconnect": needs_reconnect,
    }


def _withings_credentials() -> tuple[str, str]:
    settings = _settings_document()
    integrations = settings.get("integrations") if isinstance(settings.get("integrations"), dict) else {}
    client_id = os.getenv("WITHINGS_CLIENT_ID", "").strip() or str(integrations.get("withings_client_id") or "").strip()
    client_secret = os.getenv("WITHINGS_CLIENT_SECRET", "").strip() or str(integrations.get("withings_client_secret") or "").strip()
    return client_id, client_secret


def _google_health_redirect_uri(request: Request) -> str:
    from src.integrations.google_health_client import redirect_uri

    configured = redirect_uri(_settings_document())
    if configured:
        return configured
    frontend_origin = (
        os.getenv("NEXT_PUBLIC_APP_URL", "").strip().rstrip("/")
        or os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    )
    vercel_url = os.getenv("VERCEL_URL", "").strip().rstrip("/")
    if not frontend_origin and vercel_url:
        frontend_origin = f"https://{vercel_url}"
    if frontend_origin:
        return f"{frontend_origin}/api/google-health/callback"
    if _production_like():
        return GOOGLE_HEALTH_EXPECTED_CALLBACK_URL
    return str(request.url_for("google_health_callback"))


def _google_health_credentials(settings: dict[str, Any] | None = None) -> tuple[str, str]:
    from src.integrations.google_health_client import client_credentials

    return client_credentials(settings if isinstance(settings, dict) else _settings_document())


def _google_health_status(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from src.integrations.google_health_client import client_credentials, redirect_uri, saved_token_state, scopes

    client_id, client_secret = client_credentials(settings)
    redirect_configured = bool(redirect_uri(settings))
    tokens, sync = saved_token_state(settings)
    refresh_token_present = bool(tokens.get("refresh_token"))
    access_token_present = bool(tokens.get("access_token"))
    needs_reconnect = bool(sync.get("needs_reconnect"))
    configured = bool(client_id and client_secret and redirect_configured)
    if not configured:
        status = "Not configured"
    elif needs_reconnect:
        status = "Reconnect required"
    elif refresh_token_present:
        status = "Connected"
    else:
        status = "Disconnected"
    try:
        expires_at = int(tokens.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    return status, {
        "connected": status == "Connected",
        "configured": configured,
        "access_token_present": access_token_present,
        "refresh_token_present": refresh_token_present,
        "token_status": "reconnect_required" if needs_reconnect else "valid" if refresh_token_present else "missing",
        "expires_at": expires_at or None,
        "scopes": str((tokens.get("scopes") or " ".join(scopes())) if configured else ""),
        "required_env_vars": ["GOOGLE_HEALTH_CLIENT_ID", "GOOGLE_HEALTH_CLIENT_SECRET", "GOOGLE_HEALTH_REDIRECT_URI"],
        "missing_env_vars": [
            name
            for name, ready in [
                ("GOOGLE_HEALTH_CLIENT_ID", bool(client_id)),
                ("GOOGLE_HEALTH_CLIENT_SECRET", bool(client_secret)),
                ("GOOGLE_HEALTH_REDIRECT_URI", redirect_configured),
            ]
            if not ready
        ],
        "last_synced_at": sync.get("last_synced_at", ""),
        "latest_record": sync.get("latest_record", ""),
        "last_error": sync.get("last_error", ""),
        "last_warning": sync.get("last_warning", ""),
        "last_status": sync.get("last_status", ""),
        "last_message": sync.get("last_message", ""),
        "last_warning_count": sync.get("last_warning_count", 0),
        "last_storage_error_count": sync.get("last_storage_error_count", 0),
        "last_imported_count": sync.get("last_imported_count", 0),
        "rows_saved": sync.get("rows_saved", sync.get("last_imported_count", 0)),
        "rows_saved_by_table": sync.get("rows_saved_by_table", {}),
        "sample_latest_normalized_row": sync.get("sample_latest_normalized_row", {}),
        "fields_populated_count": sync.get("fields_populated_count", 0),
        "fields_missing_count": sync.get("fields_missing_count", 0),
        "last_fetched_count": sync.get("last_fetched_count", 0),
        "optional_metric_warnings": sync.get("optional_metric_warnings", []),
        "required_metric_failures": sync.get("required_metric_failures", []),
        "data_sources": sync.get("data_sources", {}),
        "needs_reconnect": needs_reconnect,
    }


FITBIT_EXPECTED_SCOPES = {"activity", "heartrate", "sleep", "profile"}
FITBIT_FRESH_HOURS = 12
FITBIT_STALE_HOURS = 24


def _fitbit_text(value: Any) -> str:
    try:
        if value is None or pd_is_na(value):
            return ""
    except Exception:
        if value is None:
            return ""
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "nat"} else text


def _fitbit_credentials(settings: dict[str, Any] | None = None) -> tuple[str, str]:
    current = settings if isinstance(settings, dict) else _settings_document()
    client_id = _env_or_saved(current, "FITBIT_CLIENT_ID", "fitbit_client_id")
    client_secret = _env_or_saved(current, "FITBIT_CLIENT_SECRET", "fitbit_client_secret")
    return client_id, client_secret


def _fitbit_redirect_uri(request: Request) -> str:
    from src.integrations.fitbit_client import redirect_uri

    return redirect_uri(_settings_document(), fallback=str(request.url_for("fitbit_callback")))


def _fitbit_sync(settings: dict[str, Any]) -> dict[str, Any]:
    sync = _metadata(settings).get("fitbit_sync")
    return sync if isinstance(sync, dict) else {}


def _fitbit_tokens(settings: dict[str, Any]) -> dict[str, Any]:
    metadata = _metadata(settings)
    integrations = _integrations(settings)
    saved = metadata.get("fitbit_tokens") if isinstance(metadata.get("fitbit_tokens"), dict) else {}
    try:
        expires_at = int(
            os.getenv("FITBIT_EXPIRES_AT", "").strip()
            or os.getenv("FITBIT_TOKEN_EXPIRES_AT", "").strip()
            or integrations.get("fitbit_expires_at")
            or saved.get("expires_at")
            or 0
        )
    except (TypeError, ValueError):
        expires_at = 0
    scopes = (
        os.getenv("FITBIT_SCOPES", "").strip()
        or _fitbit_text(integrations.get("fitbit_scopes"))
        or _fitbit_text(saved.get("scopes"))
    )
    return {
        "access_token": os.getenv("FITBIT_ACCESS_TOKEN", "").strip() or _fitbit_text(integrations.get("fitbit_access_token") or saved.get("access_token")),
        "refresh_token": os.getenv("FITBIT_REFRESH_TOKEN", "").strip() or _fitbit_text(integrations.get("fitbit_refresh_token") or saved.get("refresh_token")),
        "expires_at": expires_at or None,
        "scopes": scopes,
        "user_id": os.getenv("FITBIT_USER_ID", "").strip() or _fitbit_text(integrations.get("fitbit_user_id") or saved.get("user_id")),
        "token_type": _fitbit_text(saved.get("token_type")) or "Bearer",
    }


def _fitbit_scope_parts(scopes: str) -> list[str]:
    return sorted({part.strip() for part in scopes.replace(",", " ").split() if part.strip()})


def _fitbit_status(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    client_id, client_secret = _fitbit_credentials(settings)
    redirect_configured = bool(_env_or_saved(settings, "FITBIT_REDIRECT_URI", "fitbit_redirect_uri"))
    tokens = _fitbit_tokens(settings)
    sync = _fitbit_sync(settings)
    configured = bool(client_id and client_secret and redirect_configured)
    access_token_present = bool(tokens.get("access_token"))
    refresh_token_present = bool(tokens.get("refresh_token"))
    scopes = _fitbit_scope_parts(str(tokens.get("scopes") or ""))
    missing_scopes = sorted(FITBIT_EXPECTED_SCOPES.difference(scopes)) if scopes else sorted(FITBIT_EXPECTED_SCOPES)
    expires_at = int(tokens.get("expires_at") or 0)
    access_expired = bool(access_token_present and expires_at and expires_at <= int(time.time()))
    needs_reconnect = bool(sync.get("needs_reconnect"))
    if not configured:
        status = "Not configured"
    elif needs_reconnect:
        status = "Reconnect required"
    elif access_token_present or refresh_token_present:
        status = "Connected"
    elif configured:
        status = "Disconnected"
    else:
        status = "Not configured"
    if needs_reconnect:
        token_status = "reconnect_required"
    elif access_token_present and access_expired and refresh_token_present:
        token_status = "access_expired_refresh_available"
    elif access_token_present and not access_expired:
        token_status = "valid"
    elif refresh_token_present:
        token_status = "refresh_available"
    else:
        token_status = "missing"
    return status, {
        "configured": configured,
        "connected": status == "Connected",
        "access_token_present": access_token_present,
        "refresh_token_present": refresh_token_present,
        "expires_at": expires_at or None,
        "token_status": token_status,
        "scopes": " ".join(scopes),
        "granted_scopes": scopes,
        "missing_scopes": missing_scopes,
        "required_env_vars": ["FITBIT_CLIENT_ID", "FITBIT_CLIENT_SECRET", "FITBIT_REDIRECT_URI"],
        "missing_env_vars": [
            name
            for name, ready in [
                ("FITBIT_CLIENT_ID", bool(client_id)),
                ("FITBIT_CLIENT_SECRET", bool(client_secret)),
                ("FITBIT_REDIRECT_URI", redirect_configured),
            ]
            if not ready
        ],
        "user_id": str(tokens.get("user_id") or ""),
        "last_successful_sync": sync.get("last_successful_sync", ""),
        "last_synced_at": sync.get("last_successful_sync", "") or sync.get("last_synced_at", ""),
        "last_attempt_at": sync.get("last_attempt_at", ""),
        "last_status": sync.get("last_status", ""),
        "last_message": sync.get("last_message", ""),
        "last_error": sync.get("last_error", ""),
        "last_fetched_count": sync.get("last_fetched_count", 0),
        "last_parsed_count": sync.get("last_parsed_count", 0),
        "last_stored_count": sync.get("last_stored_count", 0),
        "latest_record": sync.get("latest_record", ""),
        "needs_reconnect": needs_reconnect,
        "last_logs": sync.get("last_logs", []) if isinstance(sync.get("last_logs"), list) else [],
        "last_pipeline": sync.get("last_pipeline", {}) if isinstance(sync.get("last_pipeline"), dict) else {},
    }


def _save_fitbit_sync_state(updates: dict[str, Any]) -> dict[str, Any]:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    current = metadata.get("fitbit_sync") if isinstance(metadata.get("fitbit_sync"), dict) else {}
    metadata["fitbit_sync"] = {**current, **updates, "updated_at": utc_now_iso()}
    settings["metadata"] = metadata
    _save_settings_document(settings)
    return metadata["fitbit_sync"]


def _save_fitbit_tokens(token_patch: dict[str, Any], *, connected_at: str = "") -> dict[str, Any]:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    previous = metadata.get("fitbit_tokens") if isinstance(metadata.get("fitbit_tokens"), dict) else {}
    tokens = {**previous, **{key: value for key, value in token_patch.items() if value not in (None, "")}}
    if not tokens.get("refresh_token") and previous.get("refresh_token"):
        tokens["refresh_token"] = previous.get("refresh_token")
    metadata["fitbit_tokens"] = tokens
    sync = metadata.get("fitbit_sync") if isinstance(metadata.get("fitbit_sync"), dict) else {}
    metadata["fitbit_sync"] = {
        **sync,
        "needs_reconnect": False,
        "last_error": "",
        "last_message": "Fitbit token state saved.",
        **({"connected_at": connected_at} if connected_at else {}),
        "updated_at": utc_now_iso(),
    }
    settings["metadata"] = metadata
    saved = _save_settings_document(settings)
    logger.info("[fitbit] token state saved access_present=%s refresh_present=%s user_id_present=%s", bool(tokens.get("access_token")), bool(tokens.get("refresh_token")), bool(tokens.get("user_id")))
    return saved


def _clear_fitbit_connection(*, mark_error: bool = False, reason: str = "") -> None:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    integrations = settings.get("integrations") if isinstance(settings.get("integrations"), dict) else {}
    integrations.update(
        {
            "fitbit_access_token": "",
            "fitbit_refresh_token": "",
            "fitbit_expires_at": 0,
            "fitbit_scopes": "",
            "fitbit_user_id": "",
        }
    )
    metadata["fitbit_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "token_type": "",
        "scopes": "",
        "user_id": "",
    }
    metadata["fitbit_sync"] = {
        **(metadata.get("fitbit_sync") if isinstance(metadata.get("fitbit_sync"), dict) else {}),
        "needs_reconnect": bool(mark_error),
        "last_error": reason if mark_error else "",
        "last_message": reason,
        "disconnected_at": utc_now_iso(),
    }
    settings["integrations"] = integrations
    settings["metadata"] = metadata
    _save_settings_document(settings)
    logger.info("[fitbit] connection cleared mark_error=%s reason_present=%s", mark_error, bool(reason))


def _fitbit_access_token(settings: dict[str, Any] | None = None) -> str:
    from src.integrations.fitbit_client import refresh_access_token

    current = settings if isinstance(settings, dict) else _settings_document()
    tokens = _fitbit_tokens(current)
    access_token = _fitbit_text(tokens.get("access_token"))
    refresh_token = _fitbit_text(tokens.get("refresh_token"))
    try:
        expires_at = int(tokens.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if not access_token and not refresh_token:
        raise RuntimeError("No Fitbit access token is available. Connect Fitbit OAuth before force sync can fetch live data.")
    if access_token and expires_at > int(time.time()) + 120:
        return access_token
    if not refresh_token:
        message = "Fitbit access token expired and no refresh token is available. Reconnect Fitbit."
        _save_fitbit_sync_state({"needs_reconnect": True, "last_status": "error", "last_message": message, "last_error": message, "last_synced_at": utc_now_iso()})
        raise RuntimeError(message)
    logger.info("[fitbit] refreshing access token")
    refreshed = refresh_access_token(refresh_token, current)
    if refreshed.get("status") != "ok" or not refreshed.get("tokens", {}).get("access_token"):
        message = str(refreshed.get("message") or "Fitbit token refresh failed.")
        logger.warning("[fitbit] token refresh failed: %s", message[:500])
        _save_fitbit_sync_state({"needs_reconnect": True, "last_status": "error", "last_message": message, "last_error": message, "last_synced_at": utc_now_iso()})
        raise RuntimeError(message)
    _save_fitbit_tokens(refreshed["tokens"])
    logger.info("[fitbit] token refresh succeeded")
    return str(refreshed["tokens"]["access_token"])


def _fitbit_value(raw: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _fitbit_json_value(value: Any) -> Any:
    try:
        if value is None or pd_is_na(value):
            return None
    except Exception:
        if value is None:
            return None
    return value


FITBIT_WEARABLE_VALUE_FIELDS = {
    "sleep_hours",
    "sleep_score",
    "total_sleep_minutes",
    "rem_sleep_minutes",
    "deep_sleep_minutes",
    "light_sleep_minutes",
    "awake_minutes",
    "sleep_efficiency",
    "resting_hr",
    "hrv",
    "average_hr",
    "max_hr",
    "workout_average_hr",
    "workout_max_hr",
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "distance_miles",
    "calories_burned",
    "total_calories_burned",
    "active_calories_burned",
    "basal_calories_burned",
    "workout_minutes",
    "cardio_load",
    "breathing_rate",
    "spo2",
    "skin_temperature",
    "body_temperature",
}


def _fitbit_latest_values() -> tuple[dict[str, Any], dict[str, Any] | None]:
    ensure_jsonb_table("wearable_metrics")
    rows = fetch_json_rows("wearable_metrics", limit=500, date_field="date")
    if rows and isinstance(rows[0], dict) and "_db_error" in rows[0]:
        return {
            "storage_error": rows[0].get("_db_error"),
            "sleep_duration": {"label": "Sleep duration", "value": "Storage error", "raw": None, "status": "failed"},
            "rem_sleep": {"label": "REM sleep", "value": "Storage error", "raw": None, "status": "failed"},
            "deep_sleep": {"label": "Deep sleep", "value": "Storage error", "raw": None, "status": "failed"},
            "light_sleep": {"label": "Light sleep", "value": "Storage error", "raw": None, "status": "failed"},
            "resting_hr": {"label": "Resting HR", "value": "Storage error", "raw": None, "status": "failed"},
            "workout_hr": {"label": "Workout HR", "value": "Storage error", "raw": None, "status": "failed"},
            "calories_burned": {"label": "Calories burned", "value": "Storage error", "raw": None, "status": "failed"},
            "steps": {"label": "Steps", "value": "Storage error", "raw": None, "status": "failed"},
            "readiness": {"label": "Readiness / recovery", "value": "Storage error", "raw": None, "status": "failed"},
        }, None
    fitbit_rows = [row for row in rows if _fitbit_text(row.get("source")).lower() == "fitbit"]
    latest = fitbit_rows[0] if fitbit_rows else None

    def metric(label: str, value: Any, suffix: str = "", *, digits: int = 0) -> dict[str, Any]:
        if value in (None, ""):
            return {"label": label, "value": "No Fitbit value", "raw": None, "status": "missing"}
        try:
            parsed = float(value)
            display = f"{parsed:.{digits}f}" if digits else f"{round(parsed):,}"
            return {"label": label, "value": f"{display}{suffix}", "raw": parsed, "status": "ok"}
        except (TypeError, ValueError):
            return {"label": label, "value": str(value), "raw": value, "status": "ok"}

    if not latest:
        empty = {key: {"label": label, "value": "No Fitbit value", "raw": None, "status": "missing"} for key, label in {
            "sleep_duration": "Sleep duration",
            "rem_sleep": "REM sleep",
            "deep_sleep": "Deep sleep",
            "light_sleep": "Light sleep",
            "resting_hr": "Resting HR",
            "workout_hr": "Workout HR",
            "calories_burned": "Calories burned",
            "steps": "Steps",
            "readiness": "Readiness / recovery",
        }.items()}
        return empty, None

    return {
        "date": {"label": "Latest Fitbit date", "value": _fitbit_text(latest.get("date")) or "Unknown", "raw": latest.get("date"), "status": "ok" if latest.get("date") else "missing"},
        "sleep_duration": metric("Sleep duration", _fitbit_value(latest, "total_sleep_minutes"), " min"),
        "rem_sleep": metric("REM sleep", _fitbit_value(latest, "rem_sleep_minutes"), " min"),
        "deep_sleep": metric("Deep sleep", _fitbit_value(latest, "deep_sleep_minutes"), " min"),
        "light_sleep": metric("Light sleep", _fitbit_value(latest, "light_sleep_minutes"), " min"),
        "resting_hr": metric("Resting HR", _fitbit_value(latest, "resting_hr"), " bpm"),
        "workout_hr": metric("Workout HR", _fitbit_value(latest, "workout_average_hr", "average_hr"), " bpm"),
        "calories_burned": metric("Calories burned", _fitbit_value(latest, "total_calories_burned", "calories_burned"), " kcal"),
        "steps": metric("Steps", _fitbit_value(latest, "steps")),
        "readiness": metric("Readiness / recovery", _fitbit_value(latest, "sleep_score", "hrv"), "", digits=1),
    }, latest


def _fitbit_parse_iso(value: str) -> datetime | None:
    text = _fitbit_text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fitbit_freshness(sync: dict[str, Any], latest_row: dict[str, Any] | None) -> dict[str, Any]:
    last_success = _fitbit_text(sync.get("last_successful_sync") or sync.get("last_synced_at"))
    latest_updated = _fitbit_text((latest_row or {}).get("updated_at") or (latest_row or {}).get("created_at"))
    basis = last_success or latest_updated
    last_status = _fitbit_text(sync.get("last_status")).lower()
    if last_status == "error":
        status = "red"
        label = "Failed"
    elif not basis:
        status = "red"
        label = "No Fitbit data"
    else:
        parsed = _fitbit_parse_iso(basis)
        age_hours = None if parsed is None else round((datetime.now(timezone.utc) - parsed).total_seconds() / 3600, 1)
        if age_hours is None:
            status = "yellow"
            label = "Unknown age"
        elif age_hours <= FITBIT_FRESH_HOURS:
            status = "green"
            label = "Recent"
        elif age_hours <= FITBIT_STALE_HOURS:
            status = "yellow"
            label = "Stale"
        else:
            status = "red"
            label = "Old"
        return {
            "status": status,
            "label": label,
            "last_successful_sync": last_success,
            "latest_stored_at": latest_updated,
            "age_hours": age_hours,
            "stale": bool(age_hours is not None and age_hours > FITBIT_FRESH_HOURS),
            "stale_message": f"Last sync older than {FITBIT_FRESH_HOURS} hours." if age_hours is not None and age_hours > FITBIT_FRESH_HOURS else "",
        }
    return {
        "status": status,
        "label": label,
        "last_successful_sync": last_success,
        "latest_stored_at": latest_updated,
        "age_hours": None,
        "stale": True,
        "stale_message": f"Last sync older than {FITBIT_FRESH_HOURS} hours." if basis else "No successful Fitbit sync has been recorded.",
    }


def _fitbit_pipeline(sync: dict[str, Any], latest_row: dict[str, Any] | None) -> dict[str, Any]:
    pipeline = sync.get("last_pipeline") if isinstance(sync.get("last_pipeline"), dict) else {}
    if pipeline:
        return pipeline
    row_found = bool(latest_row)
    return {
        "fetched": {"status": "not_run", "message": "Force Fitbit Sync has not fetched live data in this environment."},
        "parsed": {"status": "not_run", "message": "No Fitbit sync parse has been recorded."},
        "stored": {"status": "ok" if row_found else "missing", "message": "Latest Fitbit row found in wearable storage." if row_found else "No Fitbit rows found in wearable storage."},
    }


def _fitbit_debug_payload(*, message: str = "") -> dict[str, Any]:
    settings = _settings_document()
    status, meta = _fitbit_status(settings)
    latest_values, latest_row = _fitbit_latest_values()
    sync = _fitbit_sync(settings)
    freshness = _fitbit_freshness(sync, latest_row)
    pipeline = _fitbit_pipeline(sync, latest_row)
    return {
        "status": "ok" if freshness.get("status") != "red" else "warning",
        "provider": "fitbit",
        "checked_at": utc_now_iso(),
        "message": message or "Fitbit debug status loaded.",
        "connection_status": status,
        "configured": bool(meta.get("configured")),
        "connected": bool(meta.get("connected")),
        "oauth": {
            "token_status": meta.get("token_status", "missing"),
            "access_token_present": bool(meta.get("access_token_present")),
            "refresh_token_present": bool(meta.get("refresh_token_present")),
            "expires_at": meta.get("expires_at"),
            "granted_scopes": meta.get("granted_scopes", []),
            "missing_scopes": meta.get("missing_scopes", []),
        },
        "sync": {
            "last_successful_sync": meta.get("last_successful_sync", ""),
            "last_attempt_at": meta.get("last_attempt_at", ""),
            "last_status": meta.get("last_status", ""),
            "last_error": meta.get("last_error", ""),
            "last_message": meta.get("last_message", ""),
            "last_fetched_count": meta.get("last_fetched_count", 0),
            "last_parsed_count": meta.get("last_parsed_count", 0),
            "last_stored_count": meta.get("last_stored_count", 0),
            "latest_record": meta.get("latest_record", "") or _fitbit_text((latest_row or {}).get("date")),
        },
        "data_freshness": freshness,
        "latest_values": latest_values,
        "pipeline": pipeline,
        "logs": list(meta.get("last_logs") or []),
    }


def _save_google_health_connection_record(status: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if not status or metadata is None:
        status, metadata = _google_health_status(_settings_document())
    now = utc_now_iso()
    payload = {
        "connection_id": "primary",
        "provider": "google_health",
        "status": status,
        "connected": bool(metadata.get("connected")),
        "configured": bool(metadata.get("configured")),
        "access_token_present": bool(metadata.get("access_token_present")),
        "refresh_token_present": bool(metadata.get("refresh_token_present")),
        "token_status": metadata.get("token_status", "missing"),
        "scopes": metadata.get("scopes", ""),
        "last_synced_at": metadata.get("last_synced_at", ""),
        "latest_record": metadata.get("latest_record", ""),
        "last_error": metadata.get("last_error", ""),
        "updated_at": now,
    }
    if metadata.get("connected") and not payload.get("connected_at"):
        payload["connected_at"] = now
    return upsert_json_row("google_health_connections", "connection_id", "primary", payload)


def _google_health_env_value(name: str) -> str:
    return os.getenv(name, "")


def _google_health_env_state(settings: dict[str, Any]) -> dict[str, Any]:
    integrations = _integrations(settings)

    def state(name: str, field: str = "") -> dict[str, Any]:
        raw_env = _google_health_env_value(name)
        saved = str(integrations.get(field) or "") if field else ""
        raw = raw_env if raw_env else saved
        stripped = raw.strip()
        return {
            "present": bool(stripped),
            "source": "env" if raw_env.strip() else "saved_settings" if saved.strip() else "missing",
            "length": len(stripped),
            "has_surrounding_whitespace": bool(raw and raw != stripped),
            "has_leading_equals": stripped.startswith("="),
        }

    return {
        "GOOGLE_HEALTH_CLIENT_ID": state("GOOGLE_HEALTH_CLIENT_ID", "google_health_client_id"),
        "GOOGLE_HEALTH_CLIENT_SECRET": state("GOOGLE_HEALTH_CLIENT_SECRET", "google_health_client_secret"),
        "GOOGLE_HEALTH_REDIRECT_URI": state("GOOGLE_HEALTH_REDIRECT_URI", "google_health_redirect_uri"),
        "GOOGLE_HEALTH_SCOPES": state("GOOGLE_HEALTH_SCOPES"),
        "GOOGLE_HEALTH_API_BASE_URL": state("GOOGLE_HEALTH_API_BASE_URL"),
    }


def _google_health_sanitize_auth_url(auth_url: str) -> str:
    if not auth_url:
        return ""
    parsed = urlparse(auth_url)
    sanitized_query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key == "client_id":
            sanitized_query.append((key, _secret_preview(value)))
        elif key == "scope":
            sanitized_query.append((key, value))
        elif key == "redirect_uri":
            sanitized_query.append((key, value))
        else:
            sanitized_query.append((key, value))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(sanitized_query), parsed.fragment))


def _google_health_debug_payload(request: Request) -> dict[str, Any]:
    from src.integrations.google_health_client import get_auth_url, scopes

    settings = _settings_document()
    client_id, client_secret = _google_health_credentials(settings)
    redirect_uri = _google_health_redirect_uri(request)
    status, metadata = _google_health_status(settings)
    env_state = _google_health_env_state(settings)
    result = get_auth_url(settings, redirect_uri=redirect_uri, state="debug")
    client_id_stripped = str(client_id or "").strip()
    likely_issues: list[str] = []
    if not client_id_stripped:
        likely_issues.append("GOOGLE_HEALTH_CLIENT_ID is missing in the runtime generating the OAuth URL.")
    elif not client_id_stripped.endswith(".apps.googleusercontent.com"):
        likely_issues.append("GOOGLE_HEALTH_CLIENT_ID does not look like a Google OAuth web client ID.")
    if not str(client_secret or "").strip():
        likely_issues.append("GOOGLE_HEALTH_CLIENT_SECRET is missing in the runtime exchanging the OAuth code.")
    if redirect_uri != GOOGLE_HEALTH_EXPECTED_CALLBACK_URL:
        likely_issues.append("Effective redirect URI does not match the requested Vercel callback URL.")
    if env_state["GOOGLE_HEALTH_CLIENT_ID"]["has_surrounding_whitespace"]:
        likely_issues.append("GOOGLE_HEALTH_CLIENT_ID has surrounding whitespace/newlines in the runtime env.")
    if env_state["GOOGLE_HEALTH_CLIENT_SECRET"]["has_surrounding_whitespace"]:
        likely_issues.append("GOOGLE_HEALTH_CLIENT_SECRET has surrounding whitespace/newlines in the runtime env.")
    if env_state["GOOGLE_HEALTH_CLIENT_ID"]["has_leading_equals"]:
        likely_issues.append("GOOGLE_HEALTH_CLIENT_ID has a leading '=' in the runtime env. The backend normalizes it defensively, but the deployed env var should be fixed.")
    if env_state["GOOGLE_HEALTH_CLIENT_SECRET"]["has_leading_equals"]:
        likely_issues.append("GOOGLE_HEALTH_CLIENT_SECRET has a leading '=' in the runtime env. The backend normalizes it defensively, but the deployed env var should be fixed.")
    return {
        "status": "ok" if result.get("status") == "ok" and not likely_issues else "warning",
        "provider": "google_health",
        "checked_at": utc_now_iso(),
        "runtime": _runtime_service(),
        "request_host": request.url.hostname,
        "backend_callback_url": str(request.url_for("google_health_callback")),
        "expected_callback_url": GOOGLE_HEALTH_EXPECTED_CALLBACK_URL,
        "effective_redirect_uri": redirect_uri,
        "redirect_matches_expected": redirect_uri == GOOGLE_HEALTH_EXPECTED_CALLBACK_URL,
        "env": env_state,
        "client_id": {
            "present": bool(client_id_stripped),
            "preview": _secret_preview(client_id_stripped),
            "length": len(client_id_stripped),
            "looks_like_google_oauth_client": client_id_stripped.endswith(".apps.googleusercontent.com"),
        },
        "client_secret": {"present": bool(str(client_secret or "").strip())},
        "oauth_provider": {
            "authorize_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
            "status": result.get("status"),
            "message": result.get("message", ""),
            "generated_authorize_url_preview": _google_health_sanitize_auth_url(str(result.get("auth_url") or "")),
            "scope_count": len(scopes()),
        },
        "token_config": {
            "connection_status": status,
            "configured": bool(metadata.get("configured")),
            "token_status": metadata.get("token_status", "missing"),
            "access_token_present": bool(metadata.get("access_token_present")),
            "refresh_token_present": bool(metadata.get("refresh_token_present")),
            "last_error": metadata.get("last_error", ""),
            "needs_reconnect": bool(metadata.get("needs_reconnect")),
        },
        "frontend_backend_wiring": {
            "vercel_callback_route": "/api/google-health/callback redirects to BACKEND_API_URL /api/google-health/callback",
            "backend_proxy_default": os.getenv("BACKEND_API_URL", "").strip() or os.getenv("NEXT_PUBLIC_API_URL", "").strip() or "",
            "frontend_origin": os.getenv("NEXT_PUBLIC_APP_URL", "").strip() or os.getenv("FRONTEND_ORIGIN", "").strip() or "",
        },
        "likely_issues": likely_issues,
        "checklist": [
            "Google Cloud OAuth client type must be Web application.",
            "Authorized redirect URI must exactly match effective_redirect_uri.",
            "GOOGLE_HEALTH_CLIENT_ID and GOOGLE_HEALTH_CLIENT_SECRET must be set on the service that handles /api/google-health/connect and /api/google-health/callback.",
            "Redeploy the backend after changing Railway/Render env vars, and redeploy Vercel if the callback/proxy env changed.",
        ],
    }


def _withings_status(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    metadata = _metadata(settings)
    tokens = metadata.get("withings_tokens") if isinstance(metadata.get("withings_tokens"), dict) else {}
    sync = metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}
    client_id, client_secret = _withings_credentials()
    connected = bool(tokens.get("access_token") and tokens.get("refresh_token"))
    if sync.get("needs_reconnect"):
        status = "Disconnected"
    elif connected:
        status = "Connected"
    elif client_id and client_secret:
        status = "Ready to connect"
    else:
        status = "Not configured"
    return status, {
        "connected": connected and not bool(sync.get("needs_reconnect")),
        "userid": str(tokens.get("userid") or ""),
        "token_status": "valid" if connected else "missing",
        "scopes": str(tokens.get("scopes") or WITHINGS_SCOPES if connected else ""),
        "last_imported_count": sync.get("last_imported_count", 0),
        "last_updated_count": sync.get("last_updated_count", 0),
        "last_fetched_count": sync.get("last_fetched_groups", 0),
        "latest_measurement_date": sync.get("latest_measurement_date") or sync.get("latest_measure_date") or "",
        "last_error": sync.get("last_error", ""),
        "last_synced_at": sync.get("last_synced_at", ""),
        "needs_reconnect": bool(sync.get("needs_reconnect")),
    }


def _status_color(status: str) -> str:
    return "green" if status == "Connected" else "yellow" if status in {"Disconnected", "Reconnect required", "Expired/Reauth required"} else "gray"


def _status_slug(status: str) -> str:
    return status.lower().replace("/", "_").replace(" ", "_").replace("__", "_")


def _health_card(provider: str, title: str, status: str, metadata: dict[str, Any]) -> dict[str, Any]:
    connected = status == "Connected"
    action = f"{provider}_sync" if connected else f"{provider}_reconnect" if status in {"Reconnect required", "Expired/Reauth required"} else f"{provider}_connect"
    return {
        "id": provider,
        "title": title,
        "status": "connected" if connected else "warning" if status in {"Disconnected", "Reconnect required", "Expired/Reauth required"} else "error",
        "label": status,
        "detail": f"{title} is {status.lower()}.",
        "last_synced_at": metadata.get("last_synced_at", ""),
        "action": action,
        "metadata": metadata,
    }


def _integration_payload(*, external_checks: bool = False) -> dict[str, Any]:
    settings = _settings_document()
    base = settings_payload()
    strava_status, strava_meta = _strava_status(settings)
    withings_status, withings_meta = _withings_status(settings)
    google_health_status, google_health_meta = _google_health_status(settings)
    fitbit_status, fitbit_meta = _fitbit_status(settings)
    try:
        from src.ai.food_parser import openai_analyzer_config

        openai_config = openai_analyzer_config()
    except Exception:
        openai_config = {"openai_key_configured": bool(os.getenv("OPENAI_API_KEY", "").strip() or _integrations(settings).get("openai_api_key")), "model": "", "api_key_source": "unknown"}
    openai_configured = bool(openai_config.get("openai_key_configured"))
    openai_service = (base.get("services", {}) if isinstance(base.get("services"), dict) else {}).get("openai", {})
    openai_label = str(openai_service.get("label") or ("Configured" if openai_configured else "Missing"))
    openai_status = str(openai_service.get("status") or ("configured" if openai_configured else "missing_api_key"))
    hevy_configured = bool(os.getenv("HEVY_API_KEY", "").strip() or _integrations(settings).get("hevy_api_key"))
    db = ping()
    database_ok = db.get("status") == "ok"
    base.update(
        {
            "overall_status": "ok" if database_ok else "degraded",
            "checked_at": utc_now_iso(),
            "external_checks": external_checks,
            "backend": _component(configured=True, status="green", message="Backend is reachable.", required_env_vars=[]),
            "database": _component(
                configured=database_ok,
                status="green" if database_ok else "yellow",
                message="Postgres is reachable." if database_ok else "Postgres is not configured or did not respond.",
                required_env_vars=["DATABASE_URL"],
                details={"storage": db.get("storage"), "duration_ms": db.get("duration_ms")},
            ),
            "frontend": _component(configured=True, status="green", message="Frontend proxy can consume this backend response.", required_env_vars=[]),
            "openai": _component(
                configured=openai_configured,
                status="green" if openai_status == "connected" else "yellow" if openai_status == "configured" else "gray" if openai_status == "missing_api_key" else "red",
                message=str(openai_service.get("message") or ("OpenAI key is configured." if openai_configured else "OpenAI key is not configured. Manual logging still works.")),
                required_env_vars=["OPENAI_API_KEY"],
                details={key: value for key, value in openai_config.items() if key != "model_error"},
            ),
            "hevy": _component(
                configured=hevy_configured,
                status="green" if hevy_configured else "gray",
                message="Hevy key is configured. Sync remains manual." if hevy_configured else "Hevy key is not configured.",
                required_env_vars=["HEVY_API_KEY"],
            ),
            "strava": _component(
                configured=strava_status in {"Connected", "Disconnected", "Reconnect required", "Expired/Reauth required"},
                status=_status_color(strava_status),
                message=f"Strava is {strava_status.lower()}. Startup never calls Strava.",
                required_env_vars=["STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET"],
                latest_record=strava_meta.get("latest_activity_date", ""),
                last_successful_sync=strava_meta.get("last_synced_at", ""),
                reconnect_required=bool(strava_meta.get("needs_reconnect")),
                details={key: value for key, value in strava_meta.items() if key not in {"last_error"}},
            ),
            "withings": _component(
                configured=withings_status in {"Connected", "Ready to connect", "Disconnected"},
                status=_status_color(withings_status),
                message=f"Withings is {withings_status.lower()}. Startup never calls Withings.",
                required_env_vars=["WITHINGS_CLIENT_ID", "WITHINGS_CLIENT_SECRET"],
                latest_record=withings_meta.get("latest_measurement_date", ""),
                last_successful_sync=withings_meta.get("last_synced_at", ""),
                reconnect_required=bool(withings_meta.get("needs_reconnect")),
                details={key: value for key, value in withings_meta.items() if key not in {"last_error"}},
            ),
            "google_health": _component(
                configured=google_health_status in {"Connected", "Disconnected", "Reconnect required"},
                status=_status_color(google_health_status),
                message=f"Google Health is {google_health_status.lower()}. Sync runs only when requested.",
                required_env_vars=["GOOGLE_HEALTH_CLIENT_ID", "GOOGLE_HEALTH_CLIENT_SECRET", "GOOGLE_HEALTH_REDIRECT_URI"],
                latest_record=google_health_meta.get("latest_record", ""),
                last_successful_sync=google_health_meta.get("last_synced_at", ""),
                reconnect_required=bool(google_health_meta.get("needs_reconnect")),
                details={key: value for key, value in google_health_meta.items() if key not in {"last_error"}},
            ),
            "fitbit": _component(
                configured=fitbit_status in {"Connected", "Disconnected", "Reconnect required"},
                status=_status_color(fitbit_status),
                message=f"Fitbit is {fitbit_status.lower()}. Sync runs only when requested.",
                required_env_vars=["FITBIT_CLIENT_ID", "FITBIT_CLIENT_SECRET", "FITBIT_REDIRECT_URI"],
                latest_record=fitbit_meta.get("latest_record", ""),
                last_successful_sync=fitbit_meta.get("last_successful_sync", ""),
                reconnect_required=bool(fitbit_meta.get("needs_reconnect")),
                details={key: value for key, value in fitbit_meta.items() if key not in {"last_error"}},
            ),
            "required_user_actions": [],
            "other_integrations": {},
        }
    )
    base["statuses"] = {
        **base.get("statuses", {}),
        "strava": strava_status,
        "withings": withings_status,
        "google_health": google_health_status,
        "fitbit": fitbit_status,
        "openai_api_key": openai_label,
        "hevy_api_key": "Configured" if hevy_configured else "Not configured",
    }
    base["services"] = {
        **base.get("services", {}),
        "openai": {**openai_service, "configured": openai_configured, "status": openai_status, "message": base["openai"]["message"], "model": openai_config.get("model", ""), "api_key_source": openai_config.get("api_key_source", "unknown")},
        "hevy": {"configured": hevy_configured, "status": "ok" if hevy_configured else "missing_api_key", "message": base["hevy"]["message"]},
        "strava": {"configured": base["strava"]["configured"], "status": "ok" if strava_status == "Connected" else _status_slug(strava_status), "message": base["strava"]["message"], "last_synced_at": strava_meta.get("last_synced_at", ""), "latest_record": strava_meta.get("latest_activity_date", ""), "reconnect_required": strava_meta.get("needs_reconnect", False), "token_status": strava_meta.get("token_status", "missing")},
        "withings": {"configured": base["withings"]["configured"], "status": "ok" if withings_status == "Connected" else withings_status.lower().replace(" ", "_"), "message": base["withings"]["message"], "last_synced_at": withings_meta.get("last_synced_at", ""), "latest_record": withings_meta.get("latest_measurement_date", ""), "reconnect_required": withings_meta.get("needs_reconnect", False)},
        "google_health": {
            "configured": base["google_health"]["configured"],
            "status": "ok" if google_health_status == "Connected" else _status_slug(google_health_status),
            "message": base["google_health"]["message"],
            "last_synced_at": google_health_meta.get("last_synced_at", ""),
            "latest_record": google_health_meta.get("latest_record", ""),
            "reconnect_required": google_health_meta.get("needs_reconnect", False),
            "token_status": google_health_meta.get("token_status", "missing"),
            "last_error": google_health_meta.get("last_error", ""),
            "last_warning": google_health_meta.get("last_warning", ""),
            "last_status": google_health_meta.get("last_status", ""),
            "last_message": google_health_meta.get("last_message", ""),
            "rows_saved": google_health_meta.get("rows_saved", google_health_meta.get("last_imported_count", 0)),
            "imported_metrics": google_health_meta.get("last_imported_count", 0),
            "fetched_days": google_health_meta.get("last_fetched_count", 0),
            "optional_metric_warnings": google_health_meta.get("optional_metric_warnings", []),
            "required_metric_failures": google_health_meta.get("required_metric_failures", []),
        },
        "fitbit": {
            "configured": base["fitbit"]["configured"],
            "status": "ok" if fitbit_status == "Connected" else _status_slug(fitbit_status),
            "message": base["fitbit"]["message"],
            "last_synced_at": fitbit_meta.get("last_successful_sync", ""),
            "latest_record": fitbit_meta.get("latest_record", ""),
            "reconnect_required": fitbit_meta.get("needs_reconnect", False),
            "token_status": fitbit_meta.get("token_status", "missing"),
            "last_error": fitbit_meta.get("last_error", ""),
            "last_status": fitbit_meta.get("last_status", ""),
            "last_message": fitbit_meta.get("last_message", ""),
        },
    }
    base["health"] = [
        _health_card("hevy", "Hevy", "Connected" if hevy_configured else "Not configured", {"connected": hevy_configured}),
        _health_card("strava", "Strava", strava_status, strava_meta),
        _health_card("withings", "Withings", withings_status, withings_meta),
        _health_card("google_health", "Google Health", google_health_status, google_health_meta),
        _health_card("fitbit", "Fitbit", fitbit_status, fitbit_meta),
        _health_card("openai", "OpenAI", openai_label, {"connected": openai_status == "connected", "configured": openai_configured}),
    ]
    base["integrations"] = {
        **base.get("integrations", {}),
        "strava_access_token": _mask_present(_strava_tokens(settings).get("access_token")),
        "strava_refresh_token": _mask_present(_strava_tokens(settings).get("refresh_token")),
        "withings_access_token": _mask_present(_metadata(settings).get("withings_tokens", {}).get("access_token") if isinstance(_metadata(settings).get("withings_tokens"), dict) else ""),
        "withings_refresh_token": _mask_present(_metadata(settings).get("withings_tokens", {}).get("refresh_token") if isinstance(_metadata(settings).get("withings_tokens"), dict) else ""),
        "google_health_access_token": _mask_present(_metadata(settings).get("google_health_tokens", {}).get("access_token") if isinstance(_metadata(settings).get("google_health_tokens"), dict) else ""),
        "google_health_refresh_token": _mask_present(_metadata(settings).get("google_health_tokens", {}).get("refresh_token") if isinstance(_metadata(settings).get("google_health_tokens"), dict) else ""),
        "fitbit_access_token": _mask_present(_fitbit_tokens(settings).get("access_token")),
        "fitbit_refresh_token": _mask_present(_fitbit_tokens(settings).get("refresh_token")),
    }
    return base


def _strava_redirect_uri(request: Request) -> str:
    configured = os.getenv("STRAVA_REDIRECT_URI", "").strip()
    if configured:
        return configured.replace("/api/Strava/callback", "/api/strava/callback")
    saved = str(_integrations(_settings_document()).get("strava_redirect_uri") or "").strip()
    if saved:
        return saved.replace("/api/Strava/callback", "/api/strava/callback")
    return str(request.url_for("strava_callback"))


def _oauth_redirect_error(provider: str, redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or ""
    if not redirect_uri:
        return f"{provider.upper()}_REDIRECT_URI is not configured and the backend could not derive a callback URL."
    if _production_like() and host in {"localhost", "127.0.0.1", "::1"}:
        return f"{provider.upper()}_REDIRECT_URI is still localhost. Set it to your deployed callback URL."
    return ""


def _clear_strava_connection(*, mark_error: bool = False, reason: str = "") -> None:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("strava_tokens") if isinstance(metadata.get("strava_tokens"), dict) else {}
    integrations = settings.get("integrations") if isinstance(settings.get("integrations"), dict) else {}
    integrations.update(
        {
            "strava_access_token": "",
            "strava_refresh_token": "",
            "strava_expires_at": 0,
            "strava_athlete_id": str(integrations.get("strava_athlete_id") or tokens.get("athlete_id") or ""),
            "strava_scopes": "",
            "strava_connected_at": "",
        }
    )
    metadata["strava_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "athlete_id": integrations.get("strava_athlete_id") or tokens.get("athlete_id", ""),
        "scopes": "",
    }
    metadata["strava_sync"] = {
        **(metadata.get("strava_sync") if isinstance(metadata.get("strava_sync"), dict) else {}),
        "needs_reconnect": bool(mark_error),
        "last_error": reason if mark_error else "",
        "last_synced_at": utc_now_iso(),
    }
    settings["integrations"] = integrations
    settings["metadata"] = metadata
    _save_settings_document(settings)


@router.get("/api/integrations/status")
def integrations_status(external_checks: bool = Query(default=False)) -> dict[str, Any]:
    return _integration_payload(external_checks=external_checks)


@router.get("/api/integrations/test")
def integrations_test() -> dict[str, Any]:
    settings = _settings_document()
    strava_status, _ = _strava_status(settings)
    withings_status, _ = _withings_status(settings)
    google_health_status, _ = _google_health_status(settings)
    fitbit_status, fitbit_meta = _fitbit_status(settings)
    hevy_configured = bool(os.getenv("HEVY_API_KEY", "").strip() or _integrations(settings).get("hevy_api_key"))
    try:
        from src.ai.food_parser import test_openai_connection

        openai_test = test_openai_connection()
    except Exception as exc:
        openai_configured = bool(os.getenv("OPENAI_API_KEY", "").strip() or _integrations(settings).get("openai_api_key"))
        openai_test = {
            "configured": openai_configured,
            "client_initialized": False,
            "test_status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc) or "OpenAI test failed.",
        }
    openai_status = "connected" if openai_test.get("test_status") == "ok" else "missing_api_key" if not openai_test.get("configured") else "error"
    openai_message = (
        f"Working: {openai_test.get('message')}"
        if openai_test.get("test_status") == "ok"
        else str(openai_test.get("message") or "OpenAI test failed.")
    )
    return {
        "checkedAt": utc_now_iso(),
        "hevy": _test_result("connected" if hevy_configured else "missing_api_key", "HEVY_API_KEY is configured." if hevy_configured else "HEVY_API_KEY is not configured."),
        "openai": {
            **_test_result(openai_status, openai_message),
            "layers": {
                "configuration": {
                    "status": "configured" if openai_test.get("configured") else "missing_api_key",
                    "message": "OPENAI_API_KEY is configured." if openai_test.get("configured") else "OPENAI_API_KEY is not configured.",
                },
                "client": {
                    "status": "initialized" if openai_test.get("client_initialized") else "not_initialized",
                    "message": "OpenAI client initialized." if openai_test.get("client_initialized") else "OpenAI client did not initialize.",
                },
                "test_call": {
                    "status": str(openai_test.get("test_status") or "error"),
                    "message": openai_message,
                },
            },
        },
        "strava": _test_result(strava_status.lower().replace(" ", "_"), f"Strava is {strava_status.lower()}."),
        "withings": _test_result(withings_status.lower().replace(" ", "_"), f"Withings is {withings_status.lower()}."),
        "google_health": _test_result(google_health_status.lower().replace(" ", "_"), f"Google Health is {google_health_status.lower()}."),
        "fitbit": {
            **_test_result(fitbit_status.lower().replace(" ", "_"), f"Fitbit is {fitbit_status.lower()}."),
            "layers": {
                "configuration": {
                    "status": "configured" if fitbit_meta.get("configured") else "missing_credentials",
                    "message": "Fitbit client credentials are configured." if fitbit_meta.get("configured") else "FITBIT_CLIENT_ID and FITBIT_CLIENT_SECRET are not both configured.",
                },
                "oauth_token": {
                    "status": str(fitbit_meta.get("token_status") or "missing"),
                    "message": "Fitbit token presence checked without exposing token values.",
                },
                "scopes": {
                    "status": "ok" if not fitbit_meta.get("missing_scopes") else "missing_scopes",
                    "message": "Granted scopes include expected activity, heartrate, sleep, and profile scopes." if not fitbit_meta.get("missing_scopes") else f"Missing scopes: {', '.join(fitbit_meta.get('missing_scopes') or [])}",
                },
            },
        },
    }


@router.get("/api/fitbit/connect")
@router.get("/api/integrations/fitbit/auth-url")
def connect_fitbit(request: Request, reconnect: bool = Query(default=False)) -> dict[str, Any]:
    from src.integrations.fitbit_client import get_auth_url

    if reconnect:
        _clear_fitbit_connection(mark_error=False, reason="Reconnect requested from Settings.")
    redirect_uri = _fitbit_redirect_uri(request)
    redirect_error = _oauth_redirect_error("FITBIT", redirect_uri)
    if redirect_error:
        logger.warning("[fitbit] auth url blocked: %s", redirect_error)
        return {"status": "error", "message": redirect_error, "auth_url": "", "redirect_uri": redirect_uri}
    result = get_auth_url(_settings_document(), redirect_uri=redirect_uri, state="performance-os")
    if result.get("status") == "ok":
        logger.info("[fitbit] authorization url generated redirect_uri_present=%s reconnect=%s", bool(redirect_uri), reconnect)
    else:
        logger.warning("[fitbit] authorization url failed status=%s message=%s", result.get("status"), str(result.get("message") or "")[:300])
    return result


@router.get("/api/fitbit/callback", name="fitbit_callback")
@router.get("/api/integrations/fitbit/callback")
def fitbit_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    if not code and not error:
        return JSONResponse({"status": "ok", "provider": "fitbit", "message": "callback reachable"})
    if error:
        message = f"Fitbit authorization failed: {error}"
        logger.warning("[fitbit] callback error: %s", str(error)[:500])
        _save_fitbit_sync_state({"needs_reconnect": True, "last_status": "error", "last_message": message, "last_error": message, "last_synced_at": utc_now_iso()})
        return RedirectResponse(_frontend_return_url(request, "fitbit", "error", message), status_code=303)
    try:
        from src.integrations.fitbit_client import exchange_code_for_token

        logger.info("[fitbit] callback received authorization code")
        result = exchange_code_for_token(str(code or ""), _settings_document(), redirect_uri=_fitbit_redirect_uri(request))
        if result.get("status") != "ok" or not result.get("tokens", {}).get("access_token"):
            raise RuntimeError(str(result.get("message") or "Fitbit did not return an access token."))
        if not result.get("tokens", {}).get("refresh_token"):
            raise RuntimeError("Fitbit did not return a refresh token. Reconnect and approve offline access.")
        logger.info("[fitbit] token exchange succeeded refresh_present=%s", bool(result.get("tokens", {}).get("refresh_token")))
        _save_fitbit_tokens(result["tokens"], connected_at=utc_now_iso())
        logger.info("[fitbit] callback completed and tokens persisted")
    except Exception as exc:
        message = str(exc) or "Fitbit OAuth callback failed."
        logger.warning("[fitbit] callback failed: %s", message[:500])
        _save_fitbit_sync_state({"needs_reconnect": True, "last_status": "error", "last_message": message, "last_error": message, "last_synced_at": utc_now_iso()})
        return RedirectResponse(_frontend_return_url(request, "fitbit", "error", message), status_code=303)
    return RedirectResponse(_frontend_return_url(request, "fitbit", "connected", "Fitbit connected."), status_code=303)


@router.get("/api/fitbit/status")
def fitbit_status() -> dict[str, Any]:
    status, metadata = _fitbit_status(_settings_document())
    return {
        "status": status,
        "metadata": metadata,
        "sync": {
            "last_synced_at": metadata.get("last_successful_sync", "") or metadata.get("last_synced_at", ""),
            "last_error": metadata.get("last_error", ""),
            "last_status": metadata.get("last_status", ""),
        },
    }


@router.post("/api/fitbit/sync")
def sync_fitbit(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return fitbit_force_sync(payload)


@router.post("/api/fitbit/disconnect")
def disconnect_fitbit() -> dict[str, Any]:
    _clear_fitbit_connection(mark_error=False, reason="Fitbit disconnected from Settings.")
    return _integration_payload(external_checks=False)


@router.get("/api/fitbit/disconnect")
def disconnect_fitbit_get() -> dict[str, Any]:
    _clear_fitbit_connection(mark_error=False, reason="Fitbit disconnected from Settings.")
    return _integration_payload(external_checks=False)


@router.get("/api/debug/fitbit")
def fitbit_debug_status() -> dict[str, Any]:
    return _fitbit_debug_payload()


@router.post("/api/debug/fitbit/sync")
def fitbit_force_sync(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.integrations.fitbit_client import fetch_daily_metrics, normalize_daily_metrics

    payload = payload or {}
    settings = _settings_document()
    status, meta = _fitbit_status(settings)
    sync_run_id = f"fitbit_debug_sync:{uuid4()}"
    started_at = utc_now_iso()
    try:
        days = max(1, min(int(payload.get("days") or 7), 30))
    except (TypeError, ValueError):
        days = 7
    today = date.fromisoformat(app_today_iso())
    end_date = _fitbit_text(payload.get("end_date"))[:10] or today.isoformat()
    try:
        start_date = _fitbit_text(payload.get("start_date"))[:10] or (date.fromisoformat(end_date) - timedelta(days=days - 1)).isoformat()
    except ValueError:
        start_date = (today - timedelta(days=days - 1)).isoformat()
        end_date = today.isoformat()
    logs = [
        f"endpoint hit: POST /api/debug/fitbit/sync run_id={sync_run_id}",
        f"connection status: {status}",
        f"token status: {meta.get('token_status', 'missing')}",
    ]
    missing_scopes = list(meta.get("missing_scopes") or [])
    if missing_scopes:
        logs.append(f"missing permissions/scopes: {', '.join(missing_scopes)}")
    try:
        access_token = _fitbit_access_token(settings)
        logs.append("token refresh/check: success")
    except Exception as exc:
        message = str(exc) or "No Fitbit access token is available. Connect Fitbit OAuth before force sync can fetch live data."
        pipeline = {
            "fetched": {"status": "failed", "message": "missing_access_token"},
            "parsed": {"status": "skipped", "message": "No Fitbit response to parse."},
            "stored": {"status": "skipped", "message": "No parsed Fitbit rows to store."},
        }
        logger.warning("[fitbit] sync blocked before fetch run_id=%s error=%s", sync_run_id, message[:500])
        logs.append(f"token refresh/check: failed ({type(exc).__name__})")
        logs.append("response status: missing_access_token")
        logs.append("parsing skipped: missing access token")
        _save_fitbit_sync_state(
            {
                "last_attempt_at": started_at,
                "last_synced_at": started_at,
                "last_status": "error",
                "last_message": message,
                "last_error": message,
                "last_fetched_count": 0,
                "last_parsed_count": 0,
                "last_stored_count": 0,
                "last_pipeline": pipeline,
                "last_logs": logs,
                "needs_reconnect": bool(meta.get("configured")),
            }
        )
        return {**_fitbit_debug_payload(message=message), "status": "error", "sync_run_id": sync_run_id}

    fetched = fetch_daily_metrics(access_token, start_date=start_date, end_date=end_date)
    response_status = _fitbit_text(fetched.get("status")) or "unknown"
    logs.append(f"response status: {response_status}")
    for warning in list(fetched.get("warnings") or [])[:5]:
        logs.append(f"missing metric warning: {warning}")
    if response_status != "ok":
        message = _fitbit_text(fetched.get("message")) or "Fitbit force sync failed."
        pipeline = {
            "fetched": {"status": "failed", "message": response_status},
            "parsed": {"status": "skipped", "message": "Fitbit response did not return ok."},
            "stored": {"status": "skipped", "message": "No parsed Fitbit rows to store."},
        }
        logs.append(f"parsing skipped: {message}")
        _save_fitbit_sync_state(
            {
                "last_attempt_at": started_at,
                "last_synced_at": started_at,
                "last_status": "error",
                "last_message": message,
                "last_error": message,
                "last_fetched_count": len(fetched.get("items") or []),
                "last_parsed_count": 0,
                "last_stored_count": 0,
                "last_pipeline": pipeline,
                "last_logs": logs,
                "needs_reconnect": "token" in message.lower() or "reconnect" in message.lower(),
            }
        )
        return {**_fitbit_debug_payload(message=message), "status": "error", "sync_run_id": sync_run_id, "date_range": {"start_date": start_date, "end_date": end_date}}

    items = fetched.get("items") or []
    try:
        normalized = normalize_daily_metrics(items)
        parsed_rows = normalized.to_dict(orient="records")
        logs.append(f"parsed successfully: {len(parsed_rows)} row(s)")
    except Exception as exc:
        message = f"Fitbit parsing failed: {exc}"
        pipeline = {
            "fetched": {"status": "ok", "message": f"Fetched {len(items)} item(s)."},
            "parsed": {"status": "failed", "message": type(exc).__name__},
            "stored": {"status": "skipped", "message": "Parsing failed before storage."},
        }
        logs.append(f"parsing failure: {type(exc).__name__}: {exc}")
        _save_fitbit_sync_state(
            {
                "last_attempt_at": started_at,
                "last_synced_at": started_at,
                "last_status": "error",
                "last_message": message,
                "last_error": message,
                "last_fetched_count": len(items),
                "last_parsed_count": 0,
                "last_stored_count": 0,
                "last_pipeline": pipeline,
                "last_logs": logs,
            }
        )
        return {**_fitbit_debug_payload(message=message), "status": "error", "sync_run_id": sync_run_id}

    now = utc_now_iso()
    saved_rows: list[dict[str, Any]] = []
    storage_errors: list[Any] = []
    for row in parsed_rows:
        row_date = _fitbit_text(row.get("date"))[:10]
        if not row_date:
            continue
        cleaned_row = {key: _fitbit_json_value(value) for key, value in row.items()}
        if not any(_fitbit_text(cleaned_row.get(key)) for key in FITBIT_WEARABLE_VALUE_FIELDS):
            logs.append(f"stored skipped: no parsed metric values for {row_date}")
            continue
        payload_row = {
            **cleaned_row,
            "metric_id": _fitbit_text(row.get("metric_id")) or f"fitbit:{row_date}",
            "source": "fitbit",
            "created_at": _fitbit_text(row.get("created_at")) or now,
            "updated_at": now,
        }
        saved = upsert_json_row("wearable_metrics", "metric_id", payload_row["metric_id"], payload_row)
        if isinstance(saved, dict) and "_db_error" in saved:
            storage_errors.append(saved.get("_db_error"))
        else:
            saved_rows.append(saved)
    latest_record = max((_fitbit_text(row.get("date")) for row in saved_rows), default="")
    if storage_errors:
        logs.append(f"stored with failures: {len(saved_rows)} saved, {len(storage_errors)} failed")
    else:
        logs.append(f"stored successfully: {len(saved_rows)} row(s)")
    sync_status = "partial" if storage_errors else "ok"
    message = f"Fitbit force sync complete: {len(saved_rows)} row(s) saved." if sync_status == "ok" else f"Fitbit force sync partially stored: {len(saved_rows)} row(s) saved, {len(storage_errors)} storage error(s)."
    pipeline = {
        "fetched": {"status": "ok", "message": f"Fetched {len(items)} item(s)."},
        "parsed": {"status": "ok", "message": f"Parsed {len(parsed_rows)} row(s)."},
        "stored": {"status": "ok" if not storage_errors else "partial", "message": f"Stored {len(saved_rows)} row(s)."},
    }
    previous_sync = _fitbit_sync(settings)
    _save_fitbit_sync_state(
        {
            "last_attempt_at": started_at,
            "last_synced_at": now,
            "last_successful_sync": now if sync_status == "ok" else previous_sync.get("last_successful_sync", ""),
            "last_status": sync_status,
            "last_message": message,
            "last_error": "; ".join(str(error.get("message") or error) for error in storage_errors[:2]),
            "last_fetched_count": len(items),
            "last_parsed_count": len(parsed_rows),
            "last_stored_count": len(saved_rows),
            "latest_record": latest_record,
            "start_date": start_date,
            "end_date": end_date,
            "last_pipeline": pipeline,
            "last_logs": logs,
            "needs_reconnect": False,
        }
    )
    return {
        **_fitbit_debug_payload(message=message),
        "status": sync_status,
        "sync_run_id": sync_run_id,
        "imported_metrics": len(saved_rows),
        "fetched_days": len(items),
        "storage_errors": storage_errors[:5],
        "date_range": {"start_date": start_date, "end_date": end_date},
    }


@router.get("/api/integrations/strava/auth-url")
def get_strava_auth_url(request: Request, reconnect: bool = Query(default=False)) -> dict[str, Any]:
    if reconnect:
        _clear_strava_connection(mark_error=False, reason="Reconnect requested from Settings.")
    redirect_uri = _strava_redirect_uri(request)
    redirect_error = _oauth_redirect_error("STRAVA", redirect_uri)
    if redirect_error:
        return {"status": "error", "message": redirect_error, "auth_url": "", "redirect_uri": redirect_uri}
    settings = _settings_document()
    client_id, client_secret = _strava_credentials(settings)
    if not client_id or not client_secret:
        return {"status": "error", "message": "Strava client ID and secret are not configured.", "auth_url": "", "redirect_uri": redirect_uri}
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "force" if reconnect else "auto",
            "scope": os.getenv("STRAVA_SCOPES", "").strip() or STRAVA_SCOPES,
            "state": "performance-os",
        }
    )
    return {
        "status": "ok",
        "auth_url": f"{STRAVA_AUTH_URL}?{query}",
        "redirect_uri": redirect_uri,
        "scope": os.getenv("STRAVA_SCOPES", "").strip() or STRAVA_SCOPES,
    }


@router.get("/api/strava/callback", name="strava_callback")
@router.get("/api/integrations/strava/callback")
def strava_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    if error:
        return RedirectResponse(_frontend_return_url(request, "strava", "error", f"Strava authorization failed: {error}"), status_code=303)
    if not code:
        return RedirectResponse(_frontend_return_url(request, "strava", "error", "Missing authorization code."), status_code=303)
    try:
        from src.integrations.strava_client import exchange_strava_code

        exchange_strava_code(code)
    except Exception as exc:
        return RedirectResponse(_frontend_return_url(request, "strava", "error", str(exc)), status_code=303)
    return RedirectResponse(_frontend_return_url(request, "strava", "connected", "Strava connected."), status_code=303)


@router.post("/api/integrations/strava/disconnect")
def disconnect_strava() -> dict[str, Any]:
    _clear_strava_connection(mark_error=False, reason="Strava disconnected from backend_new settings.")
    return _integration_payload(external_checks=False)


def _save_google_health_tokens(token_patch: dict[str, Any], *, connected_at: str = "") -> dict[str, Any]:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    previous = metadata.get("google_health_tokens") if isinstance(metadata.get("google_health_tokens"), dict) else {}
    metadata["google_health_tokens"] = {
        **previous,
        **{key: value for key, value in token_patch.items() if value is not None},
    }
    sync = metadata.get("google_health_sync") if isinstance(metadata.get("google_health_sync"), dict) else {}
    metadata["google_health_sync"] = {
        **sync,
        "needs_reconnect": False,
        "last_error": "",
        **({"connected_at": connected_at} if connected_at else {}),
    }
    settings["metadata"] = metadata
    saved = _save_settings_document(settings)
    _save_google_health_connection_record()
    return saved


def _save_google_health_sync_state(updates: dict[str, Any]) -> dict[str, Any]:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    sync = metadata.get("google_health_sync") if isinstance(metadata.get("google_health_sync"), dict) else {}
    metadata["google_health_sync"] = {**sync, **updates}
    settings["metadata"] = metadata
    _save_settings_document(settings)
    _save_google_health_connection_record()
    return metadata["google_health_sync"]


def _google_health_text(value: Any) -> str:
    try:
        if value is None or pd_is_na(value):
            return ""
    except Exception:
        if value is None:
            return ""
    text = str(value or "").strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "nat"} else text


def pd_is_na(value: Any) -> bool:
    try:
        import pandas as pd

        return bool(pd.isna(value))
    except Exception:
        return False


GOOGLE_HEALTH_SYNC_SAMPLE_FIELDS = [
    "sleep_hours",
    "total_sleep_minutes",
    "rem_sleep_minutes",
    "deep_sleep_minutes",
    "light_sleep_minutes",
    "awake_minutes",
    "sleep_efficiency",
    "sleep_score",
    "resting_hr",
    "resting_hr_baseline",
    "resting_hr_deviation",
    "hrv",
    "average_hr",
    "max_hr",
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "distance_miles",
    "total_calories_burned",
    "calories_burned",
    "active_calories_burned",
    "basal_calories_burned",
    "breathing_rate",
    "spo2",
    "skin_temperature",
    "body_temperature",
]


def _google_health_metric_present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return True
    return parsed > 0


def _google_health_row_field_counts(row: dict[str, Any] | None) -> dict[str, int]:
    sample = row if isinstance(row, dict) else {}
    populated = sum(1 for field in GOOGLE_HEALTH_SYNC_SAMPLE_FIELDS if _google_health_metric_present(sample.get(field)))
    return {
        "fields_populated_count": populated,
        "fields_missing_count": len(GOOGLE_HEALTH_SYNC_SAMPLE_FIELDS) - populated,
    }


def _google_health_latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    clean = [dict(row) for row in rows if isinstance(row, dict) and _google_health_text(row.get("date"))]
    if not clean:
        return {}
    return sorted(clean, key=lambda row: _google_health_text(row.get("date")))[-1]


def _google_health_access_token(settings: dict[str, Any] | None = None) -> str:
    from src.integrations.google_health_client import refresh_access_token

    current = settings if isinstance(settings, dict) else _settings_document()
    metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    tokens = metadata.get("google_health_tokens") if isinstance(metadata.get("google_health_tokens"), dict) else {}
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    try:
        expires_at = int(tokens.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if not refresh_token:
        raise RuntimeError("Google Health is not connected. Connect Google Health before syncing.")
    if access_token and expires_at > int(time.time()) + 60:
        return access_token
    logger.info("[google_health] refreshing access token")
    refreshed = refresh_access_token(refresh_token, current)
    if refreshed.get("status") != "ok" or not refreshed.get("tokens", {}).get("access_token"):
        message = str(refreshed.get("message") or "Google Health token refresh failed.")
        logger.warning("[google_health] token refresh failed: %s", message[:500])
        _save_google_health_sync_state({"needs_reconnect": True, "last_status": "error", "last_message": message, "last_error": message, "last_synced_at": utc_now_iso()})
        raise RuntimeError(message)
    _save_google_health_tokens(refreshed["tokens"])
    logger.info("[google_health] token refresh succeeded")
    return str(refreshed["tokens"]["access_token"])


def _clear_google_health_connection(*, mark_error: bool = False, reason: str = "") -> None:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    metadata["google_health_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "token_type": "",
        "scopes": "",
    }
    metadata["google_health_sync"] = {
        **(metadata.get("google_health_sync") if isinstance(metadata.get("google_health_sync"), dict) else {}),
        "needs_reconnect": bool(mark_error),
        "last_error": reason if mark_error else "",
        "disconnected_at": utc_now_iso(),
    }
    settings["metadata"] = metadata
    _save_settings_document(settings)
    _save_google_health_connection_record("Disconnected", {"connected": False, "configured": True, "last_error": reason if mark_error else ""})


@router.get("/api/google-health/connect")
def connect_google_health(request: Request) -> dict[str, Any]:
    from src.integrations.google_health_client import get_auth_url

    redirect_uri = _google_health_redirect_uri(request)
    client_id, client_secret = _google_health_credentials(_settings_document())
    logger.info(
        "[google_health] connect requested runtime=%s env=%s client_id_present=%s client_id_preview=%s client_secret_present=%s redirect_uri=%s expected_redirect_match=%s",
        _runtime_service().get("service"),
        _runtime_service().get("environment"),
        bool(str(client_id or "").strip()),
        _secret_preview(client_id),
        bool(str(client_secret or "").strip()),
        redirect_uri,
        redirect_uri == GOOGLE_HEALTH_EXPECTED_CALLBACK_URL,
    )
    redirect_error = _oauth_redirect_error("GOOGLE_HEALTH", redirect_uri)
    if redirect_error:
        logger.warning("[google_health] connect blocked: %s", redirect_error)
        return {"status": "error", "message": redirect_error, "auth_url": "", "redirect_uri": redirect_uri}
    result = get_auth_url(_settings_document(), redirect_uri=redirect_uri, state="performance-os")
    if result.get("status") != "ok":
        logger.warning("[google_health] authorize url generation failed status=%s message=%s", result.get("status"), str(result.get("message") or "")[:500])
        return result
    logger.info("[google_health] authorize url generated redirect_uri=%s client_id_preview=%s", redirect_uri, _secret_preview(client_id))
    return result


@router.get("/api/debug/google-health")
def debug_google_health(request: Request) -> dict[str, Any]:
    return _google_health_debug_payload(request)


@router.get("/api/google-health/callback", name="google_health_callback")
def google_health_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    if not code and not error:
        return JSONResponse({"status": "ok", "provider": "google_health", "message": "callback reachable"})
    redirect_uri = _google_health_redirect_uri(request)
    client_id, client_secret = _google_health_credentials(_settings_document())
    logger.info(
        "[google_health] callback received code_present=%s error_present=%s runtime=%s client_id_present=%s client_id_preview=%s client_secret_present=%s redirect_uri=%s",
        bool(code),
        bool(error),
        _runtime_service().get("service"),
        bool(str(client_id or "").strip()),
        _secret_preview(client_id),
        bool(str(client_secret or "").strip()),
        redirect_uri,
    )
    if error:
        logger.warning("[google_health] callback authorization error=%s", str(error)[:500])
        return RedirectResponse(_frontend_return_url(request, "google_health", "error", f"Google Health authorization failed: {error}"), status_code=303)
    try:
        from src.integrations.google_health_client import exchange_code_for_token

        result = exchange_code_for_token(str(code or ""), _settings_document(), redirect_uri=redirect_uri)
        if result.get("status") != "ok" or not result.get("tokens", {}).get("refresh_token"):
            raise RuntimeError(str(result.get("message") or "Google Health did not return a refresh token."))
        _save_google_health_tokens(result["tokens"], connected_at=utc_now_iso())
        logger.info("[google_health] callback token exchange succeeded refresh_present=%s", bool(result.get("tokens", {}).get("refresh_token")))
    except Exception as exc:
        logger.warning(
            "[google_health] callback token exchange failed client_id_preview=%s redirect_uri=%s error=%s",
            _secret_preview(client_id),
            redirect_uri,
            str(exc)[:500],
        )
        _save_google_health_sync_state({"needs_reconnect": True, "last_error": str(exc), "last_synced_at": utc_now_iso()})
        return RedirectResponse(_frontend_return_url(request, "google_health", "error", str(exc)), status_code=303)
    return RedirectResponse(_frontend_return_url(request, "google_health", "connected", "Google Health connected."), status_code=303)


@router.get("/api/google-health/status")
def google_health_status() -> dict[str, Any]:
    status, metadata = _google_health_status(_settings_document())
    return {"status": status, "metadata": metadata, "sync": {"last_synced_at": metadata.get("last_synced_at", ""), "last_error": metadata.get("last_error", "")}}


GOOGLE_HEALTH_RECORD_TABLES = {
    "daily_summary": ("google_health_daily_summary", "summary_id"),
    "sleep": ("google_health_sleep", "sleep_id"),
    "heart": ("google_health_heart", "heart_id"),
    "activity": ("google_health_activity", "activity_id"),
    "recovery_signals": ("google_health_recovery_signals", "signal_id"),
}


def _save_google_health_records(records: dict[str, Any] | None) -> dict[str, Any]:
    counts = {key: 0 for key in GOOGLE_HEALTH_RECORD_TABLES}
    errors: list[dict[str, Any]] = []
    for record_key, (table, id_field) in GOOGLE_HEALTH_RECORD_TABLES.items():
        for record in (records or {}).get(record_key) or []:
            if not isinstance(record, dict):
                continue
            key_value = _google_health_text(record.get(id_field))
            if not key_value:
                continue
            saved = upsert_json_row(table, id_field, key_value, record)
            if isinstance(saved, dict) and "_db_error" in saved:
                errors.append({"table": table, "id": key_value, "error": saved.get("_db_error")})
                continue
            counts[record_key] += 1
    return {"counts": counts, "errors": errors}


@router.post("/api/google-health/sync")
def sync_google_health(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from src.integrations.google_health_client import fetch_daily_metrics, normalize_daily_metrics

    payload = payload or {}
    sync_run_id = f"google_health_sync:{uuid4()}"
    started_at = utc_now_iso()
    today = date.fromisoformat(app_today_iso())
    try:
        days = max(1, min(int(payload.get("days") or 14), 90))
    except (TypeError, ValueError):
        days = 14
    end_date = str(payload.get("end_date") or today.isoformat())[:10]
    start_date = str(payload.get("start_date") or (date.fromisoformat(end_date) - timedelta(days=days - 1)).isoformat())[:10]
    logger.info("[google_health] sync started run_id=%s start=%s end=%s days=%s", sync_run_id, start_date, end_date, days)
    try:
        access_token = _google_health_access_token()
        fetched = fetch_daily_metrics(access_token, start_date=start_date, end_date=end_date)
        if fetched.get("status") != "ok":
            raise RuntimeError(str(fetched.get("message") or "Google Health sync failed."))
        normalized = normalize_daily_metrics(fetched.get("items") or [])
        now = utc_now_iso()
        saved_rows: list[dict[str, Any]] = []
        normalized_rows = [dict(row) for row in normalized.to_dict(orient="records")]
        sample_latest_normalized_row = _google_health_latest_row(normalized_rows)
        sample_field_counts = _google_health_row_field_counts(sample_latest_normalized_row)
        for row in normalized_rows:
            row_date = _google_health_text(row.get("date"))[:10]
            if not row_date:
                continue
            payload_row = {
                **row,
                "metric_id": _google_health_text(row.get("metric_id")) or f"google_health:{row_date}",
                "source": "google_health",
                "created_at": _google_health_text(row.get("created_at")) or now,
                "updated_at": now,
            }
            saved_rows.append(upsert_json_row("wearable_metrics", "metric_id", payload_row["metric_id"], payload_row))
        saved_records = _save_google_health_records(fetched.get("records") or {})
        latest_record = max((str(row.get("date") or "") for row in saved_rows), default="")
        sync_errors = list(saved_records.get("errors") or [])
        optional_metric_warnings = list(dict.fromkeys(str(item) for item in (fetched.get("optional_metric_warnings") or []) if str(item or "").strip()))
        required_metric_failures = list(dict.fromkeys(str(item) for item in (fetched.get("required_metric_failures") or []) if str(item or "").strip()))
        sync_warnings = list(dict.fromkeys(str(item) for item in (fetched.get("warnings") or []) if str(item or "").strip()))
        rows_saved = len(saved_rows)
        rows_saved_by_table = {"wearable_metrics": rows_saved, **(saved_records.get("counts", {}) if isinstance(saved_records.get("counts"), dict) else {})}
        sync_status = "partial" if sync_errors else "ok"
        sync_message = (
            f"Google Health sync completed with storage warnings: {rows_saved} daily row(s) saved."
            if sync_errors
            else f"Google Health sync complete: {rows_saved} daily row(s) saved."
        )
        sync_state = _save_google_health_sync_state(
            {
                "last_synced_at": now,
                "last_status": sync_status,
                "last_message": sync_message,
                "last_error": "; ".join(str(error.get("error") or "") for error in sync_errors[:2]),
                "last_warning": "; ".join(sync_warnings[:2]),
                "needs_reconnect": False,
                "last_imported_count": rows_saved,
                "rows_saved": rows_saved,
                "last_fetched_count": int(fetched.get("raw_bucket_count") or len(fetched.get("items") or [])),
                "latest_record": latest_record,
                "start_date": start_date,
                "end_date": end_date,
                "last_record_counts": saved_records.get("counts", {}),
                "rows_saved_by_table": rows_saved_by_table,
                "sample_latest_normalized_row": sample_latest_normalized_row,
                **sample_field_counts,
                "last_warning_count": len(sync_warnings),
                "last_storage_error_count": len(sync_errors),
                "optional_metric_warnings": optional_metric_warnings,
                "required_metric_failures": required_metric_failures,
                "data_sources": fetched.get("data_sources") or {},
            }
        )
        logger.info(
            "[google_health] sync finished run_id=%s status=%s imported=%s fetched_days=%s warnings=%s storage_errors=%s latest=%s",
            sync_run_id,
            sync_status,
            rows_saved,
            len(fetched.get("items") or []),
            len(sync_warnings),
            len(sync_errors),
            latest_record,
        )
        upsert_json_row(
            "google_health_sync_runs",
            "sync_run_id",
            sync_run_id,
            {
                "sync_run_id": sync_run_id,
                "status": sync_status,
                "provider": "google_health",
                "started_at": started_at,
                "completed_at": now,
                "start_date": start_date,
                "end_date": end_date,
                "imported_metrics": rows_saved,
                "rows_saved": rows_saved,
                "record_counts": saved_records.get("counts", {}),
                "rows_saved_by_table": rows_saved_by_table,
                "sample_latest_normalized_row": sample_latest_normalized_row,
                **sample_field_counts,
                "warnings": sync_warnings,
                "optional_metric_warnings": optional_metric_warnings,
                "required_metric_failures": required_metric_failures,
                "storage_errors": sync_errors[:5],
                "data_sources": fetched.get("data_sources") or {},
            },
        )
        return {
            "status": sync_status,
            "message": sync_message,
            "rows_saved": rows_saved,
            "imported_metrics": rows_saved,
            "rows_saved_by_table": rows_saved_by_table,
            "sample_latest_normalized_row": sample_latest_normalized_row,
            **sample_field_counts,
            "imported_records": saved_records.get("counts", {}),
            "fetched_days": len(fetched.get("items") or []),
            "latest_record": latest_record,
            "last_synced_at": sync_state.get("last_synced_at", now),
            "warnings": sync_warnings,
            "optional_metric_warnings": optional_metric_warnings,
            "required_metric_failures": required_metric_failures,
            "storage_errors": sync_errors[:5],
            "data_sources": fetched.get("data_sources") or {},
            "date_range": {"start_date": start_date, "end_date": end_date},
        }
    except Exception as exc:
        message = str(exc) or "Google Health sync failed."
        failed_at = utc_now_iso()
        logger.warning("[google_health] sync failed run_id=%s error=%s", sync_run_id, message[:500])
        _save_google_health_sync_state({"last_status": "error", "last_message": message, "last_error": message, "last_synced_at": failed_at, "needs_reconnect": "token" in message.lower() or "reconnect" in message.lower()})
        upsert_json_row(
            "google_health_sync_runs",
            "sync_run_id",
            sync_run_id,
            {
                "sync_run_id": sync_run_id,
                "status": "error",
                "provider": "google_health",
                "started_at": started_at,
                "completed_at": failed_at,
                "start_date": start_date,
                "end_date": end_date,
                "error": message,
            },
        )
        return {
            "status": "error",
            "message": message,
            "rows_saved": 0,
            "imported_metrics": 0,
            "fetched_days": 0,
            "required_metric_failures": [message],
            "optional_metric_warnings": [],
            "date_range": {"start_date": start_date, "end_date": end_date},
        }


@router.post("/api/google-health/disconnect")
def disconnect_google_health() -> dict[str, Any]:
    _clear_google_health_connection(mark_error=False, reason="Google Health disconnected from Settings.")
    return _integration_payload(external_checks=False)


@router.get("/api/google-health/disconnect")
def disconnect_google_health_get() -> dict[str, Any]:
    _clear_google_health_connection(mark_error=False, reason="Google Health disconnected from Settings.")
    return _integration_payload(external_checks=False)


def _route_registered(request: Request, path: str, method: str = "GET") -> bool:
    target_method = method.upper()
    for route in request.app.routes:
        route_path = getattr(route, "path", "")
        route_methods = getattr(route, "methods", set()) or set()
        if route_path == path and target_method in route_methods:
            return True
    return False


@router.get("/api/debug/strava")
def debug_strava(request: Request) -> dict[str, Any]:
    settings = _settings_document()
    client_id, client_secret = _strava_credentials(settings)
    redirect_uri = os.getenv("STRAVA_REDIRECT_URI", "").strip() or str(_integrations(settings).get("strava_redirect_uri") or "").strip()
    tokens = _strava_tokens(settings)
    status, metadata = _strava_status(settings)
    if status == "Connected":
        next_action = "import_strava"
    elif status in {"Reconnect required", "Expired/Reauth required"}:
        next_action = "reconnect_strava"
    else:
        next_action = "connect_strava" if client_id and client_secret else "configure_strava_credentials"
    return {
        "client_id_configured": bool(client_id),
        "client_secret_configured": bool(client_secret),
        "redirect_uri_configured": bool(redirect_uri),
        "access_token_present": bool(tokens.get("access_token")),
        "refresh_token_present": bool(tokens.get("refresh_token")),
        "expires_at": tokens.get("expires_at") or None,
        "athlete_id": str(tokens.get("athlete_id") or "") or None,
        "status": _status_slug(status),
        "display_status": status,
        "token_status": metadata.get("token_status", "missing"),
        "last_import_date": metadata.get("last_synced_at", ""),
        "latest_activity_date": metadata.get("latest_activity_date", ""),
        "auth_url_route_registered": _route_registered(request, "/api/integrations/strava/auth-url", "GET"),
        "callback_route_registered": _route_registered(request, "/api/strava/callback", "GET"),
        "disconnect_route_registered": _route_registered(request, "/api/integrations/strava/disconnect", "POST"),
        "import_route_registered": _route_registered(request, "/api/training/import/strava", "POST"),
        "debug_route_registered": _route_registered(request, "/api/debug/strava", "GET"),
        "storage_keys_found": _strava_storage_keys_found(settings),
        "next_action": next_action,
    }


@router.get("/api/integrations/withings/auth-url")
def get_withings_auth_url(request: Request) -> dict:
    redirect_uri = _withings_redirect_uri(request)
    redirect_error = _redirect_uri_error(redirect_uri)
    if redirect_error:
        return {"status": "error", "message": redirect_error, "auth_url": "", "redirect_uri": redirect_uri}
    client_id, client_secret = _withings_credentials()
    if not client_id or not client_secret:
        return {"status": "error", "message": "Withings client ID and secret are not configured.", "auth_url": "", "redirect_uri": redirect_uri}
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "scope": WITHINGS_SCOPES,
            "redirect_uri": redirect_uri,
            "state": "performance-os",
        }
    )
    return {
        "status": "ok",
        "auth_url": f"{WITHINGS_AUTH_URL}?{query}",
        "redirect_uri": redirect_uri,
        "message": "Use this exact redirect URI in the Withings developer console.",
    }


@router.post("/api/integrations/withings/disconnect")
def disconnect_withings() -> dict:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    metadata["withings_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "userid": "",
        "scopes": "",
        "token_type": "",
    }
    metadata["withings_sync"] = {
        **(metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}),
        "last_error": "",
        "needs_reconnect": False,
        "disconnected_at": utc_now_iso(),
    }
    settings["metadata"] = metadata
    settings["updated_at"] = utc_now_iso()
    insert_json_row("api_connections", settings)
    return _integration_payload(external_checks=False)


@router.get("/api/withings/connect")
def connect_withings(request: Request):
    result = get_withings_auth_url(request)
    if result.get("status") != "ok" or not result.get("auth_url"):
        return result
    return RedirectResponse(str(result["auth_url"]), status_code=303)


def _finish_withings_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    if not code and not error:
        return JSONResponse({"status": "ok", "provider": "withings", "message": "callback reachable"})
    if error:
        return RedirectResponse(_frontend_return_url(request, "withings", "error", f"Withings authorization failed: {error}"), status_code=303)
    try:
        from src.integrations.withings_client import exchange_withings_code

        exchange_withings_code(code, _withings_redirect_uri(request))
    except Exception as exc:
        return RedirectResponse(_frontend_return_url(request, "withings", "error", str(exc)), status_code=303)
    return RedirectResponse(_frontend_return_url(request, "withings", "connected", "Withings connected."), status_code=303)


@router.get("/api/withings/callback", name="withings_callback")
def withings_callback_get(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    return _finish_withings_oauth_callback(request, code=code, error=error)


@router.post("/api/withings/callback")
def withings_callback_post(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    return _finish_withings_oauth_callback(request, code=code, error=error)


@router.head("/api/withings/callback")
def withings_callback_head() -> Response:
    return Response(status_code=200, headers={"Allow": "GET, POST, HEAD, OPTIONS"})


@router.options("/api/withings/callback")
def withings_callback_options() -> Response:
    return Response(
        status_code=204,
        headers={
            "Allow": "GET, POST, HEAD, OPTIONS",
            "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


@router.get("/api/withings/status")
def withings_status() -> dict:
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("withings_tokens") if isinstance(metadata.get("withings_tokens"), dict) else {}
    sync = metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}
    client_id, client_secret = _withings_credentials()
    if sync.get("needs_reconnect"):
        status = "Disconnected"
    elif tokens.get("access_token") and tokens.get("refresh_token"):
        status = "Connected"
    elif client_id and client_secret:
        status = "Ready to connect"
    else:
        status = "Not configured"
    return {"status": status, "sync": sync}


@router.post("/api/withings/sync")
def sync_withings_now(payload: dict | None = None) -> dict:
    payload = payload or {}
    try:
        from src.integrations.withings_client import sync_withings_measurements

        result = sync_withings_measurements(
            days=payload.get("days"),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            history=bool(payload.get("history")),
            include_rows=True,
        )
    except Exception as exc:
        return _withings_error(str(exc))
    return _withings_sync_response(result, items_limit=1000)


@router.post("/api/withings/sync-history")
def sync_withings_history(payload: dict | None = None) -> dict:
    payload = payload or {}
    try:
        from src.integrations.withings_client import DEFAULT_HISTORY_SYNC_DAYS, sync_withings_measurements

        result = sync_withings_measurements(
            days=payload.get("days") or DEFAULT_HISTORY_SYNC_DAYS,
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            history=True,
            include_rows=True,
        )
    except Exception as exc:
        return _withings_error(str(exc))
    return _withings_sync_response(result, items_limit=5000)
