"""Safe Fitbit integration scaffolding.

This module is intentionally a placeholder: it does not perform OAuth or call
Fitbit APIs yet. The functions define the future integration surface while
returning safe responses when credentials or tokens are missing.
"""

from __future__ import annotations

from urllib.parse import urlencode

import pandas as pd

from src.wearables import WEARABLE_METRIC_COLUMNS


FITBIT_AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_SCOPES = ["activity", "heartrate", "sleep", "profile"]


def is_configured(settings: dict | None = None) -> bool:
    """Return whether Fitbit client credentials are present in app settings."""
    integrations = (settings or {}).get("integrations", {})
    return bool(
        str(integrations.get("fitbit_client_id", "")).strip()
        and str(integrations.get("fitbit_client_secret", "")).strip()
    )


def get_auth_url(
    settings: dict | None = None,
    *,
    redirect_uri: str = "",
    state: str = "",
    scope: list[str] | None = None,
) -> dict:
    """Build a future Fitbit OAuth URL, or return a safe unconfigured response."""
    if not is_configured(settings):
        return {
            "status": "not_configured",
            "auth_url": "",
            "message": "Fitbit client credentials are not configured.",
        }

    integrations = (settings or {}).get("integrations", {})
    params = {
        "client_id": str(integrations.get("fitbit_client_id", "")).strip(),
        "response_type": "code",
        "scope": " ".join(scope or FITBIT_SCOPES),
    }
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    if state:
        params["state"] = state
    return {
        "status": "placeholder",
        "auth_url": f"{FITBIT_AUTH_URL}?{urlencode(params)}",
        "message": "Fitbit OAuth is scaffolded but not enabled yet.",
    }


def exchange_code_for_token(code: str, settings: dict | None = None, *, redirect_uri: str = "") -> dict:
    """Placeholder for future Fitbit authorization-code exchange."""
    if not is_configured(settings):
        return {"status": "not_configured", "message": "Fitbit client credentials are not configured."}
    if not str(code or "").strip():
        return {"status": "missing_code", "message": "No Fitbit authorization code was provided."}
    return {
        "status": "not_implemented",
        "message": "Fitbit token exchange is not implemented yet.",
        "tokens": {},
    }


def refresh_access_token(refresh_token: str, settings: dict | None = None) -> dict:
    """Placeholder for future Fitbit token refresh."""
    if not is_configured(settings):
        return {"status": "not_configured", "message": "Fitbit client credentials are not configured."}
    if not str(refresh_token or "").strip():
        return {"status": "missing_refresh_token", "message": "No Fitbit refresh token was provided."}
    return {
        "status": "not_implemented",
        "message": "Fitbit token refresh is not implemented yet.",
        "tokens": {},
    }


def fetch_daily_metrics(
    access_token: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Placeholder for future Fitbit daily metric fetching."""
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "items": [],
            "message": "No Fitbit access token is available.",
        }
    return {
        "status": "not_implemented",
        "items": [],
        "message": "Fitbit daily metrics fetch is not implemented yet.",
        "date_range": {"start_date": start_date or "", "end_date": end_date or ""},
    }


def normalize_daily_metrics(metrics: list[dict] | pd.DataFrame | None, source: str = "fitbit") -> pd.DataFrame:
    """Normalize future Fitbit metric payloads into wearable metric rows."""
    raw = metrics.copy() if isinstance(metrics, pd.DataFrame) else pd.DataFrame(metrics or [])
    if raw.empty:
        return pd.DataFrame(columns=WEARABLE_METRIC_COLUMNS)

    normalized = pd.DataFrame()
    for column in WEARABLE_METRIC_COLUMNS:
        normalized[column] = raw[column] if column in raw.columns else pd.NA
    normalized["source"] = normalized["source"].fillna(source).astype(str).str.strip().replace("", source)
    return normalized[WEARABLE_METRIC_COLUMNS]
