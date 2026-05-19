"""
Training module for logging and analyzing workouts.

This module handles:
- Logging workout data (exercises, sets, reps, weight)
- Tracking training volume and intensity
- Workout history and analytics
"""

import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.paths import processed_data_path
from src.storage import count_dataframe_rows, load_dataframe, load_dataframe_recent, load_document, mark_dataframe_deletes, save_dataframe, save_document
from src.training_schedule import is_run_row, load_training_schedule_profile

TRAINING_COLUMNS = [
    "workout_id",
    "date",
    "workout_type",
    "muscle_group",
    "exercise",
    "set_number",
    "sets",
    "reps",
    "weight",
    "rpe",
    "duration_minutes",
    "notes",
    "source",
    "external_id",
    "hevy_workout_id",
    "updated_at",
    "sync_source",
    "last_hevy_sync_at",
]

TRAINING_LOG_PATH = processed_data_path("training_log.csv")
RAW_HEVY_WORKOUTS_PATH = processed_data_path("raw_hevy_workouts.csv")
RAW_HEVY_SETS_PATH = processed_data_path("raw_hevy_sets.csv")
WEEKLY_TRAINING_SUMMARY_PATH = processed_data_path("weekly_training_summary.csv")
MONTHLY_TRAINING_SUMMARY_PATH = processed_data_path("monthly_training_summary.csv")
EXERCISE_PR_HISTORY_PATH = processed_data_path("exercise_pr_history.csv")
MUSCLE_GROUP_VOLUME_HISTORY_PATH = processed_data_path("muscle_group_volume_history.csv")
TRAINING_SUMMARY_STATE_PATH = processed_data_path("training_summary_state.json")
TRAINING_CACHE_METADATA_PATH = processed_data_path("training_cache_metadata.json")

RAW_HEVY_WORKOUT_COLUMNS = [
    "hevy_workout_id",
    "title",
    "date",
    "start_time",
    "end_time",
    "created_at",
    "updated_at",
    "duration_minutes",
    "workout_type",
    "exercise_count",
    "set_count",
    "normalized_row_count",
    "raw_payload",
    "imported_at",
    "normalized_at",
]

RAW_HEVY_SET_COLUMNS = [
    "external_id",
    "hevy_workout_id",
    "date",
    "workout_title",
    "exercise_id",
    "exercise",
    "set_index",
    "set_number",
    "reps",
    "weight_kg",
    "weight_lb",
    "rpe",
    "duration_seconds",
    "distance_meters",
    "raw_payload",
    "imported_at",
]

TRAINING_SUMMARY_COLUMNS = [
    "period_start",
    "period_end",
    "period_label",
    "workout_count",
    "total_sets",
    "hard_sets",
    "total_reps",
    "total_volume",
    "duration_minutes",
    "training_frequency_per_week",
    "volume_by_muscle_group",
    "hard_sets_by_muscle_group",
    "top_exercises",
    "best_set_by_exercise",
    "best_estimated_1rm_by_exercise",
    "prs",
    "source_counts",
    "latest_workout_date",
]

EXERCISE_PR_HISTORY_COLUMNS = [
    "exercise",
    "date",
    "workout_id",
    "estimated_1rm",
    "weight",
    "reps",
    "source",
    "period_start",
]

MUSCLE_GROUP_VOLUME_HISTORY_COLUMNS = [
    "period_type",
    "period_start",
    "period_end",
    "period_label",
    "muscle_group",
    "workout_count",
    "total_sets",
    "hard_sets",
    "total_reps",
    "total_volume",
    "latest_workout_date",
]


def training_raw_window_days() -> int:
    """Return the live raw set-level training window."""
    try:
        return max(30, min(int(os.getenv("TRAINING_RAW_WINDOW_DAYS", "180")), 730))
    except ValueError:
        return 180


def _default_training_summary_state() -> dict:
    return {
        "last_rebuilt_at": "",
        "cutoff_days": training_raw_window_days(),
        "cutoff_date": "",
        "raw_rows_total": 0,
        "raw_rows_summarized": 0,
        "weekly_summaries": 0,
        "monthly_summaries": 0,
        "exercise_prs": 0,
        "muscle_group_periods": 0,
    }


def _default_training_cache_metadata() -> dict:
    return {
        "last_hevy_sync": "",
        "last_cache_refresh": "",
        "raw_workout_count": 0,
        "raw_set_count": 0,
        "normalized_workout_count": 0,
        "normalized_set_count": 0,
        "recent_raw_rows": 0,
        "summary_weeks": 0,
        "summary_months": 0,
        "exercise_prs": 0,
        "muscle_group_periods": 0,
        "raw_window_days": training_raw_window_days(),
        "cache_health": "unknown",
    }


def load_training_summary_state() -> dict:
    state = _default_training_summary_state()
    state.update(load_document("training_summary_state", TRAINING_SUMMARY_STATE_PATH, state))
    return state


def save_training_summary_state(state: dict) -> dict:
    payload = _default_training_summary_state()
    payload.update(state or {})
    return save_document("training_summary_state", TRAINING_SUMMARY_STATE_PATH, payload)


def load_training_cache_metadata() -> dict:
    metadata = _default_training_cache_metadata()
    metadata.update(load_document("training_cache_metadata", TRAINING_CACHE_METADATA_PATH, metadata))
    return metadata


