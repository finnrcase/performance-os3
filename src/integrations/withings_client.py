"""Withings smart-scale OAuth and body-composition sync helpers.

Tokens are stored in the app settings document, which persists to Postgres
whenever ``DATABASE_URL`` is configured. Secrets and tokens are never returned
to the frontend.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.body_metrics import upsert_withings_measurements
from src.config import load_settings, save_settings


WITHINGS_AUTH_URL = "https://account.withings.com/oauth2_user/authorize2"
WITHINGS_TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
WITHINGS_MEASURE_URL = "https://wbsapi.withings.net/measure"
WITHINGS_SCOPES = "user.metrics"
DEFAULT_SYNC_DAYS = 90
TOKEN_EXPIRY_BUFFER_SECONDS = 300

KG_TO_LB = 2.2046226218
WEIGHT_TYPE = 1
HEIGHT_TYPE = 4
FAT_FREE_MASS_KG_TYPE = 5
FAT_RATIO_TYPE = 6
FAT_MASS_KG_TYPE = 8
BONE_MASS_KG_TYPE = 88
MUSCLE_MASS_KG_TYPE = 76
HYDRATION_KG_TYPE = 77
WITHINGS_REQUESTED_MEASTYPES = ",".join(
    str(value)
    for value in [
        WEIGHT_TYPE,
        HEIGHT_TYPE,
        FAT_FREE_MASS_KG_TYPE,
        FAT_RATIO_TYPE,
        FAT_MASS_KG_TYPE,
        MUSCLE_MASS_KG_TYPE,
        HYDRATION_KG_TYPE,
        BONE_MASS_KG_TYPE,
    ]
)

logger = logging.getLogger(__name__)


class WithingsIntegrationError(Exception):
    """Raised when a Withings operation cannot complete."""


class WithingsReconnectRequired(WithingsIntegrationError):
    """Raised when saved Withings tokens are invalid and OAuth must run again."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_dotenv_value(key: str) -> str:
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
    settings_value = str(load_settings().get("integrations", {}).get(settings_key, "") or "").strip()
    return os.getenv(env_key, "").strip() or _read_dotenv_value(env_key).strip() or settings_value


def _get_withings_credentials() -> tuple[str, str]:
    client_id = _config_value("withings_client_id", "WITHINGS_CLIENT_ID")
    client_secret = _config_value("withings_client_secret", "WITHINGS_CLIENT_SECRET")
    missing = []
    if not client_id:
        missing.append("WITHINGS_CLIENT_ID")
    if not client_secret:
        missing.append("WITHINGS_CLIENT_SECRET")
    if missing:
        raise WithingsIntegrationError(f"{' and '.join(missing)} must be configured before connecting Withings.")
    return client_id, client_secret


def withings_redirect_uri(fallback: str = "") -> str:
    configured = os.getenv("WITHINGS_REDIRECT_URI", "").strip() or _read_dotenv_value("WITHINGS_REDIRECT_URI").strip()
    return configured or fallback


def get_withings_connection_status() -> str:
    settings = load_settings()
    metadata = settings.get("metadata", {})
    tokens = metadata.get("withings_tokens", {})
    sync_state = metadata.get("withings_sync", {})
    if sync_state.get("needs_reconnect"):
        return "Disconnected"
    if tokens.get("access_token") and tokens.get("refresh_token"):
        return "Connected"
    if _config_value("withings_client_id", "WITHINGS_CLIENT_ID") and _config_value("withings_client_secret", "WITHINGS_CLIENT_SECRET"):
        return "Ready to connect"
    return "Not configured"


def _friendly_withings_message(message: str, context: str) -> str:
    cleaned = str(message or "").strip() or "Unknown Withings error."
    lowered = cleaned.lower()
    if "redirect_uri_mismatch" in lowered or "redirect uri" in lowered or "callback" in lowered:
        return (
            "Withings redirect URI mismatch. WITHINGS_REDIRECT_URI must exactly match "
            f"the callback URL configured in the Withings developer console. Withings said: {cleaned}"
        )
    if "invalid_grant" in lowered or "expired" in lowered or "refresh_token" in lowered:
        return f"Withings refresh token is missing or expired. Reconnect Withings. Withings said: {cleaned}"
    return f"{context}: {cleaned}"


