"""Withings smart-scale integration for automatic body-composition syncing.

Uses the Withings Public API (OAuth 2.0 authorization code flow). Access and
refresh tokens are stored in the app settings document — which persists to
Postgres when ``DATABASE_URL`` is set — and are never returned to the frontend.

Reference: https://developer.withings.com/api-reference/
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.body_metrics import upsert_withings_measurements
from src.config import load_settings, save_settings
from src.integrations.withings_measure_types import (
    WITHINGS_REQUESTED_MEASTYPES,
    derive_bmi,
    parse_measure_group,
)


WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_MEASURE_URL = "https://wbsapi.withings.net/measure"
# Minimum scopes for body-composition syncing.
WITHINGS_SCOPES = "user.info,user.metrics"
DEFAULT_SYNC_DAYS = 90
TOKEN_EXPIRY_BUFFER_SECONDS = 300

logger = logging.getLogger(__name__)


class WithingsIntegrationError(Exception):
    """Raised when a Withings operation cannot complete."""


class WithingsReconnectRequired(WithingsIntegrationError):
    """Raised when saved Withings tokens are invalid and OAuth must run again."""


# --------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------

def _read_dotenv_value(key: str) -> str:
    """Read a simple KEY=value entry from local .env without logging secrets."""
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if not os.path.exists(dotenv_path):
        return ""
    with open(dotenv_path, "r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            if name.strip() == key:
                return value.strip().strip('"').strip("'")
    return ""


def _config_value(settings_key: str, env_key: str) -> str:
    settings = load_settings()
    integrations = settings.get("integrations", {})
    return (
        str(integrations.get(settings_key, "") or "").strip()
        or os.getenv(env_key, "").strip()
        or _read_dotenv_value(env_key).strip()
    )


def _get_withings_credentials() -> tuple[str, str]:
    """Read Withings client credentials from settings, environment, or .env."""
    client_id = _config_value("withings_client_id", "WITHINGS_CLIENT_ID")
    client_secret = _config_value("withings_client_secret", "WITHINGS_CLIENT_SECRET")
    missing = []
    if not client_id:
        missing.append("WITHINGS_CLIENT_ID")
    if not client_secret:
        missing.append("WITHINGS_CLIENT_SECRET")
    if missing:
        raise WithingsIntegrationError(
            f"{' and '.join(missing)} must be configured before connecting Withings."
        )
    return client_id, client_secret


def withings_redirect_uri(fallback: str = "") -> str:
    """Resolve the Withings OAuth redirect URI (must point at this backend)."""
    configured = (
        os.getenv("WITHINGS_REDIRECT_URI", "").strip()
        or _read_dotenv_value("WITHINGS_REDIRECT_URI").strip()
    )
    return configured or fallback


def get_withings_connection_status() -> str:
    """Return a frontend-safe Withings connection status string."""
    settings = load_settings()
    metadata = settings.get("metadata", {})
    tokens = metadata.get("withings_tokens", {})
    sync_state = metadata.get("withings_sync", {})
    if sync_state.get("needs_reconnect"):
        return "Disconnected"
    if tokens.get("access_token") and tokens.get("refresh_token"):
        return "Connected"
    client_id = _config_value("withings_client_id", "WITHINGS_CLIENT_ID")
    client_secret = _config_value("withings_client_secret", "WITHINGS_CLIENT_SECRET")
    if client_id and client_secret:
        return "Ready to connect"
    return "Not configured"


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def _post_form(url: str, body: dict, headers: dict | None = None) -> dict:
    """POST a form-encoded request and return parsed JSON."""
    request = Request(
        url,
        data=urlencode(body).encode("utf-8"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        logger.exception("Withings request to %s failed with status %s", url, exc.code)
        raise WithingsIntegrationError(f"Withings request failed with status {exc.code}: {detail}") from exc
    except URLError as exc:
        raise WithingsIntegrationError(f"Could not reach Withings: {exc.reason}") from exc
    except TimeoutError as exc:
        raise WithingsIntegrationError("Withings request timed out.") from exc
    except json.JSONDecodeError as exc:
        raise WithingsIntegrationError("Withings returned invalid JSON.") from exc


def _withings_body(payload: dict) -> dict:
    """Validate the Withings ``{status, body}`` envelope and return ``body``.

    Withings always returns HTTP 200 with a ``status`` integer; 0 means success.
    """
    status = payload.get("status")
    if status == 0:
        return payload.get("body", {}) or {}
    error = payload.get("error", "") or f"Withings API status {status}"
    if status in (401, 247, 283, 286, 293, 294):
        # Auth / token errors — caller should trigger a reconnect.
        raise WithingsReconnectRequired(f"Withings authorization is invalid: {error}")
    if status == 601:
        raise WithingsIntegrationError("Withings API rate limit reached. Try again shortly.")
    raise WithingsIntegrationError(f"Withings API error (status {status}): {error}")


# --------------------------------------------------------------------------
# Token storage
# --------------------------------------------------------------------------

def _save_withings_tokens(token_body: dict) -> dict:
    """Persist Withings tokens without exposing them to frontend responses."""
    settings = load_settings()
    metadata = settings.setdefault("metadata", {})
    previous = metadata.get("withings_tokens", {})
    expires_in = int(token_body.get("expires_in") or 0)
    metadata["withings_tokens"] = {
        "access_token": str(token_body.get("access_token", "")),
        "refresh_token": str(token_body.get("refresh_token", "") or previous.get("refresh_token", "")),
        "expires_at": int(time.time()) + expires_in if expires_in else 0,
        "userid": str(token_body.get("userid", "") or previous.get("userid", "")),
        "scopes": str(token_body.get("scope", "") or previous.get("scopes", "") or WITHINGS_SCOPES),
    }
    sync = metadata.setdefault("withings_sync", {})
    sync["needs_reconnect"] = False
    sync["last_error"] = ""
    save_settings(settings)
    logger.info(
        "Stored Withings tokens for userid=%s expires_at=%s",
        metadata["withings_tokens"].get("userid", ""),
        metadata["withings_tokens"].get("expires_at", 0),
    )
    return metadata["withings_tokens"]


def clear_withings_connection(reason: str = "", mark_error: bool = True) -> dict:
    """Clear saved Withings tokens so the next action starts a clean reconnect."""
    settings = load_settings()
    metadata = settings.setdefault("metadata", {})
    userid = str(metadata.get("withings_tokens", {}).get("userid", "") or "")
    metadata["withings_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "userid": userid,
        "scopes": "",
    }
    sync = metadata.setdefault("withings_sync", {})
    sync["needs_reconnect"] = True
    sync["last_error"] = (reason or "Withings authorization expired. Reconnect Withings.") if mark_error else ""
    sync["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    save_settings(settings)
    logger.warning("Cleared Withings connection state: %s", reason or "manual reconnect")
    return sync


def load_withings_sync_state() -> dict:
    """Return the saved Withings sync metadata."""
    return load_settings().get("metadata", {}).get("withings_sync", {})


def _save_withings_sync_state(updates: dict) -> dict:
    settings = load_settings()
    sync = settings.setdefault("metadata", {}).setdefault("withings_sync", {})
    sync.update(updates)
    save_settings(settings)
    return sync


# --------------------------------------------------------------------------
# OAuth flow
# --------------------------------------------------------------------------

def build_withings_auth_url(redirect_uri: str, state: str | None = None) -> str:
    """Generate a Withings OAuth authorization URL for body-measurement scopes."""
    client_id, _ = _get_withings_credentials()
    if not redirect_uri:
        raise WithingsIntegrationError("WITHINGS_REDIRECT_URI could not be resolved.")
    query = {
        "response_type": "code",
        "client_id": client_id,
        "scope": WITHINGS_SCOPES,
        "redirect_uri": redirect_uri,
        "state": state or "performance_os",
    }
    logger.info("Starting Withings OAuth with redirect_uri=%s", redirect_uri)
    return f"{WITHINGS_AUTH_URL}?{urlencode(query)}"


def exchange_withings_code(code: str, redirect_uri: str) -> dict:
    """Exchange a Withings OAuth authorization code for stored tokens."""
    client_id, client_secret = _get_withings_credentials()
    payload = _post_form(
        WITHINGS_TOKEN_URL,
        {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    token_body = _withings_body(payload)
    tokens = _save_withings_tokens(token_body)
    logger.info("Withings token exchange succeeded for userid=%s", tokens.get("userid", ""))
    return {"status": "Connected", "userid": tokens.get("userid", "")}


def refresh_withings_token_if_needed(force: bool = False) -> str:
    """Refresh the Withings access token when expired or near expiry."""
    settings = load_settings()
    tokens = settings.get("metadata", {}).get("withings_tokens", {})
    access_token = str(tokens.get("access_token", "")).strip()
    refresh_token = str(tokens.get("refresh_token", "")).strip()
    expires_at = int(tokens.get("expires_at") or 0)
    now = int(time.time())

    if not refresh_token:
        if access_token:
            clear_withings_connection("Saved Withings token has no refresh token. Reconnect Withings.")
        raise WithingsReconnectRequired("Withings is not connected. Connect Withings from Settings.")

    if not force and access_token and expires_at > now + TOKEN_EXPIRY_BUFFER_SECONDS:
        return access_token

    client_id, client_secret = _get_withings_credentials()
    logger.info("Refreshing Withings access token; expires_at=%s now=%s force=%s", expires_at, now, force)
    try:
        payload = _post_form(
            WITHINGS_TOKEN_URL,
            {
                "action": "requesttoken",
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
        token_body = _withings_body(payload)
    except WithingsIntegrationError as exc:
        clear_withings_connection(f"Withings token refresh failed. Reconnect Withings. {exc}")
        logger.exception("Withings token refresh failed; reconnect required.")
        raise WithingsReconnectRequired("Withings token refresh failed. Reconnect Withings from Settings.") from exc
    tokens = _save_withings_tokens(token_body)
    return str(tokens.get("access_token", ""))


# --------------------------------------------------------------------------
# Measurement sync
# --------------------------------------------------------------------------

def _fetch_measure_groups(access_token: str, start_ts: int, end_ts: int) -> list[dict]:
    """Call Withings Measure Getmeas and return the raw ``measuregrps`` list."""
    payload = _post_form(
        WITHINGS_MEASURE_URL,
        {
            "action": "getmeas",
            "meastypes": WITHINGS_REQUESTED_MEASTYPES,
            "category": 1,  # 1 = real measurements (2 = user objectives)
            "startdate": start_ts,
            "enddate": end_ts,
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    body = _withings_body(payload)
    groups = body.get("measuregrps", []) or []
    return [group for group in groups if isinstance(group, dict)]


def sync_withings_measurements(start_date: str | None = None, end_date: str | None = None) -> dict:
    """Fetch recent Withings body measurements and upsert them into body_metrics.

    Dates are optional ``YYYY-MM-DD`` strings; defaults to the last 90 days. The
    access token is refreshed first and the request is retried once if the token
    turns out to be stale.
    """
    end_ts = int(time.time())
    if end_date:
        try:
            end_ts = int(datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        except ValueError as exc:
            raise WithingsIntegrationError("end_date must be YYYY-MM-DD.") from exc
    start_ts = end_ts - DEFAULT_SYNC_DAYS * 86400
    if start_date:
        try:
            start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
        except ValueError as exc:
            raise WithingsIntegrationError("start_date must be YYYY-MM-DD.") from exc

    access_token = refresh_withings_token_if_needed()
    try:
        groups = _fetch_measure_groups(access_token, start_ts, end_ts)
    except WithingsReconnectRequired:
        # Token may have just expired — force one refresh and retry once.
        access_token = refresh_withings_token_if_needed(force=True)
        groups = _fetch_measure_groups(access_token, start_ts, end_ts)

    # Withings rarely includes height in a weigh-in group; track any height seen
    # so BMI can be derived. BMI stays null when no height is available.
    height_m: float | None = None
    for group in groups:
        parsed = parse_measure_group(group)
        if parsed.get("height_m"):
            height_m = parsed["height_m"]

    rows: list[dict] = []
    latest_date = ""
    for group in groups:
        parsed = parse_measure_group(group)
        if "weight_lb" not in parsed and "body_fat_percent" not in parsed:
            continue  # skip non-body-composition groups (e.g. height-only)
        timestamp = int(group.get("date", 0) or 0)
        if not timestamp:
            continue
        date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()
        latest_date = max(latest_date, date_str)
        rows.append(
            {
                "date": date_str,
                "bodyweight": parsed.get("weight_lb"),
                "estimated_body_fat": parsed.get("body_fat_percent"),
                "lean_mass": parsed.get("lean_mass_lb"),
                "fat_mass": parsed.get("fat_mass_lb"),
                "muscle_mass": parsed.get("muscle_mass_lb"),
                "bone_mass": parsed.get("bone_mass_lb"),
                "bmi": derive_bmi(parsed.get("weight_kg"), parsed.get("height_m") or height_m),
                "source_id": str(group.get("grpid", "") or timestamp),
                "raw_payload": json.dumps(group, separators=(",", ":")),
                "notes": "Withings scale sync",
            }
        )

    result = upsert_withings_measurements(rows)
    synced_at = datetime.now(timezone.utc).isoformat()
    _save_withings_sync_state(
        {
            "last_synced_at": synced_at,
            "last_error": "",
            "needs_reconnect": False,
            "latest_measurement_date": latest_date or load_withings_sync_state().get("latest_measurement_date", ""),
            "last_fetched_count": len(groups),
            "last_imported_count": result["created"],
            "last_updated_count": result["updated"],
        }
    )
    logger.info(
        "Withings sync complete: fetched=%s created=%s updated=%s",
        len(groups), result["created"], result["updated"],
    )
    return {
        "status": "ok",
        "fetched": len(groups),
        "created": result["created"],
        "updated": result["updated"],
        "latest_measurement_date": latest_date,
        "last_synced_at": synced_at,
    }
