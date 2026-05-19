"""
Hevy API integration for importing workouts into the local training log.

This module intentionally uses a manual API key only. No OAuth flow is
implemented yet. Set HEVY_API_KEY in local settings, environment, or .env.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

from src.config import load_settings
from src.paths import PROJECT_ROOT, processed_data_path, raw_data_path
from src.storage import load_document, mark_dataframe_deletes, save_document
from src.training import TRAINING_COLUMNS, load_training_log, save_training_log
from src.training_schedule import classify_hevy_workout


HEVY_API_BASE_URL = "https://api.hevyapp.com"
HEVY_WORKOUT_MARKER = "hevy_workout_id="
KG_TO_LB = 2.2046226218
HEVY_DEBUG_PATH = raw_data_path("hevy_debug_latest.json")
HEVY_SYNC_STATE_PATH = processed_data_path("hevy_sync_state.json")
logger = logging.getLogger(__name__)
HEVY_SYNC_STATE_DEFAULT = {"last_sync_at": "", "last_event_cursor": "", "last_error": "", "last_result": {}}


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


class HevyIntegrationError(Exception):
    """Raised when the Hevy import flow cannot complete."""


class HevyRateLimitError(HevyIntegrationError):
    """Raised when Hevy asks us to slow down."""


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


def _get_api_key(api_key: str | None = None) -> str:
    """Read the Hevy API key from argument, local settings, environment, or .env."""
    try:
        settings_key = load_settings().get("integrations", {}).get("hevy_api_key", "")
    except Exception:
        settings_key = ""
    resolved_key = (
        (api_key or "").strip()
        or str(settings_key or "").strip()
        or os.getenv("HEVY_API_KEY", "").strip()
        or _read_dotenv_value("HEVY_API_KEY").strip()
    )
    if not resolved_key:
        raise HevyIntegrationError(
            "Missing Hevy API key. Enter a key or set HEVY_API_KEY."
        )
    return resolved_key


def is_hevy_api_configured(api_key: str | None = None) -> bool:
    """Return whether a Hevy API key can be resolved without exposing it."""
    try:
        _get_api_key(api_key)
        return True
    except HevyIntegrationError:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_webhook_secret() -> str:
    configured_secret = (
        os.getenv("HEVY_WEBHOOK_SECRET", "").strip()
        or _read_dotenv_value("HEVY_WEBHOOK_SECRET").strip()
    )
    if configured_secret:
        return configured_secret
    try:
        return _get_api_key()
    except HevyIntegrationError:
        return ""


def verify_webhook_token(headers: dict) -> bool:
    """Verify a simple shared-secret webhook header."""
    expected = get_webhook_secret()
    candidates = [
        headers.get("x-hevy-webhook-secret"),
        headers.get("x-webhook-secret"),
        headers.get("x-hevy-signature"),
        headers.get("x-api-key"),
        headers.get("authorization", "").replace("Bearer ", ""),
    ]
    return bool(expected and any(str(value or "").strip() == expected for value in candidates))


def load_hevy_sync_state() -> dict:
    try:
        state = load_document("hevy_sync_state", HEVY_SYNC_STATE_PATH, HEVY_SYNC_STATE_DEFAULT)
    except Exception as exc:
        logger.warning("Hevy sync state unavailable; using safe fallback: %s", exc)
        return {**HEVY_SYNC_STATE_DEFAULT, "last_error": str(exc), "safe_mode": True}
    if not isinstance(state, dict):
        return {**HEVY_SYNC_STATE_DEFAULT, "last_error": "Hevy sync state was malformed.", "safe_mode": True}
    return {**HEVY_SYNC_STATE_DEFAULT, **state}


def save_hevy_sync_state(updates: dict) -> dict:
    state = load_hevy_sync_state()
    state.update(updates)
    try:
        return save_document("hevy_sync_state", HEVY_SYNC_STATE_PATH, state)
    except Exception as exc:
        logger.warning("Hevy sync state could not be saved; continuing in safe mode: %s", exc)
        state["last_error"] = str(exc)
        state["safe_mode"] = True
        return state


def _parse_date(timestamp: str | None) -> str:
    """Convert a Hevy ISO timestamp into the app's YYYY-MM-DD date format."""
    if not timestamp:
        return datetime.today().date().isoformat()

    try:
        cleaned = timestamp.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date().isoformat()
    except ValueError:
        return str(timestamp)[:10]


