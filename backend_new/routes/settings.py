from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter

from backend_new.db import fetch_latest_document, insert_json_row
from backend_new.utils import utc_now_iso

router = APIRouter(tags=["settings"])

INTEGRATION_FIELDS = [
    "hevy_api_key",
    "strava_client_id",
    "strava_client_secret",
    "strava_redirect_uri",
    "fitbit_client_id",
    "fitbit_client_secret",
    "withings_client_id",
    "withings_client_secret",
    "openai_api_key",
    "apple_health_export_file",
]

ENV_BY_FIELD = {
    "hevy_api_key": "HEVY_API_KEY",
    "strava_client_id": "STRAVA_CLIENT_ID",
    "strava_client_secret": "STRAVA_CLIENT_SECRET",
    "strava_redirect_uri": "STRAVA_REDIRECT_URI",
    "withings_client_id": "WITHINGS_CLIENT_ID",
    "withings_client_secret": "WITHINGS_CLIENT_SECRET",
    "openai_api_key": "OPENAI_API_KEY",
}

MASK_PREFIXES = ("••••", "***")


def _default_settings() -> dict[str, Any]:
    return {
        "integrations": {},
        "metadata": {"appearance": {"accent_color": "lime"}},
    }


def _mask_secret(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "••••" if len(text) <= 4 else f"••••{text[-4:]}"


def _configured_from_env(field: str) -> bool:
    env_name = ENV_BY_FIELD.get(field)
    return bool(env_name and os.getenv(env_name, "").strip())


def _status_for_field(field: str, integrations: dict[str, Any]) -> str:
    return "Configured" if integrations.get(field) or _configured_from_env(field) else "Not configured"


def _withings_status(settings: dict[str, Any], integrations: dict[str, Any]) -> str:
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("withings_tokens") if isinstance(metadata.get("withings_tokens"), dict) else {}
    sync = metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}
    if sync.get("needs_reconnect"):
        return "Disconnected"
    if tokens.get("access_token") and tokens.get("refresh_token"):
        return "Connected"
    has_credentials = (
        integrations.get("withings_client_id")
        and integrations.get("withings_client_secret")
    ) or (
        _configured_from_env("withings_client_id")
        and _configured_from_env("withings_client_secret")
    )
    return "Ready to connect" if has_credentials else "Not configured"


