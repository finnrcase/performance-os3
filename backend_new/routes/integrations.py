from __future__ import annotations

import logging
import os
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import urlencode, urlparse
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from backend_new.db import fetch_latest_document, insert_json_row, ping, upsert_json_row
from backend_new.routes.body_metrics import withings_body_metric_sync_response
from backend_new.routes.settings import settings_payload
from backend_new.utils import app_today_iso, utc_now_iso

router = APIRouter(tags=["integrations"])
logger = logging.getLogger(__name__)

WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_SCOPES = "user.metrics"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_SCOPES = "read,activity:read_all"

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

    return redirect_uri(_settings_document(), fallback=str(request.url_for("google_health_callback")))


def _google_health_status(settings: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    from src.integrations.google_health_client import client_credentials, saved_token_state, scopes

    client_id, client_secret = client_credentials(settings)
    tokens, sync = saved_token_state(settings)
    refresh_token_present = bool(tokens.get("refresh_token"))
    access_token_present = bool(tokens.get("access_token"))
    needs_reconnect = bool(sync.get("needs_reconnect"))
    configured = bool(client_id and client_secret)
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
        "last_synced_at": sync.get("last_synced_at", ""),
        "latest_record": sync.get("latest_record", ""),
        "last_error": sync.get("last_error", ""),
        "last_warning": sync.get("last_warning", ""),
        "last_status": sync.get("last_status", ""),
        "last_message": sync.get("last_message", ""),
        "last_warning_count": sync.get("last_warning_count", 0),
        "last_storage_error_count": sync.get("last_storage_error_count", 0),
        "last_imported_count": sync.get("last_imported_count", 0),
        "last_fetched_count": sync.get("last_fetched_count", 0),
        "needs_reconnect": needs_reconnect,
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
            "required_user_actions": [],
            "other_integrations": {},
        }
    )
    base["statuses"] = {
        **base.get("statuses", {}),
        "strava": strava_status,
        "withings": withings_status,
        "google_health": google_health_status,
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
        },
    }
    base["health"] = [
        _health_card("hevy", "Hevy", "Connected" if hevy_configured else "Not configured", {"connected": hevy_configured}),
        _health_card("strava", "Strava", strava_status, strava_meta),
        _health_card("withings", "Withings", withings_status, withings_meta),
        _health_card("google_health", "Google Health", google_health_status, google_health_meta),
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
    redirect_error = _oauth_redirect_error("GOOGLE_HEALTH", redirect_uri)
    if redirect_error:
        return {"status": "error", "message": redirect_error, "auth_url": "", "redirect_uri": redirect_uri}
    result = get_auth_url(_settings_document(), redirect_uri=redirect_uri, state="performance-os")
    if result.get("status") != "ok":
        return result
    return result


@router.get("/api/google-health/callback", name="google_health_callback")
def google_health_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> Response:
    if not code and not error:
        return JSONResponse({"status": "ok", "provider": "google_health", "message": "callback reachable"})
    if error:
        return RedirectResponse(_frontend_return_url(request, "google_health", "error", f"Google Health authorization failed: {error}"), status_code=303)
    try:
        from src.integrations.google_health_client import exchange_code_for_token

        result = exchange_code_for_token(str(code or ""), _settings_document(), redirect_uri=_google_health_redirect_uri(request))
        if result.get("status") != "ok" or not result.get("tokens", {}).get("refresh_token"):
            raise RuntimeError(str(result.get("message") or "Google Health did not return a refresh token."))
        _save_google_health_tokens(result["tokens"], connected_at=utc_now_iso())
    except Exception as exc:
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
        for row in normalized.to_dict(orient="records"):
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
        sync_warnings = list(fetched.get("warnings") or [])
        sync_status = "partial" if sync_errors else "ok"
        sync_message = (
            f"Google Health sync completed with storage warnings: {len(saved_rows)} daily row(s) saved."
            if sync_errors
            else f"Google Health sync complete: {len(saved_rows)} daily row(s) saved."
        )
        sync_state = _save_google_health_sync_state(
            {
                "last_synced_at": now,
                "last_status": sync_status,
                "last_message": sync_message,
                "last_error": "; ".join(str(error.get("error") or "") for error in sync_errors[:2]),
                "last_warning": "; ".join(sync_warnings[:2]),
                "needs_reconnect": False,
                "last_imported_count": len(saved_rows),
                "last_fetched_count": int(fetched.get("raw_bucket_count") or len(fetched.get("items") or [])),
                "latest_record": latest_record,
                "start_date": start_date,
                "end_date": end_date,
                "last_record_counts": saved_records.get("counts", {}),
                "last_warning_count": len(sync_warnings),
                "last_storage_error_count": len(sync_errors),
            }
        )
        logger.info(
            "[google_health] sync finished run_id=%s status=%s imported=%s fetched_days=%s warnings=%s storage_errors=%s latest=%s",
            sync_run_id,
            sync_status,
            len(saved_rows),
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
                "imported_metrics": len(saved_rows),
                "record_counts": saved_records.get("counts", {}),
                "warnings": sync_warnings,
                "storage_errors": sync_errors[:5],
            },
        )
        return {
            "status": sync_status,
            "message": sync_message,
            "imported_metrics": len(saved_rows),
            "imported_records": saved_records.get("counts", {}),
            "fetched_days": len(fetched.get("items") or []),
            "latest_record": latest_record,
            "last_synced_at": sync_state.get("last_synced_at", now),
            "warnings": sync_warnings,
            "storage_errors": sync_errors[:5],
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
        return {"status": "error", "message": message, "imported_metrics": 0, "fetched_days": 0, "date_range": {"start_date": start_date, "end_date": end_date}}


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
