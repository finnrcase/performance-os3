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
    "google_health_client_id",
    "google_health_client_secret",
    "google_health_redirect_uri",
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
    "fitbit_client_id": "FITBIT_CLIENT_ID",
    "fitbit_client_secret": "FITBIT_CLIENT_SECRET",
    "google_health_client_id": "GOOGLE_HEALTH_CLIENT_ID",
    "google_health_client_secret": "GOOGLE_HEALTH_CLIENT_SECRET",
    "google_health_redirect_uri": "GOOGLE_HEALTH_REDIRECT_URI",
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
    access_token = os.getenv("STRAVA_ACCESS_TOKEN", "").strip() or str(integrations.get("strava_access_token") or tokens.get("access_token") or "").strip()
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN", "").strip() or str(integrations.get("strava_refresh_token") or tokens.get("refresh_token") or "").strip()
    try:
        expires_at = int(os.getenv("STRAVA_EXPIRES_AT", "").strip() or os.getenv("STRAVA_TOKEN_EXPIRES_AT", "").strip() or integrations.get("strava_expires_at") or tokens.get("expires_at") or 0)
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
    if not has_credentials:
        status = "Not configured"
        token_status = "missing"
    elif sync.get("needs_reconnect"):
        status = "Reconnect required"
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
        "athlete_id": str(os.getenv("STRAVA_ATHLETE_ID", "").strip() or integrations.get("strava_athlete_id") or tokens.get("athlete_id") or ""),
        "expires_at": expires_at or None,
        "last_synced_at": sync.get("last_synced_at", ""),
        "latest_record": sync.get("latest_activity_date", ""),
        "last_error": sync.get("last_error", ""),
        "reconnect_required": bool(sync.get("needs_reconnect") and has_credentials),
        "imported_runs": sync.get("last_imported_count", 0),
        "updated_runs": sync.get("last_updated_count", 0),
        "fetched_activities": sync.get("last_fetched_count", 0),
    }


