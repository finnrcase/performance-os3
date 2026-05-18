"""
Strava integration for importing runs into the local training log.

This module uses Strava OAuth2. Tokens are stored locally in the app's
gitignored settings file and are never returned to the frontend.
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

import pandas as pd

from src.config import load_settings, save_settings
from src.storage import mark_dataframe_deletes
from src.training import TRAINING_COLUMNS, load_training_log, save_training_log


STRAVA_API_BASE_URL = "https://www.strava.com/api/v3"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ACTIVITY_MARKER = "strava_activity_id="
RUN_SPORT_TYPES = {"Run", "TrailRun", "VirtualRun"}
METERS_PER_MILE = 1609.344
logger = logging.getLogger(__name__)

class StravaIntegrationError(Exception):
    """Raised when Strava import cannot complete."""


class StravaReconnectRequired(StravaIntegrationError):
    """Raised when saved Strava tokens are invalid and OAuth must be run again."""


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
        missing = []
        if not client_id:
            missing.append("STRAVA_CLIENT_ID")
        if not client_secret:
            missing.append("STRAVA_CLIENT_SECRET")
        raise StravaIntegrationError(f"{' and '.join(missing)} must be configured before connecting Strava.")
    return client_id, client_secret


def _env_strava_tokens() -> dict:
    """Read optional production Strava OAuth tokens from backend env vars."""
    access_token_env = os.getenv("STRAVA_ACCESS_TOKEN", "").strip()
    refresh_token_env = os.getenv("STRAVA_REFRESH_TOKEN", "").strip()
    explicit_env_tokens = bool(access_token_env or refresh_token_env)
    expires_at = os.getenv("STRAVA_EXPIRES_AT", "").strip() or os.getenv("STRAVA_TOKEN_EXPIRES_AT", "").strip()
    if not expires_at and not explicit_env_tokens:
        expires_at = _read_dotenv_value("STRAVA_EXPIRES_AT").strip() or _read_dotenv_value("STRAVA_TOKEN_EXPIRES_AT").strip()
    try:
        expires_at_int = int(expires_at or 0)
    except ValueError:
        expires_at_int = 0
    return {
        "access_token": access_token_env or _read_dotenv_value("STRAVA_ACCESS_TOKEN").strip(),
        "refresh_token": refresh_token_env or _read_dotenv_value("STRAVA_REFRESH_TOKEN").strip(),
        "expires_at": expires_at_int,
        "athlete_id": os.getenv("STRAVA_ATHLETE_ID", "").strip() or _read_dotenv_value("STRAVA_ATHLETE_ID").strip(),
        "scopes": os.getenv("STRAVA_SCOPES", "").strip() or _read_dotenv_value("STRAVA_SCOPES").strip() or "read,activity:read_all",
    }


def _effective_strava_tokens(settings: dict | None = None) -> dict:
    """Resolve Strava tokens from explicit env vars, persisted settings, or .env."""
    current_settings = settings or load_settings()
    saved_tokens = current_settings.get("metadata", {}).get("strava_tokens", {})
    explicit_env_tokens = bool(os.getenv("STRAVA_ACCESS_TOKEN", "").strip() and os.getenv("STRAVA_REFRESH_TOKEN", "").strip())
    env_tokens = _env_strava_tokens()
    if explicit_env_tokens:
        return env_tokens
    if saved_tokens.get("access_token") or saved_tokens.get("refresh_token"):
        return saved_tokens
    return env_tokens if env_tokens.get("access_token") or env_tokens.get("refresh_token") else saved_tokens


def get_strava_connection_status() -> str:
    """Return a frontend-safe Strava connection status."""
    settings = load_settings()
    tokens = _effective_strava_tokens(settings)
    sync_state = settings.get("metadata", {}).get("strava_sync", {})
    env_tokens = _env_strava_tokens()
    has_env_tokens = bool(env_tokens.get("access_token") and env_tokens.get("refresh_token"))
    if sync_state.get("needs_reconnect") and not has_env_tokens:
        return "Disconnected"
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


def get_strava_safe_token_metadata() -> dict:
    """Return frontend-safe Strava token metadata from DB or backend env tokens."""
    settings = load_settings()
    tokens = _effective_strava_tokens(settings)
    expires_at = int(tokens.get("expires_at") or 0)
    now = int(time.time())
    connected = bool(tokens.get("access_token") and tokens.get("refresh_token"))
    token_expired = bool(connected and expires_at and expires_at <= now)
    token_expiring = bool(connected and expires_at and not token_expired and expires_at <= now + 300)
    return {
        "connected": connected,
        "athlete_id": str(tokens.get("athlete_id", "") or ""),
        "token_expires_at": expires_at,
        "token_status": "expired" if token_expired else "refresh soon" if token_expiring else "valid" if connected else "missing",
        "scopes": str(tokens.get("scopes", "") or ""),
    }


def build_strava_auth_url(redirect_uri: str, state: str | None = None, force_approval: bool = False) -> str:
    """Generate a Strava OAuth URL for read and activity import scopes."""
    client_id, _ = _get_strava_credentials()
    if not redirect_uri:
        raise StravaIntegrationError("STRAVA_REDIRECT_URI could not be resolved.")
    logger.info("Starting Strava OAuth with redirect_uri=%s", redirect_uri)
    query = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "force" if force_approval else "auto",
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
        logger.exception("Strava OAuth request failed with status %s", exc.code)
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
    previous_tokens = settings.get("metadata", {}).get("strava_tokens", {})
    settings.setdefault("metadata", {})["strava_tokens"] = {
        "access_token": str(token_payload.get("access_token", "")),
        "refresh_token": str(token_payload.get("refresh_token", "")),
        "expires_at": int(token_payload.get("expires_at") or 0),
        "athlete_id": str(athlete.get("id", "") or previous_tokens.get("athlete_id", "")),
        "scopes": str(token_payload.get("scope") or previous_tokens.get("scopes") or "read,activity:read_all"),
    }
    settings.setdefault("metadata", {}).setdefault("strava_sync", {})["needs_reconnect"] = False
    settings["metadata"]["strava_sync"]["last_error"] = ""
    save_settings(settings)
    logger.info(
        "Stored Strava tokens for athlete_id=%s expires_at=%s",
        settings["metadata"]["strava_tokens"].get("athlete_id", ""),
        settings["metadata"]["strava_tokens"].get("expires_at", 0),
    )
    return settings["metadata"]["strava_tokens"]


def clear_strava_connection(reason: str = "", mark_error: bool = True) -> dict:
    """Clear saved OAuth tokens so the next action starts a clean reconnect flow."""
    settings = load_settings()
    athlete_id = str(settings.get("metadata", {}).get("strava_tokens", {}).get("athlete_id", "") or "")
    settings.setdefault("metadata", {})["strava_tokens"] = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0,
        "athlete_id": athlete_id,
        "scopes": "",
    }
    sync = settings.setdefault("metadata", {}).setdefault("strava_sync", {})
    sync["needs_reconnect"] = True
    sync["last_error"] = (reason or "Strava authorization expired. Reconnect Strava.") if mark_error else ""
    sync["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    save_settings(settings)
    logger.warning("Cleared Strava connection state: %s", reason or "manual reconnect")
    return sync


def exchange_strava_code(code: str) -> dict:
    """Exchange a Strava OAuth authorization code for local tokens."""
    logger.info("Strava OAuth callback received; exchanging code.")
    client_id, client_secret = _get_strava_credentials()
    token_payload = _post_token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
    )
    tokens = _save_strava_tokens(token_payload)
    logger.info("Strava token exchange succeeded for athlete_id=%s", tokens.get("athlete_id", ""))
    return {"status": "Connected", "athlete_id": str((token_payload.get("athlete") or {}).get("id", ""))}


def refresh_strava_token_if_needed(force: bool = False) -> str:
    """Refresh the saved Strava access token when expired or near expiry."""
    settings = load_settings()
    tokens = _effective_strava_tokens(settings)
    access_token = str(tokens.get("access_token", "")).strip()
    refresh_token = str(tokens.get("refresh_token", "")).strip()
    expires_at = int(tokens.get("expires_at") or 0)
    now = int(time.time())

    if not refresh_token:
        if access_token:
            clear_strava_connection("Saved Strava access token has no refresh token. Reconnect Strava.")
            raise StravaReconnectRequired("Saved Strava access token has no refresh token. Reconnect Strava.")
        raise StravaReconnectRequired("Strava is not connected yet. Connect Strava from Settings.")

    if not force and access_token and (expires_at == 0 or expires_at > now + 300):
        return access_token

    client_id, client_secret = _get_strava_credentials()
    logger.info("Refreshing Strava access token; expires_at=%s now=%s force=%s", expires_at, now, force)
    try:
        token_payload = _post_token_request(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )
    except StravaIntegrationError as exc:
        clear_strava_connection(f"Strava token refresh failed. Reconnect Strava. {exc}")
        logger.exception("Strava token refresh failed; reconnect required.")
        raise StravaReconnectRequired("Strava token refresh failed. Reconnect Strava from Settings.") from exc
    tokens = _save_strava_tokens(token_payload)
    logger.info("Strava token refresh succeeded; expires_at=%s", tokens.get("expires_at", 0))
    return str(tokens.get("access_token", ""))


def _get_access_token(access_token: str | None = None) -> str:
    """Read a Strava access token from saved OAuth tokens, refreshing when needed."""
    token = (access_token or "").strip()
    if not token:
        settings = load_settings()
        saved_tokens = _effective_strava_tokens(settings)
        has_saved_oauth = bool(saved_tokens.get("access_token") or saved_tokens.get("refresh_token"))
        try:
            token = refresh_strava_token_if_needed()
        except StravaReconnectRequired:
            raise
        except StravaIntegrationError:
            if has_saved_oauth:
                raise
            token = ""
    if not token:
        raise StravaReconnectRequired("Missing Strava access token. Connect Strava from Settings.")
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


def _fetch_recent_activities_with_token(token: str, per_page: int) -> list[dict]:
    safe_per_page = max(1, min(int(per_page), 200))
    query = urlencode({"page": 1, "per_page": safe_per_page})
    request = Request(
        f"{STRAVA_API_BASE_URL}/athlete/activities?{query}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_recent_runs(access_token: str | None = None, per_page: int = 30) -> list[dict]:
    """Fetch recent Strava activities and keep run-like sport types."""
    token = _get_access_token(access_token)

    try:
        activities = _fetch_recent_activities_with_token(token, per_page)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401 and access_token is None:
            logger.warning("Strava API returned 401. Attempting one forced token refresh before reconnect.")
            try:
                refreshed_token = refresh_strava_token_if_needed(force=True)
            except StravaReconnectRequired:
                raise
            except StravaIntegrationError as refresh_exc:
                clear_strava_connection(f"Strava access token is invalid. Reconnect Strava. Last response: {detail}")
                logger.exception("Strava refresh after 401 failed; reconnect required.")
                raise StravaReconnectRequired("Strava access token is invalid. Reconnect Strava from Settings.") from refresh_exc
            try:
                activities = _fetch_recent_activities_with_token(refreshed_token, per_page)
            except HTTPError as retry_exc:
                retry_detail = retry_exc.read().decode("utf-8", errors="replace")
                if retry_exc.code == 401:
                    clear_strava_connection(f"Strava access token is invalid after refresh. Reconnect Strava. Last response: {retry_detail}")
                    logger.exception("Strava 401 recovery failed; reconnect required.")
                    raise StravaReconnectRequired("Strava access token is invalid. Reconnect Strava from Settings.") from retry_exc
                raise StravaIntegrationError(f"Strava request failed with status {retry_exc.code}: {retry_detail}") from retry_exc
        else:
            if exc.code == 401:
                logger.exception("Strava request failed with 401 invalid access token.")
                raise StravaReconnectRequired("Strava access token is invalid. Reconnect Strava from Settings.") from exc
            raise StravaIntegrationError(
                f"Strava request failed with status {exc.code}: {detail}"
            ) from exc
    except StravaReconnectRequired:
        raise
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            clear_strava_connection(f"Strava access token is invalid after refresh. Reconnect Strava. Last response: {detail}")
            logger.exception("Strava request failed with 401 after refresh.")
            raise StravaReconnectRequired("Strava access token is invalid. Reconnect Strava from Settings.") from exc
        raise StravaIntegrationError(
            f"Strava request failed with status {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise StravaIntegrationError(f"Could not reach Strava: {exc.reason}") from exc
    except TimeoutError as exc:
        raise StravaIntegrationError("Strava request timed out.") from exc
    except json.JSONDecodeError as exc:
        raise StravaIntegrationError("Strava returned invalid JSON.") from exc

    runs = [
        activity
        for activity in activities
        if activity.get("sport_type") in RUN_SPORT_TYPES or activity.get("type") == "Run"
    ]
    logger.info("Fetched %s Strava activities; %s run activities after filtering.", len(activities), len(runs))
    return runs


def normalize_strava_run(activity: dict) -> dict:
    """Convert one Strava run into the app's training log schema."""
    activity_id = str(activity.get("id", "")).strip()
    distance_miles = _distance_miles(activity.get("distance"))
    duration_minutes = round(float(activity.get("moving_time") or 0) / 60, 1)
    pace = _pace_minutes_per_mile(distance_miles, activity.get("moving_time"))
    calories = round(float(activity.get("calories") or 0), 0)
    average_heart_rate = round(float(activity.get("average_heartrate") or 0), 0)
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
            f" | calories={calories}"
            f" | average_heartrate={average_heart_rate}"
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


