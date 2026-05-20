from __future__ import annotations

import os
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
    withings_status = _withings_status(settings, integrations)
    statuses.update(
        {
            "strava": "Configured" if statuses["strava_client_id"] == "Configured" and statuses["strava_client_secret"] == "Configured" else "Not configured",
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
        "strava": {"configured": statuses["strava"] == "Configured", "status": "disabled", "message": "Strava sync is disabled in backend_new."},
        "withings": withings_service,
        "openai": {"configured": statuses["openai_api_key"] == "Configured", "status": "disabled", "message": "AI enrichment is disabled in backend_new."},
    }
    health = [
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
