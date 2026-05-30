"""Server-side Google Health OAuth and daily wearable metric sync helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from src.wearables import (
    WEARABLE_METRIC_COLUMNS,
    clean_heart_rate_value,
    clean_hrv_value,
    normalize_wearable_metric_rows,
)


logger = logging.getLogger(__name__)

GOOGLE_HEALTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_HEALTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_HEALTH_SCOPES = [
    "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly",
    "https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly",
    "https://www.googleapis.com/auth/googlehealth.sleep.readonly",
    "https://www.googleapis.com/auth/googlehealth.profile.readonly",
    "https://www.googleapis.com/auth/googlehealth.settings.readonly",
]
DEFAULT_GOOGLE_HEALTH_API_BASE_URL = "https://health.googleapis.com"
GOOGLE_HEALTH_PROVIDER_ID = "google_health"
GOOGLE_FIT_LEGACY_PROVIDER_ID = "google_fit_legacy"
GOOGLE_HEALTH_API_PATH = "google_health_v4"
GOOGLE_HEALTH_API_LABEL = "Google Health API v4"
GOOGLE_FIT_LEGACY_API_PATH = "google_fit_legacy"
GOOGLE_FIT_LEGACY_API_LABEL = "Deprecated Google Fit REST API"
GOOGLE_CONNECTED_LABEL = "Google connected"
GOOGLE_HEALTH_SYNC_AVAILABLE_LABEL = "Google Health API sync available"
GOOGLE_HEALTH_SYNC_UNAVAILABLE_LABEL = "Google Health API sync unavailable"
GOOGLE_FIT_LEGACY_FOUND_LABEL = "Google Fit legacy data source found"
GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL = "Google Fit legacy data source not found"
GOOGLE_FIT_LEGACY_CONFIG_MESSAGE = (
    "GOOGLE_HEALTH_API_BASE_URL points to the deprecated Google Fit/Fitness REST API. "
    "Performance OS will not treat Google Fit REST as Google Health data. "
    "Set GOOGLE_HEALTH_API_BASE_URL=https://health.googleapis.com and reconnect with googlehealth.* scopes."
)
GOOGLE_HEALTH_DAILY_ROLLUP_TYPES = [
    "steps",
    "total-calories",
    "active-energy-burned",
    "active-minutes",
    "active-zone-minutes",
    "distance",
    "heart-rate",
]
GOOGLE_HEALTH_DAILY_POINT_TYPES = [
    "daily-resting-heart-rate",
    "daily-heart-rate-variability",
    "daily-heart-rate-zones",
    "daily-oxygen-saturation",
    "daily-respiratory-rate",
    "daily-sleep-temperature-derivations",
]
GOOGLE_HEALTH_SESSION_POINT_TYPES = [
    "sleep",
    "respiratory-rate-sleep-summary",
]
GOOGLE_HEALTH_DATA_TYPES = [
    *GOOGLE_HEALTH_DAILY_ROLLUP_TYPES,
    *GOOGLE_HEALTH_DAILY_POINT_TYPES,
    *GOOGLE_HEALTH_SESSION_POINT_TYPES,
]
GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING = "Optional heart rate metrics unavailable from Google Health."
GOOGLE_HEALTH_NO_SOURCES_MESSAGE = (
    "Google Health API connected, but no wearable data points were returned for the requested date range. "
    "Check Google Health API access, OAuth consent scopes, and that the Fitbit/Google Health app has synced recently."
)
GOOGLE_HEALTH_LEGACY_FITNESS_SCOPES_MESSAGE = (
    "This token includes deprecated Google Fit/Fitness scopes that Google Health API rejects. "
    "Reconnect Google Health to grant a clean googlehealth.* token."
)
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
GOOGLE_HEALTH_HEART_RATE_FIELDS = {
    "resting_hr",
    "resting_hr_baseline",
    "average_hr",
    "max_hr",
    "workout_average_hr",
    "workout_max_hr",
}
GOOGLE_HEALTH_HRV_FIELDS = {"hrv"}


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
        configured_scopes = [scope for scope in configured.replace(",", " ").split() if scope]
        health_scopes = [
            scope
            for scope in configured_scopes
            if "googlehealth." in scope or scope == "https://www.googleapis.com/auth/cloud-platform"
        ]
        legacy_scopes = [scope for scope in configured_scopes if "/auth/fitness." in scope or scope.startswith("fitness_")]
        if legacy_scopes:
            logger.warning("[google_health] ignoring deprecated Fitness scopes in GOOGLE_HEALTH_SCOPES: %s", ",".join(legacy_scopes))
        if health_scopes:
            return health_scopes
        logger.warning("[google_health] GOOGLE_HEALTH_SCOPES did not include Google Health scopes; using safe defaults.")
    return GOOGLE_HEALTH_SCOPES.copy()


def api_base_url() -> str:
    return os.getenv("GOOGLE_HEALTH_API_BASE_URL", "").strip().rstrip("/") or DEFAULT_GOOGLE_HEALTH_API_BASE_URL


def is_legacy_google_fit_base_url(value: str | None = None) -> bool:
    base_url = str(value if value is not None else api_base_url()).strip().lower()
    return "fitness.googleapis.com" in base_url or "googleapis.com/fitness" in base_url


def _api_family_for_url(url: str) -> str:
    host = urlparse(str(url or "")).netloc.lower()
    if "fitness.googleapis.com" in host:
        return "google_fit_legacy"
    if "health.googleapis.com" in host:
        return "google_health"
    if "oauth2.googleapis.com" in host or "accounts.google.com" in host:
        return "google_oauth"
    return "unknown"


def _request_trace_entry(
    trace: list[dict[str, Any]] | None,
    *,
    method: str,
    url: str,
    provider: str,
    endpoint: str,
    data_type: str = "",
) -> dict[str, Any]:
    parsed = urlparse(url)
    entry = {
        "provider": provider,
        "api_family": _api_family_for_url(url),
        "method": method,
        "host": parsed.netloc,
        "path": parsed.path,
        "query_present": bool(parsed.query),
        "url": url,
        "endpoint": endpoint,
        "data_type": data_type,
        "response_status": "pending",
        "response_count": 0,
    }
    if trace is not None:
        trace.append(entry)
    logger.info(
        "[google_health] api request provider=%s family=%s method=%s host=%s path=%s endpoint=%s data_type=%s",
        provider,
        entry["api_family"],
        method,
        parsed.netloc,
        parsed.path,
        endpoint,
        data_type,
    )
    return entry


def _response_count(response: dict[str, Any]) -> int:
    for key in ("rollupDataPoints", "dataPoints", "pairedDevices"):
        value = response.get(key) if isinstance(response, dict) else None
        if isinstance(value, list):
            return len(value)
    return 0


def _latest_trace_for_data_type(trace: list[dict[str, Any]], data_type: str, endpoint: str = "") -> dict[str, Any]:
    for entry in reversed(trace):
        if entry.get("data_type") != data_type:
            continue
        if endpoint and endpoint not in str(entry.get("endpoint") or ""):
            continue
        return dict(entry)
    return {}


def _request_trace_counts(trace: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "total": len(trace),
        "google_health": 0,
        "google_fit_legacy": 0,
        "google_oauth": 0,
        "unknown": 0,
    }
    for entry in trace:
        family = str(entry.get("api_family") or "unknown")
        counts[family] = int(counts.get(family, 0)) + 1
    return counts


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
        # Keep this false: Google Health rejects tokens that include legacy
        # Google Fit/Fitness scopes, and incremental auth can silently carry
        # those old grants into an otherwise-correct Google Health token.
        "include_granted_scopes": "false",
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


def _date_obj(text: str) -> date:
    return date.fromisoformat(str(text or "")[:10])


def _next_date_text(text: str) -> str:
    return (_date_obj(text) + timedelta(days=1)).isoformat()


def _google_date_text(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    try:
        year = int(value.get("year") or 0)
        month = int(value.get("month") or 0)
        day = int(value.get("day") or 0)
        if year and month and day:
            return date(year, month, day).isoformat()
    except (TypeError, ValueError):
        return ""
    return ""


def _civil_date_time(day: str) -> dict[str, Any]:
    parsed = _date_obj(day)
    return {
        "date": {"year": parsed.year, "month": parsed.month, "day": parsed.day},
        "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0},
    }


def _date_from_google_datetime(value: Any) -> str:
    if isinstance(value, dict):
        civil = _google_date_text(value.get("date"))
        if civil:
            return civil
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.astimezone(_app_timezone()).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else ""


def _rounded(value: Any, digits: int = 1) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return round(parsed, digits)


def _count_mapping_increment(mapping: dict[str, int], key: str) -> None:
    mapping[key] = int(mapping.get(key) or 0) + 1


def _clean_hr_sample(row: dict[str, Any], field: str, value: Any) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return None
    row["_raw_hr_samples_received"] = int(row.get("_raw_hr_samples_received") or 0) + 1
    _count_mapping_increment(row.setdefault("_raw_hr_samples_received_by_field", {}), field)
    cleaned = clean_heart_rate_value(value)
    if cleaned is None:
        row["_invalid_hr_samples_dropped"] = int(row.get("_invalid_hr_samples_dropped") or 0) + 1
        _count_mapping_increment(row.setdefault("_invalid_hr_samples_dropped_by_field", {}), field)
        return None
    row["_clean_hr_samples_used"] = int(row.get("_clean_hr_samples_used") or 0) + 1
    _count_mapping_increment(row.setdefault("_clean_hr_samples_used_by_field", {}), field)
    return cleaned


def _clean_hr_diagnostics_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {
        "raw_hr_samples_received": 0,
        "invalid_hr_samples_dropped": 0,
        "clean_hr_samples_used": 0,
    }
    by_field = {
        "raw_hr_samples_received_by_field": {},
        "invalid_hr_samples_dropped_by_field": {},
        "clean_hr_samples_used_by_field": {},
    }
    for row in rows:
        totals["raw_hr_samples_received"] += int(row.get("_raw_hr_samples_received") or 0)
        totals["invalid_hr_samples_dropped"] += int(row.get("_invalid_hr_samples_dropped") or 0)
        totals["clean_hr_samples_used"] += int(row.get("_clean_hr_samples_used") or 0)
        for key in by_field:
            source = row.get(f"_{key}") if isinstance(row.get(f"_{key}"), dict) else {}
            for field, count in source.items():
                by_field[key][field] = int(by_field[key].get(field) or 0) + int(count or 0)
    return {**totals, **by_field, "valid_bpm_range": {"min": 30, "max": 220}}


def _as_int(value: Any) -> int | None:
    parsed = _rounded(value, 0)
    return int(parsed) if parsed is not None else None


def _metric_present(value: Any) -> bool:
    if value is None:
        return False
    try:
        if pd.isna(value):
            return False
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return True
    if pd.isna(parsed):
        return False
    return parsed > 0


def _metric_field_present(field: str, value: Any) -> bool:
    if field in GOOGLE_HEALTH_HEART_RATE_FIELDS:
        return clean_heart_rate_value(value) is not None
    if field in GOOGLE_HEALTH_HRV_FIELDS:
        return clean_hrv_value(value) is not None
    return _metric_present(value)


def populated_metric_count(row: dict[str, Any] | None) -> int:
    sample = row if isinstance(row, dict) else {}
    return sum(1 for field in GOOGLE_HEALTH_METRIC_FIELDS if _metric_field_present(field, sample.get(field)))


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


def _row_metric_fields(row: dict[str, Any] | None) -> set[str]:
    sample = row if isinstance(row, dict) else {}
    return {field for field in GOOGLE_HEALTH_METRIC_FIELDS if _metric_field_present(field, sample.get(field))}


def _average(values: list[float]) -> float | None:
    valid = [float(value) for value in values if value is not None and not pd.isna(value)]
    return sum(valid) / len(valid) if valid else None


def _new_daily_row(day: str) -> dict[str, Any]:
    return {
        "date": day,
        "source": GOOGLE_HEALTH_PROVIDER_ID,
        "sleep_hours": None,
        "sleep_score": None,
        "total_sleep_minutes": None,
        "rem_sleep_minutes": None,
        "deep_sleep_minutes": None,
        "light_sleep_minutes": None,
        "awake_minutes": None,
        "sleep_efficiency": None,
        "resting_hr": None,
        "resting_hr_baseline": None,
        "resting_hr_deviation": None,
        "hrv": None,
        "average_hr": None,
        "max_hr": None,
        "workout_average_hr": None,
        "workout_max_hr": None,
        "steps": None,
        "active_minutes": None,
        "active_zone_minutes": None,
        "distance_meters": None,
        "distance_miles": None,
        "calories_burned": None,
        "total_calories_burned": None,
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
        "_raw_hr_samples_received": 0,
        "_invalid_hr_samples_dropped": 0,
        "_clean_hr_samples_used": 0,
        "_invalid_hr_samples_dropped_by_field": {},
        "_clean_hr_samples_used_by_field": {},
        "_raw_hr_samples_received_by_field": {},
    }


def _sanitize_data_source(source: dict[str, Any]) -> dict[str, Any]:
    data_type = source.get("dataType") if isinstance(source.get("dataType"), dict) else {}
    application = source.get("application") if isinstance(source.get("application"), dict) else {}
    device = source.get("device") if isinstance(source.get("device"), dict) else {}
    health_device = source if any(key in source for key in ("manufacturer", "model", "displayName", "deviceType")) else {}
    return {
        "data_stream_id": str(source.get("dataStreamId") or ""),
        "data_stream_name": str(source.get("dataStreamName") or ""),
        "data_type_name": str(data_type.get("name") or source.get("dataTypeName") or ""),
        "type": str(source.get("type") or ""),
        "name": str(source.get("name") or ""),
        "display_name": str(health_device.get("displayName") or ""),
        "platform": str(source.get("platform") or ""),
        "application": {
            "name": str(application.get("name") or ""),
            "package_name": str(application.get("packageName") or ""),
        },
        "device": {
            "manufacturer": str(device.get("manufacturer") or health_device.get("manufacturer") or ""),
            "model": str(device.get("model") or health_device.get("model") or ""),
            "type": str(device.get("type") or health_device.get("deviceType") or ""),
        },
    }


def list_data_sources(access_token: str, request_trace: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return Google Health paired devices and supported data type identifiers.

    Google Health API v4 does not use the deprecated Google Fit `dataSources`
    endpoint. This compatibility-named function now calls pairedDevices.list for
    debug visibility and returns the Health API data types the sync requests.
    """
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "provider": GOOGLE_HEALTH_PROVIDER_ID,
            "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "data_sources": [],
            "data_type_names": [],
            "google_health_api_sync_available": False,
            "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_UNAVAILABLE_LABEL,
            "google_fit_legacy_data_source_status": "not_found",
            "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL,
            "api_request_log": [],
            "api_request_counts": {"total": 0, "google_health": 0, "google_fit_legacy": 0, "google_oauth": 0, "unknown": 0},
            "requests_sent_to_google_health_api": 0,
            "requests_sent_to_fitness_api": 0,
            "exact_endpoint_urls": [],
            "google_health_api_requests": [],
            "fitness_api_requests": [],
            "normalization_audit": {},
        }
    base_url = api_base_url()
    if is_legacy_google_fit_base_url(base_url):
        logger.warning("[google_health] legacy Google Fit REST base URL configured; skipping source discovery")
        return {
            "status": "legacy_google_fit_configured",
            "message": GOOGLE_FIT_LEGACY_CONFIG_MESSAGE,
            "data_sources": [],
            "paired_devices": [],
            "data_type_names": [],
            "available_data_types": [],
            "data_source_count": 0,
            "paired_device_count": 0,
            "api_base_url": base_url,
            "api_path": GOOGLE_FIT_LEGACY_API_PATH,
            "api_path_label": GOOGLE_FIT_LEGACY_API_LABEL,
            "provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
            "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "legacy_google_fit_detected": True,
            "google_fit_unused": False,
            "deprecated_fitness_api_unused": False,
            "google_health_api_sync_available": False,
            "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_UNAVAILABLE_LABEL,
            "google_fit_legacy_data_source_status": "found",
            "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_FOUND_LABEL,
            "api_request_log": [],
            "api_request_counts": {"total": 0, "google_health": 0, "google_fit_legacy": 0, "google_oauth": 0, "unknown": 0},
            "requests_sent_to_google_health_api": 0,
            "requests_sent_to_fitness_api": 0,
            "exact_endpoint_urls": [],
            "google_health_api_requests": [],
            "fitness_api_requests": [],
        }
    url = f"{base_url}/v4/users/me/pairedDevices?pageSize=100"
    trace_entry = _request_trace_entry(
        request_trace,
        method="GET",
        url=url,
        provider=GOOGLE_HEALTH_PROVIDER_ID,
        endpoint="pairedDevices.list",
    )
    try:
        response = _get_json(
            url,
            access_token,
            context="Google Health paired devices listing failed",
        )
        trace_entry["response_status"] = "ok"
        trace_entry["response_count"] = _response_count(response)
        logger.info("[google_health] api response endpoint=%s status=ok count=%s", trace_entry["endpoint"], trace_entry["response_count"])
    except GoogleHealthIntegrationError as exc:
        trace_entry["response_status"] = "error"
        trace_entry["error"] = str(exc)[:500]
        logger.warning("[google_health] api response endpoint=%s status=error error=%s", trace_entry["endpoint"], str(exc)[:500])
        raise
    data_sources = response.get("pairedDevices") or []
    data_type_names = GOOGLE_HEALTH_DATA_TYPES.copy()
    sanitized_sources = [_sanitize_data_source(source) for source in data_sources if isinstance(source, dict)]
    logger.info(
        "[google_health] listed paired devices count=%s data_types=%s",
        len(data_sources),
        len(data_type_names),
    )
    trace = request_trace or [trace_entry]
    api_request_counts = _request_trace_counts(trace)
    exact_endpoint_urls = [str(entry.get("url") or "") for entry in trace if str(entry.get("url") or "").strip()]
    return {
        "status": "ok",
        "data_sources": sanitized_sources,
        "paired_devices": sanitized_sources,
        "data_type_names": data_type_names,
        "available_data_types": data_type_names,
        "data_source_count": len(data_sources),
        "paired_device_count": len(data_sources),
        "api_path": GOOGLE_HEALTH_API_PATH,
        "api_path_label": GOOGLE_HEALTH_API_LABEL,
        "provider": GOOGLE_HEALTH_PROVIDER_ID,
        "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
        "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
        "google_health_api_sync_available": True,
        "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_AVAILABLE_LABEL,
        "google_fit_legacy_data_source_status": "not_found",
        "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL,
        "api_request_log": trace,
        "api_request_counts": api_request_counts,
        "requests_sent_to_google_health_api": int(api_request_counts.get("google_health") or 0),
        "requests_sent_to_fitness_api": int(api_request_counts.get("google_fit_legacy") or 0),
        "exact_endpoint_urls": exact_endpoint_urls,
        "google_health_api_requests": [entry for entry in trace if entry.get("api_family") == "google_health"],
        "fitness_api_requests": [entry for entry in trace if entry.get("api_family") == "google_fit_legacy"],
    }


