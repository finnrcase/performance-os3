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

BODY_METRICS_COLUMNS = [
    "date",
    "bodyweight",
    "waist",
    "estimated_body_fat",
    "notes",
]

BODY_METRICS_PATH = processed_data_path("body_metrics.csv")


def _empty_body_metrics() -> pd.DataFrame:
    """Return an empty body metrics table with the expected columns."""
    return pd.DataFrame(columns=BODY_METRICS_COLUMNS)


def load_body_metrics() -> pd.DataFrame:
    """Load body metrics from local CSV."""
    if not BODY_METRICS_PATH.exists():
        return _empty_body_metrics()

    metrics_df = pd.read_csv(BODY_METRICS_PATH)

    for column in BODY_METRICS_COLUMNS:
        if column not in metrics_df.columns:
            metrics_df[column] = np.nan

    metrics_df = metrics_df[BODY_METRICS_COLUMNS]

    for column in ["bodyweight", "waist", "estimated_body_fat"]:
        metrics_df[column] = pd.to_numeric(metrics_df[column], errors="coerce")

    metrics_df["date"] = metrics_df["date"].astype(str)
    metrics_df["notes"] = metrics_df["notes"].fillna("").astype(str)

    return metrics_df


def save_body_metrics(df) -> None:
    """Save body metrics to local CSV."""
    BODY_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    metrics_df = df.reindex(columns=BODY_METRICS_COLUMNS)
    metrics_df.to_csv(BODY_METRICS_PATH, index=False)


def add_body_metric_entry(
    date,
    bodyweight,
    waist=None,
    estimated_body_fat=None,
    notes="",
) -> pd.DataFrame:
    """Add a body metric entry and return the updated table."""
    metrics_df = load_body_metrics()
    entry = {
        "date": str(date),
        "bodyweight": float(bodyweight),
        "waist": np.nan if waist is None else float(waist),
        "estimated_body_fat": (
            np.nan if estimated_body_fat is None else float(estimated_body_fat)
        ),
        "notes": str(notes).strip(),
    }

    metrics_df = pd.concat([metrics_df, pd.DataFrame([entry])], ignore_index=True)
    metrics_df = metrics_df.sort_values("date", kind="stable").reset_index(drop=True)
    save_body_metrics(metrics_df)

    return metrics_df


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
