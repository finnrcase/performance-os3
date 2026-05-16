<<<<<<< HEAD
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
=======
"""Withings OAuth and scale measurement sync helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from src.body_metrics import load_body_metrics, save_body_metrics
from src.config import load_settings, save_settings


WITHINGS_API_BASE = "https://wbsapi.withings.net"
WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_SCOPE = "user.metrics"
KG_TO_LB = 2.2046226218
WEIGHT_TYPE = 1
HEIGHT_TYPE = 4
FAT_FREE_MASS_KG_TYPE = 5
FAT_RATIO_TYPE = 6
FAT_MASS_KG_TYPE = 8
MUSCLE_MASS_KG_TYPE = 76
HYDRATION_KG_TYPE = 77


class WithingsIntegrationError(RuntimeError):
    """Raised when Withings credentials, OAuth, or API calls fail."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_value(settings_key: str, env_key: str) -> str:
    settings_value = str(load_settings().get("integrations", {}).get(settings_key, "") or "").strip()
    return os.getenv(env_key, "").strip() or settings_value


def _client_id() -> str:
    value = _config_value("withings_client_id", "WITHINGS_CLIENT_ID")
    if not value:
        raise WithingsIntegrationError("WITHINGS_CLIENT_ID is not configured.")
    return value


def _client_secret() -> str:
    value = _config_value("withings_client_secret", "WITHINGS_CLIENT_SECRET")
    if not value:
        raise WithingsIntegrationError("WITHINGS_CLIENT_SECRET is not configured.")
    return value


def configured_from_env_or_settings() -> bool:
    return bool(_config_value("withings_client_id", "WITHINGS_CLIENT_ID") and _config_value("withings_client_secret", "WITHINGS_CLIENT_SECRET"))


def get_withings_connection_status() -> str:
    settings = load_settings()
    tokens = settings.get("metadata", {}).get("withings_tokens", {})
    if tokens.get("access_token") and tokens.get("refresh_token"):
        return "Connected"
    if configured_from_env_or_settings():
>>>>>>> 37f5b2f02b51addf01efddb5467c5294101bd93a
        return "Ready to connect"
    return "Not configured"


<<<<<<< HEAD
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
=======
def build_withings_auth_url(redirect_uri: str, state: str = "") -> str:
    """Return the Withings OAuth authorization URL."""
    if not redirect_uri:
        raise WithingsIntegrationError("WITHINGS_REDIRECT_URI is not configured.")
    params = {
        "response_type": "code",
        "client_id": _client_id(),
        "scope": WITHINGS_SCOPE,
        "redirect_uri": redirect_uri,
    }
    if state:
        params["state"] = state
    return f"{WITHINGS_AUTH_URL}?{urlencode(params)}"