def fetch_identity(access_token: str) -> dict[str, Any]:
    """Fetch the connected Google Health identity without exposing tokens."""
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "provider": GOOGLE_HEALTH_PROVIDER_ID,
            "message": "No Google Health access token is available.",
        }
    base_url = api_base_url()
    if is_legacy_google_fit_base_url(base_url):
        return {
            "status": "legacy_google_fit_configured",
            "provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
            "message": GOOGLE_FIT_LEGACY_CONFIG_MESSAGE,
        }
    response = _get_json(
        f"{base_url}/v4/users/me/identity",
        access_token,
        context="Google Health identity fetch failed",
    )
    return {
        "status": "ok",
        "provider": GOOGLE_HEALTH_PROVIDER_ID,
        "identity": {
            "name": str(response.get("name") or ""),
            "health_user_id": str(response.get("healthUserId") or ""),
            "legacy_user_id": str(response.get("legacyUserId") or ""),
        },
    }


def _unique_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _row_for_day(rows: dict[str, dict[str, Any]], day: str) -> dict[str, Any]:
    clean_day = str(day or "")[:10]
    if not clean_day:
        clean_day = datetime.now(_app_timezone()).date().isoformat()
    return rows.setdefault(clean_day, _new_daily_row(clean_day))


def _health_date_range_body(start_text: str, end_text: str, *, page_token: str = "") -> dict[str, Any]:
    return {
        "range": {
            "start": _civil_date_time(start_text),
            "end": _civil_date_time(_next_date_text(end_text)),
        },
        "windowSizeDays": 1,
        "pageSize": 10000,
        "dataSourceFamily": "users/me/dataSourceFamilies/all-sources",
        **({"pageToken": page_token} if page_token else {}),
    }