def _post_form(url: str, body: dict, headers: dict | None = None, context: str = "Withings API request failed", timeout_seconds: int = 25) -> dict:
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
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WithingsIntegrationError(_friendly_withings_message(detail, context)) from exc
    except URLError as exc:
        raise WithingsIntegrationError(f"{context}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise WithingsIntegrationError(f"{context}: request timed out.") from exc
    except json.JSONDecodeError as exc:
        raise WithingsIntegrationError(f"{context}: invalid JSON response.") from exc


def _withings_body(payload: dict, context: str = "Withings API request failed") -> dict:
    status = int(payload.get("status", 0) or 0)
    if status != 0:
        message = payload.get("error") or payload.get("body", {}).get("error") or f"Withings API returned status {status}."
        raise WithingsIntegrationError(_friendly_withings_message(str(message), context))
    body = payload.get("body", {})
    if not isinstance(body, dict):
        raise WithingsIntegrationError(f"{context}: response body was missing.")
    return body


def _save_withings_tokens(token_body: dict) -> dict:
    settings = load_settings()
    metadata = settings.setdefault("metadata", {})
    previous = metadata.get("withings_tokens", {})
    expires_in = int(token_body.get("expires_in") or 0)
    metadata["withings_tokens"] = {
        "access_token": str(token_body.get("access_token", "")),
        "refresh_token": str(token_body.get("refresh_token", "")),
        "expires_at": int(time.time()) + max(expires_in - TOKEN_EXPIRY_BUFFER_SECONDS, 0),
        "userid": str(token_body.get("userid", "") or previous.get("userid", "")),
        "scopes": str(token_body.get("scope", "") or previous.get("scopes", "") or WITHINGS_SCOPES),
        "token_type": str(token_body.get("token_type", "") or previous.get("token_type", "")),
    }
    sync = metadata.setdefault("withings_sync", {})
    sync["needs_reconnect"] = False
    sync["last_error"] = ""
    save_settings(settings)
    return metadata["withings_tokens"]


def clear_withings_connection(reason: str = "", mark_error: bool = True) -> dict:
    settings = load_settings()
    metadata = settings.setdefault("metadata", {})
    userid = str(metadata.get("withings_tokens", {}).get("userid", "") or "")
    metadata["withings_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "userid": userid,
        "scopes": "",
        "token_type": "",
    }
    sync = metadata.setdefault("withings_sync", {})
    sync["needs_reconnect"] = True
    sync["last_error"] = (reason or "Withings authorization expired. Reconnect Withings.") if mark_error else ""
    sync["last_synced_at"] = _now_iso()
    save_settings(settings)
    return sync


def load_withings_sync_state() -> dict:
    return load_settings().get("metadata", {}).get("withings_sync", {})


def _save_withings_sync_state(updates: dict) -> dict:
    settings = load_settings()
    sync = settings.setdefault("metadata", {}).setdefault("withings_sync", {})
    sync.update(updates)
    save_settings(settings)
    return load_withings_sync_state()


def save_withings_sync_error(message: str) -> dict:
    return _save_withings_sync_state({"last_error": message, "last_synced_at": _now_iso(), "needs_reconnect": True})


def build_withings_auth_url(redirect_uri: str, state: str | None = None) -> str:
    client_id, _ = _get_withings_credentials()
    if not redirect_uri:
        raise WithingsIntegrationError("WITHINGS_REDIRECT_URI could not be resolved.")
    query = {
        "response_type": "code",
        "client_id": client_id,
        "scope": WITHINGS_SCOPES,
        "redirect_uri": redirect_uri,
    }
    if state:
        query["state"] = state
    return f"{WITHINGS_AUTH_URL}?{urlencode(query)}"


def exchange_withings_code(code: str, redirect_uri: str) -> dict:
    if not code:
        raise WithingsIntegrationError("Missing Withings authorization code.")
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
        context="Withings token exchange failed",
    )
    token_body = _withings_body(payload, context="Withings token exchange failed")
    if not token_body.get("access_token") or not token_body.get("refresh_token"):
        raise WithingsIntegrationError("Withings token exchange failed: response did not include access and refresh tokens.")
    return _save_withings_tokens(token_body)