def _save_strava_sync_state(state: dict) -> dict:
    settings = load_settings()
    current = settings.setdefault("metadata", {}).setdefault("strava_sync", {})
    current.update(state)
    save_settings(settings)
    return settings["metadata"]["strava_sync"]


def load_strava_sync_state() -> dict:
    return load_settings().get("metadata", {}).get("strava_sync", {})


def _run_activity_id(row: pd.Series) -> str:
    external_id = str(row.get("external_id", "") or "").strip()
    if external_id:
        return external_id
    note = str(row.get("notes", "") or "")
    if STRAVA_ACTIVITY_MARKER in note:
        return note.split(STRAVA_ACTIVITY_MARKER, 1)[1].split("|", 1)[0].strip()
    return str(row.get("workout_id", "") or "").strip()


def import_recent_runs(access_token: str | None = None, per_page: int = 30) -> dict:
    """Import recent Strava runs into the persisted training log."""
    try:
        runs = fetch_recent_runs(access_token=access_token, per_page=per_page)
        training_df = load_training_log()
        existing_ids = _imported_activity_ids(training_df)
        import_rows = []
        imported_count = 0
        updated_count = 0

        for run in runs:
            activity_id = str(run.get("id", "")).strip()
            if not activity_id:
                continue
            import_rows.append(normalize_strava_run(run))
            if activity_id in existing_ids:
                updated_count += 1
            else:
                imported_count += 1

        if import_rows:
            upsert_ids = {str(row["external_id"]) for row in import_rows if str(row.get("external_id", "")).strip()}
            removed_records: list[dict] = []
            if not training_df.empty:
                existing_row_ids = training_df.apply(_run_activity_id, axis=1)
                removed_records = training_df[existing_row_ids.isin(upsert_ids)].to_dict(orient="records")
                training_df = training_df[~existing_row_ids.isin(upsert_ids)].copy()
            import_df = pd.DataFrame(import_rows).reindex(columns=TRAINING_COLUMNS)
            training_df = pd.concat([training_df, import_df], ignore_index=True)
            training_df = training_df.sort_values("date", kind="stable").reset_index(drop=True)
            training_df = mark_dataframe_deletes(training_df, "training_log", removed_records)
            save_training_log(training_df)

        latest_activity_date = ""
        if import_rows:
            latest_activity_date = max(str(row.get("date", "")) for row in import_rows)
        state = _save_strava_sync_state(
            {
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
                "last_error": "",
                "last_imported_count": imported_count,
                "last_updated_count": updated_count,
                "last_fetched_count": len(runs),
                "latest_activity_date": latest_activity_date,
            }
        )
        logger.info(
            "Strava sync completed: fetched=%s imported=%s updated=%s latest_activity_date=%s",
            len(runs),
            imported_count,
            updated_count,
            latest_activity_date,
        )
        return {
            "imported_runs": imported_count,
            "updated_runs": updated_count,
            "skipped_duplicates": updated_count,
            "fetched_activities": len(runs),
            "latest_activity_date": latest_activity_date,
            "last_synced_at": state.get("last_synced_at", ""),
            "training_log": training_df,
        }
    except Exception as exc:
        _save_strava_sync_state({"last_error": str(exc), "last_synced_at": datetime.now(timezone.utc).isoformat()})
        logger.exception("Strava sync failed.")
        raise


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