def _duration_minutes(start_time: str | None, end_time: str | None) -> float:
    """Calculate workout duration from Hevy timestamps when available."""
    if not start_time or not end_time:
        return 0.0

    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    except ValueError:
        return 0.0

    return max((end - start).total_seconds() / 60, 0.0)


def _safe_float(value) -> float:
    """Convert optional Hevy numeric fields without crashing on blanks."""
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value) -> int:
    """Convert optional Hevy integer fields without crashing on blanks."""
    try:
        if value is None or value == "":
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _save_debug_payload(payload: dict, page: int, page_size: int) -> None:
    """Persist the latest raw Hevy response without request headers or API keys."""
    HEVY_DEBUG_PATH.parent.mkdir(parents=True, exist_ok=True)
    debug_payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "endpoint": "/v1/workouts",
        "page": page,
        "page_size": page_size,
        "workout_count": len(payload.get("workouts", []) or []),
        "payload": payload,
    }
    HEVY_DEBUG_PATH.write_text(json.dumps(debug_payload, indent=2), encoding="utf-8")


def _hevy_get(path: str, api_key: str, params: dict | None = None, retries: int = 2) -> dict:
    """GET a Hevy endpoint with small retry/rate-limit handling."""
    query = f"?{urlencode(params or {})}" if params else ""
    url = f"{HEVY_API_BASE_URL}{path}{query}"
    request = Request(url, headers={"api-key": api_key, "Accept": "application/json"})
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            if exc.code == 429:
                logger.warning("Hevy rate limit on %s: %s", path, message)
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise HevyRateLimitError("Hevy rate limit reached. Try again shortly.") from exc
            if 500 <= exc.code < 600 and attempt < retries:
                logger.warning("Hevy server error on %s, retrying: %s", path, exc.code)
                time.sleep(1.5 * (attempt + 1))
                continue
            raise HevyIntegrationError(f"Hevy request failed with status {exc.code}: {message}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt < retries:
                logger.warning("Hevy request failed on %s, retrying: %s", path, exc)
                time.sleep(1.5 * (attempt + 1))
                continue
            raise HevyIntegrationError(f"Could not reach Hevy: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise HevyIntegrationError("Hevy returned an invalid JSON response.") from exc
    raise HevyIntegrationError("Hevy request failed.")


def _fetch_workout_page(api_key: str, page: int, page_size: int) -> dict:
    """Fetch one page of recent workouts from Hevy."""
    return _hevy_get("/v1/workouts", api_key, {"page": page, "pageSize": page_size})


def fetch_workout_details(workout_id: str, api_key: str | None = None) -> dict:
    """Fetch one full Hevy workout by ID."""
    resolved_key = _get_api_key(api_key)
    logger.info("Fetching Hevy workout %s", workout_id)
    payload = _hevy_get(f"/v1/workouts/{workout_id}", resolved_key)
    workout = payload.get("workout") if isinstance(payload, dict) else None
    return workout or payload


def fetch_recent_workouts(
    api_key: str | None = None,
    page_size: int = 10,
    pages: int = 1,
    save_debug: bool = True,
) -> list[dict]:
    """
    Fetch recent workouts from Hevy.

    Hevy's public API uses an `api-key` header and caps pageSize at 10.
    """
    resolved_key = _get_api_key(api_key)
    safe_page_size = max(1, min(int(page_size), 10))
    safe_pages = max(1, min(int(pages or 1), 5))
    workouts: list[dict] = []
    latest_payload: dict = {}

    for page in range(1, safe_pages + 1):
        payload = _fetch_workout_page(resolved_key, page, safe_page_size)
        latest_payload = payload
        page_workouts = payload.get("workouts", []) or []
        workouts.extend(page_workouts)
        if len(page_workouts) < safe_page_size:
            break

    if save_debug and latest_payload:
        _save_debug_payload(latest_payload, page=min(safe_pages, max(1, len(workouts) // safe_page_size)), page_size=safe_page_size)

    return workouts


def _exercise_id(exercise: dict, exercise_index: int) -> str:
    """Return the most stable exercise identifier Hevy provides."""
    for key in ("id", "exercise_id", "exercise_template_id"):
        value = str(exercise.get(key) or "").strip()
        if value:
            return value
    title = str(exercise.get("title") or f"exercise-{exercise_index + 1}").strip()
    return title.lower().replace(" ", "-")


def _muscle_group(exercise: dict) -> str:
    """Normalize optional Hevy muscle group metadata when present."""
    for key in ("muscle_group", "muscle_groups", "primary_muscle_group"):
        value = exercise.get(key)
        if isinstance(value, list):
            return ", ".join(str(item) for item in value if item)
        if value:
            return str(value)
    return ""


def _walk_payload_dicts(value) -> list[dict]:
    if isinstance(value, dict):
        rows = [value]
        for item in value.values():
            rows.extend(_walk_payload_dicts(item))
        return rows
    if isinstance(value, list):
        rows = []
        for item in value:
            rows.extend(_walk_payload_dicts(item))
        return rows
    return []


def _cardio_metrics(workout: dict) -> dict:
    distance_miles = 0.0
    duration_minutes = 0.0
    calories = 0.0
    for item in _walk_payload_dicts(workout):
        for key, value in item.items():
            key_text = str(key).lower()
            number = _safe_float(value)
            if number <= 0:
                continue
            if key_text in {"distance_miles", "miles"}:
                distance_miles += number
            elif key_text in {"distance_km", "kilometers", "kilometres"}:
                distance_miles += number * 0.621371
            elif key_text in {"distance_m", "distance_meters", "meters", "metres"}:
                distance_miles += number / 1609.344
            elif key_text in {"duration_minutes", "minutes"}:
                duration_minutes += number
            elif key_text in {"duration_seconds", "elapsed_seconds", "moving_time", "seconds", "time_seconds"}:
                duration_minutes += number / 60
            elif key_text in {"calories", "calories_burned", "active_calories"}:
                calories += number
    return {
        "distance_miles": round(distance_miles, 2),
        "duration_minutes": round(duration_minutes, 1),
        "calories": round(calories, 0),
    }


def _append_cardio_notes(notes_parts: list[str], metrics: dict, duration: float) -> None:
    notes_parts.append("classification=running_cardio")
    distance = float(metrics.get("distance_miles") or 0)
    duration_minutes = float(metrics.get("duration_minutes") or 0) or float(duration or 0)
    calories = float(metrics.get("calories") or 0)
    if distance > 0:
        notes_parts.append(f"distance_miles={round(distance, 2)}")
    if duration_minutes > 0:
        notes_parts.append(f"cardio_duration_minutes={round(duration_minutes, 1)}")
    if distance > 0 and duration_minutes > 0:
        notes_parts.append(f"pace_min_per_mile={round(duration_minutes / distance, 2)}")
    if calories > 0:
        notes_parts.append(f"calories={round(calories)}")


def _cardio_note_parts(metrics: dict, duration: float) -> list[str]:
    parts: list[str] = []
    _append_cardio_notes(parts, metrics, duration)
    return parts


def normalize_hevy_workout(workout: dict) -> list[dict]:
    """
    Convert one Hevy workout into local training log rows.

    Each Hevy set becomes one local row with sets=1 so volume remains accurate
    even when reps or weights vary across sets.
    """
    workout_id = str(workout.get("id", "")).strip()
    workout_updated_at = str(workout.get("updated_at") or workout.get("modified_at") or workout.get("created_at") or "").strip()
    title = str(workout.get("title") or "Hevy Workout").strip()
    workout_date = _parse_date(workout.get("start_time") or workout.get("created_at"))
    classification = classify_hevy_workout(workout)
    workout_type = classification["workout_type"]
    is_cardio = bool(classification["is_run"])
    cardio_metrics = _cardio_metrics(workout) if is_cardio else {}
    duration = _duration_minutes(workout.get("start_time"), workout.get("end_time"))
    if duration <= 0 and cardio_metrics.get("duration_minutes"):
        duration = float(cardio_metrics["duration_minutes"])
    workout_description = str(workout.get("description") or "").strip()
    rows = []

    start_time = str(workout.get("start_time") or "").strip()
    end_time = str(workout.get("end_time") or "").strip()
    duration_written = False

    for exercise_index, exercise in enumerate(workout.get("exercises", []) or []):
        exercise_name = str(exercise.get("title") or "Unknown Exercise").strip()
        exercise_id = _exercise_id(exercise, exercise_index)
        exercise_notes = str(exercise.get("notes") or "").strip()
        sets = exercise.get("sets", []) or []

        for set_position, set_item in enumerate(sets):
            set_index = _safe_int(set_item.get("index") if set_item.get("index") is not None else set_position)
            weight_kg = _safe_float(set_item.get("weight_kg"))
            external_id = f"{workout_id}:{exercise_id}:{set_index}"
            notes_parts = [
                "Imported from Hevy",
                f"{HEVY_WORKOUT_MARKER}{workout_id}",
                f"hevy_exercise_id={exercise_id}",
                f"set_index={set_index}",
                f"workout_title={title}",
                f"start_time={start_time}",
                f"end_time={end_time}",
                "weight_unit=lb",
            ]
            if is_cardio:
                notes_parts.append(f"classification_reason={','.join(classification.get('reasons') or ['cardio_signal'])}")
                notes_parts.append(f"planned_workout={classification.get('planned', {}).get('display_label', '')}")
                if not duration_written:
                    _append_cardio_notes(notes_parts, cardio_metrics, duration)
            if weight_kg:
                notes_parts.append(f"source_weight_kg={round(weight_kg, 4)}")
            if set_item.get("type"):
                notes_parts.append(f"set_type={set_item.get('type')}")
            if workout_description:
                notes_parts.append(f"workout_notes={workout_description}")
            if exercise_notes:
                notes_parts.append(f"exercise_notes={exercise_notes}")

            rows.append(
                {
                    "workout_id": workout_id,
                    "date": workout_date,
                    "workout_type": workout_type,
                    "muscle_group": "Cardio" if is_cardio else _muscle_group(exercise),
                    "exercise": exercise_name,
                    "set_number": set_index + 1,
                    "sets": 0 if is_cardio else 1,
                    "reps": 0 if is_cardio else _safe_int(set_item.get("reps")),
                    "weight": 0.0 if is_cardio else round(weight_kg * KG_TO_LB, 2) if weight_kg else 0.0,
                    "rpe": _safe_float(set_item.get("rpe")),
                    "duration_minutes": duration if not duration_written else 0.0,
                    "notes": " | ".join(notes_parts),
                    "source": "hevy",
                    "external_id": external_id,
                    "hevy_workout_id": workout_id,
                    "updated_at": workout_updated_at,
                    "sync_source": "hevy_import",
                    "last_hevy_sync_at": _now_iso(),
                }
            )
            duration_written = True

    # If Hevy returns a workout without exercises, keep a workout-level row.
    if not rows:
        rows.append(
            {
                "workout_id": workout_id,
                "date": workout_date,
                "workout_type": workout_type,
                "muscle_group": "Cardio" if is_cardio else "",
                "exercise": title,
                "set_number": 1,
                "sets": 0,
                "reps": 0,
                "weight": 0.0,
                "rpe": 0.0,
                "duration_minutes": duration,
                "notes": " | ".join(
                    [
                        "Imported from Hevy",
                        f"{HEVY_WORKOUT_MARKER}{workout_id}",
                        f"workout_title={title}",
                        f"start_time={start_time}",
                        f"end_time={end_time}",
                        "weight_unit=lb",
                        *(
                            [
                                f"classification_reason={','.join(classification.get('reasons') or ['cardio_signal'])}",
                                f"planned_workout={classification.get('planned', {}).get('display_label', '')}",
                                *_cardio_note_parts(cardio_metrics, duration),
                            ]
                            if is_cardio
                            else []
                        ),
                    ]
                ),
                "source": "hevy",
                "external_id": f"{workout_id}:workout",
                "hevy_workout_id": workout_id,
                "updated_at": workout.get("updated_at") or workout.get("created_at") or "",
                "sync_source": "hevy_import",
                "last_hevy_sync_at": _now_iso(),
            }
        )

    return rows


def _row_hevy_workout_id(row: pd.Series | dict) -> str:
    explicit = str(row.get("hevy_workout_id", "") or "").strip()
    if explicit:
        return explicit
    return _extract_note_value(str(row.get("notes", "") or ""), "hevy_workout_id")


def upsert_hevy_workout(workout: dict, sync_source: str = "manual_import") -> dict:
    """Idempotently replace local rows for one Hevy workout."""
    workout_id = str(workout.get("id", "") or "").strip()
    if not workout_id:
        raise HevyIntegrationError("Cannot upsert Hevy workout without an ID.")
    rows = normalize_hevy_workout(workout)
    now = _now_iso()
    for row in rows:
        row["sync_source"] = sync_source
        row["last_hevy_sync_at"] = now
        row["hevy_workout_id"] = workout_id

    training_df = load_training_log()
    before_rows = len(training_df)
    removed_records: list[dict] = []
    if training_df.empty:
        kept_df = training_df
    else:
        mask = training_df.apply(lambda row: _row_hevy_workout_id(row) != workout_id, axis=1)
        removed_records = training_df.loc[~mask].to_dict(orient="records")
        kept_df = training_df[mask].copy()
    removed_rows = before_rows - len(kept_df)
    if removed_rows:
        logger.info("Prevented duplicates by replacing %s existing rows for Hevy workout %s", removed_rows, workout_id)
    import_df = pd.DataFrame(rows).reindex(columns=TRAINING_COLUMNS)
    training_df = pd.concat([kept_df, import_df], ignore_index=True).sort_values("date", kind="stable").reset_index(drop=True)
    training_df = mark_dataframe_deletes(training_df, "training_log", removed_records)
    save_training_log(training_df)
    logger.info("Saved Hevy workout %s with %s rows via %s", workout_id, len(rows), sync_source)
    return {"workout_id": workout_id, "saved_rows": len(rows), "replaced_rows": removed_rows, "training_log": training_df}


def delete_hevy_workout(workout_id: str, sync_source: str = "hevy_delete") -> dict:
    training_df = load_training_log()
    if training_df.empty:
        return {"workout_id": workout_id, "deleted_rows": 0, "training_log": training_df}
    before_rows = len(training_df)
    keep_mask = training_df.apply(lambda row: _row_hevy_workout_id(row) != str(workout_id), axis=1)
    removed_records = training_df.loc[~keep_mask].to_dict(orient="records")
    kept_df = training_df[keep_mask].copy()
    deleted_rows = before_rows - len(kept_df)
    if deleted_rows:
        kept_df = mark_dataframe_deletes(kept_df, "training_log", removed_records)
        save_training_log(kept_df)
        logger.info("Deleted %s rows for Hevy workout %s via %s", deleted_rows, workout_id, sync_source)
    return {"workout_id": workout_id, "deleted_rows": deleted_rows, "training_log": kept_df}


def _extract_note_value(note: str, key: str) -> str:
    marker = f"{key}="
    if marker not in note:
        return ""
    return note.split(marker, 1)[1].split("|", 1)[0].strip()


def _duplicate_state(training_df: pd.DataFrame) -> tuple[set[str], set[tuple[str, str, str]]]:
    """Return imported Hevy workout IDs and row keys from the local log."""
    if training_df.empty:
        return set(), set()

    imported_workout_ids: set[str] = set()
    row_keys: set[tuple[str, str, str]] = set()
    for _, row in training_df.iterrows():
        note = str(row.get("notes", "") or "")
        source = str(row.get("source", "") or "").lower()
        external_id = str(row.get("external_id", "") or "").strip()
        if HEVY_WORKOUT_MARKER not in note:
            if source == "hevy" and external_id:
                row_keys.add((external_id, str(row.get("exercise", "")), str(row.get("date", ""))))
            continue

        workout_id = _extract_note_value(note, "hevy_workout_id")
        if workout_id:
            imported_workout_ids.add(workout_id)
        if not external_id and workout_id:
            set_index = _extract_note_value(note, "set_index")
            external_id = f"{workout_id}:{row.get('exercise', '')}:{set_index}"
        if external_id:
            row_keys.add((external_id, str(row.get("exercise", "")), str(row.get("date", ""))))

    return imported_workout_ids, row_keys


def _row_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("external_id", "") or "").strip(),
        str(row.get("exercise", "") or "").strip().lower(),
        str(row.get("date", "") or "").strip(),
    )


def preview_hevy_import(api_key: str | None = None, page_size: int = 10, pages: int = 1) -> dict:
    """Fetch and normalize recent Hevy workouts without saving them."""
    workouts = fetch_recent_workouts(api_key=api_key, page_size=page_size, pages=pages)
    training_df = load_training_log()
    existing_workout_ids, existing_row_keys = _duplicate_state(training_df)
    preview_workouts = []
    total_rows = 0
    duplicate_rows = 0
    warnings = []

    for workout in workouts:
        workout_id = str(workout.get("id", "") or "").strip()
        rows = normalize_hevy_workout(workout)
        row_keys = [_row_key(row) for row in rows]
        workout_duplicate = bool(workout_id and workout_id in existing_workout_ids)
        row_duplicate_count = len(rows) if workout_duplicate else sum(1 for key in row_keys if key in existing_row_keys)
        exercise_names = sorted({row["exercise"] for row in rows if row.get("exercise")})

        if not workout_id:
            warnings.append("A workout was skipped in preview because it did not include an ID.")

        total_rows += len(rows)
        duplicate_rows += row_duplicate_count
        preview_workouts.append(
            {
                "workout_id": workout_id,
                "title": str(workout.get("title") or "Hevy Workout"),
                "date": _parse_date(workout.get("start_time") or workout.get("created_at")),
                "exercise_names": exercise_names,
                "estimated_rows": len(rows),
                "duplicate": workout_duplicate,
                "duplicate_rows": row_duplicate_count,
                "new_rows": 0 if workout_duplicate else max(len(rows) - row_duplicate_count, 0),
            }
        )

    return {
        "status": "ok",
        "workouts": preview_workouts,
        "estimated_rows": total_rows,
        "duplicates_detected": duplicate_rows,
        "debug_file": _display_path(HEVY_DEBUG_PATH),
        "warnings": warnings,
    }


def import_hevy_workouts(api_key: str | None = None, page_size: int = 10, pages: int = 1) -> dict:
    """
    Fetch recent Hevy workouts and append new rows to training_log.csv.

    Duplicate imports are prevented with the Hevy workout ID plus per-set
    external IDs, exercise name, and date.
    """
    workouts = fetch_recent_workouts(api_key=api_key, page_size=page_size, pages=pages)
    training_df = load_training_log()
    imported_workouts = 0
    imported_rows = 0
    replaced_rows = 0
    skipped_workouts = []
    failures = []

    for workout in workouts:
        workout_id = str(workout.get("id", "")).strip()
        if not workout_id:
            skipped_workouts.append("missing-id")
            continue

        try:
            result = upsert_hevy_workout(workout, sync_source="manual_import")
            imported_workouts += 1
            imported_rows += result["saved_rows"]
            replaced_rows += result["replaced_rows"]
            training_df = result["training_log"]
        except Exception as exc:
            logger.exception("Hevy workout import failed for %s", workout_id)
            failures.append(f"{workout_id}: {exc}")

    save_hevy_sync_state({"last_sync_at": _now_iso(), "last_error": "", "last_result": {"source": "manual_import", "imported_workouts": imported_workouts}})
    return {
        "imported_workouts": imported_workouts,
        "imported_rows": imported_rows,
        "skipped_duplicates": replaced_rows,
        "skipped_workouts": skipped_workouts,
        "failures": failures,
        "debug_file": _display_path(HEVY_DEBUG_PATH),
        "training_log": training_df,
        "last_synced_at": load_hevy_sync_state().get("last_sync_at", ""),
    }


def _event_workout_id(event: dict) -> str:
    for key in ["workout_id", "workoutId", "id"]:
        value = str(event.get(key) or "").strip()
        if value:
            return value
    workout = event.get("workout") if isinstance(event.get("workout"), dict) else {}
    return str(workout.get("id") or "").strip()


def _event_type(event: dict) -> str:
    return str(event.get("type") or event.get("event") or event.get("action") or "").lower()


def fetch_workout_events(api_key: str | None = None, since: str | None = None) -> dict:
    """Fetch Hevy workout events for polling fallback."""
    resolved_key = _get_api_key(api_key)
    params = {}
    if since:
        params["since"] = since
    logger.info("Fetching Hevy workout events since %s", since or "beginning")
    return _hevy_get("/v1/workouts/events", resolved_key, params)


def sync_hevy_events(api_key: str | None = None) -> dict:
    """Poll Hevy workout events and upsert changed workouts."""
    state = load_hevy_sync_state()
    since = state.get("last_sync_at") or state.get("last_event_cursor") or ""
    try:
        payload = fetch_workout_events(api_key=api_key, since=since)
        events = payload.get("events") or payload.get("workout_events") or payload.get("workouts") or []
        saved = 0
        deleted = 0
        failures = []
        training_df = load_training_log()
        for event in events:
            workout_id = _event_workout_id(event)
            if not workout_id:
                continue
            event_type = _event_type(event)
            if "delete" in event_type or event.get("deleted") is True:
                result = delete_hevy_workout(workout_id, sync_source="event_poll_delete")
                deleted += result["deleted_rows"]
                training_df = result["training_log"]
                continue
            try:
                workout = fetch_workout_details(workout_id, api_key=api_key)
                logger.info("Workout fetched from Hevy events: %s", workout_id)
                result = upsert_hevy_workout(workout, sync_source="event_poll")
                saved += 1
                training_df = result["training_log"]
            except HevyIntegrationError as exc:
                logger.warning("Hevy event sync failure for %s: %s", workout_id, exc)
                failures.append(f"{workout_id}: {exc}")
        now = _now_iso()
        next_cursor = str(payload.get("next_cursor") or payload.get("cursor") or now)
        sync_result = {"status": "ok", "events": len(events), "saved_workouts": saved, "deleted_rows": deleted, "failures": failures}
        save_hevy_sync_state({"last_sync_at": now, "last_event_cursor": next_cursor, "last_error": "", "last_result": sync_result})
        return {**sync_result, "last_synced_at": now, "training_log": training_df}
    except HevyIntegrationError as exc:
        logger.warning("Hevy event sync failed: %s", exc)
        save_hevy_sync_state({"last_error": str(exc), "last_result": {"status": "error"}})
        raise


def sync_single_hevy_workout(workout_id: str, sync_source: str = "webhook") -> dict:
    workout = fetch_workout_details(workout_id)
    logger.info("Workout fetched from Hevy webhook/manual refresh: %s", workout_id)
    result = upsert_hevy_workout(workout, sync_source=sync_source)
    save_hevy_sync_state({"last_sync_at": _now_iso(), "last_error": "", "last_result": {"source": sync_source, "workout_id": workout_id}})
    return result


def handle_hevy_webhook(payload: dict) -> dict:
    """Handle one Hevy webhook payload."""
    logger.info("Hevy webhook received: %s", {key: payload.get(key) for key in ["type", "event", "workout_id", "workoutId", "id"]})
    workout_id = _event_workout_id(payload)
    if not workout_id:
        raise HevyIntegrationError("Webhook did not include a workout ID.")
    event_type = _event_type(payload)
    if "delete" in event_type or payload.get("deleted") is True:
        result = delete_hevy_workout(workout_id, sync_source="webhook_delete")
        save_hevy_sync_state({"last_sync_at": _now_iso(), "last_error": "", "last_result": {"source": "webhook_delete", "workout_id": workout_id}})
        return {"status": "ok", "action": "deleted", **result}
    result = sync_single_hevy_workout(workout_id, sync_source="webhook")
    return {"status": "ok", "action": "upserted", **result}
