from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.config import INTEGRATION_FIELDS, fitbit_google_health_status, integration_status, load_settings, mask_secret, save_settings
from src.integrations.strava_client import (
    StravaIntegrationError,
    build_strava_auth_url,
    exchange_strava_code,
    get_strava_connection_status,
)


router = APIRouter(tags=["integrations"])


@router.get("/status")
def status() -> dict:
    """Return placeholder route status."""
    return {"status": "placeholder", "module": "integrations"}


class SettingsPayload(BaseModel):
    integrations: dict[str, str] = {}


def _read_dotenv_value(key: str) -> str:
    """Read local .env config without returning secret values."""
    from pathlib import Path

    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if not dotenv_path.exists():
        return ""
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _configured_from_env(key: str) -> bool:
    """Return whether a key exists in env or .env without exposing it."""
    import os

    return bool(os.getenv(key, "").strip() or _read_dotenv_value(key).strip())


def _settings_response(settings: dict) -> dict:
    """Return settings with secrets masked for frontend display."""
    integrations = settings.get("integrations", {})
    masked = {
        key: mask_secret(integrations.get(key, ""))
        for key in INTEGRATION_FIELDS
    }
    openai_configured = bool(integrations.get("openai_api_key")) or _configured_from_env("OPENAI_API_KEY")
    statuses = {
        "hevy_api_key": integration_status("hevy_api_key", settings),
        "strava": get_strava_connection_status(),
        "strava_client_id": integration_status("strava_client_id", settings),
        "strava_client_secret": integration_status("strava_client_secret", settings),
        "fitbit_client_id": integration_status("fitbit_client_id", settings),
        "fitbit_client_secret": integration_status("fitbit_client_secret", settings),
        "fitbit_google_health": fitbit_google_health_status(settings),
        "withings_client_id": integration_status("withings_client_id", settings),
        "withings_client_secret": integration_status("withings_client_secret", settings),
        "openai_api_key": "Configured" if openai_configured else "Not configured",
        "apple_health_export_file": integration_status("apple_health_export_file", settings),
    }
    return {"integrations": masked, "statuses": statuses}


@router.get("/api/settings")
def get_settings() -> dict:
    """Return masked local settings."""
    return _settings_response(load_settings())


@router.put("/api/settings")
def update_settings(payload: SettingsPayload) -> dict:
    """Update local integration settings.

    Empty values and masked values preserve the existing secret, so the frontend
    never needs to display saved keys in plain text.
    """
    settings = load_settings()
    incoming = payload.integrations or {}
    for key in INTEGRATION_FIELDS:
        value = str(incoming.get(key, "")).strip()
        if value and not value.startswith("••"):
            settings["integrations"][key] = value
    save_settings(settings)
    return _settings_response(load_settings())


@router.get("/api/integrations/status")
def get_integration_statuses() -> dict:
    """Return local integration configuration statuses."""
    settings = load_settings()
    return _settings_response(settings)


@router.get("/api/integrations/strava/auth-url")
def get_strava_auth_url(request: Request) -> dict:
    """Return a Strava OAuth URL for the frontend Connect Strava button."""
    redirect_uri = str(request.url_for("strava_callback"))
    try:
        auth_url = build_strava_auth_url(redirect_uri=redirect_uri)
    except StravaIntegrationError as exc:
        return {"status": "error", "message": str(exc), "auth_url": ""}
    return {"status": "ok", "auth_url": auth_url}


@router.get("/api/integrations/strava/callback", name="strava_callback")
def strava_callback(
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> HTMLResponse:
    """Exchange Strava OAuth callback code and store tokens locally."""
    if error:
        message = f"Strava authorization failed: {error}"
        return HTMLResponse(f"<h1>Strava connection failed</h1><p>{message}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h1>Strava connection failed</h1><p>Missing authorization code.</p>", status_code=400)

    try:
        exchange_strava_code(code)
    except StravaIntegrationError as exc:
        return HTMLResponse(f"<h1>Strava connection failed</h1><p>{str(exc)}</p>", status_code=400)

    return HTMLResponse(
        """
        <h1>Strava connected</h1>
        <p>You can close this tab and return to Performance OS.</p>
        <p>No tokens are displayed here; they were stored locally.</p>
        """
    )
