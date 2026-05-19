"""
Body Metrics module for tracking physical measurements and performance indicators.

This module handles:
- Body composition tracking (weight, body fat, muscle mass)
- Performance metrics (strength, endurance, flexibility)
- Health markers (heart rate, blood pressure, etc.)
"""

import pandas as pd
import numpy as np
from pathlib import Path

from src.paths import processed_data_path
from src.storage import load_dataframe, save_dataframe

BODY_METRICS_COLUMNS = [
    "date",
    "bodyweight",
    "waist",
    "estimated_body_fat",
    "body_fat_percent",
    "lean_mass",
    "fat_mass",
    "muscle_mass",
    "hydration",
    "bone_mass",
    "bmi",
    "source",
    "source_id",
    "raw_payload",
    "notes",
]

# Columns added for Withings body-composition syncing. Older rows lack them and
# are backfilled on load; manual entries simply leave them blank.
BODY_METRICS_NUMERIC_COLUMNS = [
    "bodyweight",
    "waist",
    "estimated_body_fat",
    "body_fat_percent",
    "lean_mass",
    "fat_mass",
    "muscle_mass",
    "hydration",
    "bone_mass",
    "bmi",
]
BODY_METRICS_STRING_COLUMNS = ["source", "source_id", "raw_payload", "notes"]

BODY_METRICS_PATH = processed_data_path("body_metrics.csv")


def _empty_body_metrics() -> pd.DataFrame:
    """Return an empty body metrics table with the expected columns."""
    return pd.DataFrame(columns=BODY_METRICS_COLUMNS)


def load_body_metrics() -> pd.DataFrame:
    """Load body metrics from local CSV."""
    metrics_df = load_dataframe("body_metrics", BODY_METRICS_PATH, BODY_METRICS_COLUMNS)

    for column in BODY_METRICS_COLUMNS:
        if column not in metrics_df.columns:
            metrics_df[column] = np.nan

    metrics_df["estimated_body_fat"] = pd.to_numeric(metrics_df["estimated_body_fat"], errors="coerce")
    metrics_df["body_fat_percent"] = pd.to_numeric(metrics_df["body_fat_percent"], errors="coerce")
    metrics_df["estimated_body_fat"] = metrics_df["estimated_body_fat"].combine_first(metrics_df["body_fat_percent"])
    metrics_df["body_fat_percent"] = metrics_df["body_fat_percent"].combine_first(metrics_df["estimated_body_fat"])

    metrics_df = metrics_df[BODY_METRICS_COLUMNS]

    for column in BODY_METRICS_NUMERIC_COLUMNS:
        metrics_df[column] = pd.to_numeric(metrics_df[column], errors="coerce")

    metrics_df["date"] = metrics_df["date"].astype(str)
    for column in BODY_METRICS_STRING_COLUMNS:
        metrics_df[column] = metrics_df[column].fillna("").astype(str)

    return metrics_df


def save_body_metrics(df) -> None:
    """Save body metrics to local CSV."""
    save_dataframe("body_metrics", BODY_METRICS_PATH, df, BODY_METRICS_COLUMNS)


def add_body_metric_entry(
    date,
    bodyweight,
    waist=None,
    estimated_body_fat=None,
    body_fat_percent=None,
    lean_mass=None,
    fat_mass=None,
    muscle_mass=None,
    hydration=None,
    bmi=None,
    notes="",
) -> pd.DataFrame:
    """Add a body metric entry and return the updated table."""
    metrics_df = load_body_metrics()
    body_fat_value = estimated_body_fat if estimated_body_fat is not None else body_fat_percent
    entry = {
        "date": str(date),
        "bodyweight": float(bodyweight),
        "waist": np.nan if waist is None else float(waist),
        "estimated_body_fat": (
            np.nan if body_fat_value is None else float(body_fat_value)
        ),
        "body_fat_percent": (
            np.nan if body_fat_value is None else float(body_fat_value)
        ),
        "lean_mass": np.nan if lean_mass is None else float(lean_mass),
        "fat_mass": np.nan if fat_mass is None else float(fat_mass),
        "muscle_mass": np.nan if muscle_mass is None else float(muscle_mass),
        "hydration": np.nan if hydration is None else float(hydration),
        "bone_mass": np.nan,
        "bmi": np.nan if bmi is None else float(bmi),
        "source": "manual",
        "source_id": "",
        "raw_payload": "",
        "notes": str(notes).strip(),
    }

    metrics_df = pd.concat([metrics_df, pd.DataFrame([entry])], ignore_index=True)
    metrics_df = metrics_df.sort_values("date", kind="stable").reset_index(drop=True)
    save_body_metrics(metrics_df)

    return metrics_df