def save_training_cache_metadata(metadata: dict) -> dict:
    payload = _default_training_cache_metadata()
    payload.update(metadata or {})
    return save_document("training_cache_metadata", TRAINING_CACHE_METADATA_PATH, payload)


def _empty_training_log() -> pd.DataFrame:
    """Return an empty training log with the expected columns."""
    return pd.DataFrame(columns=TRAINING_COLUMNS)


def _extract_note_value(note: str, key: str) -> str:
    """Extract a pipe-delimited key=value marker from imported workout notes."""
    marker = f"{key}="
    if marker not in note:
        return ""
    return note.split(marker, 1)[1].split("|", 1)[0].strip()


def _missing_number(value) -> bool:
    """Return True when a numeric field is blank, zero, or invalid."""
    parsed = pd.to_numeric(value, errors="coerce")
    return pd.isna(parsed) or float(parsed) == 0


def _hydrate_legacy_import_metadata(training_df: pd.DataFrame) -> pd.DataFrame:
    """Backfill source/external_id and fix older Hevy kg rows for analytics.

    Early Hevy imports stored the API's `weight_kg` directly in the app's
    pound-based training log. We convert only rows that still carry the old
    Hevy note marker and do not yet have a weight-unit marker, so saved rows
    are not converted repeatedly.
    """
    if training_df.empty:
        return training_df

    df = training_df.copy()
    profile = load_training_schedule_profile()
    for index, row in df.iterrows():
        note = str(row.get("notes", ""))
        source = str(row.get("source", "") or "").strip().lower()

        if "hevy_workout_id=" in note:
            workout_id = _extract_note_value(note, "hevy_workout_id")
            set_index = _extract_note_value(note, "set_index") or str(index)
            exercise = str(row.get("exercise", "") or "").strip()

            if workout_id and not str(row.get("workout_id", "") or "").strip():
                df.at[index, "workout_id"] = workout_id
            if _missing_number(row.get("set_number", 0)):
                df.at[index, "set_number"] = int(float(set_index or 0)) + 1
            if not source:
                df.at[index, "source"] = "hevy"
            if not str(row.get("external_id", "") or "").strip() and workout_id:
                df.at[index, "external_id"] = f"{workout_id}:{exercise}:{set_index}"

            if "weight_unit=lb" not in note:
                weight = pd.to_numeric(row.get("weight", 0), errors="coerce")
                if pd.notna(weight) and float(weight) > 0:
                    df.at[index, "weight"] = round(float(weight) * 2.2046226218, 2)
                    df.at[index, "notes"] = f"{note} | legacy_weight_converted_kg_to_lb=true | weight_unit=lb"

            if is_run_row(df.loc[index].to_dict(), profile=profile):
                df.at[index, "workout_type"] = "Run"
                df.at[index, "muscle_group"] = "Cardio"
                if "classification=running_cardio" not in str(df.at[index, "notes"]).lower():
                    df.at[index, "notes"] = f"{df.at[index, 'notes']} | classification=running_cardio"

        if "strava_activity_id=" in note:
            activity_id = _extract_note_value(note, "strava_activity_id")
            if activity_id and not str(row.get("workout_id", "") or "").strip():
                df.at[index, "workout_id"] = activity_id
            if _missing_number(row.get("set_number", 0)):
                df.at[index, "set_number"] = 1
            if not source:
                df.at[index, "source"] = "strava"
            if not str(row.get("external_id", "") or "").strip() and activity_id:
                df.at[index, "external_id"] = activity_id

        if not str(df.at[index, "workout_id"] or "").strip():
            date = str(row.get("date", "") or "").strip()
            df.at[index, "workout_id"] = f"manual-{date}-{index}"
        if _missing_number(df.at[index, "set_number"]):
            df.at[index, "set_number"] = 1

    return df


def _normalize_training_log(training_df: pd.DataFrame) -> pd.DataFrame:
    for column in TRAINING_COLUMNS:
        if column not in training_df.columns:
            training_df[column] = np.nan

    training_df = training_df[TRAINING_COLUMNS]

    for column in ["set_number", "sets", "reps", "weight", "rpe", "duration_minutes"]:
        training_df[column] = pd.to_numeric(training_df[column], errors="coerce").fillna(0)

    for column in [
        "workout_id",
        "date",
        "workout_type",
        "muscle_group",
        "exercise",
        "notes",
        "source",
        "external_id",
        "hevy_workout_id",
        "updated_at",
        "sync_source",
        "last_hevy_sync_at",
    ]:
        training_df[column] = training_df[column].fillna("").astype(str)

    return _hydrate_legacy_import_metadata(training_df)


def recent_training_window(training_df: pd.DataFrame | None, days: int = 365) -> pd.DataFrame:
    """Return a date-clean recent training window for live analytics."""
    if training_df is None or training_df.empty or "date" not in training_df.columns:
        return pd.DataFrame(columns=TRAINING_COLUMNS)
    df = training_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return pd.DataFrame(columns=TRAINING_COLUMNS)
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=max(int(days), 0))
    df = df[df["date"] >= cutoff].copy()
    df["date"] = df["date"].dt.date.astype(str)
    for column in TRAINING_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    return df[TRAINING_COLUMNS]


def load_training_log() -> pd.DataFrame:
    """Load training entries from local CSV/Postgres."""
    return _normalize_training_log(load_dataframe("training_log", TRAINING_LOG_PATH, TRAINING_COLUMNS))


