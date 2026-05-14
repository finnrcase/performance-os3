import os

import pandas as pd
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.config import INTEGRATION_FIELDS, fitbit_google_health_status, integration_status, load_settings, mask_secret, save_settings
from src.body_metrics import load_body_metrics
from src.integrations.hevy_client import load_hevy_sync_state
from src.integrations.strava_client import (
    StravaIntegrationError,
    build_strava_auth_url,
    exchange_strava_code,
    get_strava_connection_status,
)
from src.nutrition import load_nutrition_log
from src.recovery import load_recovery_log, load_sleep_entries
from src.storage import production_storage_warnings, use_database
from src.training import load_training_log


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


def _latest_date(df: pd.DataFrame, source_filter: str | None = None) -> str:
    if df.empty or "date" not in df.columns:
        return ""
    work = df.copy()
    if source_filter and "source" in work.columns:
        work = work[work["source"].fillna("").astype(str).str.lower() == source_filter]
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date")
    if work.empty:
        return ""
    return work.iloc[-1]["date"].date().isoformat()


def _days_since(date_value: str) -> int | None:
    if not date_value:
        return None
    parsed = pd.to_datetime(date_value, errors="coerce")
    if pd.isna(parsed):
        return None
    return int((pd.Timestamp.today().normalize() - parsed.normalize()).days)


def _freshness_detail(label: str, date_value: str) -> str:
    days = _days_since(date_value)
    if days is None:
        return f"No {label} data yet."
    if days == 0:
        return f"{label} data updated today."
    if days == 1:
        return f"{label} data updated yesterday."
    return f"{label} data updated {days} days ago."


def _integration_health(settings: dict, statuses: dict[str, str]) -> list[dict]:
    training_df = load_training_log()
    body_df = load_body_metrics()
    nutrition_df = load_nutrition_log()
    recovery_df = load_recovery_log()
    sleep_df = load_sleep_entries()
    hevy_state = load_hevy_sync_state()
    hevy_last_sync = str(hevy_state.get("last_sync_at", "") or "")
    hevy_error = str(hevy_state.get("last_error", "") or "")
    hevy_configured = statuses.get("hevy_api_key") == "Configured"
    strava_status = statuses.get("strava", "Not configured")
    latest_strava = _latest_date(training_df, "strava")
    latest_weight = _latest_date(body_df)
    latest_food = _latest_date(nutrition_df)
    latest_recovery = _latest_date(recovery_df) or _latest_date(sleep_df)
    storage_warnings = production_storage_warnings()

    cards = [
        {
            "id": "database",
            "title": "Database",
            "status": "connected" if use_database() else ("error" if storage_warnings else "warning"),
            "label": "Postgres connected" if use_database() else "Local file storage",
            "detail": storage_warnings[0] if storage_warnings else ("Data is using DATABASE_URL." if use_database() else "Fine for local dev; production should use DATABASE_URL."),
        },
        {
            "id": "hevy",
            "title": "Hevy",
            "status": "error" if hevy_error else "connected" if hevy_configured and hevy_last_sync else "warning",
            "label": "Connected" if hevy_configured else "Not configured",
            "detail": hevy_error or (f"Last sync: {hevy_last_sync}" if hevy_last_sync else "No Hevy sync has completed yet."),
            "last_synced_at": hevy_last_sync,
            "action": "hevy_sync" if hevy_configured else "",
        },
        {
            "id": "strava",
            "title": "Strava",
            "status": "connected" if strava_status == "Connected" and latest_strava else "warning",
            "label": strava_status,
            "detail": _freshness_detail("Strava run", latest_strava) if strava_status == "Connected" else "OAuth is required before run sync works.",
            "last_synced_at": latest_strava,
            "action": "strava_import" if strava_status == "Connected" else "",
        },
        {
            "id": "fitbit_google_health",
            "title": "Fitbit / Google Fit",
            "status": "connected" if statuses.get("fitbit_google_health") == "Connected" else "warning",
            "label": statuses.get("fitbit_google_health", "Not configured"),
            "detail": _freshness_detail("Recovery", latest_recovery) if latest_recovery else "Prepared, but wearable sync is not connected yet.",
        },
        {
            "id": "withings",
            "title": "Withings",
            "status": "warning",
            "label": "Configured" if settings.get("integrations", {}).get("withings_client_id") and settings.get("integrations", {}).get("withings_client_secret") else "Not configured",
            "detail": "Body composition sync is planned; use manual bodyweight logs for now.",
        },
        {
            "id": "openai",
            "title": "OpenAI",
            "status": "connected" if statuses.get("openai_api_key") == "Configured" else "warning",
            "label": statuses.get("openai_api_key", "Not configured"),
            "detail": "Food parsing is available." if statuses.get("openai_api_key") == "Configured" else "Add OPENAI_API_KEY or save the key in settings.",
        },
        {
            "id": "bodyweight",
            "title": "Bodyweight",
            "status": "warning" if (_days_since(latest_weight) is None or (_days_since(latest_weight) or 0) > 5) else "connected",
            "label": "Fresh" if latest_weight and (_days_since(latest_weight) or 0) <= 5 else "Missing data",
            "detail": _freshness_detail("Bodyweight", latest_weight),
        },
        {
            "id": "food_logs",
            "title": "Food logs",
            "status": "warning" if (_days_since(latest_food) is None or (_days_since(latest_food) or 0) > 2) else "connected",
            "label": "Fresh" if latest_food and (_days_since(latest_food) or 0) <= 2 else "Missing recent food",
            "detail": _freshness_detail("Food", latest_food),
        },
    ]
    return cards


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
    return {"integrations": masked, "statuses": statuses, "health": _integration_health(settings, statuses)}


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
    redirect_uri = os.getenv("STRAVA_REDIRECT_URI", "").strip() or str(request.url_for("strava_callback"))
    production_like = os.getenv("VERCEL") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER") or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
    if production_like and "localhost" in redirect_uri:
        return {
            "status": "error",
            "message": "STRAVA_REDIRECT_URI is still localhost. Set it to your deployed backend callback URL.",
            "auth_url": "",
        }
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