def _fetch_health_daily_rollup(
    access_token: str,
    data_type: str,
    start_text: str,
    end_text: str,
    *,
    page_token: str = "",
    request_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    url = f"{api_base_url()}/v4/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"
    trace_entry = _request_trace_entry(
        request_trace,
        method="POST",
        url=url,
        provider=GOOGLE_HEALTH_PROVIDER_ID,
        endpoint="dataPoints.dailyRollUp",
        data_type=data_type,
    )
    try:
        response = _post_json(
            url,
            _health_date_range_body(start_text, end_text, page_token=page_token),
            access_token,
            context=f"Google Health {data_type} daily rollup failed",
        )
        trace_entry["response_status"] = "ok"
        trace_entry["response_count"] = _response_count(response)
        logger.info("[google_health] api response endpoint=%s data_type=%s status=ok count=%s", trace_entry["endpoint"], data_type, trace_entry["response_count"])
        return response
    except GoogleHealthIntegrationError as exc:
        trace_entry["response_status"] = "error"
        trace_entry["error"] = str(exc)[:500]
        logger.warning("[google_health] api response endpoint=%s data_type=%s status=error error=%s", trace_entry["endpoint"], data_type, str(exc)[:500])
        raise


def _health_point_filter(data_type: str, start_text: str, end_text: str) -> str:
    end_exclusive = _next_date_text(end_text)
    snake = data_type.replace("-", "_")
    if data_type == "sleep":
        return f'sleep.interval.civil_end_time >= "{start_text}" AND sleep.interval.civil_end_time < "{end_exclusive}"'
    if data_type in GOOGLE_HEALTH_DAILY_POINT_TYPES:
        return f'{snake}.date >= "{start_text}" AND {snake}.date < "{end_exclusive}"'
    return f'{snake}.sample_time.civil_time >= "{start_text}" AND {snake}.sample_time.civil_time < "{end_exclusive}"'


def _fetch_health_points(
    access_token: str,
    data_type: str,
    start_text: str,
    end_text: str,
    *,
    page_token: str = "",
    request_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    params = {
        "pageSize": 10000 if data_type not in {"sleep", "exercise"} else 25,
        "filter": _health_point_filter(data_type, start_text, end_text),
    }
    if page_token:
        params["pageToken"] = page_token
    url = f"{api_base_url()}/v4/users/me/dataTypes/{data_type}/dataPoints?{urlencode(params)}"
    trace_entry = _request_trace_entry(
        request_trace,
        method="GET",
        url=url,
        provider=GOOGLE_HEALTH_PROVIDER_ID,
        endpoint="dataPoints.list",
        data_type=data_type,
    )
    try:
        response = _get_json(
            url,
            access_token,
            context=f"Google Health {data_type} data point listing failed",
        )
        trace_entry["response_status"] = "ok"
        trace_entry["response_count"] = _response_count(response)
        logger.info("[google_health] api response endpoint=%s data_type=%s status=ok count=%s", trace_entry["endpoint"], data_type, trace_entry["response_count"])
        return response
    except GoogleHealthIntegrationError as exc:
        trace_entry["response_status"] = "error"
        trace_entry["error"] = str(exc)[:500]
        logger.warning("[google_health] api response endpoint=%s data_type=%s status=error error=%s", trace_entry["endpoint"], data_type, str(exc)[:500])
        raise


def _fetch_health_reconciled_points(
    access_token: str,
    data_type: str,
    start_text: str,
    end_text: str,
    *,
    page_token: str = "",
    request_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    params = {
        "pageSize": 10000 if data_type not in {"sleep", "exercise"} else 25,
        "filter": _health_point_filter(data_type, start_text, end_text),
        "dataSourceFamily": "users/me/dataSourceFamilies/all-sources",
    }
    if page_token:
        params["pageToken"] = page_token
    url = f"{api_base_url()}/v4/users/me/dataTypes/{data_type}/dataPoints:reconcile?{urlencode(params)}"
    trace_entry = _request_trace_entry(
        request_trace,
        method="GET",
        url=url,
        provider=GOOGLE_HEALTH_PROVIDER_ID,
        endpoint="dataPoints.reconcile",
        data_type=data_type,
    )
    try:
        response = _get_json(
            url,
            access_token,
            context=f"Google Health {data_type} reconciled data listing failed",
        )
        trace_entry["response_status"] = "ok"
        trace_entry["response_count"] = _response_count(response)
        logger.info("[google_health] api response endpoint=%s data_type=%s status=ok count=%s", trace_entry["endpoint"], data_type, trace_entry["response_count"])
        return response
    except GoogleHealthIntegrationError as exc:
        trace_entry["response_status"] = "error"
        trace_entry["error"] = str(exc)[:500]
        logger.warning("[google_health] api response endpoint=%s data_type=%s status=error error=%s", trace_entry["endpoint"], data_type, str(exc)[:500])
        raise


def _compact_health_rollup_response(response: dict[str, Any], data_type: str) -> dict[str, Any]:
    points = response.get("rollupDataPoints") if isinstance(response.get("rollupDataPoints"), list) else []
    populated = 0
    value_keys: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        keys = [key for key in point.keys() if key not in {"civilStartTime", "civilEndTime"} and point.get(key) not in (None, {}, [])]
        if keys:
            populated += 1
            value_keys.update(keys)
    return {
        "requested_data_types": [data_type],
        "data_type": data_type,
        "endpoint": "dailyRollUp",
        "point_count": len(points),
        "populated_point_count": populated,
        "value_keys": sorted(value_keys),
        "next_page_token_present": bool(response.get("nextPageToken")),
        "sample": points[0] if points else {},
    }


def _compact_health_points_response(response: dict[str, Any], data_type: str, *, endpoint: str) -> dict[str, Any]:
    points = response.get("dataPoints") if isinstance(response.get("dataPoints"), list) else []
    value_keys: set[str] = set()
    platforms: set[str] = set()
    for point in points:
        if not isinstance(point, dict):
            continue
        value_keys.update(key for key in point.keys() if key not in {"name", "dataPointName", "dataSource"} and point.get(key) not in (None, {}, []))
        source = point.get("dataSource") if isinstance(point.get("dataSource"), dict) else {}
        platform = str(source.get("platform") or "").strip()
        if platform:
            platforms.add(platform)
    return {
        "requested_data_types": [data_type],
        "data_type": data_type,
        "endpoint": endpoint,
        "point_count": len(points),
        "populated_point_count": len([point for point in points if isinstance(point, dict) and any(key not in {"name", "dataPointName", "dataSource"} for key in point.keys())]),
        "value_keys": sorted(value_keys),
        "platforms": sorted(platforms),
        "next_page_token_present": bool(response.get("nextPageToken")),
        "sample": points[0] if points else {},
    }


def _sum_int_fields(payload: dict[str, Any], fields: tuple[str, ...]) -> int | None:
    total = 0
    seen = False
    for field in fields:
        value = _as_int(payload.get(field))
        if value is not None:
            total += value
            seen = True
    return total if seen else None


def _apply_health_rollup(row: dict[str, Any], data_type: str, point: dict[str, Any]) -> None:
    if data_type == "steps" and isinstance(point.get("steps"), dict):
        row["steps"] = _as_int(point["steps"].get("countSum"))
        row["_seen_steps"] = row["steps"] is not None
    elif data_type == "total-calories" and isinstance(point.get("totalCalories"), dict):
        row["total_calories_burned"] = _rounded(point["totalCalories"].get("kcalSum"))
        row["calories_burned"] = row["total_calories_burned"]
        row["_seen_calories"] = row["total_calories_burned"] is not None
    elif data_type == "active-energy-burned" and isinstance(point.get("activeEnergyBurned"), dict):
        row["active_calories_burned"] = _rounded(point["activeEnergyBurned"].get("kcalSum"))
    elif data_type == "distance" and isinstance(point.get("distance"), dict):
        millimeters = _rounded(point["distance"].get("millimetersSum"))
        if millimeters is not None:
            row["distance_meters"] = _rounded(millimeters / 1000)
            row["_seen_distance"] = True
    elif data_type == "active-minutes" and isinstance(point.get("activeMinutes"), dict):
        records = point["activeMinutes"].get("activeMinutesRollupByActivityLevel") or []
        minutes = sum(_as_int(item.get("activeMinutesSum")) or 0 for item in records if isinstance(item, dict))
        row["active_minutes"] = minutes if records else None
        row["_seen_active_minutes"] = row["active_minutes"] is not None
    elif data_type == "active-zone-minutes" and isinstance(point.get("activeZoneMinutes"), dict):
        minutes = _sum_int_fields(point["activeZoneMinutes"], ("sumInCardioHeartZone", "sumInPeakHeartZone", "sumInFatBurnHeartZone"))
        row["active_zone_minutes"] = minutes
        row["cardio_load"] = _rounded(minutes)
        row["_seen_active_zone_minutes"] = minutes is not None
    elif data_type == "heart-rate" and isinstance(point.get("heartRate"), dict):
        heart = point["heartRate"]
        row["average_hr"] = _clean_hr_sample(row, "average_hr", heart.get("beatsPerMinuteAvg"))
        row["max_hr"] = _clean_hr_sample(row, "max_hr", heart.get("beatsPerMinuteMax"))
        if row.get("resting_hr") is None:
            row["resting_hr"] = _clean_hr_sample(row, "resting_hr", heart.get("beatsPerMinuteMin"))


def _sleep_stage_key(stage_type: str) -> str:
    stage = str(stage_type or "").upper()
    if stage == "REM":
        return "rem"
    if stage == "DEEP":
        return "deep"
    if stage == "LIGHT":
        return "light"
    if stage in {"AWAKE", "RESTLESS"}:
        return "awake"
    if stage == "ASLEEP":
        return "sleep"
    return "unknown"


def _apply_sleep_point(row: dict[str, Any], sleep: dict[str, Any]) -> None:
    summary = sleep.get("summary") if isinstance(sleep.get("summary"), dict) else {}
    minutes_asleep = _rounded(summary.get("minutesAsleep"))
    minutes_awake = _rounded(summary.get("minutesAwake"))
    if minutes_asleep is not None:
        row["total_sleep_minutes"] = _rounded(float(row.get("total_sleep_minutes") or 0) + minutes_asleep)
        row["_seen_sleep"] = True
    if minutes_awake is not None:
        row["awake_minutes"] = _rounded(float(row.get("awake_minutes") or 0) + minutes_awake)
    stage_minutes = row.get("sleep_stage_minutes") if isinstance(row.get("sleep_stage_minutes"), dict) else {}
    for stage in summary.get("stagesSummary") or []:
        if not isinstance(stage, dict):
            continue
        key = _sleep_stage_key(str(stage.get("type") or ""))
        minutes = _rounded(stage.get("minutes"))
        if minutes is None:
            continue
        stage_minutes[key] = _rounded(float(stage_minutes.get(key) or 0) + minutes)
        if key == "rem":
            row["rem_sleep_minutes"] = _rounded(float(row.get("rem_sleep_minutes") or 0) + minutes)
        elif key == "deep":
            row["deep_sleep_minutes"] = _rounded(float(row.get("deep_sleep_minutes") or 0) + minutes)
        elif key == "light":
            row["light_sleep_minutes"] = _rounded(float(row.get("light_sleep_minutes") or 0) + minutes)
    row["sleep_stage_minutes"] = stage_minutes


def _apply_health_point(row: dict[str, Any], data_type: str, point: dict[str, Any]) -> None:
    if data_type == "daily-resting-heart-rate" and isinstance(point.get("dailyRestingHeartRate"), dict):
        row["resting_hr"] = _clean_hr_sample(row, "resting_hr", point["dailyRestingHeartRate"].get("beatsPerMinute"))
    elif data_type == "daily-heart-rate-variability" and isinstance(point.get("dailyHeartRateVariability"), dict):
        hrv = point["dailyHeartRateVariability"]
        row["hrv"] = clean_hrv_value(
            hrv.get("averageHeartRateVariabilityMilliseconds")
            or hrv.get("deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds")
        )
    elif data_type == "daily-heart-rate-zones" and isinstance(point.get("dailyHeartRateZones"), dict):
        zones = point["dailyHeartRateZones"].get("heartRateZones")
        row["heart_rate_zones"] = zones if isinstance(zones, list) else []
    elif data_type == "daily-oxygen-saturation" and isinstance(point.get("dailyOxygenSaturation"), dict):
        row["spo2"] = _rounded(point["dailyOxygenSaturation"].get("averagePercentage"))
    elif data_type == "daily-respiratory-rate" and isinstance(point.get("dailyRespiratoryRate"), dict):
        row["breathing_rate"] = _rounded(point["dailyRespiratoryRate"].get("breathsPerMinute"))
    elif data_type == "daily-sleep-temperature-derivations" and isinstance(point.get("dailySleepTemperatureDerivations"), dict):
        temp = point["dailySleepTemperatureDerivations"]
        nightly = _rounded(temp.get("nightlyTemperatureCelsius"))
        baseline = _rounded(temp.get("baselineTemperatureCelsius"))
        row["skin_temperature"] = _rounded(nightly - baseline) if nightly is not None and baseline is not None else nightly
    elif data_type == "respiratory-rate-sleep-summary" and isinstance(point.get("respiratoryRateSleepSummary"), dict):
        stats = point["respiratoryRateSleepSummary"].get("fullSleepStats") or {}
        if isinstance(stats, dict):
            row["breathing_rate"] = _rounded(stats.get("breathsPerMinute"))
    elif data_type == "sleep" and isinstance(point.get("sleep"), dict):
        _apply_sleep_point(row, point["sleep"])


def _point_day(data_type: str, point: dict[str, Any]) -> str:
    if data_type == "sleep" and isinstance(point.get("sleep"), dict):
        interval = point["sleep"].get("interval") if isinstance(point["sleep"].get("interval"), dict) else {}
        civil = interval.get("civilEndTime") if isinstance(interval.get("civilEndTime"), dict) else {}
        return _google_date_text(civil.get("date")) or _date_from_google_datetime(interval.get("endTime"))
    for key in (
        "dailyRestingHeartRate",
        "dailyHeartRateVariability",
        "dailyHeartRateZones",
        "dailyOxygenSaturation",
        "dailyRespiratoryRate",
        "dailySleepTemperatureDerivations",
    ):
        if isinstance(point.get(key), dict):
            day = _google_date_text(point[key].get("date"))
            if day:
                return day
    if data_type == "respiratory-rate-sleep-summary" and isinstance(point.get("respiratoryRateSleepSummary"), dict):
        sample_time = point["respiratoryRateSleepSummary"].get("sampleTime") if isinstance(point["respiratoryRateSleepSummary"].get("sampleTime"), dict) else {}
        civil = sample_time.get("civilTime") if isinstance(sample_time.get("civilTime"), dict) else {}
        return _google_date_text(civil.get("date")) or _date_from_google_datetime(sample_time.get("physicalTime"))
    return ""


def _finalize_health_daily_row(row: dict[str, Any]) -> dict[str, Any]:
    for field in ("resting_hr", "resting_hr_baseline", "average_hr", "max_hr", "workout_average_hr", "workout_max_hr"):
        row[field] = clean_heart_rate_value(row.get(field))
    row["hrv"] = clean_hrv_value(row.get("hrv"))
    if row.get("resting_hr") is None or row.get("resting_hr_baseline") is None:
        row["resting_hr_deviation"] = None
    if row.get("total_sleep_minutes") is not None:
        sleep_minutes = float(row.get("total_sleep_minutes") or 0)
        awake_minutes = float(row.get("awake_minutes") or 0)
        row["sleep_hours"] = _rounded(sleep_minutes / 60, 2)
        denominator = sleep_minutes + awake_minutes
        row["sleep_efficiency"] = _rounded((sleep_minutes / denominator) * 100) if denominator > 0 else None
        for key in ("total_sleep_minutes", "rem_sleep_minutes", "deep_sleep_minutes", "light_sleep_minutes", "awake_minutes"):
            row[key] = _rounded(row.get(key), 1)
    if row.get("distance_meters") is not None:
        row["distance_miles"] = _rounded(float(row["distance_meters"]) / 1609.344, 2)
    if row.get("total_calories_burned") is not None:
        row["calories_burned"] = row["total_calories_burned"]
    elif row.get("active_calories_burned") is not None:
        row["calories_burned"] = None
    if row.get("average_hr") is not None and (row.get("active_minutes") is not None or row.get("active_zone_minutes") is not None):
        row["workout_average_hr"] = row["average_hr"]
        row["workout_max_hr"] = row.get("max_hr")
    return {key: value for key, value in row.items() if not key.startswith("_")}


def _with_resting_hr_baselines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[float] = []
    enriched: list[dict[str, Any]] = []
    for row in sorted((dict(item) for item in items), key=lambda item: str(item.get("date") or "")):
        rhr = clean_heart_rate_value(row.get("resting_hr"))
        row["resting_hr"] = rhr
        baseline = _average(history[-7:])
        if rhr is not None and baseline is not None and len(history[-7:]) >= 3:
            row["resting_hr_baseline"] = clean_heart_rate_value(baseline)
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
        for field in ("resting_hr", "resting_hr_baseline", "average_hr", "max_hr", "workout_average_hr", "workout_max_hr"):
            row[field] = clean_heart_rate_value(row.get(field))
        row["hrv"] = clean_hrv_value(row.get("hrv"))
        if row.get("resting_hr") is None or row.get("resting_hr_baseline") is None:
            row["resting_hr_deviation"] = None
        source = str(row.get("source") or GOOGLE_HEALTH_PROVIDER_ID)
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
    """Fetch daily-level wearable metrics from Google Health API v4."""
    if not str(access_token or "").strip():
        return {
            "status": "missing_access_token",
            "provider": GOOGLE_HEALTH_PROVIDER_ID,
            "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
            "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "items": [],
            "message": "No Google Health access token is available.",
            "google_health_api_sync_available": False,
            "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_UNAVAILABLE_LABEL,
            "google_fit_legacy_data_source_status": "not_found",
            "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL,
            "api_request_log": [],
            "api_request_counts": {"total": 0, "google_health": 0, "google_fit_legacy": 0, "google_oauth": 0, "unknown": 0},
            "requests_sent_to_google_health_api": 0,
            "requests_sent_to_fitness_api": 0,
            "exact_endpoint_urls": [],
            "google_health_api_requests": [],
            "fitness_api_requests": [],
        }
    today = datetime.now(_app_timezone()).date()
    end_text = _date_text(end_date, today)
    start_text = _date_text(start_date, date.fromisoformat(end_text) - timedelta(days=13))
    base_url = api_base_url()
    if is_legacy_google_fit_base_url(base_url):
        logger.warning("[google_health] sync blocked because legacy Google Fit REST base URL is configured: %s", base_url)
        return {
            "status": "ok",
            "items": [],
            "message": GOOGLE_FIT_LEGACY_CONFIG_MESSAGE,
            "date_range": {"start_date": start_text, "end_date": end_text},
            "records": build_google_health_records([]),
            "warnings": [GOOGLE_FIT_LEGACY_CONFIG_MESSAGE],
            "optional_metric_warnings": [],
            "required_metric_failures": [],
            "data_sources": {
                "status": "legacy_google_fit_configured",
                "message": GOOGLE_FIT_LEGACY_CONFIG_MESSAGE,
                "data_sources": [],
                "paired_devices": [],
                "data_type_names": [],
                "available_data_types": [],
                "data_source_count": 0,
                "paired_device_count": 0,
                "api_base_url": base_url,
                "api_path": GOOGLE_FIT_LEGACY_API_PATH,
                "api_path_label": GOOGLE_FIT_LEGACY_API_LABEL,
                "provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
                "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
                "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
                "legacy_google_fit_detected": True,
                "google_health_api_sync_available": False,
                "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_UNAVAILABLE_LABEL,
                "google_fit_legacy_data_source_status": "found",
                "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_FOUND_LABEL,
            },
            "provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
            "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
            "api_base_url": base_url,
            "api_path": GOOGLE_FIT_LEGACY_API_PATH,
            "api_path_label": GOOGLE_FIT_LEGACY_API_LABEL,
            "google_health_api_sync_available": False,
            "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_UNAVAILABLE_LABEL,
            "google_fit_legacy_data_source_status": "found",
            "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_FOUND_LABEL,
            "google_fit_unused": False,
            "deprecated_fitness_api_unused": False,
            "legacy_google_fit_detected": True,
            "phone_app_data_note": "Deprecated Google Fit/Fitness API endpoints are not Google Health API data and are not used for successful wearable sync.",
            "fallback_plan": ["google_health_api_v4"],
            "discovered_metric_groups": {},
            "requested_scopes": scopes(),
            "requested_data_types": [],
            "raw_aggregate_responses": {},
            "raw_health_responses": {},
            "raw_response_count": 0,
            "raw_bucket_count": 0,
            "fetched_days": 0,
            "populated_days": 0,
            "placeholder_rows": [],
            "empty_date_rows": [],
            "empty_date_rows_count": 0,
            "populated_metric_counts_by_day": {},
            "populated_fields_by_metric": {},
            "normalization_audit": {},
            "data_available": False,
            "recommended_next_action": GOOGLE_FIT_LEGACY_CONFIG_MESSAGE,
            "fields_populated_count": 0,
            "fields_missing_count": 0,
            "api_request_log": [],
            "api_request_counts": {"total": 0, "google_health": 0, "google_fit_legacy": 0, "google_oauth": 0, "unknown": 0},
            "requests_sent_to_google_health_api": 0,
            "requests_sent_to_fitness_api": 0,
            "exact_endpoint_urls": [],
            "google_health_api_requests": [],
            "fitness_api_requests": [],
        }
    rows_by_day: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    optional_metric_warnings: list[str] = []
    required_metric_failures: list[str] = []
    raw_aggregate_responses: dict[str, Any] = {}
    data_source_summary: dict[str, Any] = {
        "status": "not_checked",
        "provider": GOOGLE_HEALTH_PROVIDER_ID,
        "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
        "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
        "data_sources": [],
        "data_type_names": [],
        "available_data_types": GOOGLE_HEALTH_DATA_TYPES.copy(),
        "data_source_count": 0,
        "paired_devices": [],
        "paired_device_count": 0,
        "google_health_api_sync_available": True,
        "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_AVAILABLE_LABEL,
        "google_fit_legacy_data_source_status": "not_found",
        "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL,
    }
    discovered_groups: dict[str, list[str]] = {
        "daily_rollup": GOOGLE_HEALTH_DAILY_ROLLUP_TYPES.copy(),
        "daily_points": GOOGLE_HEALTH_DAILY_POINT_TYPES.copy(),
        "session_points": GOOGLE_HEALTH_SESSION_POINT_TYPES.copy(),
    }
    api_request_log: list[dict[str, Any]] = []
    requested_data_types: list[str] = []
    recommended_next_action = ""
    raw_response_count = 0
    populated_by_metric: dict[str, int] = {}
    normalization_audit: dict[str, dict[str, Any]] = {}

    try:
        data_sources = list_data_sources(access_token, request_trace=api_request_log)
        data_source_summary = {
            "status": data_sources.get("status", "ok"),
            "data_sources": data_sources.get("data_sources") or [],
            "paired_devices": data_sources.get("paired_devices") or data_sources.get("data_sources") or [],
            "data_type_names": data_sources.get("data_type_names") or GOOGLE_HEALTH_DATA_TYPES.copy(),
            "available_data_types": data_sources.get("available_data_types") or GOOGLE_HEALTH_DATA_TYPES.copy(),
            "data_source_count": int(data_sources.get("data_source_count") or 0),
            "paired_device_count": int(data_sources.get("paired_device_count") or data_sources.get("data_source_count") or 0),
            "api_path": data_sources.get("api_path", GOOGLE_HEALTH_API_PATH),
            "api_path_label": data_sources.get("api_path_label", GOOGLE_HEALTH_API_LABEL),
            "provider": data_sources.get("provider", GOOGLE_HEALTH_PROVIDER_ID),
            "primary_provider": data_sources.get("primary_provider", GOOGLE_HEALTH_PROVIDER_ID),
            "legacy_provider": data_sources.get("legacy_provider", GOOGLE_FIT_LEGACY_PROVIDER_ID),
            "google_health_api_sync_available": data_sources.get("google_health_api_sync_available", True),
            "google_health_api_sync_label": data_sources.get("google_health_api_sync_label", GOOGLE_HEALTH_SYNC_AVAILABLE_LABEL),
            "google_fit_legacy_data_source_status": data_sources.get("google_fit_legacy_data_source_status", "not_found"),
            "google_fit_legacy_data_source_label": data_sources.get("google_fit_legacy_data_source_label", GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL),
        }
    except GoogleHealthIntegrationError as exc:
        message = f"Google Health paired device listing failed: {exc}"
        logger.warning("[google_health] %s", message[:500])
        data_source_summary = {**data_source_summary, "status": "warning", "message": str(exc)}
        warnings.append(message)

    for data_type in GOOGLE_HEALTH_DAILY_ROLLUP_TYPES:
        requested_data_types.append(data_type)
        try:
            response = _fetch_health_daily_rollup(
                access_token,
                data_type,
                start_text,
                end_text,
                request_trace=api_request_log,
            )
        except GoogleHealthIntegrationError as exc:
            failure = f"Google Health API {data_type} dailyRollUp failed: {exc}"
            if data_type in {"heart-rate"}:
                optional_metric_warnings.append(GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING)
                logger.warning("[google_health] %s", failure[:500])
            else:
                required_metric_failures.append(failure)
                warnings.append(failure)
            raw_aggregate_responses[data_type] = {"status": "error", "requested_data_types": [data_type], "endpoint": "dailyRollUp", "error": str(exc)}
            trace_entry = _latest_trace_for_data_type(api_request_log, data_type, "dailyRollUp")
            normalization_audit[data_type] = {
                "provider": GOOGLE_HEALTH_PROVIDER_ID,
                "source": GOOGLE_HEALTH_PROVIDER_ID,
                "endpoint": "dailyRollUp",
                "endpoint_url": trace_entry.get("url", f"{api_base_url()}/v4/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"),
                "api_family": trace_entry.get("api_family", "google_health"),
                "data_type": data_type,
                "status": "error",
                "error": str(exc),
                "raw_datapoint_count": 0,
                "raw_populated_datapoint_count": 0,
                "normalized_field_count": 0,
                "applied_datapoint_count": 0,
                "dropped_datapoint_count": 0,
                "dropped_reasons": {"request_error": 1},
                "raw_sample": {},
            }
            continue
        compact = _compact_health_rollup_response(response, data_type)
        trace_entry = _latest_trace_for_data_type(api_request_log, data_type, "dailyRollUp")
        audit = {
            "provider": GOOGLE_HEALTH_PROVIDER_ID,
            "source": GOOGLE_HEALTH_PROVIDER_ID,
            "endpoint": "dailyRollUp",
            "endpoint_url": trace_entry.get("url", f"{api_base_url()}/v4/users/me/dataTypes/{data_type}/dataPoints:dailyRollUp"),
            "api_family": trace_entry.get("api_family", "google_health"),
            "data_type": data_type,
            "raw_datapoint_count": compact["point_count"],
            "raw_populated_datapoint_count": compact["populated_point_count"],
            "value_keys": compact.get("value_keys", []),
            "normalized_field_count": 0,
            "applied_datapoint_count": 0,
            "dropped_datapoint_count": 0,
            "dropped_reasons": {},
            "raw_sample": compact.get("sample", {}),
        }
        raw_aggregate_responses[data_type] = {"status": "ok", **compact}
        raw_response_count += compact["point_count"]
        populated_by_metric[data_type] = int(compact["populated_point_count"])
        for point in response.get("rollupDataPoints") or []:
            if not isinstance(point, dict):
                continue
            day = _google_date_text((point.get("civilStartTime") if isinstance(point.get("civilStartTime"), dict) else {}).get("date"))
            if not day:
                audit["dropped_datapoint_count"] += 1
                audit["dropped_reasons"]["missing_day"] = int(audit["dropped_reasons"].get("missing_day", 0)) + 1
                continue
            row = _row_for_day(rows_by_day, day)
            before_fields = _row_metric_fields(row)
            before_hr_counts = _clean_hr_diagnostics_from_rows([row])
            _apply_health_rollup(row, data_type, point)
            after_hr_counts = _clean_hr_diagnostics_from_rows([row])
            for key in ("raw_hr_samples_received", "invalid_hr_samples_dropped", "clean_hr_samples_used"):
                audit[key] = int(audit.get(key) or 0) + max(0, int(after_hr_counts.get(key) or 0) - int(before_hr_counts.get(key) or 0))
            added_fields = sorted(_row_metric_fields(row) - before_fields)
            if added_fields:
                audit["applied_datapoint_count"] += 1
                audit["normalized_field_count"] += len(added_fields)
                audit.setdefault("normalized_fields", [])
                audit["normalized_fields"] = sorted(set([*audit["normalized_fields"], *added_fields]))
            elif compact["populated_point_count"]:
                audit["dropped_datapoint_count"] += 1
                audit["dropped_reasons"]["no_supported_fields"] = int(audit["dropped_reasons"].get("no_supported_fields", 0)) + 1
        normalization_audit[data_type] = audit

    for data_type in [*GOOGLE_HEALTH_DAILY_POINT_TYPES, *GOOGLE_HEALTH_SESSION_POINT_TYPES]:
        requested_data_types.append(data_type)
        try:
            response = _fetch_health_reconciled_points(
                access_token,
                data_type,
                start_text,
                end_text,
                request_trace=api_request_log,
            )
            endpoint = "reconcile"
        except GoogleHealthIntegrationError as reconcile_error:
            try:
                response = _fetch_health_points(
                    access_token,
                    data_type,
                    start_text,
                    end_text,
                    request_trace=api_request_log,
                )
                endpoint = "list"
            except GoogleHealthIntegrationError as list_error:
                message = f"Google Health API {data_type} dataPoints failed: reconcile={reconcile_error}; list={list_error}"
                if data_type in {"daily-resting-heart-rate", "daily-heart-rate-variability"}:
                    optional_metric_warnings.append(GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING)
                elif data_type in {"daily-heart-rate-zones", "daily-oxygen-saturation", "daily-respiratory-rate", "daily-sleep-temperature-derivations", "respiratory-rate-sleep-summary"}:
                    optional_metric_warnings.append("Optional Google Health vitals unavailable.")
                else:
                    warnings.append(message)
                raw_aggregate_responses[data_type] = {"status": "error", "requested_data_types": [data_type], "endpoint": "reconcile/list", "error": message}
                trace_entry = _latest_trace_for_data_type(api_request_log, data_type)
                normalization_audit[data_type] = {
                    "provider": GOOGLE_HEALTH_PROVIDER_ID,
                    "source": GOOGLE_HEALTH_PROVIDER_ID,
                    "endpoint": "reconcile/list",
                    "endpoint_url": trace_entry.get("url", ""),
                    "api_family": trace_entry.get("api_family", "google_health"),
                    "data_type": data_type,
                    "status": "error",
                    "error": message,
                    "raw_datapoint_count": 0,
                    "raw_populated_datapoint_count": 0,
                    "normalized_field_count": 0,
                    "applied_datapoint_count": 0,
                    "dropped_datapoint_count": 0,
                    "dropped_reasons": {"request_error": 1},
                    "raw_sample": {},
                }
                continue
        compact = _compact_health_points_response(response, data_type, endpoint=endpoint)
        trace_entry = _latest_trace_for_data_type(api_request_log, data_type, endpoint)
        audit = {
            "provider": GOOGLE_HEALTH_PROVIDER_ID,
            "source": GOOGLE_HEALTH_PROVIDER_ID,
            "endpoint": endpoint,
            "endpoint_url": trace_entry.get("url", ""),
            "api_family": trace_entry.get("api_family", "google_health"),
            "data_type": data_type,
            "raw_datapoint_count": compact["point_count"],
            "raw_populated_datapoint_count": compact["populated_point_count"],
            "value_keys": compact.get("value_keys", []),
            "normalized_field_count": 0,
            "applied_datapoint_count": 0,
            "dropped_datapoint_count": 0,
            "dropped_reasons": {},
            "raw_sample": compact.get("sample", {}),
        }
        raw_aggregate_responses[data_type] = {"status": "ok", **compact}
        raw_response_count += compact["point_count"]
        populated_by_metric[data_type] = int(compact["populated_point_count"])
        for point in response.get("dataPoints") or []:
            if not isinstance(point, dict):
                continue
            day = _point_day(data_type, point)
            if not day:
                audit["dropped_datapoint_count"] += 1
                audit["dropped_reasons"]["missing_day"] = int(audit["dropped_reasons"].get("missing_day", 0)) + 1
                continue
            row = _row_for_day(rows_by_day, day)
            before_fields = _row_metric_fields(row)
            before_hr_counts = _clean_hr_diagnostics_from_rows([row])
            _apply_health_point(row, data_type, point)
            after_hr_counts = _clean_hr_diagnostics_from_rows([row])
            for key in ("raw_hr_samples_received", "invalid_hr_samples_dropped", "clean_hr_samples_used"):
                audit[key] = int(audit.get(key) or 0) + max(0, int(after_hr_counts.get(key) or 0) - int(before_hr_counts.get(key) or 0))
            added_fields = sorted(_row_metric_fields(row) - before_fields)
            if added_fields:
                audit["applied_datapoint_count"] += 1
                audit["normalized_field_count"] += len(added_fields)
                audit.setdefault("normalized_fields", [])
                audit["normalized_fields"] = sorted(set([*audit["normalized_fields"], *added_fields]))
            elif compact["populated_point_count"]:
                audit["dropped_datapoint_count"] += 1
                audit["dropped_reasons"]["no_supported_fields"] = int(audit["dropped_reasons"].get("no_supported_fields", 0)) + 1
        normalization_audit[data_type] = audit

    clean_hr_diagnostics = _clean_hr_diagnostics_from_rows([row for _, row in sorted(rows_by_day.items())])
    all_items = [_finalize_health_daily_row(row) for _, row in sorted(rows_by_day.items())]
    all_items = _with_resting_hr_baselines(all_items)
    for row in all_items:
        row["source"] = GOOGLE_HEALTH_PROVIDER_ID
        row["provider"] = GOOGLE_HEALTH_PROVIDER_ID
        row["populated_metric_count"] = populated_metric_count(row)
        row["placeholder"] = row["populated_metric_count"] <= 0
        row["raw_payload"] = {
            "api_base_url": base_url,
            "api_path": GOOGLE_HEALTH_API_PATH,
            "provider": GOOGLE_HEALTH_PROVIDER_ID,
            "date": row.get("date"),
            "requested_data_types": requested_data_types,
        }
    items = [row for row in all_items if has_populated_metrics(row)]
    empty_items = [row for row in all_items if not has_populated_metrics(row)]
    empty_date_rows = [str(row.get("date") or "")[:10] for row in empty_items if str(row.get("date") or "").strip()]

    if int(clean_hr_diagnostics.get("invalid_hr_samples_dropped") or 0):
        warnings.append(
            f"Dropped {int(clean_hr_diagnostics.get('invalid_hr_samples_dropped') or 0)} invalid heart-rate sample(s) outside the clean BPM range."
        )

    if not items:
        recommended_next_action = GOOGLE_HEALTH_NO_SOURCES_MESSAGE
        if recommended_next_action not in warnings:
            warnings.append(recommended_next_action)
    else:
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
                    warnings.append(f"Missing Google Health API metric group: {label}.")

    optional_metric_warnings = list(dict.fromkeys(optional_metric_warnings))
    warnings = list(dict.fromkeys([*warnings, *optional_metric_warnings]))
    requested_data_types = _unique_preserve_order(requested_data_types)
    for audit in normalization_audit.values():
        audit["status"] = audit.get("status", "ok")
        audit["dropped_field_count"] = max(
            0,
            int(audit.get("raw_populated_datapoint_count") or 0) - int(audit.get("normalized_field_count") or 0),
        )
    api_request_counts = _request_trace_counts(api_request_log)
    google_health_api_requests = [entry for entry in api_request_log if entry.get("api_family") == "google_health"]
    fitness_api_requests = [entry for entry in api_request_log if entry.get("api_family") == "google_fit_legacy"]
    exact_endpoint_urls = [str(entry.get("url") or "") for entry in api_request_log if str(entry.get("url") or "").strip()]
    for warning in warnings:
        if warning.startswith("Missing") or warning.startswith("No Google Health") or "unavailable" in warning.lower():
            logger.warning("[google_health] %s", warning)
    records = build_google_health_records(items)
    field_counts = _field_count_summary(all_items)
    logger.info(
        "[google_health] fetched v4 metrics populated_days=%s empty_days=%s raw_points=%s warnings=%s start=%s end=%s paired_devices=%s health_requests=%s fitness_requests=%s",
        len(items),
        len(empty_items),
        raw_response_count,
        len(warnings),
        start_text,
        end_text,
        data_source_summary.get("paired_device_count", 0),
        api_request_counts.get("google_health", 0),
        api_request_counts.get("google_fit_legacy", 0),
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
        "api_base_url": api_base_url(),
        "api_path": GOOGLE_HEALTH_API_PATH,
        "api_path_label": GOOGLE_HEALTH_API_LABEL,
        "provider": GOOGLE_HEALTH_PROVIDER_ID,
        "primary_provider": GOOGLE_HEALTH_PROVIDER_ID,
        "legacy_provider": GOOGLE_FIT_LEGACY_PROVIDER_ID,
        "google_connection_label": GOOGLE_CONNECTED_LABEL,
        "google_health_api_sync_available": True,
        "google_health_api_sync_label": GOOGLE_HEALTH_SYNC_AVAILABLE_LABEL,
        "google_fit_legacy_data_source_status": "not_found",
        "google_fit_legacy_data_source_label": GOOGLE_FIT_LEGACY_NOT_FOUND_LABEL,
        "google_fit_unused": True,
        "deprecated_fitness_api_unused": True,
        "phone_app_data_note": "Google Health API v4 is the primary wearable provider. Deprecated Google Fit/Fitness API endpoints are not used for sync.",
        "fallback_plan": ["google_health_api_v4"],
        "discovered_metric_groups": discovered_groups,
        "requested_scopes": scopes(),
        "requested_data_types": requested_data_types,
        "raw_aggregate_responses": raw_aggregate_responses,
        "raw_health_responses": raw_aggregate_responses,
        "raw_response_count": raw_response_count,
        "raw_bucket_count": 0,
        "fetched_days": len(all_items),
        "populated_days": len(items),
        "placeholder_rows": empty_items,
        "empty_date_rows": empty_date_rows,
        "empty_date_rows_count": len(empty_date_rows),
        "populated_metric_counts_by_day": populated_metric_counts_by_day(all_items),
        "populated_fields_by_metric": populated_by_metric,
        "clean_hr_diagnostics": clean_hr_diagnostics,
        "raw_hr_samples_received": int(clean_hr_diagnostics.get("raw_hr_samples_received") or 0),
        "invalid_hr_samples_dropped": int(clean_hr_diagnostics.get("invalid_hr_samples_dropped") or 0),
        "clean_hr_samples_used": int(clean_hr_diagnostics.get("clean_hr_samples_used") or 0),
        "normalization_audit": normalization_audit,
        "data_available": bool(items),
        "recommended_next_action": recommended_next_action,
        "api_request_log": api_request_log,
        "api_request_counts": api_request_counts,
        "requests_sent_to_google_health_api": int(api_request_counts.get("google_health") or 0),
        "requests_sent_to_fitness_api": int(api_request_counts.get("google_fit_legacy") or 0),
        "exact_endpoint_urls": exact_endpoint_urls,
        "google_health_api_requests": google_health_api_requests,
        "fitness_api_requests": fitness_api_requests,
        **field_counts,
    }


def normalize_daily_metrics(metrics: list[dict] | pd.DataFrame | None, source: str = GOOGLE_HEALTH_PROVIDER_ID) -> pd.DataFrame:
    """Normalize Google Health daily payloads into wearable metric rows."""
    return normalize_wearable_metric_rows(metrics, source=source, provider=source)


def saved_token_state(settings: dict | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = _settings_metadata(settings)
    tokens = metadata.get("google_health_tokens") if isinstance(metadata.get("google_health_tokens"), dict) else {}
    sync = metadata.get("google_health_sync") if isinstance(metadata.get("google_health_sync"), dict) else {}
    return tokens, sync
