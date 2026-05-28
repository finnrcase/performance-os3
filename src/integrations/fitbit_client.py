"""Fitbit OAuth and daily wearable ingestion helpers.

The frontend never receives the client secret or token values. This module is
used by FastAPI routes that run the OAuth exchange, token refresh, and daily
metric fetch server-side.
"""

from __future__ import annotations

import base64
import json
import os
import time
from datetime import date, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from src.wearables import normalize_wearable_metric_rows


FITBIT_AUTH_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"
FITBIT_API_BASE_URL = "https://api.fitbit.com"
FITBIT_SCOPES = ["activity", "heartrate", "profile", "sleep"]


class FitbitIntegrationError(RuntimeError):
    """Raised when Fitbit returns an unrecoverable API or OAuth error."""


def _settings_integrations(settings: dict | None = None) -> dict:
    integrations = (settings or {}).get("integrations")
    return integrations if isinstance(integrations, dict) else {}


def _config_value(env_name: str, settings: dict | None, key: str) -> str:
    return os.getenv(env_name, "").strip() or str(_settings_integrations(settings).get(key) or "").strip()


def client_credentials(settings: dict | None = None) -> tuple[str, str]:
    """Return configured Fitbit client credentials without logging them."""
    return (
        _config_value("FITBIT_CLIENT_ID", settings, "fitbit_client_id"),
        _config_value("FITBIT_CLIENT_SECRET", settings, "fitbit_client_secret"),
    )


def redirect_uri(settings: dict | None = None, *, fallback: str = "") -> str:
    return _config_value("FITBIT_REDIRECT_URI", settings, "fitbit_redirect_uri") or fallback


def scopes() -> list[str]:
    configured = os.getenv("FITBIT_SCOPES", "").replace(",", " ").split()
    unique = [scope.strip() for scope in configured if scope.strip()]
    return unique or FITBIT_SCOPES.copy()


def api_base_url() -> str:
    return (os.getenv("FITBIT_API_BASE_URL", "").strip() or FITBIT_API_BASE_URL).rstrip("/")


def is_configured(settings: dict | None = None) -> bool:
    """Return whether Fitbit client credentials are present in app settings."""
    client_id, client_secret = client_credentials(settings)
    return bool(client_id and client_secret)


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    token = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _read_error(exc: HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    if not body:
        return f"HTTP {exc.code}"
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body[:500]
    if isinstance(parsed, dict):
        errors = parsed.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict):
                return str(first.get("message") or first.get("errorType") or parsed)[:500]
        return str(parsed.get("error_description") or parsed.get("message") or parsed)[:500]
    return str(parsed)[:500]


def _request_json(request: Request, *, timeout: int = 25) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        message = _read_error(exc)
        raise FitbitIntegrationError(f"Fitbit API returned HTTP {exc.code}: {message}") from exc
    except URLError as exc:
        raise FitbitIntegrationError(f"Fitbit API request failed: {exc.reason}") from exc
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FitbitIntegrationError("Fitbit API returned invalid JSON.") from exc
    return parsed if isinstance(parsed, dict) else {"items": parsed}


def _post_form(url: str, form: dict[str, Any], settings: dict | None = None) -> dict[str, Any]:
    client_id, client_secret = client_credentials(settings)
    if not client_id or not client_secret:
        raise FitbitIntegrationError("Fitbit client credentials are not configured.")
    body = urlencode({key: value for key, value in form.items() if value is not None}).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": _basic_auth_header(client_id, client_secret),
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    return _request_json(request)


