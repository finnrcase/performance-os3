"""Server-side Google Health OAuth and daily wearable metric sync helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from src.wearables import WEARABLE_METRIC_COLUMNS


logger = logging.getLogger(__name__)

GOOGLE_HEALTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_HEALTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_GOOGLE_HEALTH_API_BASE_URL = "https://www.googleapis.com/fitness/v1"
GOOGLE_HEALTH_SCOPES = [
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "https://www.googleapis.com/auth/fitness.body_temperature.read",
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.location.read",
    "https://www.googleapis.com/auth/fitness.oxygen_saturation.read",
    "https://www.googleapis.com/auth/fitness.sleep.read",
]
GOOGLE_HEALTH_CORE_AGGREGATE_TYPES = [
    "com.google.step_count.delta",
    "com.google.calories.expended",
    "com.google.active_minutes",
    "com.google.sleep.segment",
]
GOOGLE_HEALTH_HEART_RATE_AGGREGATE_TYPES = [
    "com.google.heart_rate.summary",
    "com.google.heart_rate.bpm",
]
GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING = "Optional heart rate summary unavailable from Google Health."
GOOGLE_HEALTH_NO_SOURCES_MESSAGE = (
    "Google Health connected, but this API path does not expose the wearable data shown in the phone app. "
    "Use direct Fitbit API sync or a Health Connect export/import path for that data."
)
GOOGLE_HEALTH_OPTIONAL_AGGREGATE_TYPE_BATCHES = [
    [
        "com.google.heart_rate.summary",
    ],
    [
        "com.google.heart_minutes.summary",
        "com.google.distance.delta",
        "com.google.calories.bmr.summary",
    ],
    [
        "com.google.oxygen_saturation.summary",
        "com.google.body.temperature.summary",
    ],
]
GOOGLE_HEALTH_AGGREGATE_TYPES = [
    *GOOGLE_HEALTH_CORE_AGGREGATE_TYPES,
    *[data_type for batch in GOOGLE_HEALTH_OPTIONAL_AGGREGATE_TYPE_BATCHES for data_type in batch],
]
GOOGLE_HEALTH_METRIC_FIELDS = [
    "sleep_hours",
    "total_sleep_minutes",
    "rem_sleep_minutes",
    "deep_sleep_minutes",
    "light_sleep_minutes",
    "awake_minutes",
    "sleep_efficiency",
    "sleep_score",
    "resting_hr",
    "resting_hr_baseline",
    "resting_hr_deviation",
    "hrv",
    "average_hr",
    "max_hr",
    "workout_average_hr",
    "workout_max_hr",
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "distance_miles",
    "total_calories_burned",
    "calories_burned",
    "active_calories_burned",
    "basal_calories_burned",
    "workout_minutes",
    "cardio_load",
    "breathing_rate",
    "spo2",
    "skin_temperature",
    "body_temperature",
]
GOOGLE_HEALTH_DISCOVERY_GROUPS: dict[str, list[str]] = {
    "steps": ["com.google.step_count.delta"],
    "calories": ["com.google.calories.expended"],
    "active_minutes": ["com.google.active_minutes"],
    "sleep": ["com.google.sleep.segment"],
    "heart_rate": ["com.google.heart_rate.summary", "com.google.heart_rate.bpm"],
    "active_zone_minutes": ["com.google.heart_minutes.summary"],
    "distance": ["com.google.distance.delta"],
    "basal_calories": ["com.google.calories.bmr.summary"],
    "oxygen_saturation": ["com.google.oxygen_saturation.summary"],
    "body_temperature": [
        "com.google.body.temperature.summary",
        "com.google.body_temperature.summary",
        "com.google.skin.temperature.summary",
    ],
}
GOOGLE_HEALTH_CORE_GROUPS = ("steps", "calories", "active_minutes", "sleep")
SLEEP_STAGE_NAMES = {
    1: "awake",
    2: "sleep",
    3: "out_of_bed",
    4: "light",
    5: "deep",
    6: "rem",
}


class GoogleHealthIntegrationError(RuntimeError):
    """Raised when Google Health auth or sync cannot complete."""


def _settings_integrations(settings: dict | None = None) -> dict[str, Any]:
    integrations = (settings or {}).get("integrations")
    return integrations if isinstance(integrations, dict) else {}


def _settings_metadata(settings: dict | None = None) -> dict[str, Any]:
    metadata = (settings or {}).get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _config_value(settings: dict | None, env_name: str, field: str) -> str:
    return os.getenv(env_name, "").strip() or str(_settings_integrations(settings).get(field) or "").strip()


def _normalize_oauth_config_value(value: str) -> str:
    text = str(value or "").strip().strip('"').strip("'").strip()
    if text.startswith("="):
        text = text[1:].strip()
    return text


def client_credentials(settings: dict | None = None) -> tuple[str, str]:
    return (
        _normalize_oauth_config_value(_config_value(settings, "GOOGLE_HEALTH_CLIENT_ID", "google_health_client_id")),
        _normalize_oauth_config_value(_config_value(settings, "GOOGLE_HEALTH_CLIENT_SECRET", "google_health_client_secret")),
    )


def redirect_uri(settings: dict | None = None, fallback: str = "") -> str:
    return (
        os.getenv("GOOGLE_HEALTH_REDIRECT_URI", "").strip()
        or str(_settings_integrations(settings).get("google_health_redirect_uri") or "").strip()
        or str(fallback or "").strip()
    )


def scopes() -> list[str]:
    configured = os.getenv("GOOGLE_HEALTH_SCOPES", "").strip()
    if configured:
        return [scope for scope in configured.replace(",", " ").split() if scope]
    return GOOGLE_HEALTH_SCOPES.copy()


def aggregate_type_batches() -> list[list[str]]:
    configured = os.getenv("GOOGLE_HEALTH_AGGREGATE_TYPES", "").strip()
    if configured:
        data_types = [data_type for data_type in configured.replace(",", " ").split() if data_type]
        return [data_types] if data_types else [GOOGLE_HEALTH_CORE_AGGREGATE_TYPES.copy()]
    return [GOOGLE_HEALTH_CORE_AGGREGATE_TYPES.copy(), *[batch.copy() for batch in GOOGLE_HEALTH_OPTIONAL_AGGREGATE_TYPE_BATCHES]]


def api_base_url() -> str:
    return os.getenv("GOOGLE_HEALTH_API_BASE_URL", "").strip().rstrip("/") or DEFAULT_GOOGLE_HEALTH_API_BASE_URL


def is_configured(settings: dict | None = None) -> bool:
    """Return whether Google Health OAuth credentials are available server-side."""
    client_id, client_secret = client_credentials(settings)
    return bool(client_id and client_secret)


def get_auth_url(
    settings: dict | None = None,
    *,
    redirect_uri: str = "",
    state: str = "",
    scope: list[str] | None = None,
) -> dict[str, Any]:
    """Build a Google OAuth URL without exposing the client secret."""
    client_id, client_secret = client_credentials(settings)
    if not client_id or not client_secret:
        return {
            "status": "not_configured",
            "auth_url": "",
            "message": "Google Health client credentials are not configured.",
        }
    callback_uri = redirect_uri or globals()["redirect_uri"](settings)
    if not callback_uri:
        return {
            "status": "missing_redirect_uri",
            "auth_url": "",
            "message": "GOOGLE_HEALTH_REDIRECT_URI is not configured.",
        }

    params = {
        "client_id": client_id,
        "redirect_uri": callback_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "scope": " ".join(scope or scopes()),
    }
    if state:
        params["state"] = state
    return {
        "status": "ok",
        "auth_url": f"{GOOGLE_HEALTH_AUTH_URL}?{urlencode(params)}",
        "redirect_uri": callback_uri,
        "scope": params["scope"],
        "message": "Google Health authorization URL generated.",
    }


def _request_json(request: Request, *, context: str, timeout_seconds: int = 25) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(detail)
            message = body.get("error_description") or body.get("error") or detail
        except json.JSONDecodeError:
            message = detail or str(exc)
        if getattr(exc, "code", None) == 429:
            logger.warning("[google_health] API rate limit context=%s detail=%s", context, str(message)[:500])
            raise GoogleHealthIntegrationError(f"{context}: API rate limit reached. Try syncing again later.") from exc
        raise GoogleHealthIntegrationError(f"{context}: {message}") from exc
    except URLError as exc:
        raise GoogleHealthIntegrationError(f"{context}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise GoogleHealthIntegrationError(f"{context}: request timed out") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GoogleHealthIntegrationError(f"{context}: invalid JSON response") from exc


def _post_form(url: str, body: dict[str, Any], *, context: str, timeout_seconds: int = 25) -> dict[str, Any]:
    request = Request(
        url,
        data=urlencode({key: value for key, value in body.items() if value is not None}).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return _request_json(request, context=context, timeout_seconds=timeout_seconds)


def _post_json(url: str, body: dict[str, Any], access_token: str, *, context: str, timeout_seconds: int = 30) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    return _request_json(request, context=context, timeout_seconds=timeout_seconds)


def _get_json(url: str, access_token: str, *, context: str, timeout_seconds: int = 20) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        },
        method="GET",
    )
    return _request_json(request, context=context, timeout_seconds=timeout_seconds)


def _normalize_token_body(token_body: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = previous or {}
    expires_in = int(token_body.get("expires_in") or 3600)
    return {
        "access_token": str(token_body.get("access_token") or previous.get("access_token") or ""),
        "refresh_token": str(token_body.get("refresh_token") or previous.get("refresh_token") or ""),
        "expires_at": int(time.time()) + max(60, expires_in - 60),
        "token_type": str(token_body.get("token_type") or previous.get("token_type") or "Bearer"),
        "scopes": str(token_body.get("scope") or previous.get("scopes") or " ".join(scopes())),
    }


def exchange_code_for_token(code: str, settings: dict | None = None, *, redirect_uri: str = "") -> dict[str, Any]:
    """Exchange an OAuth authorization code for tokens server-side."""
    client_id, client_secret = client_credentials(settings)
    if not client_id or not client_secret:
        return {"status": "not_configured", "message": "Google Health client credentials are not configured.", "tokens": {}}
    if not str(code or "").strip():
        return {"status": "missing_code", "message": "No Google authorization code was provided.", "tokens": {}}
    callback_uri = redirect_uri or globals()["redirect_uri"](settings)
    if not callback_uri:
        return {"status": "missing_redirect_uri", "message": "GOOGLE_HEALTH_REDIRECT_URI is not configured.", "tokens": {}}
    token_body = _post_form(
        GOOGLE_HEALTH_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": callback_uri,
        },
        context="Google Health token exchange failed",
    )
    tokens = _normalize_token_body(token_body)
    return {"status": "ok", "message": "Google Health connected.", "tokens": tokens}


def refresh_access_token(refresh_token: str, settings: dict | None = None) -> dict[str, Any]:
    """Refresh a Google Health access token server-side."""
    client_id, client_secret = client_credentials(settings)
    if not client_id or not client_secret:
        return {"status": "not_configured", "message": "Google Health client credentials are not configured.", "tokens": {}}
    if not str(refresh_token or "").strip():
        return {"status": "missing_refresh_token", "message": "No Google refresh token was provided.", "tokens": {}}
    token_body = _post_form(
        GOOGLE_HEALTH_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        context="Google Health token refresh failed",
    )
    tokens = _normalize_token_body(token_body, {"refresh_token": refresh_token})
    return {"status": "ok", "message": "Google Health token refreshed.", "tokens": tokens}


def _app_timezone() -> ZoneInfo:
    name = os.getenv("APP_TIMEZONE") or os.getenv("TIMEZONE") or os.getenv("TZ") or "America/Los_Angeles"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("America/Los_Angeles")


def _date_text(value: str | date | datetime | None, fallback: date) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return fallback.isoformat()


def _millis_for_local_date(day: str, *, end: bool = False) -> int:
    tz = _app_timezone()
    parsed = date.fromisoformat(day)
    if end:
        parsed = parsed + timedelta(days=1)
    return int(datetime(parsed.year, parsed.month, parsed.day, tzinfo=tz).timestamp() * 1000)


def _point_value(value: dict[str, Any]) -> float | None:
    for key in ("fpVal", "intVal"):
        if key in value:
            try:
                return float(value[key])
            except (TypeError, ValueError):
                return None
    return None


def _point_values(point: dict[str, Any]) -> list[float]:
    values = point.get("value") if isinstance(point.get("value"), list) else []
    return [parsed for parsed in (_point_value(value) for value in values) if parsed is not None]


def _point_int_value(point: dict[str, Any]) -> int | None:
    values = point.get("value") if isinstance(point.get("value"), list) else []
    for value in values:
        if "intVal" not in value:
            continue
        try:
            return int(value["intVal"])
        except (TypeError, ValueError):
            return None
    return None


def _point_duration_minutes(point: dict[str, Any]) -> float:
    try:
        start_nanos = int(point.get("startTimeNanos") or 0)
        end_nanos = int(point.get("endTimeNanos") or 0)
    except (TypeError, ValueError):
        return 0.0
    if end_nanos <= start_nanos:
        return 0.0
    return (end_nanos - start_nanos) / 60_000_000_000


def _date_from_millis(value: Any) -> str:
    try:
        millis = int(value)
        return datetime.fromtimestamp(millis / 1000, _app_timezone()).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _rounded(value: Any, digits: int = 1) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return round(parsed, digits)


def _as_int(value: Any) -> int | None:
    parsed = _rounded(value, 0)
    return int(parsed) if parsed is not None else None


def _metric_present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return True
    if pd.isna(parsed):
        return False
    return parsed > 0


def populated_metric_count(row: dict[str, Any] | None) -> int:
    sample = row if isinstance(row, dict) else {}
    return sum(1 for field in GOOGLE_HEALTH_METRIC_FIELDS if _metric_present(sample.get(field)))


def has_populated_metrics(row: dict[str, Any] | None) -> bool:
    return populated_metric_count(row) > 0


def populated_metric_counts_by_day(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in items:
        day = str(row.get("date") or "")[:10]
        if day:
            counts[day] = populated_metric_count(row)
    return counts


def _field_count_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    populated = sum(populated_metric_count(row) for row in rows)
    return {
        "fields_populated_count": populated,
        "fields_missing_count": max(0, (len(GOOGLE_HEALTH_METRIC_FIELDS) * len(rows)) - populated),
    }


def _average(values: list[float]) -> float | None:
    valid = [float(value) for value in values if value is not None and not pd.isna(value)]
    return sum(valid) / len(valid) if valid else None


def _new_daily_row(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "source": "google_health",
        "sleep_hours": None,
        "sleep_score": None,
        "total_sleep_minutes": 0.0,
        "rem_sleep_minutes": 0.0,
        "deep_sleep_minutes": 0.0,
        "light_sleep_minutes": 0.0,
        "awake_minutes": 0.0,
        "sleep_efficiency": None,
        "resting_hr": None,
        "resting_hr_baseline": None,
        "resting_hr_deviation": None,
        "hrv": None,
        "average_hr": None,
        "max_hr": None,
        "workout_average_hr": None,
        "workout_max_hr": None,
        "steps": 0.0,
        "active_minutes": 0.0,
        "active_zone_minutes": 0.0,
        "distance_meters": 0.0,
        "distance_miles": None,
        "calories_burned": 0.0,
        "total_calories_burned": 0.0,
        "active_calories_burned": None,
        "basal_calories_burned": None,
        "workout_minutes": None,
        "cardio_load": None,
        "breathing_rate": None,
        "spo2": None,
        "skin_temperature": None,
        "body_temperature": None,
        "heart_rate_zones": None,
        "sleep_stage_minutes": {},
        "_seen_steps": False,
        "_seen_active_minutes": False,
        "_seen_active_zone_minutes": False,
        "_seen_distance": False,
        "_seen_calories": False,
        "_seen_sleep": False,
        "_heart_averages": [],
        "_heart_mins": [],
        "_heart_maxes": [],
    }


def _add_sleep_segment(row: dict[str, Any], point: dict[str, Any]) -> None:
    stage = _point_int_value(point)
    duration = _point_duration_minutes(point)
    if duration <= 0:
        return
    row["_seen_sleep"] = True
    stage_name = SLEEP_STAGE_NAMES.get(stage or 0, "unknown")
    stage_minutes = row.get("sleep_stage_minutes") if isinstance(row.get("sleep_stage_minutes"), dict) else {}
    stage_minutes[stage_name] = float(stage_minutes.get(stage_name) or 0) + duration
    row["sleep_stage_minutes"] = stage_minutes
    if stage_name in {"sleep", "light", "deep", "rem"}:
        row["total_sleep_minutes"] = float(row.get("total_sleep_minutes") or 0) + duration
    if stage_name == "light":
        row["light_sleep_minutes"] = float(row.get("light_sleep_minutes") or 0) + duration
    elif stage_name == "deep":
        row["deep_sleep_minutes"] = float(row.get("deep_sleep_minutes") or 0) + duration
    elif stage_name == "rem":
        row["rem_sleep_minutes"] = float(row.get("rem_sleep_minutes") or 0) + duration
    elif stage_name in {"awake", "out_of_bed"}:
        row["awake_minutes"] = float(row.get("awake_minutes") or 0) + duration


def _parse_summary_values(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if len(values) >= 3:
        average, max_value, min_value = values[0], values[1], values[2]
        return average, max_value, min_value
    if values:
        average = _average(values)
        return average, max(values), min(values)
    return None, None, None


def _parse_aggregate_point(row: dict[str, Any], data_type: str, point: dict[str, Any]) -> None:
    values = _point_values(point)
    if not values and "sleep.segment" not in data_type:
        return
    if "step_count" in data_type:
        row["steps"] = float(row.get("steps") or 0) + sum(values)
        row["_seen_steps"] = True
    elif "calories.expended" in data_type:
        total = sum(values)
        row["calories_burned"] = float(row.get("calories_burned") or 0) + total
        row["total_calories_burned"] = float(row.get("total_calories_burned") or 0) + total
        row["_seen_calories"] = True
    elif "calories.bmr" in data_type:
        average, _, _ = _parse_summary_values(values)
        if average is not None:
            row["basal_calories_burned"] = max(float(row.get("basal_calories_burned") or 0), float(average))
    elif "active_minutes" in data_type:
        row["active_minutes"] = float(row.get("active_minutes") or 0) + sum(values)
        row["_seen_active_minutes"] = True
    elif "heart_minutes" in data_type:
        intensity = values[0] if values else None
        duration = values[1] if len(values) > 1 else sum(values)
        row["active_zone_minutes"] = float(row.get("active_zone_minutes") or 0) + float(duration or 0)
        row["cardio_load"] = float(row.get("cardio_load") or 0) + float(intensity or duration or 0)
        row["_seen_active_zone_minutes"] = True
    elif "distance.delta" in data_type:
        row["distance_meters"] = float(row.get("distance_meters") or 0) + sum(values)
        row["_seen_distance"] = True
    elif "heart_rate" in data_type:
        average, max_value, min_value = _parse_summary_values(values)
        if average is not None:
            row["_heart_averages"].append(float(average))
        if min_value is not None:
            row["_heart_mins"].append(float(min_value))
        if max_value is not None:
            row["_heart_maxes"].append(float(max_value))
    elif "sleep.segment" in data_type:
        _add_sleep_segment(row, point)
    elif "oxygen_saturation" in data_type:
        average, _, _ = _parse_summary_values(values)
        row["spo2"] = _rounded(average)
    elif "body.temperature" in data_type or "body_temperature" in data_type:
        average, _, _ = _parse_summary_values(values)
        row["body_temperature"] = _rounded(average)
    elif "skin.temperature" in data_type or "skin_temperature" in data_type:
        average, _, _ = _parse_summary_values(values)
        row["skin_temperature"] = _rounded(average)
    elif "respir" in data_type or "breathing" in data_type:
        average, _, _ = _parse_summary_values(values)
        row["breathing_rate"] = _rounded(average)
    elif "variability" in data_type or ".hrv" in data_type:
        average, _, _ = _parse_summary_values(values)
        row["hrv"] = _rounded(average)


def _finalize_daily_row(row: dict[str, Any]) -> dict[str, Any]:
    heart_average = _average(row.get("_heart_averages") or [])
    if heart_average is not None:
        row["average_hr"] = _rounded(heart_average)
    if row.get("_heart_mins"):
        row["resting_hr"] = _rounded(min(row["_heart_mins"]))
    if row.get("_heart_maxes"):
        row["max_hr"] = _rounded(max(row["_heart_maxes"]))
    if row.get("average_hr") is not None and (row.get("active_minutes") or row.get("active_zone_minutes")):
        row["workout_average_hr"] = row["average_hr"]
        row["workout_max_hr"] = row.get("max_hr")

    if row.get("_seen_sleep"):
        sleep_minutes = float(row.get("total_sleep_minutes") or 0)
        awake_minutes = float(row.get("awake_minutes") or 0)
        row["sleep_hours"] = _rounded(sleep_minutes / 60, 2)
        for key in ("total_sleep_minutes", "rem_sleep_minutes", "deep_sleep_minutes", "light_sleep_minutes", "awake_minutes"):
            row[key] = _rounded(row.get(key), 1)
        denominator = sleep_minutes + awake_minutes
        row["sleep_efficiency"] = _rounded((sleep_minutes / denominator) * 100) if denominator > 0 else None
    else:
        for key in ("total_sleep_minutes", "rem_sleep_minutes", "deep_sleep_minutes", "light_sleep_minutes", "awake_minutes"):
            row[key] = None

    for key, seen_key in [
        ("steps", "_seen_steps"),
        ("active_minutes", "_seen_active_minutes"),
        ("active_zone_minutes", "_seen_active_zone_minutes"),
        ("distance_meters", "_seen_distance"),
        ("calories_burned", "_seen_calories"),
        ("total_calories_burned", "_seen_calories"),
    ]:
        if row.get(seen_key):
            row[key] = _as_int(row.get(key)) if key in {"steps", "active_minutes", "active_zone_minutes"} else _rounded(row.get(key))
        else:
            row[key] = None

    if row.get("distance_meters") is not None:
        row["distance_miles"] = _rounded(float(row["distance_meters"]) / 1609.344, 2)
    if row.get("total_calories_burned") is not None and row.get("basal_calories_burned") is not None:
        row["active_calories_burned"] = _rounded(max(0.0, float(row["total_calories_burned"]) - float(row["basal_calories_burned"])))
    if row.get("cardio_load") is not None:
        row["cardio_load"] = _rounded(row.get("cardio_load"))
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _parse_aggregate_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    row = _new_daily_row(_date_from_millis(bucket.get("startTimeMillis")))
    for dataset in bucket.get("dataset") or []:
        for point in dataset.get("point") or []:
            data_type = str(point.get("dataTypeName") or dataset.get("dataSourceId") or "").lower()
            _parse_aggregate_point(row, data_type, point)
    return _finalize_daily_row(row)


def _aggregate_body(data_types: list[str], start_text: str, end_text: str) -> dict[str, Any]:
    return {
        "aggregateBy": [{"dataTypeName": data_type} for data_type in data_types],
        "bucketByTime": {"durationMillis": 86_400_000},
        "startTimeMillis": _millis_for_local_date(start_text),
        "endTimeMillis": _millis_for_local_date(end_text, end=True),
    }


def _merge_buckets(target: dict[str, dict[str, Any]], response: dict[str, Any]) -> None:
    for bucket in response.get("bucket") or []:
        key = str(bucket.get("startTimeMillis") or "")
        if not key:
            continue
        current = target.setdefault(
            key,
            {
                "startTimeMillis": bucket.get("startTimeMillis"),
                "endTimeMillis": bucket.get("endTimeMillis"),
                "dataset": [],
            },
        )
        current.setdefault("dataset", [])
        current["dataset"].extend(bucket.get("dataset") or [])


def _fetch_aggregate_batch(access_token: str, data_types: list[str], start_text: str, end_text: str) -> dict[str, Any]:
    return _post_json(
        f"{api_base_url()}/users/me/dataset:aggregate",
        _aggregate_body(data_types, start_text, end_text),
        access_token,
        context="Google Health daily metrics fetch failed",
    )


def _sanitize_data_source(source: dict[str, Any]) -> dict[str, Any]:
    data_type = source.get("dataType") if isinstance(source.get("dataType"), dict) else {}
    application = source.get("application") if isinstance(source.get("application"), dict) else {}
    device = source.get("device") if isinstance(source.get("device"), dict) else {}
    return {
        "data_stream_id": str(source.get("dataStreamId") or ""),
        "data_stream_name": str(source.get("dataStreamName") or ""),
        "data_type_name": str(data_type.get("name") or source.get("dataTypeName") or ""),
        "type": str(source.get("type") or ""),
        "application": {
            "name": str(application.get("name") or ""),
            "package_name": str(application.get("packageName") or ""),
        },
        "device": {
            "manufacturer": str(device.get("manufacturer") or ""),
            "model": str(device.get("model") or ""),
            "type": str(device.get("type") or ""),
        },
    }


def _data_source_type_names(response: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for source in response.get("dataSource") or []:
        if not isinstance(source, dict):
            continue
        data_type = source.get("dataType") if isinstance(source.get("dataType"), dict) else {}
        for candidate in (
            data_type.get("name"),
            source.get("dataTypeName"),
            source.get("dataStreamId"),
            source.get("dataStreamName"),
        ):
            text = str(candidate or "").strip()
            if text:
                names.add(text)
    return names


def list_data_sources(access_token: str) -> dict[str, Any]:
    """Return available Google Fitness data sources for optional metric gating."""
    if not str(access_token or "").strip():
        return {"status": "missing_access_token", "data_sources": [], "data_type_names": []}
    response = _get_json(
        f"{api_base_url()}/users/me/dataSources",
        access_token,
        context="Google Health data source listing failed",
    )
    data_sources = response.get("dataSource") or []
    data_type_names = sorted(_data_source_type_names(response))
    sanitized_sources = [_sanitize_data_source(source) for source in data_sources if isinstance(source, dict)]
    logger.info(
        "[google_health] listed data sources count=%s data_types=%s",
        len(data_sources),
        len(data_type_names),
    )
    return {
        "status": "ok",
        "data_sources": sanitized_sources,
        "data_type_names": data_type_names,
        "available_data_types": data_type_names,
        "data_source_count": len(data_sources),
    }


def _matches_data_type(available: set[str], candidate: str) -> bool:
    needle = str(candidate or "").lower()
    if not needle:
        return False
    return any(needle == name.lower() or needle in name.lower() for name in available)


def _discovered_metric_groups(data_type_names: set[str]) -> dict[str, list[str]]:
    lowered = {str(name or "").lower() for name in data_type_names if str(name or "").strip()}
    discovered: dict[str, list[str]] = {}
    for group, candidates in GOOGLE_HEALTH_DISCOVERY_GROUPS.items():
        selected = [candidate for candidate in candidates if _matches_data_type(lowered, candidate)]
        if selected:
            discovered[group] = selected
    return discovered


def _unique_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _compact_aggregate_response(response: dict[str, Any], data_types: list[str]) -> dict[str, Any]:
    buckets = response.get("bucket") if isinstance(response.get("bucket"), list) else []
    point_types: set[str] = set()
    point_count = 0
    dataset_count = 0
    sample_bucket: dict[str, Any] = {}
    for bucket_index, bucket in enumerate(buckets):
        if not isinstance(bucket, dict):
            continue
        if bucket_index == 0:
            sample_bucket = {
                "startTimeMillis": bucket.get("startTimeMillis"),
                "endTimeMillis": bucket.get("endTimeMillis"),
                "datasets": [],
            }
        for dataset in bucket.get("dataset") or []:
            if not isinstance(dataset, dict):
                continue
            dataset_count += 1
            dataset_points = dataset.get("point") if isinstance(dataset.get("point"), list) else []
            if bucket_index == 0:
                sample_bucket.setdefault("datasets", []).append(
                    {
                        "dataSourceId": dataset.get("dataSourceId", ""),
                        "point_count": len(dataset_points),
                        "point_types": _unique_preserve_order([str(point.get("dataTypeName") or "") for point in dataset_points if isinstance(point, dict)]),
                    }
                )
            for point in dataset_points:
                if not isinstance(point, dict):
                    continue
                point_count += 1
                data_type = str(point.get("dataTypeName") or dataset.get("dataSourceId") or "").strip()
                if data_type:
                    point_types.add(data_type)
    return {
        "requested_data_types": data_types,
        "bucket_count": len(buckets),
        "dataset_count": dataset_count,
        "point_count": point_count,
        "point_types": sorted(point_types),
        "sample_bucket": sample_bucket,
    }


def _is_heart_rate_batch(batch: list[str]) -> bool:
    return any("heart_rate" in str(data_type).lower() for data_type in batch)


def _heart_rate_optional_batch(data_type_names: set[str]) -> list[str]:
    lowered = {name.lower() for name in data_type_names}
    if "com.google.heart_rate.summary" in lowered:
        return ["com.google.heart_rate.summary"]
    if "com.google.heart_rate.bpm" in lowered:
        return ["com.google.heart_rate.bpm"]
    if any("heart_rate" in name for name in lowered):
        return ["com.google.heart_rate.bpm"]
    return []


def _optional_warning_for_batch(batch: list[str], exc: Exception | None = None) -> str:
    if _is_heart_rate_batch(batch):
        return GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING
    batch_text = " ".join(str(data_type).lower() for data_type in batch)
    if "oxygen_saturation" in batch_text or "temperature" in batch_text:
        return "Optional vitals unavailable from Google Health."
    if "heart_minutes" in batch_text or "distance" in batch_text or "calories.bmr" in batch_text:
        return "Optional activity detail metrics unavailable from Google Health."
    if exc is None:
        return f"Optional Google Health metric batch unavailable: {', '.join(batch)}."
    return f"Skipped optional Google Health metric batch ({', '.join(batch)}): {exc}"


def _with_resting_hr_baselines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[float] = []
    enriched: list[dict[str, Any]] = []
    for row in sorted((dict(item) for item in items), key=lambda item: str(item.get("date") or "")):
        rhr = _rounded(row.get("resting_hr"))
        baseline = _average(history[-7:])
        if rhr is not None and baseline is not None and len(history[-7:]) >= 3:
            row["resting_hr_baseline"] = _rounded(baseline)
            row["resting_hr_deviation"] = _rounded(rhr - baseline)
        else:
            row["resting_hr_baseline"] = None
            row["resting_hr_deviation"] = None
        if rhr is not None:
            history.append(float(rhr))
        enriched.append(row)
    return enriched


def build_google_health_records(items: list[dict[str, Any]] | pd.DataFrame | None) -> dict[str, list[dict[str, Any]]]:
    """Build flexible Google Health table records from normalized daily rows."""
    raw = items.to_dict(orient="records") if isinstance(items, pd.DataFrame) else list(items or [])
    rows = _with_resting_hr_baselines([dict(row) for row in raw if dict(row).get("date")])
    records: dict[str, list[dict[str, Any]]] = {
        "daily_summary": [],
        "sleep": [],
        "heart": [],
        "activity": [],
        "recovery_signals": [],
    }
    for row in rows:
        day = str(row.get("date") or "")[:10]
        if not day:
            continue
        source = str(row.get("source") or "google_health")
        daily_summary = {
            "summary_id": f"google_health_daily:{day}",
            "date": day,
            "source": source,
            **{key: row.get(key) for key in WEARABLE_METRIC_COLUMNS if key not in {"metric_id", "date", "source", "created_at", "updated_at"}},
        }
        records["daily_summary"].append(daily_summary)
        records["sleep"].append(
            {
                "sleep_id": f"google_health_sleep:{day}",
                "date": day,
                "source": source,
                "total_sleep_minutes": row.get("total_sleep_minutes"),
                "total_sleep_time": row.get("sleep_hours"),
                "rem_sleep_minutes": row.get("rem_sleep_minutes"),
                "deep_sleep_minutes": row.get("deep_sleep_minutes"),
                "light_sleep_minutes": row.get("light_sleep_minutes"),
                "awake_minutes": row.get("awake_minutes"),
                "sleep_efficiency": row.get("sleep_efficiency"),
                "sleep_score": row.get("sleep_score"),
                "sleep_stage_minutes": row.get("sleep_stage_minutes") if isinstance(row.get("sleep_stage_minutes"), dict) else {},
            }
        )
        records["heart"].append(
            {
                "heart_id": f"google_health_heart:{day}",
                "date": day,
                "source": source,
                "resting_hr": row.get("resting_hr"),
                "resting_hr_baseline": row.get("resting_hr_baseline"),
                "resting_hr_deviation": row.get("resting_hr_deviation"),
                "hrv": row.get("hrv"),
                "average_hr": row.get("average_hr"),
                "max_hr": row.get("max_hr"),
                "workout_average_hr": row.get("workout_average_hr"),
                "workout_max_hr": row.get("workout_max_hr"),
                "hr_zones": row.get("heart_rate_zones"),
            }
        )
        records["activity"].append(
            {
                "activity_id": f"google_health_activity:{day}",
                "date": day,
                "source": source,
                "steps": row.get("steps"),
                "active_minutes": row.get("active_minutes"),
                "active_zone_minutes": row.get("active_zone_minutes"),
                "distance_meters": row.get("distance_meters"),
                "distance_miles": row.get("distance_miles"),
                "total_calories_burned": row.get("total_calories_burned") or row.get("calories_burned"),
                "active_calories_burned": row.get("active_calories_burned"),
                "basal_calories_burned": row.get("basal_calories_burned"),
                "workout_minutes": row.get("workout_minutes"),
                "cardio_load": row.get("cardio_load"),
            }
        )
        rhr_deviation = _rounded(row.get("resting_hr_deviation"))
        spo2 = _rounded(row.get("spo2"))
        breathing_rate = _rounded(row.get("breathing_rate"))
        skin_temperature = _rounded(row.get("skin_temperature"))
        body_temperature = _rounded(row.get("body_temperature"))
        sickness_warning = bool(
            (spo2 is not None and spo2 < 94)
            or (breathing_rate is not None and breathing_rate >= 22)
            or (skin_temperature is not None and abs(float(skin_temperature)) <= 5 and abs(float(skin_temperature)) >= 1)
            or (body_temperature is not None and body_temperature >= 37.8)
        )
        recovery_warning = bool(
            sickness_warning
            or (rhr_deviation is not None and rhr_deviation >= 5)
            or (row.get("sleep_hours") is not None and float(row.get("sleep_hours") or 0) < 6.5)
        )
        records["recovery_signals"].append(
            {
                "signal_id": f"google_health_recovery:{day}",
                "date": day,
                "source": source,
                "hrv": row.get("hrv"),
                "breathing_rate": breathing_rate,
                "spo2": spo2,
                "skin_temperature": skin_temperature,
                "body_temperature": body_temperature,
                "resting_hr_deviation": rhr_deviation,
                "sickness_warning": sickness_warning,
                "recovery_warning": recovery_warning,
                "unusual_fatigue": bool(recovery_warning and (row.get("active_minutes") or row.get("active_zone_minutes"))),
            }
        )
    return records


def fetch_daily_metrics(
    access_token: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Fetch daily-level Google Health metrics for the configured date range."""
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "items": [],
            "message": "No Google Health access token is available.",
        }
    today = datetime.now(_app_timezone()).date()
    end_text = _date_text(end_date, today)
    start_text = _date_text(start_date, date.fromisoformat(end_text) - timedelta(days=13))
    merged_buckets: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    optional_metric_warnings: list[str] = []
    required_metric_failures: list[str] = []
    raw_bucket_count = 0
    raw_aggregate_responses: dict[str, Any] = {}
    data_source_summary: dict[str, Any] = {
        "status": "not_checked",
        "data_sources": [],
        "data_type_names": [],
        "available_data_types": [],
        "data_source_count": 0,
    }
    discovered_groups: dict[str, list[str]] = {}
    requested_data_types: list[str] = []
    recommended_next_action = ""
    configured_aggregate_types = bool(os.getenv("GOOGLE_HEALTH_AGGREGATE_TYPES", "").strip())
    if configured_aggregate_types:
        batches: list[tuple[str, list[str], bool]] = [
            (f"configured_batch_{index + 1}", batch, index == 0)
            for index, batch in enumerate(aggregate_type_batches())
            if batch
        ]
        try:
            data_sources = list_data_sources(access_token)
            source_types = set(data_sources.get("data_type_names") or [])
            discovered_groups = _discovered_metric_groups(source_types)
            data_source_summary = {
                "status": data_sources.get("status", "ok"),
                "data_sources": data_sources.get("data_sources") or [],
                "data_type_names": sorted(source_types),
                "available_data_types": sorted(source_types),
                "data_source_count": int(data_sources.get("data_source_count") or len(data_sources.get("data_sources") or [])),
            }
        except GoogleHealthIntegrationError as exc:
            logger.warning("[google_health] data source listing failed before configured aggregate fetch: %s", str(exc)[:500])
            data_source_summary = {
                "status": "warning",
                "message": str(exc),
                "data_sources": [],
                "data_type_names": [],
                "available_data_types": [],
                "data_source_count": 0,
            }
            warnings.append(f"Google Health data source listing failed: {exc}")
    else:
        try:
            data_sources = list_data_sources(access_token)
            source_types = set(data_sources.get("data_type_names") or [])
            discovered_groups = _discovered_metric_groups(source_types)
            data_source_summary = {
                "status": data_sources.get("status", "ok"),
                "data_sources": data_sources.get("data_sources") or [],
                "data_type_names": sorted(source_types),
                "available_data_types": sorted(source_types),
                "data_source_count": int(data_sources.get("data_source_count") or len(data_sources.get("data_sources") or [])),
            }
            if data_source_summary["data_source_count"] <= 0:
                recommended_next_action = GOOGLE_HEALTH_NO_SOURCES_MESSAGE
                warnings.append(GOOGLE_HEALTH_NO_SOURCES_MESSAGE)
                optional_metric_warnings.append(GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING)
                batches = []
            else:
                missing_core_groups = [group for group in GOOGLE_HEALTH_CORE_GROUPS if not discovered_groups.get(group)]
                for group in missing_core_groups:
                    warnings.append(f"Missing Google Health data source group: {group.replace('_', ' ')}.")
                if not discovered_groups.get("heart_rate"):
                    optional_metric_warnings.append(GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING)

                batches = []
                for group in GOOGLE_HEALTH_CORE_GROUPS:
                    if discovered_groups.get(group):
                        batches.append((group, discovered_groups[group], True))
                for group in ("heart_rate", "active_zone_minutes", "distance", "basal_calories", "oxygen_saturation", "body_temperature"):
                    if discovered_groups.get(group):
                        batches.append((group, discovered_groups[group], False))
        except GoogleHealthIntegrationError as exc:
            message = f"Google Health data source listing failed: {exc}"
            logger.warning("[google_health] %s", message[:500])
            data_source_summary = {
                "status": "warning",
                "message": str(exc),
                "data_sources": [],
                "data_type_names": [],
                "available_data_types": [],
                "data_source_count": 0,
            }
            required_metric_failures.append(message)
            warnings.append(message)
            batches = []

    for label, batch, required in batches:
        batch = _unique_preserve_order(batch)
        if not batch:
            continue
        requested_data_types.extend(batch)
        try:
            response = _fetch_aggregate_batch(access_token, batch, start_text, end_text)
        except GoogleHealthIntegrationError as exc:
            if required:
                failure = f"Required Google Health metric group '{label}' failed: {exc}"
                required_metric_failures.append(failure)
                warnings.append(failure)
            else:
                warning = _optional_warning_for_batch(batch, exc)
                logger.warning("[google_health] %s", warning)
                optional_metric_warnings.append(warning)
            raw_aggregate_responses[label] = {
                "status": "error",
                "requested_data_types": batch,
                "error": str(exc),
            }
            continue
        raw_bucket_count += len(response.get("bucket") or [])
        raw_aggregate_responses[label] = {
            "status": "ok",
            **_compact_aggregate_response(response, batch),
        }
        _merge_buckets(merged_buckets, response)

    requested_data_types = _unique_preserve_order(requested_data_types)
    buckets = sorted(merged_buckets.values(), key=lambda bucket: int(bucket.get("startTimeMillis") or 0))
    all_items = [
        item
        for item in (_parse_aggregate_bucket(bucket) for bucket in buckets)
        if item.get("date")
    ]
    all_items = _with_resting_hr_baselines(all_items)
    items = [row for row in all_items if has_populated_metrics(row)]
    empty_items = [row for row in all_items if not has_populated_metrics(row)]
    empty_date_rows = [str(row.get("date") or "")[:10] for row in empty_items if str(row.get("date") or "").strip()]

    if not all_items and not warnings:
        warnings.append("No Google Health daily buckets returned for the requested date range.")
    elif empty_items:
        warnings.append(f"Google Health returned {len(empty_items)} empty daily bucket(s) with no populated wearable metrics.")

    if items:
        missing_groups = {
            "sleep": ("sleep_hours", "total_sleep_minutes"),
            "resting heart rate": ("resting_hr",),
            "calories burned": ("total_calories_burned", "calories_burned"),
            "activity": ("steps", "active_minutes", "active_zone_minutes"),
        }
        for label, fields in missing_groups.items():
            if all(all(row.get(field) is None or str(row.get(field)).strip() == "" for field in fields) for row in items):
                if label == "resting heart rate":
                    optional_metric_warnings.append(GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING)
                else:
                    warnings.append(f"Missing Google Health metric group: {label}.")
    elif not recommended_next_action and data_source_summary.get("data_source_count", 0) <= 0:
        recommended_next_action = GOOGLE_HEALTH_NO_SOURCES_MESSAGE

    if not items and recommended_next_action and recommended_next_action not in warnings:
        warnings.append(recommended_next_action)

    optional_metric_warnings = list(dict.fromkeys(optional_metric_warnings))
    warnings = list(dict.fromkeys([*warnings, *optional_metric_warnings]))
    for warning in warnings:
        if warning.startswith("Missing") or warning.startswith("No Google Health") or "empty daily bucket" in warning:
            logger.warning("[google_health] %s", warning)
    records = build_google_health_records(items)
    field_counts = _field_count_summary(all_items)
    logger.info(
        "[google_health] fetched daily metrics populated_days=%s empty_days=%s raw_buckets=%s warnings=%s start=%s end=%s data_sources=%s",
        len(items),
        len(empty_items),
        raw_bucket_count,
        len(warnings),
        start_text,
        end_text,
        data_source_summary.get("data_source_count", 0),
    )
    return {
        "status": "ok",
        "items": items,
        "message": (
            recommended_next_action
            if not items and recommended_next_action
            else f"Fetched {len(items)} populated Google Health daily row(s)."
        ),
        "date_range": {"start_date": start_text, "end_date": end_text},
        "records": records,
        "warnings": warnings,
        "optional_metric_warnings": optional_metric_warnings,
        "required_metric_failures": required_metric_failures,
        "data_sources": data_source_summary,
        "api_path": "google_fit_rest",
        "api_path_label": "Google Fit REST API",
        "phone_app_data_note": "Google Health phone app data may come from Health Connect and may not be visible through Google Fit REST aggregate endpoints.",
        "fallback_plan": ["fitbit_direct_api", "health_connect_export_import"],
        "discovered_metric_groups": discovered_groups,
        "requested_scopes": scopes(),
        "requested_data_types": requested_data_types,
        "raw_aggregate_responses": raw_aggregate_responses,
        "raw_bucket_count": raw_bucket_count,
        "fetched_days": len(all_items),
        "populated_days": len(items),
        "placeholder_rows": empty_items,
        "empty_date_rows": empty_date_rows,
        "empty_date_rows_count": len(empty_date_rows),
        "populated_metric_counts_by_day": populated_metric_counts_by_day(all_items),
        "data_available": bool(items),
        "recommended_next_action": recommended_next_action,
        **field_counts,
    }


def normalize_daily_metrics(metrics: list[dict] | pd.DataFrame | None, source: str = "google_health") -> pd.DataFrame:
    """Normalize Google Health daily payloads into wearable metric rows."""
    raw = metrics.copy() if isinstance(metrics, pd.DataFrame) else pd.DataFrame(metrics or [])
    if raw.empty:
        return pd.DataFrame(columns=WEARABLE_METRIC_COLUMNS)

    normalized = pd.DataFrame()
    for column in WEARABLE_METRIC_COLUMNS:
        normalized[column] = raw[column] if column in raw.columns else pd.NA
    normalized["source"] = normalized["source"].fillna(source).astype(str).str.strip().replace("", source)
    normalized = normalized.where(pd.notna(normalized), None)
    return normalized[WEARABLE_METRIC_COLUMNS]


def saved_token_state(settings: dict | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = _settings_metadata(settings)
    tokens = metadata.get("google_health_tokens") if isinstance(metadata.get("google_health_tokens"), dict) else {}
    sync = metadata.get("google_health_sync") if isinstance(metadata.get("google_health_sync"), dict) else {}
    return tokens, sync
