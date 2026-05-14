"""
Recovery module for tracking sleep, stress, and recovery metrics.

This module handles:
- Logging sleep data
- Tracking stress levels and mood
- Recovery readiness assessment
- Rest day management
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

from src.paths import processed_data_path
from src.storage import load_dataframe, save_dataframe

RECOVERY_COLUMNS = [
    "date",
    "sleep_hours",
    "sleep_quality",
    "fatigue",
    "soreness",
    "stress",
    "motivation",
    "resting_hr",
    "hrv",
    "notes",
]

RECOVERY_LOG_PATH = processed_data_path("recovery_log.csv")
SLEEP_ENTRY_COLUMNS = [
    "id",
    "userId",
    "date",
    "sleepStart",
    "sleepEnd",
    "durationMinutes",
    "efficiencyPercent",
    "deepSleepMinutes",
    "remSleepMinutes",
    "lightSleepMinutes",
    "awakeMinutes",
    "restingHeartRate",
    "hrv",
    "source",
    "createdAt",
    "updatedAt",
]
SLEEP_ENTRIES_PATH = processed_data_path("sleep_entries.csv")


def _empty_recovery_log() -> pd.DataFrame:
    """Return an empty recovery log with the expected columns."""
    return pd.DataFrame(columns=RECOVERY_COLUMNS)


def load_recovery_log() -> pd.DataFrame:
    """Load recovery check-ins from local CSV."""
    recovery_df = load_dataframe("recovery_log", RECOVERY_LOG_PATH, RECOVERY_COLUMNS)

    for column in RECOVERY_COLUMNS:
        if column not in recovery_df.columns:
            recovery_df[column] = np.nan

    recovery_df = recovery_df[RECOVERY_COLUMNS]

    numeric_columns = [
        "sleep_hours",
        "sleep_quality",
        "fatigue",
        "soreness",
        "stress",
        "motivation",
        "resting_hr",
        "hrv",
    ]
    for column in numeric_columns:
        recovery_df[column] = pd.to_numeric(recovery_df[column], errors="coerce")

    recovery_df["date"] = recovery_df["date"].astype(str)
    recovery_df["notes"] = recovery_df["notes"].fillna("").astype(str)

    return recovery_df


def save_recovery_log(df) -> None:
    """Save recovery check-ins to local CSV."""
    save_dataframe("recovery_log", RECOVERY_LOG_PATH, df, RECOVERY_COLUMNS)


def _empty_sleep_entries() -> pd.DataFrame:
    """Return an empty future-ready sleep entry table."""
    return pd.DataFrame(columns=SLEEP_ENTRY_COLUMNS)


def _sleep_entries_from_recovery_log() -> pd.DataFrame:
    """Derive manual sleep entries from existing recovery check-ins."""
    recovery_df = load_recovery_log()
    if recovery_df.empty:
        return _empty_sleep_entries()
    rows = []
    for _, row in recovery_df.iterrows():
        date = str(row.get("date", "") or "").strip()
        duration_hours = pd.to_numeric(row.get("sleep_hours"), errors="coerce")
        if not date or pd.isna(duration_hours) or float(duration_hours) <= 0:
            continue
        sleep_quality = pd.to_numeric(row.get("sleep_quality"), errors="coerce")
        efficiency = float(sleep_quality) * 10 if not pd.isna(sleep_quality) else np.nan
        rows.append(
            {
                "id": f"manual-recovery-{date}",
                "userId": "local",
                "date": date,
                "sleepStart": "",
                "sleepEnd": "",
                "durationMinutes": round(float(duration_hours) * 60, 0),
                "efficiencyPercent": max(0, min(100, efficiency)) if not pd.isna(efficiency) else np.nan,
                "deepSleepMinutes": np.nan,
                "remSleepMinutes": np.nan,
                "lightSleepMinutes": np.nan,
                "awakeMinutes": np.nan,
                "restingHeartRate": row.get("resting_hr"),
                "hrv": row.get("hrv"),
                "source": "manual",
                "createdAt": "",
                "updatedAt": "",
            }
        )
    return pd.DataFrame(rows, columns=SLEEP_ENTRY_COLUMNS) if rows else _empty_sleep_entries()


def load_sleep_entries() -> pd.DataFrame:
    """Load future Fitbit/Google Fit sleep entries, with manual recovery fallback."""
    sleep_df = load_dataframe("sleep_entries", SLEEP_ENTRIES_PATH, SLEEP_ENTRY_COLUMNS)
    if sleep_df.empty:
        sleep_df = _sleep_entries_from_recovery_log()

    numeric_columns = [
        "durationMinutes",
        "efficiencyPercent",
        "deepSleepMinutes",
        "remSleepMinutes",
        "lightSleepMinutes",
        "awakeMinutes",
        "restingHeartRate",
        "hrv",
    ]
    for column in numeric_columns:
        sleep_df[column] = pd.to_numeric(sleep_df[column], errors="coerce")
    for column in ["id", "userId", "date", "sleepStart", "sleepEnd", "source", "createdAt", "updatedAt"]:
        sleep_df[column] = sleep_df[column].fillna("").astype(str)
    return sleep_df.sort_values("date", kind="stable").reset_index(drop=True)


def _score_high_value(value, best_value=10.0) -> float:
    """Score a metric where higher is better on a 0-1 scale."""
    if pd.isna(value):
        return 0.0
    return max(0.0, min(float(value) / best_value, 1.0))


def _score_low_value(value, worst_value=10.0) -> float:
    """Score a metric where lower is better on a 0-1 scale."""
    if pd.isna(value):
        return 0.0
    return max(0.0, min((worst_value - float(value) + 1.0) / worst_value, 1.0))


def calculate_recovery_score(row) -> float:
    """Calculate a simple explainable 0-100 recovery score.

    Sleep hours are scored against an 8-hour target. Subjective 1-10 scores are
    normalized so higher sleep quality and motivation help, while higher
    fatigue, soreness, and stress reduce the score. Optional resting HR and HRV
    are stored but not required for scoring.
    """
    scores = [
        _score_high_value(row.get("sleep_hours"), best_value=8.0),
        _score_high_value(row.get("sleep_quality")),
        _score_low_value(row.get("fatigue")),
        _score_low_value(row.get("soreness")),
        _score_low_value(row.get("stress")),
        _score_high_value(row.get("motivation")),
    ]

    return round(float(np.mean(scores) * 100), 1)


def add_recovery_entry(
    date,
    sleep_hours,
    sleep_quality,
    fatigue,
    soreness,
    stress,
    motivation,
    resting_hr=None,
    hrv=None,
    notes="",
) -> pd.DataFrame:
    """Add a daily recovery check-in and return the updated log."""
    recovery_df = load_recovery_log()
    entry = {
        "date": str(date),
        "sleep_hours": float(sleep_hours),
        "sleep_quality": int(sleep_quality),
        "fatigue": int(fatigue),
        "soreness": int(soreness),
        "stress": int(stress),
        "motivation": int(motivation),
        "resting_hr": np.nan if resting_hr is None else float(resting_hr),
        "hrv": np.nan if hrv is None else float(hrv),
        "notes": str(notes).strip(),
    }

    recovery_df = pd.concat([recovery_df, pd.DataFrame([entry])], ignore_index=True)
    recovery_df = recovery_df.sort_values("date", kind="stable").reset_index(drop=True)
    save_recovery_log(recovery_df)

    return recovery_df


class RecoveryTracker:
    """Tracks sleep, stress, and recovery metrics."""
    
    def __init__(self, data_dir: str = "data/processed"):
        """Initialize the recovery tracker.
        
        Args:
            data_dir: Directory path for storing processed recovery data
        """
        self.data_dir = Path(data_dir)
        self.recovery_file = self.data_dir / "recovery.csv"
    
    def log_sleep(self, date: str, hours: float, quality: int = 5) -> bool:
        """Log sleep data for a night.
        
        Args:
            date: Date of sleep (YYYY-MM-DD format)
            hours: Hours of sleep
            quality: Sleep quality rating (1-10)
            
        Returns:
            True if successfully logged, False otherwise
        """
        add_recovery_entry(
            date=date,
            sleep_hours=hours,
            sleep_quality=quality,
            fatigue=5,
            soreness=5,
            stress=5,
            motivation=5,
        )
        return True
    
    def log_stress(self, date: str, stress_level: int, notes: str = "") -> bool:
        """Log stress level for a day.
        
        Args:
            date: Date of stress log (YYYY-MM-DD format)
            stress_level: Stress level rating (1-10)
            notes: Optional notes about stress sources
            
        Returns:
            True if successfully logged, False otherwise
        """
        add_recovery_entry(
            date=date,
            sleep_hours=0,
            sleep_quality=5,
            fatigue=5,
            soreness=5,
            stress=stress_level,
            motivation=5,
            notes=notes,
        )
        return True
    
    def log_mood(self, date: str, mood: int, energy: int = 5) -> bool:
        """Log mood and energy levels.
        
        Args:
            date: Date of mood log (YYYY-MM-DD format)
            mood: Mood rating (1-10)
            energy: Energy level (1-10)
            
        Returns:
            True if successfully logged, False otherwise
        """
        # TODO: Implement mood logging
        return False
    
    def get_recovery_readiness(self) -> float:
        """Calculate recovery readiness score.
        
        Returns:
            Readiness score (0-100) based on recent sleep, stress, mood
        """
        recovery_df = load_recovery_log()
        if recovery_df.empty:
            return 0.0

        latest = recovery_df.sort_values("date").iloc[-1]
        return calculate_recovery_score(latest)
    
    def get_recovery_history(self, days: int = 30) -> pd.DataFrame:
        """Get recovery data for recent period.
        
        Args:
            days: Number of days to retrieve (default: 30)
            
        Returns:
            DataFrame with recovery data
        """
        recovery_df = load_recovery_log()
        if recovery_df.empty:
            return recovery_df

        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        dates = pd.to_datetime(recovery_df["date"], errors="coerce")
        return recovery_df[dates >= cutoff].copy()