def _signature(params: dict[str, Any], client_secret: str) -> str:
    values = []
    for key in ["action", "client_id", "timestamp", "nonce"]:
        value = params.get(key)
        if value not in (None, ""):
            values.append(str(value))
    message = ",".join(values).encode("utf-8")
    return hmac.new(client_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _friendly_withings_message(message: str, context: str) -> str:
    cleaned = str(message or "").strip() or "Unknown Withings error."
    lowered = cleaned.lower()
    if "redirect_uri_mismatch" in lowered or "redirect uri" in lowered or "callback" in lowered:
        return (
            "Withings redirect URI mismatch. The WITHINGS_REDIRECT_URI used by the backend must exactly match "
            f"the callback URL configured in the Withings developer console. Withings said: {cleaned}"
        )
    if "invalid_grant" in lowered or "expired" in lowered or "refresh_token" in lowered:
        return f"Withings refresh token is missing or expired. Reconnect Withings. Withings said: {cleaned}"
    return f"{context}: {cleaned}"


def _post_form(path: str, params: dict[str, Any], access_token: str = "", context: str = "Withings API fetch failed") -> dict:
    data = urlencode(params).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    request = Request(f"{WITHINGS_API_BASE}{path}", data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise WithingsIntegrationError(f"{context}: {exc}") from exc

    status = int(payload.get("status", 0) or 0)
    if status != 0:
        message = payload.get("error") or payload.get("body", {}).get("error") or f"Withings API returned status {status}."
        raise WithingsIntegrationError(_friendly_withings_message(str(message), context))
    return payload


def _get_nonce() -> str:
    client_id = _client_id()
    client_secret = _client_secret()
    params: dict[str, Any] = {
        "action": "getnonce",
        "client_id": client_id,
        "timestamp": int(time.time()),
    }
    params["signature"] = _signature(params, client_secret)
    payload = _post_form("/v2/signature", params, context="Withings token exchange failed")
    nonce = str(payload.get("body", {}).get("nonce", "") or "")
    if not nonce:
        raise WithingsIntegrationError("Withings nonce response did not include a nonce.")
    return nonce


def _request_token(params: dict[str, Any]) -> dict:
    client_secret = _client_secret()
    params = {**params, "action": "requesttoken", "client_id": _client_id(), "nonce": _get_nonce()}
    params["signature"] = _signature(params, client_secret)
    payload = _post_form("/v2/oauth2", params, context="Withings token exchange failed")
    body = payload.get("body", {})
    if not body.get("access_token") or not body.get("refresh_token"):
        raise WithingsIntegrationError("Withings token exchange failed: response did not include access and refresh tokens.")
    return body


def _save_withings_tokens(token_body: dict) -> dict:
    settings = load_settings()
    expires_in = int(token_body.get("expires_in") or 0)
    settings.setdefault("metadata", {}).setdefault("withings_tokens", {}).update(
        {
            "access_token": str(token_body.get("access_token", "") or ""),
            "refresh_token": str(token_body.get("refresh_token", "") or ""),
            "expires_at": int(time.time()) + max(expires_in - 60, 0),
            "userid": str(token_body.get("userid", "") or ""),
            "scopes": str(token_body.get("scope", "") or ""),
            "token_type": str(token_body.get("token_type", "") or ""),
        }
    )
    settings.setdefault("metadata", {}).setdefault("withings_sync", {})["needs_reconnect"] = False
    settings["metadata"]["withings_sync"]["last_error"] = ""
    save_settings(settings)
    return settings["metadata"]["withings_tokens"]


def exchange_withings_code(code: str, redirect_uri: str) -> dict:
    if not code:
        raise WithingsIntegrationError("Missing Withings authorization code.")
    if not redirect_uri:
        raise WithingsIntegrationError("WITHINGS_REDIRECT_URI is not configured.")
    token_body = _request_token(
        {
            "redirect_uri": redirect_uri,
            "code": code,
            "grant_type": "authorization_code",
        }
    )
    return _save_withings_tokens(token_body)


def refresh_withings_token_if_needed(force: bool = False) -> dict:
    settings = load_settings()
    tokens = settings.get("metadata", {}).get("withings_tokens", {})
    if not tokens.get("refresh_token"):
        raise WithingsIntegrationError("Withings refresh token is missing or expired. Reconnect Withings before syncing.")
    expires_at = int(tokens.get("expires_at") or 0)
    if not force and tokens.get("access_token") and expires_at > int(time.time()) + 120:
        return tokens
    token_body = _request_token({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    return _save_withings_tokens(token_body)


def load_withings_sync_state() -> dict:
>>>>>>> 37f5b2f02b51addf01efddb5467c5294101bd93a
    return load_settings().get("metadata", {}).get("withings_sync", {})


def _save_withings_sync_state(updates: dict) -> dict:
    settings = load_settings()
    sync = settings.setdefault("metadata", {}).setdefault("withings_sync", {})
    sync.update(updates)
    save_settings(settings)
<<<<<<< HEAD
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
=======
    return load_withings_sync_state()


def save_withings_sync_error(message: str) -> dict:
    return _save_withings_sync_state({"last_error": message, "last_synced_at": _now_iso(), "needs_reconnect": True})


def _measure_value(measure: dict) -> float | None:
    try:
        return float(measure["value"]) * (10 ** int(measure.get("unit", 0)))
    except (KeyError, TypeError, ValueError):
        return None


def _kg_to_lb(value: float | None) -> float | None:
    return round(value * KG_TO_LB, 2) if value is not None else None


def _measure_groups_to_rows(measure_groups: list[dict]) -> list[dict]:
    rows = []
    for group in measure_groups:
        measures = {}
        for measure in group.get("measures", []):
            measure_type = int(measure.get("type", 0) or 0)
            value = _measure_value(measure)
            if value is not None:
                measures[measure_type] = value
        weight_kg = measures.get(WEIGHT_TYPE)
        if not weight_kg:
            continue
        measured_at = datetime.fromtimestamp(int(group.get("date", 0) or 0), tz=timezone.utc)
        height_m = measures.get(HEIGHT_TYPE)
        fat_free_mass_kg = measures.get(FAT_FREE_MASS_KG_TYPE)
        fat_ratio = measures.get(FAT_RATIO_TYPE)
        fat_mass_kg = measures.get(FAT_MASS_KG_TYPE)
        muscle_mass_kg = measures.get(MUSCLE_MASS_KG_TYPE)
        hydration_kg = measures.get(HYDRATION_KG_TYPE)
        if fat_ratio is None and fat_mass_kg is not None and weight_kg:
            fat_ratio = fat_mass_kg / weight_kg * 100
        if fat_mass_kg is None and fat_ratio is not None and weight_kg:
            fat_mass_kg = weight_kg * fat_ratio / 100
        if fat_free_mass_kg is None and fat_mass_kg is not None:
            fat_free_mass_kg = weight_kg - fat_mass_kg
        bmi = weight_kg / (height_m * height_m) if height_m and height_m > 0 else None
        notes = [
            "source=withings",
            f"withings_measure_group_id={group.get('grpid', '')}",
            f"measured_at={measured_at.isoformat()}",
            f"bodyweight_kg={weight_kg:.3f}",
        ]
        if fat_mass_kg is not None:
            notes.append(f"fat_mass_kg={fat_mass_kg:.3f}")
        if fat_free_mass_kg is not None:
            notes.append(f"lean_mass_kg={fat_free_mass_kg:.3f}")
        if muscle_mass_kg is not None:
            notes.append(f"muscle_mass_kg={muscle_mass_kg:.3f}")
        if hydration_kg is not None:
            notes.append(f"hydration_kg={hydration_kg:.3f}")
        if bmi is not None:
            notes.append(f"bmi={bmi:.2f}")
        rows.append(
            {
                "date": measured_at.date().isoformat(),
                "bodyweight": round(weight_kg * KG_TO_LB, 2),
                "waist": pd.NA,
                "estimated_body_fat": round(float(fat_ratio), 2) if fat_ratio is not None else pd.NA,
                "lean_mass": _kg_to_lb(fat_free_mass_kg) if fat_free_mass_kg is not None else pd.NA,
                "fat_mass": _kg_to_lb(fat_mass_kg) if fat_mass_kg is not None else pd.NA,
                "muscle_mass": _kg_to_lb(muscle_mass_kg) if muscle_mass_kg is not None else pd.NA,
                "hydration": _kg_to_lb(hydration_kg) if hydration_kg is not None else pd.NA,
                "bmi": round(float(bmi), 2) if bmi is not None else pd.NA,
                "notes": " | ".join(notes),
            }
        )
    return rows


def _merge_body_metric_rows(imported_rows: list[dict]) -> None:
    if not imported_rows:
        return
    existing = load_body_metrics()
    imported_ids = {
        str(row.get("notes", "")).split("withings_measure_group_id=", 1)[1].split("|", 1)[0].strip()
        for row in imported_rows
        if "withings_measure_group_id=" in str(row.get("notes", ""))
    }
    imported_dates = {str(row.get("date", "")) for row in imported_rows}
    notes = existing["notes"].fillna("").astype(str) if "notes" in existing.columns else pd.Series(dtype=str)
    dates = existing["date"].astype(str) if "date" in existing.columns else pd.Series(dtype=str)

    def keep_row(index: int) -> bool:
        note = notes.iloc[index]
        if "source=withings" not in note:
            return True
        existing_id = note.split("withings_measure_group_id=", 1)[1].split("|", 1)[0].strip() if "withings_measure_group_id=" in note else ""
        if existing_id and existing_id in imported_ids:
            return False
        return dates.iloc[index] not in imported_dates

    filtered = existing[[keep_row(index) for index in range(len(existing))]].copy() if len(existing) else existing
    merged = pd.concat([filtered, pd.DataFrame(imported_rows)], ignore_index=True)
    merged = merged.sort_values(["date", "notes"], kind="stable").reset_index(drop=True)
    save_body_metrics(merged)


def sync_withings_measurements(days: int | None = None) -> dict:
    """Fetch Withings scale measurements and import them into body metrics."""
    tokens = refresh_withings_token_if_needed()
    lookback_days = int(days or os.getenv("WITHINGS_SYNC_LOOKBACK_DAYS", "3650") or 3650)
    end_ts = int(time.time())
    start_ts = end_ts - max(1, lookback_days) * 86400
    payload = _post_form(
        "/measure",
        {
            "action": "getmeas",
            "category": 1,
            "meastypes": ",".join(
                str(value)
                for value in [
                    WEIGHT_TYPE,
                    HEIGHT_TYPE,
                    FAT_FREE_MASS_KG_TYPE,
                    FAT_RATIO_TYPE,
                    FAT_MASS_KG_TYPE,
                    MUSCLE_MASS_KG_TYPE,
                    HYDRATION_KG_TYPE,
                ]
            ),
            "startdate": start_ts,
            "enddate": end_ts,
        },
        access_token=str(tokens.get("access_token", "")),
        context="Withings API fetch failed",
    )
    measure_groups = payload.get("body", {}).get("measuregrps", []) or []
    rows = _measure_groups_to_rows(measure_groups)
    _merge_body_metric_rows(rows)
    latest_measure_date = max((row["date"] for row in rows), default="")
    sync = _save_withings_sync_state(
        {
            "last_synced_at": _now_iso(),
            "last_error": "",
            "last_imported_count": len(rows),
            "last_fetched_groups": len(measure_groups),
            "latest_measure_date": latest_measure_date,
            "needs_reconnect": False,
        }
    )
    return {
        "status": "ok",
        "imported_measurements": len(rows),
        "fetched_groups": len(measure_groups),
        "latest_measure_date": latest_measure_date,
        "last_synced_at": sync.get("last_synced_at", ""),
>>>>>>> 37f5b2f02b51addf01efddb5467c5294101bd93a
    }
