"""Local settings management for Performance OS integrations."""

from __future__ import annotations

import json
from pathlib import Path

from src.paths import processed_data_path
from src.storage import load_document, save_document

SETTINGS_PATH = processed_data_path("user_settings.json")
ACCENT_COLORS = {"lime", "pink", "purple", "orange", "blue", "rainbow"}

INTEGRATION_FIELDS = {
    "hevy_api_key": "",
    "strava_client_id": "",
    "strava_client_secret": "",
    "strava_redirect_uri": "",
    "fitbit_client_id": "",
    "fitbit_client_secret": "",
    "google_health_client_id": "",
    "google_health_client_secret": "",
    "google_health_redirect_uri": "",
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
    "scopes": "",
}

STRAVA_SYNC_FIELDS = {
    "last_synced_at": "",
    "last_error": "",
    "last_imported_count": 0,
    "last_updated_count": 0,
    "last_fetched_count": 0,
    "latest_activity_date": "",
    "needs_reconnect": False,
}

WITHINGS_TOKEN_FIELDS = {
    "access_token": "",
    "refresh_token": "",
    "expires_at": 0,
    "userid": "",
    "scopes": "",
    "token_type": "",
}

WITHINGS_SYNC_FIELDS = {
    "last_synced_at": "",
    "last_error": "",
    "last_imported_count": 0,
    "last_fetched_groups": 0,
    "latest_measure_date": "",
    "needs_reconnect": False,
}

GOOGLE_HEALTH_TOKEN_FIELDS = {
    "access_token": "",
    "refresh_token": "",
    "expires_at": 0,
    "token_type": "",
    "scopes": "",
}

GOOGLE_HEALTH_SYNC_FIELDS = {
    "last_synced_at": "",
    "last_error": "",
    "last_imported_count": 0,
    "last_fetched_count": 0,
    "last_record_counts": {},
    "last_warning_count": 0,
    "last_storage_error_count": 0,
    "latest_record": "",
    "needs_reconnect": False,
}


def normalize_accent_color(value: object) -> str:
    """Return a supported accent theme id, preserving lime as the default."""
    normalized = str(value or "lime").strip().lower()
    return normalized if normalized in ACCENT_COLORS else "lime"