def _get_json(path: str, access_token: str) -> dict[str, Any]:
    token = str(access_token or "").strip()
    if not token:
        raise FitbitIntegrationError("No Fitbit access token is available.")
    request = Request(
        f"{api_base_url()}{path}",
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    return _request_json(request)


def _token_payload(raw: dict[str, Any], *, refresh_fallback: str = "") -> dict[str, Any]:
    try:
        expires_in = int(raw.get("expires_in") or 0)
    except (TypeError, ValueError):
        expires_in = 0
    granted_scopes = raw.get("scope") or " ".join(scopes())
    if isinstance(granted_scopes, list):
        granted_scopes = " ".join(str(scope) for scope in granted_scopes)
    refresh_token = str(raw.get("refresh_token") or refresh_fallback or "").strip()
    return {
        "access_token": str(raw.get("access_token") or "").strip(),
        "refresh_token": refresh_token,
        "expires_at": int(time.time()) + expires_in if expires_in else 0,
        "token_type": str(raw.get("token_type") or "Bearer").strip(),
        "user_id": str(raw.get("user_id") or raw.get("encoded_user_id") or "").strip(),
        "scopes": str(granted_scopes or "").replace(",", " ").strip(),
    }


def get_auth_url(
    settings: dict | None = None,
    *,
    redirect_uri: str = "",
    state: str = "",
    scope: list[str] | None = None,
) -> dict:
    """Build a Fitbit OAuth authorization URL, or explain missing config."""
    if not is_configured(settings):
        return {
            "status": "not_configured",
            "auth_url": "",
            "message": "Fitbit client credentials are not configured.",
        }
    client_id, _ = client_credentials(settings)
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": " ".join(scope or scopes()),
    }
    resolved_redirect = redirect_uri or globals()["redirect_uri"](settings)
    if resolved_redirect:
        params["redirect_uri"] = resolved_redirect
    if state:
        params["state"] = state
    return {
        "status": "ok",
        "auth_url": f"{FITBIT_AUTH_URL}?{urlencode(params)}",
        "redirect_uri": resolved_redirect,
        "scope": params["scope"],
        "message": "Open this URL to connect Fitbit.",
    }


def exchange_code_for_token(code: str, settings: dict | None = None, *, redirect_uri: str = "") -> dict:
    """Exchange a Fitbit authorization code for durable OAuth tokens."""
    if not is_configured(settings):
        return {"status": "not_configured", "message": "Fitbit client credentials are not configured."}
    if not str(code or "").strip():
        return {"status": "missing_code", "message": "No Fitbit authorization code was provided."}
    try:
        raw = _post_form(
            FITBIT_TOKEN_URL,
            {
                "client_id": client_credentials(settings)[0],
                "grant_type": "authorization_code",
                "code": str(code).strip(),
                "redirect_uri": redirect_uri or globals()["redirect_uri"](settings),
            },
            settings,
        )
    except Exception as exc:
        return {"status": "error", "message": str(exc), "tokens": {}}
    tokens = _token_payload(raw)
    if not tokens.get("access_token"):
        return {"status": "error", "message": "Fitbit did not return an access token.", "tokens": tokens}
    return {"status": "ok", "message": "Fitbit token exchange succeeded.", "tokens": tokens}


def refresh_access_token(refresh_token: str, settings: dict | None = None) -> dict:
    """Refresh a Fitbit access token using the saved refresh token."""
    if not is_configured(settings):
        return {"status": "not_configured", "message": "Fitbit client credentials are not configured."}
    refresh_token = str(refresh_token or "").strip()
    if not refresh_token:
        return {"status": "missing_refresh_token", "message": "No Fitbit refresh token was provided."}
    try:
        raw = _post_form(
            FITBIT_TOKEN_URL,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            settings,
        )
    except Exception as exc:
        return {"status": "error", "message": str(exc), "tokens": {}}
    tokens = _token_payload(raw, refresh_fallback=refresh_token)
    if not tokens.get("access_token"):
        return {"status": "error", "message": "Fitbit refresh did not return an access token.", "tokens": tokens}
    return {"status": "ok", "message": "Fitbit token refresh succeeded.", "tokens": tokens}


def _date_range(start_date: str | None, end_date: str | None) -> list[str]:
    today = date.today()
    try:
        end = date.fromisoformat(str(end_date or today.isoformat())[:10])
    except ValueError:
        end = today
    try:
        start = date.fromisoformat(str(start_date or end.isoformat())[:10])
    except ValueError:
        start = end
    if start > end:
        start, end = end, start
    days = min((end - start).days + 1, 31)
    return [(start + timedelta(days=index)).isoformat() for index in range(days)]


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    parsed = _safe_float(value)
    return None if parsed is None else int(round(parsed))


