from __future__ import annotations

import os

from fastapi import APIRouter

from backend_v2.db import load_document

router = APIRouter(tags=["settings"])
INTEGRATION_FIELDS = ["hevy_api_key", "strava_client_id", "strava_client_secret", "strava_redirect_uri", "fitbit_client_id", "fitbit_client_secret", "withings_client_id", "withings_client_secret", "openai_api_key", "apple_health_export_file"]


def _mask_secret(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return "••••" if len(text) <= 4 else f"••••{text[-4:]}"


def _configured_from_env(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def settings_payload() -> dict:
    settings = load_document("user_settings", {"integrations": {}, "metadata": {"appearance": {"accent_color": "lime"}}}, timeout_ms=750)
    integrations = settings.get("integrations", {}) if isinstance(settings.get("integrations"), dict) else {}
    appearance = (settings.get("metadata", {}) or {}).get("appearance", {}) if isinstance(settings.get("metadata", {}), dict) else {}
    statuses = {key: "Configured" if integrations.get(key) else "Not configured" for key in INTEGRATION_FIELDS}
    statuses.update({"strava": "Check integrations", "withings": "Check integrations", "fitbit_google_health": "Prepared", "openai_api_key": "Configured" if _configured_from_env("OPENAI_API_KEY") or integrations.get("openai_api_key") else "Not configured"})
    return {"integrations": {key: _mask_secret(integrations.get(key, "")) for key in INTEGRATION_FIELDS}, "appearance": {"accent_color": appearance.get("accent_color") or "lime"}, "statuses": statuses, "health": [], "services": {}}


@router.get("/api/settings")
def get_settings() -> dict:
    return settings_payload()