def load_recent_training_log(days: int = 365, max_rows: int = 20000, statement_timeout_ms: int | None = None) -> pd.DataFrame:
    """Load a bounded recent training slice for live dashboard/goal analytics."""
    return _normalize_training_log(load_dataframe_recent("training_log", TRAINING_LOG_PATH, TRAINING_COLUMNS, days=days, max_rows=max_rows, statement_timeout_ms=statement_timeout_ms))


def load_live_training_log(days: int | None = None, max_rows: int = 20000, statement_timeout_ms: int | None = None) -> pd.DataFrame:
    """Load raw set-level rows that are safe for live UI/analytics paths."""
    window_days = training_raw_window_days() if days is None else max(1, min(int(days), training_raw_window_days()))
    return load_recent_training_log(days=window_days, max_rows=max_rows, statement_timeout_ms=statement_timeout_ms)


def save_training_log(df) -> None:
    """Save training entries to local CSV."""
    save_dataframe("training_log", TRAINING_LOG_PATH, df, TRAINING_COLUMNS)


def load_raw_hevy_workouts() -> pd.DataFrame:
    """Load raw Hevy workout payload metadata imported during sync."""
    return load_dataframe("raw_hevy_workouts", RAW_HEVY_WORKOUTS_PATH, RAW_HEVY_WORKOUT_COLUMNS)


def save_raw_hevy_workouts(df: pd.DataFrame) -> None:
    save_dataframe("raw_hevy_workouts", RAW_HEVY_WORKOUTS_PATH, df, RAW_HEVY_WORKOUT_COLUMNS)


def load_raw_hevy_sets() -> pd.DataFrame:
    """Load raw Hevy set payload metadata imported during sync."""
    return load_dataframe("raw_hevy_sets", RAW_HEVY_SETS_PATH, RAW_HEVY_SET_COLUMNS)


def save_raw_hevy_sets(df: pd.DataFrame) -> None:
    save_dataframe("raw_hevy_sets", RAW_HEVY_SETS_PATH, df, RAW_HEVY_SET_COLUMNS)


def _json_payload(value) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _number_or_none(value) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _number_or_zero(value) -> float:
    parsed = _number_or_none(value)
    return 0.0 if parsed is None else parsed


def _raw_hevy_workout_record(workout: dict, normalized_rows: list[dict], imported_at: str) -> dict:
    workout_id = str(workout.get("id", "") or "").strip()
    start_time = str(workout.get("start_time") or "").strip()
    end_time = str(workout.get("end_time") or "").strip()
    exercises = workout.get("exercises", []) or []
    return {
        "hevy_workout_id": workout_id,
        "title": str(workout.get("title") or "Hevy Workout"),
        "date": str(normalized_rows[0].get("date") if normalized_rows else "") or str(workout.get("created_at") or "")[:10],
        "start_time": start_time,
        "end_time": end_time,
        "created_at": str(workout.get("created_at") or ""),
        "updated_at": str(workout.get("updated_at") or workout.get("modified_at") or ""),
        "duration_minutes": float(normalized_rows[0].get("duration_minutes") or 0) if normalized_rows else 0,
        "workout_type": str(normalized_rows[0].get("workout_type") if normalized_rows else ""),
        "exercise_count": len(exercises),
        "set_count": sum(len(exercise.get("sets", []) or []) for exercise in exercises if isinstance(exercise, dict)),
        "normalized_row_count": len(normalized_rows),
        "raw_payload": _json_payload(workout),
        "imported_at": imported_at,
        "normalized_at": imported_at,
    }


def _raw_hevy_set_records(workout: dict, normalized_rows: list[dict], imported_at: str) -> list[dict]:
    workout_id = str(workout.get("id", "") or "").strip()
    workout_title = str(workout.get("title") or "Hevy Workout")
    workout_date = str(normalized_rows[0].get("date") if normalized_rows else "") or str(workout.get("created_at") or "")[:10]
    by_external_id = {str(row.get("external_id", "") or ""): row for row in normalized_rows}
    records: list[dict] = []
    for exercise_index, exercise in enumerate(workout.get("exercises", []) or []):
        if not isinstance(exercise, dict):
            continue
        exercise_name = str(exercise.get("title") or "Unknown Exercise")
        exercise_id = ""
        for key in ("id", "exercise_id", "exercise_template_id"):
            exercise_id = str(exercise.get(key) or "").strip()
            if exercise_id:
                break
        if not exercise_id:
            exercise_id = exercise_name.lower().replace(" ", "-") or f"exercise-{exercise_index + 1}"
        for set_position, set_item in enumerate(exercise.get("sets", []) or []):
            if not isinstance(set_item, dict):
                continue
            try:
                set_index = int(float(set_item.get("index") if set_item.get("index") is not None else set_position))
            except (TypeError, ValueError):
                set_index = set_position
            external_id = f"{workout_id}:{exercise_id}:{set_index}"
            normalized = by_external_id.get(external_id, {})
            weight_kg = _number_or_none(set_item.get("weight_kg"))
            weight_lb = _number_or_none(normalized.get("weight"))
            records.append(
                {
                    "external_id": external_id,
                    "hevy_workout_id": workout_id,
                    "date": workout_date,
                    "workout_title": workout_title,
                    "exercise_id": exercise_id,
                    "exercise": exercise_name,
                    "set_index": set_index,
                    "set_number": int(normalized.get("set_number") or set_index + 1),
                    "reps": int(_number_or_zero(set_item.get("reps"))),
                    "weight_kg": weight_kg,
                    "weight_lb": weight_lb,
                    "rpe": _number_or_zero(set_item.get("rpe")),
                    "duration_seconds": _number_or_zero(set_item.get("duration_seconds")),
                    "distance_meters": _number_or_zero(set_item.get("distance_meters")),
                    "raw_payload": _json_payload(set_item),
                    "imported_at": imported_at,
                }
            )
    if records:
        return records
    return [
        {
            "external_id": f"{workout_id}:workout",
            "hevy_workout_id": workout_id,
            "date": workout_date,
            "workout_title": workout_title,
            "exercise_id": "workout",
            "exercise": workout_title,
            "set_index": 0,
            "set_number": 1,
            "reps": 0,
            "weight_kg": None,
            "weight_lb": None,
            "rpe": 0,
            "duration_seconds": 0,
            "distance_meters": 0,
            "raw_payload": _json_payload(workout),
            "imported_at": imported_at,
        }
    ]