def _google_health_connection(settings: dict[str, Any], integrations: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("google_health_tokens") if isinstance(metadata.get("google_health_tokens"), dict) else {}
    sync = metadata.get("google_health_sync") if isinstance(metadata.get("google_health_sync"), dict) else {}
    has_credentials = (
        integrations.get("google_health_client_id")
        and integrations.get("google_health_client_secret")
    ) or (
        _configured_from_env("google_health_client_id")
        and _configured_from_env("google_health_client_secret")
    )
    refresh_token = str(tokens.get("refresh_token") or "").strip()
    access_token = str(tokens.get("access_token") or "").strip()
    if not has_credentials:
        status = "Not configured"
    elif sync.get("needs_reconnect"):
        status = "Reconnect required"
    elif refresh_token:
        status = "Connected"
    else:
        status = "Disconnected"
    return status, {
        "connected": status == "Connected",
        "configured": bool(has_credentials),
        "token_status": "reconnect_required" if sync.get("needs_reconnect") else "valid" if refresh_token else "missing",
        "access_token_present": bool(access_token),
        "refresh_token_present": bool(refresh_token),
        "last_synced_at": sync.get("last_synced_at", ""),
        "latest_record": sync.get("latest_record", ""),
        "last_error": sync.get("last_error", ""),
        "reconnect_required": bool(sync.get("needs_reconnect") and has_credentials),
        "imported_metrics": sync.get("last_imported_count", 0),
        "fetched_days": sync.get("last_fetched_count", 0),
    }


def _fitbit_connection(settings: dict[str, Any], integrations: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("fitbit_tokens") if isinstance(metadata.get("fitbit_tokens"), dict) else {}
    sync = metadata.get("fitbit_sync") if isinstance(metadata.get("fitbit_sync"), dict) else {}
    has_credentials = (
        integrations.get("fitbit_client_id")
        and integrations.get("fitbit_client_secret")
    ) or (
        _configured_from_env("fitbit_client_id")
        and _configured_from_env("fitbit_client_secret")
    )
    access_token = os.getenv("FITBIT_ACCESS_TOKEN", "").strip() or str(integrations.get("fitbit_access_token") or tokens.get("access_token") or "").strip()
    refresh_token = os.getenv("FITBIT_REFRESH_TOKEN", "").strip() or str(integrations.get("fitbit_refresh_token") or tokens.get("refresh_token") or "").strip()
    scopes = os.getenv("FITBIT_SCOPES", "").strip() or str(integrations.get("fitbit_scopes") or tokens.get("scopes") or "").strip()
    try:
        expires_at = int(os.getenv("FITBIT_EXPIRES_AT", "").strip() or os.getenv("FITBIT_TOKEN_EXPIRES_AT", "").strip() or integrations.get("fitbit_expires_at") or tokens.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    access_expired = bool(access_token and expires_at and expires_at <= int(time.time()))
    if not has_credentials:
        status = "Not configured"
    elif sync.get("needs_reconnect"):
        status = "Reconnect required"
    elif access_token or refresh_token:
        status = "Connected"
    else:
        status = "Disconnected"
    token_status = (
        "reconnect_required" if sync.get("needs_reconnect")
        else "access_expired_refresh_available" if access_token and access_expired and refresh_token
        else "valid" if access_token and not access_expired
        else "refresh_available" if refresh_token
        else "missing"
    )
    return status, {
        "connected": status == "Connected",
        "configured": bool(has_credentials),
        "token_status": token_status,
        "access_token_present": bool(access_token),
        "refresh_token_present": bool(refresh_token),
        "scopes": scopes,
        "expires_at": expires_at or None,
        "last_synced_at": sync.get("last_successful_sync", "") or sync.get("last_synced_at", ""),
        "latest_record": sync.get("latest_record", ""),
        "last_error": sync.get("last_error", ""),
        "last_status": sync.get("last_status", ""),
        "last_message": sync.get("last_message", ""),
        "reconnect_required": bool(sync.get("needs_reconnect") and has_credentials),
        "imported_metrics": sync.get("last_stored_count", 0),
        "fetched_days": sync.get("last_fetched_count", 0),
        "parsed_metrics": sync.get("last_parsed_count", 0),
    }


def _openai_status(openai_config: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    configured = bool(openai_config.get("openai_key_configured"))
    last_test = metadata.get("openai_last_test") if isinstance(metadata.get("openai_last_test"), dict) else {}
    label = "Missing"
    status = "missing_api_key"
    message = "OpenAI API key is missing. Manual food logging still works."
    if configured:
        label = "Configured"
        status = "configured"
        message = "OpenAI key exists. Run Test OpenAI to verify auth, model, SDK, and network."
    if configured and last_test:
        test_status = str(last_test.get("test_status") or "").lower()
        error_type = str(last_test.get("error_type") or "")
        if test_status == "ok":
            label = "Connected"
            status = "connected"
            message = str(last_test.get("message") or "OpenAI test request succeeded.")
        elif error_type in {"AuthenticationError"}:
            label = "Auth failed"
            status = "auth_failed"
            message = str(last_test.get("message") or "OpenAI rejected the configured API key.")
        elif error_type in {"ModelConfigurationError", "ModelInvalidError"}:
            label = "Model invalid"
            status = "model_invalid"
            message = str(last_test.get("message") or "OpenAI model configuration is invalid.")
        elif error_type in {"RateLimitError"}:
            label = "Rate limited"
            status = "rate_limited"
            message = str(last_test.get("message") or "OpenAI quota or rate limit was reached.")
        else:
            label = "Request failed"
            status = "request_failed"
            message = str(last_test.get("message") or "OpenAI test request failed.")
    return {
        "configured": configured,
        "label": label,
        "status": status,
        "message": message,
        "model": openai_config.get("model", ""),
        "api_key_source": openai_config.get("api_key_source", "unknown"),
        "last_checked_at": metadata.get("openai_last_test_at", ""),
        "last_test_status": last_test.get("test_status", ""),
        "last_error_type": last_test.get("error_type", ""),
        "response_ms": last_test.get("response_ms", last_test.get("latency_ms")),
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
    openai_service = _openai_status(openai_config, metadata)
    statuses["openai_api_key"] = openai_service["label"]
    withings_status = _withings_status(settings, integrations)
    strava_status, strava_service = _strava_connection(settings, integrations)
    google_health_status, google_health_service = _google_health_connection(settings, integrations)
    fitbit_status, fitbit_service = _fitbit_connection(settings, integrations)
    wearable_credentials_configured = all(
        statuses.get(field) == "Configured"
        for field in ["fitbit_client_id", "fitbit_client_secret"]
    ) or all(
        statuses.get(field) == "Configured"
        for field in ["google_health_client_id", "google_health_client_secret"]
    )
    statuses.update(
        {
            "strava": strava_status,
            "withings": withings_status,
            "google_health": google_health_status,
            "fitbit": fitbit_status,
            "fitbit_google_health": "Configured" if wearable_credentials_configured else "Prepared",
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
            "status": "connected" if strava_status == "Connected" else "needs_reconnect" if strava_status in {"Reconnect required", "Expired/Reauth required"} else "disconnected" if strava_status == "Disconnected" else "not_configured",
            "message": "Strava import is manual in backend_new. Startup never calls the Strava API.",
            **strava_service,
        },
        "withings": withings_service,
        "fitbit_google_health": {
            "configured": wearable_credentials_configured,
            "status": "configured" if wearable_credentials_configured else "placeholder",
            "message": "Wearable storage and manual/mock metrics are ready.",
        },
        "fitbit": {
            "configured": fitbit_service["configured"],
            "status": "connected" if fitbit_status == "Connected" else "needs_reconnect" if fitbit_status == "Reconnect required" else "disconnected" if fitbit_status == "Disconnected" else "not_configured",
            "message": "Fitbit debug sync is available from Settings Advanced / Debug.",
            **fitbit_service,
        },
        "google_health": {
            "configured": google_health_service["configured"],
            "status": "connected" if google_health_status == "Connected" else "needs_reconnect" if google_health_status == "Reconnect required" else "disconnected" if google_health_status == "Disconnected" else "not_configured",
            "message": "Google Health daily sync is available from Settings.",
            **google_health_service,
        },
        "openai": {
            **openai_service,
        },
    }
    health = [
        {
            "id": "google_health",
            "name": "Google Health",
            "status": "green" if google_health_status == "Connected" else "yellow" if google_health_status in {"Disconnected", "Reconnect required"} else "gray",
            "message": services["google_health"]["message"],
            "last_synced_at": google_health_service["last_synced_at"],
            "latest_record": google_health_service["latest_record"],
            "action": "google_health_sync" if google_health_status == "Connected" else "google_health_reconnect" if google_health_status == "Reconnect required" else "google_health_connect",
            "metadata": {
                "connection": google_health_status,
                "configured": google_health_service["configured"],
                "reconnect_required": google_health_service["reconnect_required"],
                "token_status": google_health_service["token_status"],
                "imported_metrics": google_health_service["imported_metrics"],
                "fetched_days": google_health_service["fetched_days"],
                "latest_record": google_health_service["latest_record"],
                "last_error": google_health_service["last_error"],
            },
        },
        {
            "id": "fitbit",
            "name": "Fitbit",
            "status": "green" if fitbit_status == "Connected" else "yellow" if fitbit_status in {"Disconnected", "Reconnect required"} else "gray",
            "message": services["fitbit"]["message"],
            "last_synced_at": fitbit_service["last_synced_at"],
            "latest_record": fitbit_service["latest_record"],
            "action": "fitbit_debug_sync",
            "metadata": {
                "connection": fitbit_status,
                "configured": fitbit_service["configured"],
                "reconnect_required": fitbit_service["reconnect_required"],
                "token_status": fitbit_service["token_status"],
                "imported_metrics": fitbit_service["imported_metrics"],
                "fetched_days": fitbit_service["fetched_days"],
                "latest_record": fitbit_service["latest_record"],
                "last_error": fitbit_service["last_error"],
                "last_status": fitbit_service["last_status"],
            },
        },
        {
            "id": "strava",
            "name": "Strava",
            "status": "green" if strava_status == "Connected" else "yellow" if strava_status in {"Disconnected", "Reconnect required", "Expired/Reauth required"} else "gray",
            "message": services["strava"]["message"],
            "last_synced_at": strava_service["last_synced_at"],
            "latest_record": strava_service["latest_record"],
            "action": "strava_import" if strava_status == "Connected" else "strava_reconnect" if strava_status in {"Reconnect required", "Expired/Reauth required"} else "strava_connect",
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
        "google_health": {
            "status": google_health_status,
            "last_successful_sync": google_health_service["last_synced_at"],
            "latest_record": google_health_service["latest_record"],
            "reconnect_required": google_health_service["reconnect_required"],
            "last_error": google_health_service["last_error"],
        },
        "fitbit": {
            "status": fitbit_status,
            "last_successful_sync": fitbit_service["last_synced_at"],
            "latest_record": fitbit_service["latest_record"],
            "reconnect_required": fitbit_service["reconnect_required"],
            "last_error": fitbit_service["last_error"],
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