def _first_number(raw: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        parsed = _safe_float(raw.get(key))
        if parsed is not None:
            return parsed
    return None


def _distance_miles(summary: dict[str, Any]) -> float | None:
    distances = summary.get("distances")
    if not isinstance(distances, list):
        return None
    for item in distances:
        if not isinstance(item, dict):
            continue
        activity = str(item.get("activity") or "").lower()
        if activity == "total":
            return _safe_float(item.get("distance"))
    return None


def _active_zone_minutes(summary: dict[str, Any]) -> int | None:
    minutes = _safe_int(summary.get("activeZoneMinutes"))
    if minutes is not None:
        return minutes
    total = 0
    found = False
    zone_minutes = summary.get("activeZoneMinutes") or summary.get("activeZones")
    if isinstance(zone_minutes, list):
        for zone in zone_minutes:
            if isinstance(zone, dict):
                parsed = _safe_int(zone.get("minutes") or zone.get("activeZoneMinutes"))
                if parsed is not None:
                    total += parsed
                    found = True
    return total if found else None


def _parse_activity(raw: dict[str, Any], row: dict[str, Any]) -> None:
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    steps = _safe_int(summary.get("steps"))
    distance_miles = _distance_miles(summary)
    calories_out = _safe_float(summary.get("caloriesOut"))
    activity_calories = _safe_float(summary.get("activityCalories"))
    basal_calories = _safe_float(summary.get("caloriesBMR"))
    active_minutes = sum(
        value
        for value in (
            _safe_int(summary.get("lightlyActiveMinutes")),
            _safe_int(summary.get("fairlyActiveMinutes")),
            _safe_int(summary.get("veryActiveMinutes")),
        )
        if value is not None
    )
    if steps is not None:
        row["steps"] = steps
    if active_minutes:
        row["active_minutes"] = active_minutes
    zone_minutes = _active_zone_minutes(summary)
    if zone_minutes is not None:
        row["active_zone_minutes"] = zone_minutes
    if distance_miles is not None:
        row["distance_miles"] = distance_miles
        row["distance_meters"] = distance_miles * 1609.344
    if calories_out is not None:
        row["calories_burned"] = calories_out
        row["total_calories_burned"] = calories_out
    if activity_calories is not None:
        row["active_calories_burned"] = activity_calories
    if basal_calories is not None:
        row["basal_calories_burned"] = basal_calories


def _parse_heart(raw: dict[str, Any], row: dict[str, Any]) -> None:
    entries = raw.get("activities-heart")
    entry = entries[0] if isinstance(entries, list) and entries and isinstance(entries[0], dict) else {}
    value = entry.get("value") if isinstance(entry.get("value"), dict) else {}
    resting_hr = _safe_float(value.get("restingHeartRate"))
    if resting_hr is not None:
        row["resting_hr"] = resting_hr
    zones = value.get("heartRateZones")
    if isinstance(zones, list):
        max_hr = max((_safe_float(zone.get("max")) or 0 for zone in zones if isinstance(zone, dict)), default=0)
        if max_hr:
            row["max_hr"] = max_hr


def _parse_sleep(raw: dict[str, Any], row: dict[str, Any]) -> None:
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    stages = summary.get("stages") if isinstance(summary.get("stages"), dict) else {}
    total_minutes = _safe_float(summary.get("totalMinutesAsleep"))
    time_in_bed = _safe_float(summary.get("totalTimeInBed"))
    rem = _safe_float(stages.get("rem"))
    deep = _safe_float(stages.get("deep"))
    light = _safe_float(stages.get("light"))
    wake = _safe_float(stages.get("wake"))
    sleep_records = raw.get("sleep") if isinstance(raw.get("sleep"), list) else []
    primary_record = sleep_records[0] if sleep_records and isinstance(sleep_records[0], dict) else {}
    efficiency = _safe_float(primary_record.get("efficiency") or summary.get("efficiency"))
    score = _safe_float(primary_record.get("score") or summary.get("score"))
    if total_minutes is not None:
        row["total_sleep_minutes"] = total_minutes
        row["sleep_hours"] = round(total_minutes / 60, 2)
    if rem is not None:
        row["rem_sleep_minutes"] = rem
    if deep is not None:
        row["deep_sleep_minutes"] = deep
    if light is not None:
        row["light_sleep_minutes"] = light
    if wake is not None:
        row["awake_minutes"] = wake
    elif time_in_bed is not None and total_minutes is not None:
        row["awake_minutes"] = max(time_in_bed - total_minutes, 0)
    if efficiency is not None:
        row["sleep_efficiency"] = efficiency
    elif total_minutes is not None and time_in_bed:
        row["sleep_efficiency"] = round((total_minutes / time_in_bed) * 100, 1)
    if score is not None:
        row["sleep_score"] = score


def _parse_hrv(raw: dict[str, Any], row: dict[str, Any]) -> None:
    items = raw.get("hrv")
    entry = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    value = entry.get("value") if isinstance(entry.get("value"), dict) else {}
    hrv = _first_number(value, "dailyRmssd", "deepRmssd")
    if hrv is not None:
        row["hrv"] = hrv


def _parse_spo2(raw: dict[str, Any], row: dict[str, Any]) -> None:
    value = raw.get("value") if isinstance(raw.get("value"), dict) else {}
    spo2 = _first_number(value, "avg", "min", "max")
    if spo2 is not None:
        row["spo2"] = spo2


def _parse_skin_temperature(raw: dict[str, Any], row: dict[str, Any]) -> None:
    items = raw.get("tempSkin")
    entry = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
    value = entry.get("value") if isinstance(entry.get("value"), dict) else {}
    skin_temperature = _first_number(value, "nightlyRelative", "value")
    if skin_temperature is not None:
        row["skin_temperature"] = skin_temperature


def _fetch_optional(path: str, access_token: str, warnings: list[str], label: str) -> dict[str, Any]:
    try:
        return _get_json(path, access_token)
    except FitbitIntegrationError as exc:
        message = str(exc)
        if "HTTP 401" in message:
            raise
        warnings.append(f"{label}: {message[:220]}")
        return {}


def fetch_daily_metrics(
    access_token: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Fetch Fitbit daily aggregates and normalize them into row dictionaries."""
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "items": [],
            "message": "No Fitbit access token is available.",
        }
    dates = _date_range(start_date, end_date)
    warnings: list[str] = []
    items: list[dict[str, Any]] = []
    try:
        for day in dates:
            row: dict[str, Any] = {
                "metric_id": f"fitbit:{day}",
                "date": day,
                "source": "fitbit",
            }
            for label, path, parser in (
                ("activity", f"/1/user/-/activities/date/{day}.json", _parse_activity),
                ("heart", f"/1/user/-/activities/heart/date/{day}/1d.json", _parse_heart),
                ("sleep", f"/1.2/user/-/sleep/date/{day}.json", _parse_sleep),
                ("hrv", f"/1/user/-/hrv/date/{day}.json", _parse_hrv),
                ("spo2", f"/1/user/-/spo2/date/{day}.json", _parse_spo2),
                ("skin temperature", f"/1/user/-/temp/skin/date/{day}.json", _parse_skin_temperature),
            ):
                raw = _fetch_optional(path, access_token, warnings, label)
                if raw:
                    parser(raw, row)
            items.append(row)
        profile = _fetch_optional("/1/user/-/profile.json", access_token, warnings, "profile")
    except FitbitIntegrationError as exc:
        return {
            "status": "error",
            "items": items,
            "message": str(exc),
            "warnings": warnings,
            "date_range": {"start_date": dates[0] if dates else "", "end_date": dates[-1] if dates else ""},
        }
    return {
        "status": "ok",
        "items": items,
        "warnings": warnings,
        "profile_user_id": str((profile.get("user") or {}).get("encodedId") or "") if isinstance(profile.get("user"), dict) else "",
        "date_range": {"start_date": dates[0] if dates else "", "end_date": dates[-1] if dates else ""},
    }


def normalize_daily_metrics(metrics: list[dict] | pd.DataFrame | None, source: str = "fitbit") -> pd.DataFrame:
    """Normalize Fitbit daily metric payloads into wearable metric rows."""
    return normalize_wearable_metric_rows(metrics, source=source, provider=source)
