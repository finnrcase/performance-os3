from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from backend_new.db import fetch_json_rows, fetch_latest_document, insert_json_row, ping
from backend_new.routes.settings import settings_payload
from backend_new.utils import utc_now_iso

router = APIRouter(tags=["integrations"])

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
    return f"{app_url}/?{urlencode({provider: status, 'message': message})}"


def _withings_error(message: str) -> dict:
    return {
        "status": "error",
        "message": message,
        "imported_measurements": 0,
        "fetched_groups": 0,
        "latest_measure_date": "",
        "last_synced_at": "",
    }


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
    saved = metadata.get("strava_tokens") if isinstance(metadata.get("strava_tokens"), dict) else {}
    try:
        expires_at = int(os.getenv("STRAVA_EXPIRES_AT", "") or os.getenv("STRAVA_TOKEN_EXPIRES_AT", "") or saved.get("expires_at") or 0)
    except ValueError:
        expires_at = 0
    return {
        "access_token": os.getenv("STRAVA_ACCESS_TOKEN", "").strip() or str(saved.get("access_token") or "").strip(),
        "refresh_token": os.getenv("STRAVA_REFRESH_TOKEN", "").strip() or str(saved.get("refresh_token") or "").strip(),
        "expires_at": expires_at,
        "athlete_id": os.getenv("STRAVA_ATHLETE_ID", "").strip() or str(saved.get("athlete_id") or "").strip(),
        "scopes": os.getenv("STRAVA_SCOPES", "").strip() or str(saved.get("scopes") or "").strip() or STRAVA_SCOPES,
    }


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
    needs_reconnect = bool(sync.get("needs_reconnect") and (access_token_present or refresh_token_present))
    if needs_reconnect:
        status = "Expired/Reauth required"
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
    return "green" if status == "Connected" else "yellow" if status in {"Disconnected", "Expired/Reauth required"} else "gray"


def _status_slug(status: str) -> str:
    return status.lower().replace("/", "_").replace(" ", "_").replace("__", "_")


