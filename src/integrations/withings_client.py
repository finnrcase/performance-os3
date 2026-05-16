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
        return "Ready to connect"
    return "Not configured"


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
    return load_settings().get("metadata", {}).get("withings_sync", {})


def _save_withings_sync_state(updates: dict) -> dict:
    settings = load_settings()
    sync = settings.setdefault("metadata", {}).setdefault("withings_sync", {})
    sync.update(updates)
    save_settings(settings)
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
    }