def upsert_raw_hevy_import(workout: dict, normalized_rows: list[dict], imported_at: str | None = None) -> dict:
    """Persist raw Hevy workout/set payloads idempotently for export/debugging."""
    workout_id = str(workout.get("id", "") or "").strip()
    if not workout_id:
        return {"raw_workouts_saved": 0, "raw_sets_saved": 0, "raw_sets_replaced": 0}
    now = imported_at or datetime.now(timezone.utc).isoformat()
    workout_record = _raw_hevy_workout_record(workout, normalized_rows, now)
    set_records = _raw_hevy_set_records(workout, normalized_rows, now)

    workouts_df = load_raw_hevy_workouts()
    if not workouts_df.empty:
        workouts_df = workouts_df[workouts_df["hevy_workout_id"].fillna("").astype(str) != workout_id].copy()
    workouts_df = pd.concat([workouts_df, pd.DataFrame([workout_record])], ignore_index=True)
    workouts_df = workouts_df.sort_values("date", kind="stable").reset_index(drop=True)
    save_raw_hevy_workouts(workouts_df)

    sets_df = load_raw_hevy_sets()
    replaced = 0
    if not sets_df.empty:
        keep_mask = sets_df["hevy_workout_id"].fillna("").astype(str) != workout_id
        replaced = int((~keep_mask).sum())
        sets_df = sets_df[keep_mask].copy()
    sets_df = pd.concat([sets_df, pd.DataFrame(set_records)], ignore_index=True)
    sets_df = sets_df.sort_values(["date", "hevy_workout_id", "set_number"], kind="stable").reset_index(drop=True)
    save_raw_hevy_sets(sets_df)
    return {"raw_workouts_saved": 1, "raw_sets_saved": len(set_records), "raw_sets_replaced": replaced}


def delete_raw_hevy_import(workout_id: str) -> dict:
    """Delete raw Hevy cache rows for one workout when a webhook reports deletion."""
    workout_id = str(workout_id or "").strip()
    if not workout_id:
        return {"raw_workouts_deleted": 0, "raw_sets_deleted": 0}
    workouts_df = load_raw_hevy_workouts()
    sets_df = load_raw_hevy_sets()
    workouts_deleted = 0
    sets_deleted = 0
    if not workouts_df.empty:
        keep = workouts_df["hevy_workout_id"].fillna("").astype(str) != workout_id
        workouts_deleted = int((~keep).sum())
        save_raw_hevy_workouts(workouts_df[keep].copy())
    if not sets_df.empty:
        keep = sets_df["hevy_workout_id"].fillna("").astype(str) != workout_id
        sets_deleted = int((~keep).sum())
        save_raw_hevy_sets(sets_df[keep].copy())
    return {"raw_workouts_deleted": workouts_deleted, "raw_sets_deleted": sets_deleted}


def refresh_training_cache_metadata(last_hevy_sync: str = "") -> dict:
    """Refresh cheap cache counts used by the UI and diagnostics."""
    raw_window_days = training_raw_window_days()
    weekly_count = count_dataframe_rows("weekly_training_summary", WEEKLY_TRAINING_SUMMARY_PATH)
    monthly_count = count_dataframe_rows("monthly_training_summary", MONTHLY_TRAINING_SUMMARY_PATH)
    metadata = {
        "last_hevy_sync": last_hevy_sync or load_training_cache_metadata().get("last_hevy_sync", ""),
        "last_cache_refresh": datetime.now(timezone.utc).isoformat(),
        "raw_workout_count": count_dataframe_rows("raw_hevy_workouts", RAW_HEVY_WORKOUTS_PATH),
        "raw_set_count": count_dataframe_rows("raw_hevy_sets", RAW_HEVY_SETS_PATH),
        "normalized_set_count": count_dataframe_rows("training_log", TRAINING_LOG_PATH),
        "recent_raw_rows": int(len(load_live_training_log(days=raw_window_days, max_rows=100000))),
        "summary_weeks": weekly_count,
        "summary_months": monthly_count,
        "exercise_prs": count_dataframe_rows("exercise_pr_history", EXERCISE_PR_HISTORY_PATH),
        "muscle_group_periods": count_dataframe_rows("muscle_group_volume_history", MUSCLE_GROUP_VOLUME_HISTORY_PATH),
        "raw_window_days": raw_window_days,
    }
    try:
        live = load_live_training_log(days=raw_window_days, max_rows=100000)
        workout_count = int(live["workout_id"].fillna("").astype(str).str.strip().replace("", pd.NA).dropna().nunique()) if not live.empty else 0
    except Exception:
        workout_count = 0
    metadata["normalized_workout_count"] = workout_count
    metadata["cache_health"] = "ready" if metadata["normalized_set_count"] or metadata["raw_set_count"] else "empty"
    return save_training_cache_metadata(metadata)


