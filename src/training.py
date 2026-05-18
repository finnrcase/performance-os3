"""
Training module for logging and analyzing workouts.

This module handles:
- Logging workout data (exercises, sets, reps, weight)
- Tracking training volume and intensity
- Workout history and analytics
"""

import pandas as pd
import numpy as np
from pathlib import Path
from uuid import uuid4

from src.paths import processed_data_path
from src.storage import load_dataframe, mark_dataframe_deletes, save_dataframe
from src.training_schedule import is_run_row

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

            if is_run_row(df.loc[index].to_dict()):
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


def load_training_log() -> pd.DataFrame:
    """Load training entries from local CSV."""
    training_df = load_dataframe("training_log", TRAINING_LOG_PATH, TRAINING_COLUMNS)

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


def save_training_log(df) -> None:
    """Save training entries to local CSV."""
    save_dataframe("training_log", TRAINING_LOG_PATH, df, TRAINING_COLUMNS)


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
