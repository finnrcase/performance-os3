"""Safe Google Health / Google Fit integration scaffolding.

This placeholder module prepares the integration surface without making live
API calls or requiring OAuth to work yet.
"""

from __future__ import annotations

from urllib.parse import urlencode

import pandas as pd

from src.wearables import WEARABLE_METRIC_COLUMNS


GOOGLE_HEALTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_HEALTH_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
]


def is_configured(settings: dict | None = None) -> bool:
    """Return whether Google Health client credentials are present in settings."""
    integrations = (settings or {}).get("integrations", {})
    return bool(
        str(integrations.get("google_health_client_id", "")).strip()
        and str(integrations.get("google_health_client_secret", "")).strip()
    )


def get_auth_url(
    settings: dict | None = None,
    *,
    redirect_uri: str = "",
    state: str = "",
    scope: list[str] | None = None,
) -> dict:
    """Build a future Google OAuth URL, or return a safe unconfigured response."""
    if not is_configured(settings):
        return {
            "status": "not_configured",
            "auth_url": "",
            "message": "Google Health client credentials are not configured.",
        }

    integrations = (settings or {}).get("integrations", {})
    params = {
        "client_id": str(integrations.get("google_health_client_id", "")).strip(),
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": " ".join(scope or GOOGLE_HEALTH_SCOPES),
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    if state:
        params["state"] = state
    return {
        "status": "placeholder",
        "auth_url": f"{GOOGLE_HEALTH_AUTH_URL}?{urlencode(params)}",
        "message": "Google Health OAuth is scaffolded but not enabled yet.",
    }


def exchange_code_for_token(code: str, settings: dict | None = None, *, redirect_uri: str = "") -> dict:
    """Placeholder for future Google authorization-code exchange."""
    if not is_configured(settings):
        return {"status": "not_configured", "message": "Google Health client credentials are not configured."}
    if not str(code or "").strip():
        return {"status": "missing_code", "message": "No Google authorization code was provided."}
    return {
        "status": "not_implemented",
        "message": "Google Health token exchange is not implemented yet.",
        "tokens": {},
    }


def refresh_access_token(refresh_token: str, settings: dict | None = None) -> dict:
    """Placeholder for future Google token refresh."""
    if not is_configured(settings):
        return {"status": "not_configured", "message": "Google Health client credentials are not configured."}
    if not str(refresh_token or "").strip():
        return {"status": "missing_refresh_token", "message": "No Google refresh token was provided."}
    return {
        "status": "not_implemented",
        "message": "Google Health token refresh is not implemented yet.",
        "tokens": {},
    }


def fetch_daily_metrics(
    access_token: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Placeholder for future Google Health daily metric fetching."""
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "items": [],
            "message": "No Google Health access token is available.",
        }
    return {
        "status": "not_implemented",
        "items": [],
        "message": "Google Health daily metrics fetch is not implemented yet.",
        "date_range": {"start_date": start_date or "", "end_date": end_date or ""},
    }


def normalize_daily_metrics(metrics: list[dict] | pd.DataFrame | None, source: str = "google_health") -> pd.DataFrame:
    """Normalize future Google Health payloads into wearable metric rows."""
    raw = metrics.copy() if isinstance(metrics, pd.DataFrame) else pd.DataFrame(metrics or [])
    if raw.empty:
        return pd.DataFrame(columns=WEARABLE_METRIC_COLUMNS)

    normalized = pd.DataFrame()
    for column in WEARABLE_METRIC_COLUMNS:
        normalized[column] = raw[column] if column in raw.columns else pd.NA
    normalized["source"] = normalized["source"].fillna(source).astype(str).str.strip().replace("", source)
    return normalized[WEARABLE_METRIC_COLUMNS]