def default_settings() -> dict:
    """Return the default local settings shape."""
    return {
        "integrations": INTEGRATION_FIELDS.copy(),
        "metadata": {
            "version": 1,
            "appearance": {"accent_color": "lime"},
            "strava_tokens": STRAVA_TOKEN_FIELDS.copy(),
            "strava_sync": STRAVA_SYNC_FIELDS.copy(),
            "withings_tokens": WITHINGS_TOKEN_FIELDS.copy(),
            "withings_sync": WITHINGS_SYNC_FIELDS.copy(),
            "google_health_tokens": GOOGLE_HEALTH_TOKEN_FIELDS.copy(),
            "google_health_sync": GOOGLE_HEALTH_SYNC_FIELDS.copy(),
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
    saved_appearance = saved.get("metadata", {}).get("appearance", {})
    settings["metadata"]["appearance"] = {
        "accent_color": normalize_accent_color(saved_appearance.get("accent_color") or settings["metadata"].get("appearance", {}).get("accent_color"))
    }
    saved_tokens = saved.get("metadata", {}).get("strava_tokens", {})
    settings["metadata"]["strava_tokens"] = {
        key: saved_tokens.get(key, default)
        for key, default in STRAVA_TOKEN_FIELDS.items()
    }
    saved_sync = saved.get("metadata", {}).get("strava_sync", {})
    settings["metadata"]["strava_sync"] = {
        key: saved_sync.get(key, default)
        for key, default in STRAVA_SYNC_FIELDS.items()
    }
    saved_withings_tokens = saved.get("metadata", {}).get("withings_tokens", {})
    settings["metadata"]["withings_tokens"] = {
        key: saved_withings_tokens.get(key, default)
        for key, default in WITHINGS_TOKEN_FIELDS.items()
    }
    saved_withings_sync = saved.get("metadata", {}).get("withings_sync", {})
    settings["metadata"]["withings_sync"] = {
        key: saved_withings_sync.get(key, default)
        for key, default in WITHINGS_SYNC_FIELDS.items()
    }
    saved_google_health_tokens = saved.get("metadata", {}).get("google_health_tokens", {})
    settings["metadata"]["google_health_tokens"] = {
        key: saved_google_health_tokens.get(key, default)
        for key, default in GOOGLE_HEALTH_TOKEN_FIELDS.items()
    }
    saved_google_health_sync = saved.get("metadata", {}).get("google_health_sync", {})
    settings["metadata"]["google_health_sync"] = {
        key: saved_google_health_sync.get(key, default)
        for key, default in GOOGLE_HEALTH_SYNC_FIELDS.items()
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
    appearance = settings.get("metadata", {}).get("appearance", {})
    normalized["metadata"]["appearance"] = {
        "accent_color": normalize_accent_color(appearance.get("accent_color"))
    }
    tokens = settings.get("metadata", {}).get("strava_tokens", {})
    normalized["metadata"]["strava_tokens"] = {
        key: tokens.get(key, default)
        for key, default in STRAVA_TOKEN_FIELDS.items()
    }
    sync = settings.get("metadata", {}).get("strava_sync", {})
    normalized["metadata"]["strava_sync"] = {
        key: sync.get(key, default)
        for key, default in STRAVA_SYNC_FIELDS.items()
    }
    withings_tokens = settings.get("metadata", {}).get("withings_tokens", {})
    normalized["metadata"]["withings_tokens"] = {
        key: withings_tokens.get(key, default)
        for key, default in WITHINGS_TOKEN_FIELDS.items()
    }
    withings_sync = settings.get("metadata", {}).get("withings_sync", {})
    normalized["metadata"]["withings_sync"] = {
        key: withings_sync.get(key, default)
        for key, default in WITHINGS_SYNC_FIELDS.items()
    }
    google_health_tokens = settings.get("metadata", {}).get("google_health_tokens", {})
    normalized["metadata"]["google_health_tokens"] = {
        key: google_health_tokens.get(key, default)
        for key, default in GOOGLE_HEALTH_TOKEN_FIELDS.items()
    }
    google_health_sync = settings.get("metadata", {}).get("google_health_sync", {})
    normalized["metadata"]["google_health_sync"] = {
        key: google_health_sync.get(key, default)
        for key, default in GOOGLE_HEALTH_SYNC_FIELDS.items()
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
        if tokens.get("refresh_token"):
            return "Connected"
        if integrations.get("strava_client_id") and integrations.get("strava_client_secret"):
            return "Disconnected"
        return "Not configured"
    if key == "withings_connection":
        tokens = settings.get("metadata", {}).get("withings_tokens", {})
        if tokens.get("access_token") and tokens.get("refresh_token"):
            return "Connected"
        if integrations.get("withings_client_id") and integrations.get("withings_client_secret"):
            return "Ready to connect"
        return "Not configured"
    if key == "google_health_connection":
        tokens = settings.get("metadata", {}).get("google_health_tokens", {})
        sync = settings.get("metadata", {}).get("google_health_sync", {})
        if sync.get("needs_reconnect"):
            return "Reconnect required"
        if tokens.get("refresh_token"):
            return "Connected"
        if integrations.get("google_health_client_id") and integrations.get("google_health_client_secret"):
            return "Disconnected"
        return "Not configured"
    if key in {
        "fitbit_client_id",
        "fitbit_client_secret",
        "google_health_client_id",
        "google_health_client_secret",
        "google_health_redirect_uri",
        "withings_client_id",
        "withings_client_secret",
    }:
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
    fitbit_configured = bool(integrations.get("fitbit_client_id") and integrations.get("fitbit_client_secret"))
    google_configured = bool(
        integrations.get("google_health_client_id")
        and integrations.get("google_health_client_secret")
    )
    if fitbit_configured and google_configured:
        return "Configured"
    if fitbit_configured or google_configured:
        return "Configured"
    if any(
        integrations.get(key)
        for key in [
            "fitbit_client_id",
            "fitbit_client_secret",
            "google_health_client_id",
            "google_health_client_secret",
        ]
    ):
        return "Sync pending"
    return "Not configured"