def upsert_withings_measurements(rows: list[dict]) -> dict:
    """Insert or update Withings body-composition rows in body_metrics.

    Dedup identity is ``source="withings"`` + ``source_id`` (the Withings
    measure-group id). Re-syncing the same measurement updates the existing row
    rather than creating a duplicate. Returns ``{"created", "updated"}`` counts.
    """
    metrics_df = load_body_metrics()
    created = 0
    updated = 0

    for row in rows:
        source_id = str(row.get("source_id", "") or "").strip()
        if not source_id:
            continue
        existing = metrics_df.index[
            (metrics_df["source"].astype(str) == "withings")
            & (metrics_df["source_id"].astype(str) == source_id)
        ]
        entry = {
            "date": str(row.get("date", "")),
            "bodyweight": row.get("bodyweight"),
            "waist": row.get("waist"),
            "estimated_body_fat": row.get("estimated_body_fat"),
            "body_fat_percent": row.get("body_fat_percent", row.get("estimated_body_fat")),
            "lean_mass": row.get("lean_mass"),
            "fat_mass": row.get("fat_mass"),
            "muscle_mass": row.get("muscle_mass"),
            "hydration": row.get("hydration"),
            "bone_mass": row.get("bone_mass"),
            "bmi": row.get("bmi"),
            "source": "withings",
            "source_id": source_id,
            "raw_payload": row.get("raw_payload", "") or "",
            "notes": str(row.get("notes", "") or ""),
        }
        if len(existing):
            for column, value in entry.items():
                metrics_df.loc[existing[0], column] = value
            updated += 1
        else:
            metrics_df = pd.concat([metrics_df, pd.DataFrame([entry])], ignore_index=True)
            created += 1

    metrics_df = metrics_df.sort_values("date", kind="stable").reset_index(drop=True)
    save_body_metrics(metrics_df)
    return {"created": created, "updated": updated}


class BodyMetricsTracker:
    """Tracks body composition and performance metrics."""
    
    def __init__(self, data_dir: str = "data/processed"):
        """Initialize the body metrics tracker.
        
        Args:
            data_dir: Directory path for storing processed metrics data
        """
        self.data_dir = Path(data_dir)
        self.metrics_file = self.data_dir / "body_metrics.csv"
    
    def log_weight(self, date: str, weight: float, unit: str = "kg") -> bool:
        """Log body weight measurement.
        
        Args:
            date: Date of measurement (YYYY-MM-DD format)
            weight: Weight value
            unit: Unit of measurement (kg or lbs)
            
        Returns:
            True if successfully logged, False otherwise
        """
        add_body_metric_entry(date=date, bodyweight=weight)
        return True
    
    def log_body_composition(self, date: str, weight: float, body_fat: float,
                            muscle_mass: float = 0.0) -> bool:
        """Log detailed body composition data.
        
        Args:
            date: Date of measurement (YYYY-MM-DD format)
            weight: Body weight
            body_fat: Body fat percentage
            muscle_mass: Muscle mass (optional)
            
        Returns:
            True if successfully logged, False otherwise
        """
        add_body_metric_entry(
            date=date,
            bodyweight=weight,
            estimated_body_fat=body_fat,
        )
        return True
    
    def log_vitals(self, date: str, resting_heart_rate: int,
                  systolic_bp: int = 0, diastolic_bp: int = 0) -> bool:
        """Log vital signs.
        
        Args:
            date: Date of measurement (YYYY-MM-DD format)
            resting_heart_rate: Resting heart rate (bpm)
            systolic_bp: Systolic blood pressure (optional)
            diastolic_bp: Diastolic blood pressure (optional)
            
        Returns:
            True if successfully logged, False otherwise
        """
        # TODO: Implement vitals logging
        return False
    
    def get_metrics_trend(self, days: int = 30) -> pd.DataFrame:
        """Get body metrics trend over time.
        
        Args:
            days: Number of days to analyze (default: 30)
            
        Returns:
            DataFrame with metrics data
        """
        metrics_df = load_body_metrics()
        if metrics_df.empty:
            return metrics_df

        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        dates = pd.to_datetime(metrics_df["date"], errors="coerce")
        return metrics_df[dates >= cutoff].copy()
    
    def get_current_metrics(self) -> dict:
        """Get most recent body metrics.
        
        Returns:
            Dictionary with latest measurements
        """
        metrics_df = load_body_metrics()
        if metrics_df.empty:
            return {}

        return metrics_df.sort_values("date").iloc[-1].to_dict()