def load_weekly_training_summary() -> pd.DataFrame:
    return load_dataframe("weekly_training_summary", WEEKLY_TRAINING_SUMMARY_PATH, TRAINING_SUMMARY_COLUMNS)


def save_weekly_training_summary(df: pd.DataFrame) -> None:
    save_dataframe("weekly_training_summary", WEEKLY_TRAINING_SUMMARY_PATH, df, TRAINING_SUMMARY_COLUMNS)


def load_monthly_training_summary() -> pd.DataFrame:
    return load_dataframe("monthly_training_summary", MONTHLY_TRAINING_SUMMARY_PATH, TRAINING_SUMMARY_COLUMNS)


def save_monthly_training_summary(df: pd.DataFrame) -> None:
    save_dataframe("monthly_training_summary", MONTHLY_TRAINING_SUMMARY_PATH, df, TRAINING_SUMMARY_COLUMNS)


def load_exercise_pr_history() -> pd.DataFrame:
    return load_dataframe("exercise_pr_history", EXERCISE_PR_HISTORY_PATH, EXERCISE_PR_HISTORY_COLUMNS)


def save_exercise_pr_history(df: pd.DataFrame) -> None:
    save_dataframe("exercise_pr_history", EXERCISE_PR_HISTORY_PATH, df, EXERCISE_PR_HISTORY_COLUMNS)


def load_muscle_group_volume_history() -> pd.DataFrame:
    return load_dataframe("muscle_group_volume_history", MUSCLE_GROUP_VOLUME_HISTORY_PATH, MUSCLE_GROUP_VOLUME_HISTORY_COLUMNS)


def save_muscle_group_volume_history(df: pd.DataFrame) -> None:
    save_dataframe("muscle_group_volume_history", MUSCLE_GROUP_VOLUME_HISTORY_PATH, df, MUSCLE_GROUP_VOLUME_HISTORY_COLUMNS)


def move_workout_date(workout_id: str, new_date: str) -> dict:
    """Move every set-level row of one workout to a new date.

    The workout is moved, not copied: workout_id, source, external_id and
    hevy_workout_id are left untouched so source metadata and Hevy/Strava IDs
    stay intact. The original date is recorded in notes as
    ``date_corrected_from=`` for provenance, and updated_at is refreshed.
    """
    from datetime import datetime, timezone

    workout_id = str(workout_id or "").strip()
    if not workout_id:
        raise ValueError("workout_id is required.")
    parsed = pd.to_datetime(new_date, errors="coerce")
    if pd.isna(parsed):
        raise ValueError("new_date must be a valid YYYY-MM-DD date.")
    normalized_date = parsed.date().isoformat()

    df = load_training_log()
    if df.empty:
        raise ValueError(f"No workout found with id {workout_id}.")
    mask = df["workout_id"].fillna("").astype(str).str.strip() == workout_id
    if not mask.any():
        raise ValueError(f"No workout found with id {workout_id}.")

    old_dates = sorted({str(value) for value in df.loc[mask, "date"].dropna().astype(str) if str(value).strip()})
    old_date = old_dates[0] if old_dates else ""
    now = datetime.now(timezone.utc).isoformat()

    for index in df.index[mask]:
        if old_date:
            previous = str(df.at[index, "notes"] or "").strip()
            if "date_corrected_from=" not in previous:
                marker = f"date_corrected_from={old_date}"
                df.at[index, "notes"] = f"{previous} | {marker}" if previous else marker
        df.at[index, "date"] = normalized_date
        df.at[index, "updated_at"] = now

    # Delete the old row identities when the date participates in the fallback
    # row key for manual workouts.
    df = mark_dataframe_deletes(df, "training_log", df.loc[mask].assign(date=old_date).to_dict(orient="records") if old_date else [])
    save_training_log(df)
    return {
        "workout_id": workout_id,
        "old_date": old_date,
        "new_date": normalized_date,
        "moved_rows": int(mask.sum()),
    }


def add_training_entry(
    date,
    workout_type,
    workout_id="",
    muscle_group="",
    exercise="",
    set_number=1,
    sets=0,
    reps=0,
    weight=0,
    rpe=0,
    duration_minutes=0,
    notes="",
    source="manual",
    external_id="",
) -> pd.DataFrame:
    """Add a training entry and return the updated log."""
    training_df = load_training_log()
    resolved_workout_id = str(workout_id or "").strip() or f"manual-{date}-{uuid4().hex[:8]}"
    entry = {
        "workout_id": resolved_workout_id,
        "date": str(date),
        "workout_type": str(workout_type),
        "muscle_group": str(muscle_group).strip(),
        "exercise": str(exercise).strip(),
        "set_number": int(set_number or 1),
        "sets": int(sets or 0),
        "reps": int(reps or 0),
        "weight": float(weight or 0),
        "rpe": float(rpe or 0),
        "duration_minutes": float(duration_minutes or 0),
        "notes": str(notes).strip(),
        "source": str(source or "manual").strip(),
        "external_id": str(external_id or "").strip(),
        "hevy_workout_id": str(workout_id or "").strip() if str(source or "").strip().lower() == "hevy" else "",
        "updated_at": "",
        "sync_source": str(source or "manual").strip(),
        "last_hevy_sync_at": "",
    }

    training_df = pd.concat([training_df, pd.DataFrame([entry])], ignore_index=True)
    training_df = training_df.sort_values("date", kind="stable").reset_index(drop=True)
    save_training_log(training_df)

    return training_df