def _health_card(provider: str, title: str, status: str, metadata: dict[str, Any]) -> dict[str, Any]:
    connected = status == "Connected"
    action = f"{provider}_sync" if connected else f"{provider}_reconnect" if status == "Expired/Reauth required" else f"{provider}_connect"
    return {
        "id": provider,
        "title": title,
        "status": "connected" if connected else "warning" if status in {"Disconnected", "Expired/Reauth required"} else "error",
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
    try:
        from src.ai.food_parser import openai_analyzer_config

        openai_config = openai_analyzer_config()
    except Exception:
        openai_config = {"openai_key_configured": bool(os.getenv("OPENAI_API_KEY", "").strip() or _integrations(settings).get("openai_api_key")), "model": "", "api_key_source": "unknown"}
    openai_configured = bool(openai_config.get("openai_key_configured"))
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
                status="green" if openai_configured else "gray",
                message="OpenAI key is configured." if openai_configured else "OpenAI key is not configured. Manual logging still works.",
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
                configured=strava_status in {"Connected", "Disconnected", "Expired/Reauth required"},
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
            "required_user_actions": [],
            "other_integrations": {},
        }
    )
    base["statuses"] = {
        **base.get("statuses", {}),
        "strava": strava_status,
        "withings": withings_status,
        "openai_api_key": "Configured" if openai_configured else "Not configured",
        "hevy_api_key": "Configured" if hevy_configured else "Not configured",
    }
    base["services"] = {
        **base.get("services", {}),
        "openai": {"configured": openai_configured, "status": "ok" if openai_configured else "missing_api_key", "message": base["openai"]["message"], "model": openai_config.get("model", ""), "api_key_source": openai_config.get("api_key_source", "unknown")},
        "hevy": {"configured": hevy_configured, "status": "ok" if hevy_configured else "missing_api_key", "message": base["hevy"]["message"]},
        "strava": {"configured": base["strava"]["configured"], "status": "ok" if strava_status == "Connected" else _status_slug(strava_status), "message": base["strava"]["message"], "last_synced_at": strava_meta.get("last_synced_at", ""), "latest_record": strava_meta.get("latest_activity_date", ""), "reconnect_required": strava_meta.get("needs_reconnect", False), "token_status": strava_meta.get("token_status", "missing")},
        "withings": {"configured": base["withings"]["configured"], "status": "ok" if withings_status == "Connected" else withings_status.lower().replace(" ", "_"), "message": base["withings"]["message"], "last_synced_at": withings_meta.get("last_synced_at", ""), "latest_record": withings_meta.get("latest_measurement_date", ""), "reconnect_required": withings_meta.get("needs_reconnect", False)},
    }
    base["health"] = [
        _health_card("hevy", "Hevy", "Connected" if hevy_configured else "Not configured", {"connected": hevy_configured}),
        _health_card("strava", "Strava", strava_status, strava_meta),
        _health_card("withings", "Withings", withings_status, withings_meta),
        _health_card("openai", "OpenAI", "Connected" if openai_configured else "Not configured", {"connected": openai_configured}),
    ]
    base["integrations"] = {
        **base.get("integrations", {}),
        "strava_access_token": _mask_present(_strava_tokens(settings).get("access_token")),
        "strava_refresh_token": _mask_present(_strava_tokens(settings).get("refresh_token")),
        "withings_access_token": _mask_present(_metadata(settings).get("withings_tokens", {}).get("access_token") if isinstance(_metadata(settings).get("withings_tokens"), dict) else ""),
        "withings_refresh_token": _mask_present(_metadata(settings).get("withings_tokens", {}).get("refresh_token") if isinstance(_metadata(settings).get("withings_tokens"), dict) else ""),
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
    metadata["strava_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "athlete_id": tokens.get("athlete_id", ""),
        "scopes": "",
    }
    metadata["strava_sync"] = {
        **(metadata.get("strava_sync") if isinstance(metadata.get("strava_sync"), dict) else {}),
        "needs_reconnect": bool(mark_error),
        "last_error": reason if mark_error else "",
        "last_synced_at": utc_now_iso(),
    }
    settings["metadata"] = metadata
    settings["updated_at"] = utc_now_iso()
    insert_json_row("api_connections", settings)


@router.get("/api/integrations/status")
def integrations_status(external_checks: bool = Query(default=False)) -> dict[str, Any]:
    return _integration_payload(external_checks=external_checks)


@router.get("/api/integrations/test")
def integrations_test() -> dict[str, Any]:
    settings = _settings_document()
    strava_status, _ = _strava_status(settings)
    withings_status, _ = _withings_status(settings)
    hevy_configured = bool(os.getenv("HEVY_API_KEY", "").strip() or _integrations(settings).get("hevy_api_key"))
    try:
        from src.ai.food_parser import get_openai_key_status

        openai_configured = get_openai_key_status()
    except Exception:
        openai_configured = bool(os.getenv("OPENAI_API_KEY", "").strip() or _integrations(settings).get("openai_api_key"))
    return {
        "checkedAt": utc_now_iso(),
        "hevy": _test_result("connected" if hevy_configured else "missing_api_key", "HEVY_API_KEY is configured." if hevy_configured else "HEVY_API_KEY is not configured."),
        "openai": _test_result("connected" if openai_configured else "missing_api_key", "OPENAI_API_KEY is configured." if openai_configured else "OPENAI_API_KEY is not configured."),
        "strava": _test_result(strava_status.lower().replace(" ", "_"), f"Strava is {strava_status.lower()}."),
        "withings": _test_result(withings_status.lower().replace(" ", "_"), f"Withings is {withings_status.lower()}."),
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


@router.get("/api/debug/strava")
def debug_strava() -> dict[str, Any]:
    settings = _settings_document()
    client_id, client_secret = _strava_credentials(settings)
    redirect_uri = os.getenv("STRAVA_REDIRECT_URI", "").strip() or str(_integrations(settings).get("strava_redirect_uri") or "").strip()
    tokens = _strava_tokens(settings)
    status, metadata = _strava_status(settings)
    if status == "Connected":
        next_action = "import_strava"
    elif status == "Expired/Reauth required":
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
        )
    except Exception as exc:
        return _withings_error(str(exc))
    items = fetch_json_rows("body_metric_logs", limit=1000, date_field="date")
    return {**result, "items": items if not (items and "_db_error" in items[0]) else []}


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
        )
    except Exception as exc:
        return _withings_error(str(exc))
    items = fetch_json_rows("body_metric_logs", limit=5000, date_field="date")
    return {**result, "items": items if not (items and "_db_error" in items[0]) else []}
