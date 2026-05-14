"""
Strava integration for importing runs into the local training log.

This module uses Strava OAuth2. Tokens are stored locally in the app's
gitignored settings file and are never returned to the frontend.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from src.config import load_settings, save_settings
from src.training import TRAINING_COLUMNS, load_training_log, save_training_log


STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ACTIVITY_MARKER = "strava_activity_id="
RUN_SPORT_TYPES = {"Run", "TrailRun", "VirtualRun"}
METERS_PER_MILE = 1609.344

class StravaIntegrationError(Exception):
    """Raised when Strava import cannot complete."""


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


def _get_strava_credentials() -> tuple[str, str]:
    """Read Strava client credentials from settings, environment, or .env."""
    settings = load_settings()
    integrations = settings.get("integrations", {})
    client_id = (
        integrations.get("strava_client_id", "").strip()
        or os.getenv("STRAVA_CLIENT_ID", "").strip()
        or _read_dotenv_value("STRAVA_CLIENT_ID").strip()
    )
    client_secret = (
        integrations.get("strava_client_secret", "").strip()
        or os.getenv("STRAVA_CLIENT_SECRET", "").strip()
        or _read_dotenv_value("STRAVA_CLIENT_SECRET").strip()
    )
    if not client_id or not client_secret:
        raise StravaIntegrationError("Strava client ID and secret are required before connecting.")
    return client_id, client_secret


def get_strava_connection_status() -> str:
    """Return a frontend-safe Strava connection status."""
    settings = load_settings()
    tokens = settings.get("metadata", {}).get("strava_tokens", {})
    integrations = settings.get("integrations", {})
    if tokens.get("access_token") and tokens.get("refresh_token"):
        return "Connected"
    client_id = (
        integrations.get("strava_client_id", "").strip()
        or os.getenv("STRAVA_CLIENT_ID", "").strip()
        or _read_dotenv_value("STRAVA_CLIENT_ID").strip()
    )
    client_secret = (
        integrations.get("strava_client_secret", "").strip()
        or os.getenv("STRAVA_CLIENT_SECRET", "").strip()
        or _read_dotenv_value("STRAVA_CLIENT_SECRET").strip()
    )
    if client_id and client_secret:
        return "Ready to connect"
    return "Not configured"


def build_strava_auth_url(redirect_uri: str, state: str | None = None) -> str:
    """Generate a Strava OAuth URL for read and activity import scopes."""
    client_id, _ = _get_strava_credentials()
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": "read,activity:read_all",
    }
    if state:
        query["state"] = state
    return f"{STRAVA_AUTH_URL}?{urlencode(query)}"


def _post_token_request(body: dict) -> dict:
    """Send a form-encoded request to Strava's OAuth token endpoint."""
    request = Request(
        STRAVA_TOKEN_URL,
        data=urlencode(body).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StravaIntegrationError(f"Strava OAuth request failed with status {exc.code}: {detail}") from exc
    except URLError as exc:
        raise StravaIntegrationError(f"Could not reach Strava OAuth: {exc.reason}") from exc
    except TimeoutError as exc:
        raise StravaIntegrationError("Strava OAuth request timed out.") from exc
    except json.JSONDecodeError as exc:
        raise StravaIntegrationError("Strava OAuth returned invalid JSON.") from exc


def _save_strava_tokens(token_payload: dict) -> dict:
    """Persist Strava tokens locally without exposing them to frontend responses."""
    settings = load_settings()
    athlete = token_payload.get("athlete") or {}
    settings.setdefault("metadata", {})["strava_tokens"] = {
        "access_token": str(token_payload.get("access_token", "")),
        "refresh_token": str(token_payload.get("refresh_token", "")),
        "expires_at": int(token_payload.get("expires_at") or 0),
        "athlete_id": str(athlete.get("id", "")),
    }
    save_settings(settings)
    return settings["metadata"]["strava_tokens"]


def exchange_strava_code(code: str) -> dict:
    """Exchange a Strava OAuth authorization code for local tokens."""
    client_id, client_secret = _get_strava_credentials()
    token_payload = _post_token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
    )
    _save_strava_tokens(token_payload)
    return {"status": "Connected", "athlete_id": str((token_payload.get("athlete") or {}).get("id", ""))}


