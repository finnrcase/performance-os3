"""Local settings management for Performance OS integrations."""

from __future__ import annotations

import json
from pathlib import Path

from src.paths import processed_data_path
from src.storage import load_document, save_document

SETTINGS_PATH = processed_data_path("user_settings.json")

INTEGRATION_FIELDS = {
    "hevy_api_key": "",
    "strava_client_id": "",
    "strava_client_secret": "",
    "fitbit_client_id": "",
    "fitbit_client_secret": "",
    "withings_client_id": "",
    "withings_client_secret": "",
    "openai_api_key": "",
    "apple_health_export_file": "",
}

STRAVA_TOKEN_FIELDS = {
    "access_token": "",
    "refresh_token": "",
    "expires_at": 0,
    "athlete_id": "",
}


def default_settings() -> dict:
    """Return the default local settings shape."""
    return {
        "integrations": INTEGRATION_FIELDS.copy(),
        "metadata": {
            "version": 1,
            "strava_tokens": STRAVA_TOKEN_FIELDS.copy(),
        },
    }


def load_settings() -> dict:
    """Load local settings from data/processed/user_settings.json."""
    settings = default_settings()
    saved = load_document("user_settings", SETTINGS_PATH, settings)

    saved_integrations = saved.get("integrations", {})
    settings["integrations"].update(
        {
            key: str(saved_integrations.get(key, ""))
            for key in INTEGRATION_FIELDS
        }
    )
    settings["metadata"].update(saved.get("metadata", {}))
    saved_tokens = saved.get("metadata", {}).get("strava_tokens", {})
    settings["metadata"]["strava_tokens"] = {
        key: saved_tokens.get(key, default)
        for key, default in STRAVA_TOKEN_FIELDS.items()
    }
    return settings


def save_settings(settings: dict) -> None:
    """Persist local settings. The file is ignored by git."""
    normalized = default_settings()
    normalized["integrations"].update(
        {
            key: str(settings.get("integrations", {}).get(key, ""))
            for key in INTEGRATION_FIELDS
        }
    )
    normalized["metadata"].update(settings.get("metadata", {}))
    tokens = settings.get("metadata", {}).get("strava_tokens", {})
    normalized["metadata"]["strava_tokens"] = {
        key: tokens.get(key, default)
        for key, default in STRAVA_TOKEN_FIELDS.items()
    }
    save_document("user_settings", SETTINGS_PATH, normalized)


def mask_secret(value: str) -> str:
    """Mask a saved secret for UI display."""
    if not value:
        return "Not configured"
    if len(value) <= 4:
        return "••••"
    return f"••••••{value[-4:]}"


def integration_status(key: str, settings: dict) -> str:
    """Return a human-readable status for integration config."""
    integrations = settings.get("integrations", {})
    value = integrations.get(key, "")
    if key == "apple_health_export_file":
        return "Local upload only"
    if key == "strava_connection":
        tokens = settings.get("metadata", {}).get("strava_tokens", {})
        if tokens.get("access_token") and tokens.get("refresh_token"):
            return "Connected"
        if integrations.get("strava_client_id") and integrations.get("strava_client_secret"):
            return "Ready to connect"
        return "Not configured"
    if key in {"fitbit_client_id", "fitbit_client_secret", "withings_client_id", "withings_client_secret"}:
        return "Configured" if value else "Not configured"
    if key in {"strava_client_id", "strava_client_secret"}:
        return "Needs OAuth setup" if value else "Not configured"
    return "Configured" if value else "Not configured"


def fitbit_google_health_status(settings: dict) -> str:
    """Return the prepared Fitbit/Google Health connection state."""
    integrations = settings.get("integrations", {})
    metadata = settings.get("metadata", {})
    if metadata.get("fitbit_connected") or metadata.get("google_health_connected"):
        return "Connected"
    has_client_id = bool(integrations.get("fitbit_client_id"))
    has_client_secret = bool(integrations.get("fitbit_client_secret"))
    if has_client_id and has_client_secret:
        return "Configured"
    if has_client_id or has_client_secret:
        return "Sync pending"
    return "Not configured"