def _strava_connection(settings: dict[str, Any], integrations: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("strava_tokens") if isinstance(metadata.get("strava_tokens"), dict) else {}
    sync = metadata.get("strava_sync") if isinstance(metadata.get("strava_sync"), dict) else {}
    access_token = os.getenv("STRAVA_ACCESS_TOKEN", "").strip() or str(tokens.get("access_token") or "").strip()
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN", "").strip() or str(tokens.get("refresh_token") or "").strip()
    try:
        expires_at = int(os.getenv("STRAVA_EXPIRES_AT", "").strip() or os.getenv("STRAVA_TOKEN_EXPIRES_AT", "").strip() or tokens.get("expires_at") or 0)
    except ValueError:
        expires_at = 0
    has_credentials = (
        integrations.get("strava_client_id")
        and integrations.get("strava_client_secret")
    ) or (
        _configured_from_env("strava_client_id")
        and _configured_from_env("strava_client_secret")
    )
    access_expired = bool(access_token and expires_at and expires_at <= int(time.time()))
    has_tokens = bool(access_token or refresh_token)
    if sync.get("needs_reconnect") and has_tokens:
        status = "Expired/Reauth required"
        token_status = "reconnect_required"
    elif refresh_token:
        status = "Connected"
        token_status = "access_expired_refresh_available" if access_expired else "valid" if access_token else "refresh_available"
    elif has_credentials:
        status = "Disconnected"
        token_status = "missing"
    else:
        status = "Not configured"
        token_status = "missing"
    return status, {
        "connected": status == "Connected",
        "configured": bool(has_credentials),
        "token_status": token_status,
        "access_token_present": bool(access_token),
        "refresh_token_present": bool(refresh_token),
        "athlete_id": str(os.getenv("STRAVA_ATHLETE_ID", "").strip() or tokens.get("athlete_id") or ""),
        "expires_at": expires_at or None,
        "last_synced_at": sync.get("last_synced_at", ""),
        "latest_record": sync.get("latest_activity_date", ""),
        "last_error": sync.get("last_error", ""),
        "reconnect_required": bool(sync.get("needs_reconnect") and has_tokens),
        "imported_runs": sync.get("last_imported_count", 0),
        "updated_runs": sync.get("last_updated_count", 0),
        "fetched_activities": sync.get("last_fetched_count", 0),
    }


def _saved_settings() -> dict[str, Any]:
    stored = fetch_latest_document("api_connections", _default_settings())
    if not isinstance(stored, dict):
        return _default_settings()
    return {**_default_settings(), **stored}


def _appearance(settings: dict[str, Any]) -> dict[str, Any]:
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    appearance = metadata.get("appearance") if isinstance(metadata.get("appearance"), dict) else {}
    return {"accent_color": appearance.get("accent_color") or "lime"}


def settings_payload() -> dict[str, Any]:
    settings = _saved_settings()
    integrations = settings.get("integrations") if isinstance(settings.get("integrations"), dict) else {}
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    withings_sync = metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}
    statuses = {field: _status_for_field(field, integrations) for field in INTEGRATION_FIELDS}
    try:
        from src.ai.food_parser import openai_analyzer_config

        openai_config = openai_analyzer_config()
    except Exception:
        openai_config = {"openai_key_configured": statuses["openai_api_key"] == "Configured", "model": "", "api_key_source": "unknown"}
    statuses["openai_api_key"] = "Configured" if openai_config.get("openai_key_configured") else "Not configured"
    withings_status = _withings_status(settings, integrations)
    strava_status, strava_service = _strava_connection(settings, integrations)
    statuses.update(
        {
            "strava": strava_status,
            "withings": withings_status,
            "fitbit_google_health": "Prepared",
        }
    )
    withings_service = {
        "configured": withings_status in {"Ready to connect", "Connected", "Disconnected"},
        "status": "connected" if withings_status == "Connected" else "needs_reconnect" if withings_status == "Disconnected" else "ready" if withings_status == "Ready to connect" else "not_configured",
        "message": "Withings sync is manual in backend_new. Startup never calls the Withings API.",
        "last_synced_at": withings_sync.get("last_synced_at", ""),
        "latest_record": withings_sync.get("latest_measure_date") or withings_sync.get("latest_measurement_date") or "",
        "last_error": withings_sync.get("last_error", ""),
        "reconnect_required": bool(withings_sync.get("needs_reconnect")),
        "imported_measurements": withings_sync.get("last_imported_count", 0),
        "fetched_groups": withings_sync.get("last_fetched_groups", 0),
    }
    services = {
        "hevy": {"configured": statuses["hevy_api_key"] == "Configured", "status": "disabled", "message": "Hevy sync is disabled in backend_new."},
        "strava": {
            "configured": strava_service["configured"],
            "status": "connected" if strava_status == "Connected" else "needs_reconnect" if strava_status == "Expired/Reauth required" else "disconnected" if strava_status == "Disconnected" else "not_configured",
            "message": "Strava import is manual in backend_new. Startup never calls the Strava API.",
            **strava_service,
        },
        "withings": withings_service,
        "openai": {
            "configured": statuses["openai_api_key"] == "Configured",
            "status": "configured" if statuses["openai_api_key"] == "Configured" else "missing_api_key",
            "message": "OpenAI analyzer key is configured; use the OpenAI test button for a live Working check." if statuses["openai_api_key"] == "Configured" else "OpenAI analyzer is not configured.",
            "model": openai_config.get("model", ""),
            "api_key_source": openai_config.get("api_key_source", "unknown"),
        },
    }
    health = [
        {
            "id": "strava",
            "name": "Strava",
            "status": "green" if strava_status == "Connected" else "yellow" if strava_status in {"Disconnected", "Expired/Reauth required"} else "gray",
            "message": services["strava"]["message"],
            "last_synced_at": strava_service["last_synced_at"],
            "latest_record": strava_service["latest_record"],
            "action": "strava_import" if strava_status == "Connected" else "strava_reconnect" if strava_status == "Expired/Reauth required" else "strava_connect",
            "metadata": {
                "connection": strava_status,
                "configured": strava_service["configured"],
                "reconnect_required": strava_service["reconnect_required"],
                "token_status": strava_service["token_status"],
                "imported_runs": strava_service["imported_runs"],
                "updated_runs": strava_service["updated_runs"],
                "fetched_activities": strava_service["fetched_activities"],
            },
        },
        {
            "id": "withings",
            "name": "Withings",
            "status": "green" if withings_status == "Connected" else "yellow" if withings_status == "Ready to connect" else "red" if withings_status == "Disconnected" else "gray",
            "message": withings_service["message"],
            "last_synced_at": withings_service["last_synced_at"],
            "latest_record": withings_service["latest_record"],
            "action": "withings_sync" if withings_status == "Connected" else "withings_connect",
            "metadata": {
                "connection": withings_status,
                "reconnect_required": withings_service["reconnect_required"],
                "imported_measurements": withings_service["imported_measurements"],
                "fetched_groups": withings_service["fetched_groups"],
            },
        }
    ]
    return {
        "overall_status": "ok",
        "environment": os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "production",
        "checked_at": utc_now_iso(),
        "integrations": {field: _mask_secret(integrations.get(field, "")) for field in INTEGRATION_FIELDS},
        "appearance": _appearance(settings),
        "statuses": statuses,
        "health": health,
        "services": services,
        "withings": {
            "status": withings_status,
            "last_successful_sync": withings_service["last_synced_at"],
            "latest_measure_date": withings_service["latest_record"],
            "reconnect_required": withings_service["reconnect_required"],
        },
    }


def _merge_integrations(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for field in INTEGRATION_FIELDS:
        if field not in incoming:
            continue
        value = str(incoming.get(field) or "").strip()
        if not value or value.startswith(MASK_PREFIXES):
            continue
        merged[field] = value
    return merged


@router.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return settings_payload()


@router.put("/api/settings")
def put_settings(payload: dict[str, Any]) -> dict[str, Any]:
    current = _saved_settings()
    current_integrations = current.get("integrations") if isinstance(current.get("integrations"), dict) else {}
    metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
    appearance = metadata.get("appearance") if isinstance(metadata.get("appearance"), dict) else {}

    next_settings = dict(current)
    if isinstance(payload.get("integrations"), dict):
        next_settings["integrations"] = _merge_integrations(current_integrations, payload["integrations"])
    if isinstance(payload.get("appearance"), dict):
        next_settings["metadata"] = {
            **metadata,
            "appearance": {**appearance, **payload["appearance"]},
        }
    next_settings["updated_at"] = utc_now_iso()
    insert_json_row("api_connections", next_settings)
    return settings_payload()