def calculate_training_volume(df, date=None) -> pd.DataFrame:
    """Calculate strength training volume as sets * reps * weight."""
    if df.empty:
        return pd.DataFrame(columns=["date", "volume"])

    volume_df = df.copy()
    if date is not None:
        volume_df = volume_df[volume_df["date"].astype(str) == str(date)]

    volume_df = volume_df[
        volume_df["workout_type"].astype(str).str.lower() == "strength"
    ].copy()

    if volume_df.empty:
        return pd.DataFrame(columns=["date", "volume"])

    for column in ["sets", "reps", "weight"]:
        volume_df[column] = pd.to_numeric(volume_df[column], errors="coerce").fillna(0)

    volume_df["volume"] = volume_df["sets"] * volume_df["reps"] * volume_df["weight"]
    return (
        volume_df.groupby("date", as_index=False)["volume"]
        .sum()
        .sort_values("date")
        .reset_index(drop=True)
    )


def _jsonish_counts(series: pd.Series) -> dict[str, int]:
    counts = series.fillna("").astype(str).str.strip()
    counts = counts[counts != ""]
    return {str(key): int(value) for key, value in counts.value_counts().to_dict().items()}


def _prepare_training_for_summary(training_df: pd.DataFrame) -> pd.DataFrame:
    if training_df is None or training_df.empty:
        return pd.DataFrame(columns=[*TRAINING_COLUMNS, "date_dt", "total_reps", "volume", "hard_sets", "estimated_1rm"])
    df = _normalize_training_log(training_df).copy()
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date_dt"])
    if df.empty:
        return pd.DataFrame(columns=[*TRAINING_COLUMNS, "date_dt", "total_reps", "volume", "hard_sets", "estimated_1rm"])
    for column in ["sets", "reps", "weight", "rpe", "duration_minutes"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    inferred_set_mask = (df["sets"] <= 0) & ((df["reps"] > 0) | (df["weight"] > 0))
    df.loc[inferred_set_mask, "sets"] = 1
    df["total_reps"] = df["sets"] * df["reps"]
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    df["hard_sets"] = np.where(df["rpe"] >= 7, df["sets"], 0)
    missing_hard_sets = (df["hard_sets"] <= 0) & (df["rpe"] <= 0) & (df["weight"] > 0) & (df["reps"] > 0)
    df.loc[missing_hard_sets, "hard_sets"] = df.loc[missing_hard_sets, "sets"]
    df["estimated_1rm"] = np.where(
        (df["weight"] > 0) & (df["reps"] > 0),
        df["weight"] * (1 + (df["reps"] / 30)),
        0,
    )
    return df


def _period_bounds(df: pd.DataFrame, period: str) -> pd.DataFrame:
    period_df = df.copy()
    if period == "weekly":
        start = period_df["date_dt"].dt.normalize() - pd.to_timedelta(period_df["date_dt"].dt.weekday, unit="D")
        period_df["period_start"] = start.dt.date.astype(str)
        period_df["period_end"] = (start + pd.Timedelta(days=6)).dt.date.astype(str)
        iso = period_df["date_dt"].dt.isocalendar()
        period_df["period_label"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
    else:
        start = period_df["date_dt"].dt.to_period("M").dt.start_time
        period_df["period_start"] = start.dt.date.astype(str)
        period_df["period_end"] = (start + pd.offsets.MonthEnd(0)).dt.date.astype(str)
        period_df["period_label"] = start.dt.strftime("%Y-%m")
    return period_df


def _summarize_periods(training_df: pd.DataFrame, period: str) -> pd.DataFrame:
    df = _period_bounds(_prepare_training_for_summary(training_df), period)
    if df.empty:
        return pd.DataFrame(columns=TRAINING_SUMMARY_COLUMNS)
    rows: list[dict] = []
    for period_start, group in df.groupby("period_start", sort=True):
        workout_keys = group[["date", "workout_id"]].drop_duplicates()
        duration_by_workout = group.groupby(["date", "workout_id"], dropna=False)["duration_minutes"].max()
        muscle_groups = group["muscle_group"].fillna("").astype(str).str.strip().replace("", "Unknown")
        volume_by_muscle = group.assign(_muscle_group=muscle_groups).groupby("_muscle_group")["volume"].sum().sort_values(ascending=False)
        hard_sets_by_muscle = group.assign(_muscle_group=muscle_groups).groupby("_muscle_group")["hard_sets"].sum().sort_values(ascending=False)
        top_exercises = (
            group[group["exercise"].fillna("").astype(str).str.strip() != ""]
            .groupby("exercise", as_index=False)["volume"]
            .sum()
            .sort_values("volume", ascending=False)
            .head(8)
        )
        best_1rm = (
            group[(group["exercise"].fillna("").astype(str).str.strip() != "") & (group["estimated_1rm"] > 0)]
            .groupby("exercise")["estimated_1rm"]
            .max()
            .sort_values(ascending=False)
            .head(12)
        )
        best_sets = []
        best_set_rows = (
            group[(group["exercise"].fillna("").astype(str).str.strip() != "") & (group["estimated_1rm"] > 0)]
            .sort_values(["exercise", "estimated_1rm", "weight", "reps"], ascending=[True, False, False, False])
        )
        for exercise, exercise_rows in best_set_rows.groupby("exercise", sort=True):
            row = exercise_rows.iloc[0]
            best_sets.append(
                {
                    "exercise": str(exercise),
                    "date": row["date_dt"].date().isoformat(),
                    "weight": round(float(row.get("weight", 0) or 0), 1),
                    "reps": int(round(float(row.get("reps", 0) or 0))),
                    "estimated_1rm": round(float(row.get("estimated_1rm", 0) or 0), 1),
                }
            )
        prs = [
            {"exercise": str(exercise), "estimated_1rm": round(float(value), 1)}
            for exercise, value in best_1rm.head(8).items()
        ]
        period_days = max(1, (pd.to_datetime(group["period_end"].iloc[0]) - pd.to_datetime(group["period_start"].iloc[0])).days + 1)
        rows.append(
            {
                "period_start": str(period_start),
                "period_end": str(group["period_end"].iloc[0]),
                "period_label": str(group["period_label"].iloc[0]),
                "workout_count": int(len(workout_keys)),
                "total_sets": int(round(float(group["sets"].sum()))),
                "hard_sets": int(round(float(group["hard_sets"].sum()))),
                "total_reps": int(round(float(group["total_reps"].sum()))),
                "total_volume": round(float(group["volume"].sum()), 1),
                "duration_minutes": round(float(duration_by_workout.sum()), 1),
                "training_frequency_per_week": round(float(len(workout_keys)) / period_days * 7, 2),
                "volume_by_muscle_group": {str(key): round(float(value), 1) for key, value in volume_by_muscle.items()},
                "hard_sets_by_muscle_group": {str(key): int(round(float(value))) for key, value in hard_sets_by_muscle.items()},
                "top_exercises": [
                    {"exercise": str(item["exercise"]), "volume": round(float(item["volume"]), 1)}
                    for item in top_exercises.to_dict(orient="records")
                ],
                "best_set_by_exercise": best_sets[:12],
                "best_estimated_1rm_by_exercise": {str(key): round(float(value), 1) for key, value in best_1rm.items()},
                "prs": prs,
                "source_counts": _jsonish_counts(group["source"]),
                "latest_workout_date": str(group["date_dt"].max().date()),
            }
        )
    return pd.DataFrame(rows, columns=TRAINING_SUMMARY_COLUMNS)


def _build_exercise_pr_history(training_df: pd.DataFrame) -> pd.DataFrame:
    df = _prepare_training_for_summary(training_df)
    if df.empty:
        return pd.DataFrame(columns=EXERCISE_PR_HISTORY_COLUMNS)
    df = df[(df["exercise"].fillna("").astype(str).str.strip() != "") & (df["estimated_1rm"] > 0)].copy()
    if df.empty:
        return pd.DataFrame(columns=EXERCISE_PR_HISTORY_COLUMNS)
    df = df.sort_values(["exercise", "date_dt", "estimated_1rm"])
    rows: list[dict] = []
    for exercise, group in df.groupby("exercise", sort=True):
        best = 0.0
        for _, row in group.iterrows():
            estimated = float(row["estimated_1rm"] or 0)
            if estimated <= best + 0.01:
                continue
            best = estimated
            date_value = row["date_dt"].date().isoformat()
            week_start = row["date_dt"].normalize() - pd.Timedelta(days=int(row["date_dt"].weekday()))
            rows.append(
                {
                    "exercise": str(exercise),
                    "date": date_value,
                    "workout_id": str(row.get("workout_id", "")),
                    "estimated_1rm": round(estimated, 1),
                    "weight": round(float(row.get("weight", 0) or 0), 1),
                    "reps": int(round(float(row.get("reps", 0) or 0))),
                    "source": str(row.get("source", "") or ""),
                    "period_start": week_start.date().isoformat(),
                }
            )
    return pd.DataFrame(rows, columns=EXERCISE_PR_HISTORY_COLUMNS)


def _build_muscle_group_volume_history(training_df: pd.DataFrame, period: str) -> pd.DataFrame:
    df = _period_bounds(_prepare_training_for_summary(training_df), period)
    if df.empty:
        return pd.DataFrame(columns=MUSCLE_GROUP_VOLUME_HISTORY_COLUMNS)
    df["_muscle_group"] = df["muscle_group"].fillna("").astype(str).str.strip().replace("", "Unknown")
    rows: list[dict] = []
    for (period_start, muscle_group), group in df.groupby(["period_start", "_muscle_group"], sort=True):
        rows.append(
            {
                "period_type": period,
                "period_start": str(period_start),
                "period_end": str(group["period_end"].iloc[0]),
                "period_label": str(group["period_label"].iloc[0]),
                "muscle_group": str(muscle_group),
                "workout_count": int(group[["date", "workout_id"]].drop_duplicates().shape[0]),
                "total_sets": int(round(float(group["sets"].sum()))),
                "hard_sets": int(round(float(group["hard_sets"].sum()))),
                "total_reps": int(round(float(group["total_reps"].sum()))),
                "total_volume": round(float(group["volume"].sum()), 1),
                "latest_workout_date": str(group["date_dt"].max().date()),
            }
        )
    return pd.DataFrame(rows, columns=MUSCLE_GROUP_VOLUME_HISTORY_COLUMNS)


def consolidate_old_training_history(cutoff_days: int | None = None, training_df: pd.DataFrame | None = None) -> dict:
    """Create lightweight summaries for raw rows older than the live window.

    This first phase intentionally does not delete or archive raw rows. Live
    endpoints ignore old set-level data, while this manual job preserves the
    long-term signal in summary datasets.
    """
    days = training_raw_window_days() if cutoff_days is None else max(30, int(cutoff_days))
    source_df = load_training_log() if training_df is None else training_df
    prepared = _prepare_training_for_summary(source_df)
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    old_df = prepared[prepared["date_dt"] < cutoff].copy()
    weekly = _summarize_periods(old_df, "weekly")
    monthly = _summarize_periods(old_df, "monthly")
    prs = _build_exercise_pr_history(old_df)
    muscle_weekly = _build_muscle_group_volume_history(old_df, "weekly")
    muscle_monthly = _build_muscle_group_volume_history(old_df, "monthly")
    muscle = pd.concat([muscle_weekly, muscle_monthly], ignore_index=True) if not muscle_weekly.empty or not muscle_monthly.empty else pd.DataFrame(columns=MUSCLE_GROUP_VOLUME_HISTORY_COLUMNS)

    save_weekly_training_summary(weekly)
    save_monthly_training_summary(monthly)
    save_exercise_pr_history(prs)
    save_muscle_group_volume_history(muscle)

    result = {
        "status": "ok",
        "cutoff_days": days,
        "cutoff_date": cutoff.date().isoformat(),
        "raw_rows_total": int(len(prepared)),
        "raw_rows_summarized": int(len(old_df)),
        "weekly_summaries": int(len(weekly)),
        "monthly_summaries": int(len(monthly)),
        "exercise_prs": int(len(prs)),
        "muscle_group_periods": int(len(muscle)),
        "raw_rows_deleted": 0,
        "message": "Historical summaries updated. Raw set-level rows were preserved.",
    }
    result["last_rebuilt_at"] = datetime.now(timezone.utc).isoformat()
    save_training_summary_state(result)
    return result


class TrainingLogger:
    """Logs and analyzes workout data."""
    
    def __init__(self, data_dir: str = "data/processed"):
        """Initialize the training logger.
        
        Args:
            data_dir: Directory path for storing processed training data
        """
        self.data_dir = Path(data_dir)
        self.training_file = self.data_dir / "training.csv"
    
    def log_workout(self, date: str, workout_type: str, duration: int,
                   exercises: list, notes: str = "") -> bool:
        """Log a workout session.
        
        Args:
            date: Date of workout (YYYY-MM-DD format)
            workout_type: Type of workout (strength, cardio, flexibility, etc.)
            duration: Duration in minutes
            exercises: List of exercises with sets, reps, weight
            notes: Optional notes about the workout
            
        Returns:
            True if successfully logged, False otherwise
        """
        if exercises:
            for exercise in exercises:
                add_training_entry(
                    date=date,
                    workout_type=workout_type,
                    muscle_group=exercise.get("muscle_group", ""),
                    exercise=exercise.get("exercise", exercise.get("name", "")),
                    sets=exercise.get("sets", 0),
                    reps=exercise.get("reps", 0),
                    weight=exercise.get("weight", 0),
                    rpe=exercise.get("rpe", 0),
                    duration_minutes=duration,
                    notes=notes,
                )
        else:
            add_training_entry(
                date=date,
                workout_type=workout_type,
                duration_minutes=duration,
                notes=notes,
            )
        return True
    
    def log_exercise(self, workout_id: str, exercise_name: str, sets: int,
                    reps: int, weight: float = 0.0) -> bool:
        """Log exercise details within a workout.
        
        Args:
            workout_id: ID of the parent workout session
            exercise_name: Name of the exercise
            sets: Number of sets completed
            reps: Number of reps per set
            weight: Weight used (0 for bodyweight exercises)
            
        Returns:
            True if successfully logged, False otherwise
        """
        add_training_entry(
            date=workout_id,
            workout_type="Strength",
            exercise=exercise_name,
            sets=sets,
            reps=reps,
            weight=weight,
        )
        return True
    
    def get_training_volume(self, days: int = 7) -> dict:
        """Calculate total training volume for recent period.
        
        Args:
            days: Number of days to analyze (default: 7)
            
        Returns:
            Dictionary with volume metrics by workout type
        """
        training_df = load_training_log()
        if training_df.empty:
            return {}

        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        dates = pd.to_datetime(training_df["date"], errors="coerce")
        recent_df = training_df[dates >= cutoff].copy()
        volume_df = calculate_training_volume(recent_df)

        return dict(zip(volume_df["date"], volume_df["volume"]))
    
    def get_workout_history(self, days: int = 30) -> pd.DataFrame:
        """Get workout history for recent period.
        
        Args:
            days: Number of days to retrieve (default: 30)
            
        Returns:
            DataFrame with workout data
        """
        training_df = load_training_log()
        if training_df.empty:
            return training_df

        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        dates = pd.to_datetime(training_df["date"], errors="coerce")
        return training_df[dates >= cutoff].copy()