def refresh_withings_token_if_needed(force: bool = False, timeout_seconds: int = 25):
    settings = load_settings()
    tokens = settings.get("metadata", {}).get("withings_tokens", {})
    access_token = str(tokens.get("access_token", "") or "")
    refresh_token = str(tokens.get("refresh_token", "") or "")
    expires_at = int(tokens.get("expires_at") or 0)
    now = int(time.time())
    if not refresh_token:
        if access_token:
            clear_withings_connection("Saved Withings token has no refresh token. Reconnect Withings.")
        raise WithingsReconnectRequired("Withings refresh token is missing or expired. Reconnect Withings before syncing.")
    if not force and access_token and expires_at > now + TOKEN_EXPIRY_BUFFER_SECONDS:
        return access_token

    client_id, client_secret = _get_withings_credentials()
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
            context="Withings token refresh failed",
            timeout_seconds=timeout_seconds,
        )
        token_body = _withings_body(payload, context="Withings token refresh failed")
    except WithingsIntegrationError as exc:
        clear_withings_connection(f"Withings token refresh failed. Reconnect Withings. {exc}")
        raise WithingsReconnectRequired("Withings token refresh failed. Reconnect Withings from Settings.") from exc
    tokens = _save_withings_tokens(token_body)
    return str(tokens.get("access_token", ""))


def _date_to_timestamp(date_value: str | None, fallback: datetime) -> int:
    if not date_value:
        return int(fallback.timestamp())
    try:
        parsed = datetime.fromisoformat(str(date_value)).replace(tzinfo=timezone.utc)
    except ValueError:
        return int(fallback.timestamp())
    return int(parsed.timestamp())


def _measure_value(measure: dict) -> float | None:
    try:
        return float(measure["value"]) * (10 ** int(measure.get("unit", 0)))
    except (KeyError, TypeError, ValueError):
        return None


def _kg_to_lb(value: float | None) -> float | None:
    return round(value * KG_TO_LB, 2) if value is not None else None


def derive_bmi(weight_kg: float | None, height_m: float | None) -> float | None:
    if not weight_kg or not height_m:
        return None
    if height_m <= 0:
        return None
    return round(weight_kg / (height_m * height_m), 2)


def parse_measure_group(group: dict) -> dict:
    parsed: dict[str, float | None] = {
        "weight_kg": None,
        "weight_lb": None,
        "height_m": None,
        "body_fat_percent": None,
        "lean_mass_kg": None,
        "lean_mass_lb": None,
        "fat_mass_kg": None,
        "fat_mass_lb": None,
        "muscle_mass_kg": None,
        "muscle_mass_lb": None,
        "hydration_kg": None,
        "hydration_lb": None,
        "bone_mass_kg": None,
        "bone_mass_lb": None,
    }
    for measure in group.get("measures", []) or []:
        value = _measure_value(measure)
        if value is None:
            continue
        measure_type = int(measure.get("type") or 0)
        if measure_type == WEIGHT_TYPE:
            parsed["weight_kg"] = round(value, 3)
            parsed["weight_lb"] = _kg_to_lb(value)
        elif measure_type == HEIGHT_TYPE:
            parsed["height_m"] = round(value, 3)
        elif measure_type == FAT_FREE_MASS_KG_TYPE:
            parsed["lean_mass_kg"] = round(value, 3)
            parsed["lean_mass_lb"] = _kg_to_lb(value)
        elif measure_type == FAT_RATIO_TYPE:
            parsed["body_fat_percent"] = round(value, 2)
        elif measure_type == FAT_MASS_KG_TYPE:
            parsed["fat_mass_kg"] = round(value, 3)
            parsed["fat_mass_lb"] = _kg_to_lb(value)
        elif measure_type == MUSCLE_MASS_KG_TYPE:
            parsed["muscle_mass_kg"] = round(value, 3)
            parsed["muscle_mass_lb"] = _kg_to_lb(value)
        elif measure_type == HYDRATION_KG_TYPE:
            parsed["hydration_kg"] = round(value, 3)
            parsed["hydration_lb"] = _kg_to_lb(value)
        elif measure_type == BONE_MASS_KG_TYPE:
            parsed["bone_mass_kg"] = round(value, 3)
            parsed["bone_mass_lb"] = _kg_to_lb(value)
    return parsed


