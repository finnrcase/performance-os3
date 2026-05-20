from __future__ import annotations

import os

from fastapi import APIRouter

from backend.app.core.database import load_document, save_document


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


def _mask_secret(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "••••"
    return f"••••{text[-4:]}"


def _configured_from_env(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _default_settings() -> dict:
    return {"integrations": {}, "metadata": {"appearance": {"accent_color": "lime"}}}


def settings_payload() -> dict:
    settings = load_document("user_settings", _default_settings(), timeout_ms=750)
    integrations = settings.get("integrations", {}) if isinstance(settings.get("integrations"), dict) else {}
    metadata = settings.get("metadata", {}) if isinstance(settings.get("metadata"), dict) else {}
    appearance = metadata.get("appearance", {}) if isinstance(metadata.get("appearance"), dict) else {}
    masked = {key: _mask_secret(integrations.get(key, "")) for key in INTEGRATION_FIELDS}
    statuses = {
        "hevy_api_key": "Configured" if integrations.get("hevy_api_key") or _configured_from_env("HEVY_API_KEY") else "Not configured",
        "strava": "Check integrations",
        "strava_client_id": "Configured" if _configured_from_env("STRAVA_CLIENT_ID") or integrations.get("strava_client_id") else "Not configured",
        "strava_client_secret": "Configured" if _configured_from_env("STRAVA_CLIENT_SECRET") or integrations.get("strava_client_secret") else "Not configured",
        "strava_redirect_uri": "Configured" if _configured_from_env("STRAVA_REDIRECT_URI") or integrations.get("strava_redirect_uri") else "Auto from app URL",
        "fitbit_client_id": "Configured" if integrations.get("fitbit_client_id") else "Not configured",
        "fitbit_client_secret": "Configured" if integrations.get("fitbit_client_secret") else "Not configured",
        "fitbit_google_health": "Prepared",
        "withings_client_id": "Configured" if _configured_from_env("WITHINGS_CLIENT_ID") or integrations.get("withings_client_id") else "Not configured",
        "withings_client_secret": "Configured" if _configured_from_env("WITHINGS_CLIENT_SECRET") or integrations.get("withings_client_secret") else "Not configured",
        "withings": "Check integrations",
        "openai_api_key": "Configured" if _configured_from_env("OPENAI_API_KEY") or integrations.get("openai_api_key") else "Not configured",
        "apple_health_export_file": "Configured" if integrations.get("apple_health_export_file") else "Not configured",
    }
    return {
        "integrations": masked,
        "appearance": {"accent_color": appearance.get("accent_color") or "lime"},
        "statuses": statuses,
        "health": [],
        "services": {},
    }


@router.get("/api/settings")
def get_settings() -> dict:
    return settings_payload()


@router.put("/api/settings")
def update_settings(payload: dict) -> dict:
    current = load_document("user_settings", _default_settings(), timeout_ms=750)
    merged = {**current, **payload}
    if "integrations" in payload and isinstance(payload["integrations"], dict):
        merged["integrations"] = {**(current.get("integrations") if isinstance(current.get("integrations"), dict) else {}), **payload["integrations"]}
    if "appearance" in payload and isinstance(payload["appearance"], dict):
        metadata = current.get("metadata") if isinstance(current.get("metadata"), dict) else {}
        merged["metadata"] = {**metadata, "appearance": {**(metadata.get("appearance") if isinstance(metadata.get("appearance"), dict) else {}), **payload["appearance"]}}
    save_document("user_settings", merged, timeout_ms=1000)
    return settings_payload()