def refresh_strava_token_if_needed(force: bool = False) -> str:
    """Refresh the saved Strava access token when expired or near expiry."""
    settings = load_settings()
    tokens = settings.get("metadata", {}).get("strava_tokens", {})
    access_token = str(tokens.get("access_token", "")).strip()
    refresh_token = str(tokens.get("refresh_token", "")).strip()
    expires_at = int(tokens.get("expires_at") or 0)

    if not refresh_token:
        if access_token:
            return access_token
        raise StravaIntegrationError("Strava is not connected yet.")

    if not force and access_token and expires_at > int(time.time()) + 120:
        return access_token

    client_id, client_secret = _get_strava_credentials()
    token_payload = _post_token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    )
    tokens = _save_strava_tokens(token_payload)
    return str(tokens.get("access_token", ""))


def _get_access_token(access_token: str | None = None) -> str:
    """Read a Strava access token from argument, saved OAuth tokens, env, or .env."""
    token = (access_token or "").strip()
    if not token:
        try:
            token = refresh_strava_token_if_needed()
        except StravaIntegrationError:
            token = ""
    token = token or os.getenv("STRAVA_ACCESS_TOKEN", "").strip() or _read_dotenv_value("STRAVA_ACCESS_TOKEN").strip()
    if not token:
        raise StravaIntegrationError(
            "Missing Strava access token. Connect Strava or set STRAVA_ACCESS_TOKEN."
        )
    return token


def _parse_date(timestamp: str | None) -> str:
    """Convert Strava timestamps into YYYY-MM-DD for local logs."""
    if not timestamp:
        return datetime.today().date().isoformat()
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(timestamp)[:10]


def _distance_miles(distance_meters) -> float:
    """Convert Strava meters to miles."""
    return round(float(distance_meters or 0) / METERS_PER_MILE, 2)


def _pace_minutes_per_mile(distance_miles: float, moving_time_seconds) -> float:
    """Calculate mile pace from distance and moving time."""
    if distance_miles <= 0:
        return 0.0
    return round((float(moving_time_seconds or 0) / 60) / distance_miles, 2)


def _estimate_run_load(distance_miles: float, duration_minutes: float, average_speed) -> float:
    """Estimate running load from distance, duration, and speed."""
    speed_component = min(float(average_speed or 0) * 2, 10)
    return round((distance_miles * 10) + (duration_minutes * 0.45) + speed_component, 1)