def _measurement_rows(measure_groups: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for group in measure_groups:
        parsed = parse_measure_group(group)
        weight_lb = parsed.get("weight_lb")
        weight_kg = parsed.get("weight_kg")
        if not weight_lb or not weight_kg:
            continue
        measured_at = datetime.fromtimestamp(int(group.get("date", 0) or 0), tz=timezone.utc)
        fat_percent = parsed.get("body_fat_percent")
        fat_mass_lb = parsed.get("fat_mass_lb")
        if fat_mass_lb is None and fat_percent is not None:
            fat_mass_lb = round(weight_lb * fat_percent / 100, 2)
        lean_mass_lb = parsed.get("lean_mass_lb")
        if lean_mass_lb is None and fat_mass_lb is not None:
            lean_mass_lb = round(weight_lb - fat_mass_lb, 2)
        bmi = derive_bmi(weight_kg, parsed.get("height_m"))
        source_id = str(group.get("grpid", "") or "")
        notes = [
            "source=withings",
            f"withings_measure_group_id={source_id}",
            f"measured_at={measured_at.isoformat()}",
            f"bodyweight_kg={weight_kg:.3f}",
        ]
        if parsed.get("fat_mass_kg") is not None:
            notes.append(f"fat_mass_kg={parsed['fat_mass_kg']:.3f}")
        if parsed.get("lean_mass_kg") is not None:
            notes.append(f"lean_mass_kg={parsed['lean_mass_kg']:.3f}")
        if parsed.get("muscle_mass_kg") is not None:
            notes.append(f"muscle_mass_kg={parsed['muscle_mass_kg']:.3f}")
        if parsed.get("hydration_kg") is not None:
            notes.append(f"hydration_kg={parsed['hydration_kg']:.3f}")
        if bmi is not None:
            notes.append(f"bmi={bmi:.2f}")
        rows.append(
            {
                "date": measured_at.date().isoformat(),
                "bodyweight": weight_lb,
                "waist": None,
                "estimated_body_fat": round(float(fat_percent), 2) if fat_percent is not None else None,
                "body_fat_percent": round(float(fat_percent), 2) if fat_percent is not None else None,
                "lean_mass": lean_mass_lb,
                "fat_mass": fat_mass_lb,
                "muscle_mass": parsed.get("muscle_mass_lb"),
                "hydration": parsed.get("hydration_lb"),
                "bone_mass": parsed.get("bone_mass_lb"),
                "bmi": bmi,
                "source_id": source_id,
                "raw_payload": json.dumps({"group": group, "parsed": parsed}, separators=(",", ":"), default=str),
                "notes": " | ".join(notes),
            }
        )
    return rows


def sync_withings_measurements(days: int | None = None, start_date: str | None = None, end_date: str | None = None) -> dict:
    end_dt = datetime.now(timezone.utc)
    lookback_days = int(days or os.getenv("WITHINGS_SYNC_LOOKBACK_DAYS", str(DEFAULT_SYNC_DAYS)) or DEFAULT_SYNC_DAYS)
    start_dt = end_dt - timedelta(days=max(1, lookback_days))
    start_ts = _date_to_timestamp(start_date, start_dt)
    end_ts = _date_to_timestamp(end_date, end_dt)

    access_token = refresh_withings_token_if_needed()
    if isinstance(access_token, dict):
        access_token = str(access_token.get("access_token", ""))

    request_body = {
        "action": "getmeas",
        "category": 1,
        "meastypes": WITHINGS_REQUESTED_MEASTYPES,
        "startdate": start_ts,
        "enddate": end_ts,
    }
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        payload = _post_form(WITHINGS_MEASURE_URL, request_body, headers=headers, context="Withings API fetch failed")
        body = _withings_body(payload, context="Withings API fetch failed")
    except WithingsIntegrationError:
        access_token = refresh_withings_token_if_needed(force=True)
        if isinstance(access_token, dict):
            access_token = str(access_token.get("access_token", ""))
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = _post_form(WITHINGS_MEASURE_URL, request_body, headers=headers, context="Withings API fetch failed")
        body = _withings_body(payload, context="Withings API fetch failed")

    measure_groups = body.get("measuregrps", []) or []
    rows = _measurement_rows(measure_groups)
    result = upsert_withings_measurements(rows)
    imported = result["created"] + result["updated"]
    latest_date = max((row["date"] for row in rows), default="")
    sync = _save_withings_sync_state(
        {
            "last_synced_at": _now_iso(),
            "last_error": "",
            "last_imported_count": imported,
            "last_created_count": result["created"],
            "last_updated_count": result["updated"],
            "last_fetched_groups": len(measure_groups),
            "latest_measure_date": latest_date,
            "latest_measurement_date": latest_date,
            "needs_reconnect": False,
        }
    )
    return {
        "status": "ok",
        "imported_measurements": imported,
        "created_measurements": result["created"],
        "updated_measurements": result["updated"],
        "fetched_groups": len(measure_groups),
        "latest_measure_date": latest_date,
        "latest_measurement_date": latest_date,
        "last_synced_at": sync.get("last_synced_at", ""),
    }