def fetch_recent_runs(access_token: str | None = None, per_page: int = 30) -> list[dict]:
    """Fetch recent Strava activities and keep run-like sport types."""
    token = _get_access_token(access_token)
    safe_per_page = max(1, min(int(per_page), 200))
    query = urlencode({"page": 1, "per_page": safe_per_page})
    request = Request(
        f"{STRAVA_API_BASE_URL}/athlete/activities?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )

    try:
        with urlopen(request, timeout=20) as response:
            activities = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise StravaIntegrationError(
            f"Strava request failed with status {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise StravaIntegrationError(f"Could not reach Strava: {exc.reason}") from exc
    except TimeoutError as exc:
        raise StravaIntegrationError("Strava request timed out.") from exc
    except json.JSONDecodeError as exc:
        raise StravaIntegrationError("Strava returned invalid JSON.") from exc

    return [
        activity
        for activity in activities
        if activity.get("sport_type") in RUN_SPORT_TYPES or activity.get("type") == "Run"
    ]


def normalize_strava_run(activity: dict) -> dict:
    """Convert one Strava run into the app's training log schema."""
    activity_id = str(activity.get("id", "")).strip()
    distance_miles = _distance_miles(activity.get("distance"))
    duration_minutes = round(float(activity.get("moving_time") or 0) / 60, 1)
    pace = _pace_minutes_per_mile(distance_miles, activity.get("moving_time"))
    estimated_load = _estimate_run_load(
        distance_miles=distance_miles,
        duration_minutes=duration_minutes,
        average_speed=activity.get("average_speed"),
    )
    name = str(activity.get("name") or "Strava Run").strip()
    sport_type = str(activity.get("sport_type") or activity.get("type") or "Run")

    return {
        "workout_id": activity_id,
        "date": _parse_date(activity.get("start_date_local") or activity.get("start_date")),
        "workout_type": "Run",
        "muscle_group": "Cardio",
        "exercise": name,
        "set_number": 1,
        "sets": 0,
        "reps": 0,
        "weight": 0.0,
        "rpe": 0.0,
        "duration_minutes": duration_minutes,
        "notes": (
            "Imported from Strava"
            f" | {STRAVA_ACTIVITY_MARKER}{activity_id}"
            f" | sport_type={sport_type}"
            f" | distance_miles={distance_miles}"
            f" | pace_min_per_mile={pace}"
            f" | estimated_run_load={estimated_load}"
        ),
        "source": "strava",
        "external_id": activity_id,
    }


def _imported_activity_ids(training_df: pd.DataFrame) -> set[str]:
    """Extract already-imported Strava IDs from local training notes."""
    if training_df.empty or "notes" not in training_df.columns:
        return set()

    imported_ids = set()
    for note in training_df["notes"].fillna("").astype(str):
        if STRAVA_ACTIVITY_MARKER not in note:
            continue
        value = note.split(STRAVA_ACTIVITY_MARKER, 1)[1].split("|", 1)[0].strip()
        imported_ids.add(value)
    return imported_ids


def import_recent_runs(access_token: str | None = None, per_page: int = 30) -> dict:
    """Import recent Strava runs into data/processed/training_log.csv."""
    runs = fetch_recent_runs(access_token=access_token, per_page=per_page)
    training_df = load_training_log()
    existing_ids = _imported_activity_ids(training_df)
    imported_rows = []
    skipped_duplicates = 0

    for run in runs:
        activity_id = str(run.get("id", "")).strip()
        if not activity_id:
            continue
        if activity_id in existing_ids:
            skipped_duplicates += 1
            continue
        imported_rows.append(normalize_strava_run(run))
        existing_ids.add(activity_id)

    if imported_rows:
        import_df = pd.DataFrame(imported_rows).reindex(columns=TRAINING_COLUMNS)
        training_df = pd.concat([training_df, import_df], ignore_index=True)
        training_df = training_df.sort_values("date", kind="stable").reset_index(drop=True)
        save_training_log(training_df)

    return {
        "imported_runs": len(imported_rows),
        "skipped_duplicates": skipped_duplicates,
        "training_log": training_df,
    }


def _extract_note_number(note: str, key: str) -> float:
    """Extract numeric analytics values embedded in Strava import notes."""
    marker = f"{key}="
    if marker not in note:
        return 0.0
    raw = note.split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def calculate_running_analytics(training_df: pd.DataFrame) -> pd.DataFrame:
    """Create pace, distance, weekly mileage, and load trends from run rows."""
    columns = [
        "date",
        "exercise",
        "distance_miles",
        "pace_min_per_mile",
        "estimated_run_load",
        "weekly_mileage",
    ]
    if training_df.empty:
        return pd.DataFrame(columns=columns)

    runs_df = training_df[
        training_df["workout_type"].astype(str).str.lower() == "run"
    ].copy()
    if runs_df.empty:
        return pd.DataFrame(columns=columns)

    runs_df["date"] = pd.to_datetime(runs_df["date"], errors="coerce")
    runs_df = runs_df.dropna(subset=["date"]).sort_values("date")
    runs_df["notes"] = runs_df["notes"].fillna("").astype(str)
    runs_df["distance_miles"] = runs_df["notes"].apply(
        lambda note: _extract_note_number(note, "distance_miles")
    )
    runs_df["pace_min_per_mile"] = runs_df["notes"].apply(
        lambda note: _extract_note_number(note, "pace_min_per_mile")
    )
    runs_df["estimated_run_load"] = runs_df["notes"].apply(
        lambda note: _extract_note_number(note, "estimated_run_load")
    )
    runs_df["weekly_mileage"] = (
        runs_df.set_index("date")["distance_miles"]
        .rolling("7D", min_periods=1)
        .sum()
        .values
    )
    runs_df["date"] = runs_df["date"].dt.date.astype(str)

    return runs_df[columns].reset_index(drop=True)
