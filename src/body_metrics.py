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
BODY_COMP_FIELDS = [
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


def _empty_body_metrics() -> pd.DataFrame:
    """Return an empty body metrics table with the expected columns."""
    return pd.DataFrame(columns=BODY_METRICS_COLUMNS)


def _measurement_timestamp(df: pd.DataFrame) -> pd.Series:
    """Best-effort timestamp for tie-breaking same-day weigh-ins."""
    candidates = ["measured_at", "measurement_time", "timestamp", "created_at", "updated_at", "_date_ts", "date"]
    stamp = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    for column in candidates:
        if column in df.columns:
            parsed = pd.to_datetime(df[column], errors="coerce").dt.tz_localize(None)
            stamp = stamp.combine_first(parsed)
    return stamp


def canonical_daily_bodyweights(body_metrics_df) -> pd.DataFrame:
    """
    Return one row per date using the lowest valid bodyweight for each date.

    Raw rows are not modified. If multiple entries tie for the lowest weight,
    the earliest measurement timestamp wins. Body-composition fields are kept
    from the selected row when present; missing composition fields are filled
    from the closest same-day Withings/body-composition row when available.
    """
    if body_metrics_df is None:
        return pd.DataFrame(columns=BODY_METRICS_COLUMNS)
    df = pd.DataFrame(body_metrics_df).copy()
    if df.empty or "date" not in df.columns or "bodyweight" not in df.columns:
        return pd.DataFrame(columns=list(df.columns) if not df.empty else BODY_METRICS_COLUMNS)
    if "excluded_from_analytics" in df.columns:
        excluded = df["excluded_from_analytics"].fillna(False).astype(str).str.lower().isin({"true", "1", "yes"})
        df = df[~excluded].copy()
        if df.empty:
            return pd.DataFrame(columns=list(body_metrics_df.columns) if hasattr(body_metrics_df, "columns") else BODY_METRICS_COLUMNS)

    original_date = pd.to_datetime(df["date"], errors="coerce")
    df["_date_ts"] = original_date
    df["date"] = original_date.dt.normalize()
    df["bodyweight"] = pd.to_numeric(df["bodyweight"], errors="coerce")
    df = df.dropna(subset=["date", "bodyweight"]).copy()
    df = df[df["bodyweight"] > 0].copy()
    if df.empty:
        return pd.DataFrame(columns=list(body_metrics_df.columns) if hasattr(body_metrics_df, "columns") else BODY_METRICS_COLUMNS)

    for column in BODY_COMP_FIELDS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    df["_measurement_ts"] = _measurement_timestamp(df)
    df["_source_rank"] = df.get("source", pd.Series("", index=df.index)).fillna("").astype(str).str.lower().str.contains("withings").map(lambda value: 0 if value else 1)
    df = df.sort_values(["date", "bodyweight", "_measurement_ts"], kind="stable")

    chosen_rows = []
    for day, day_df in df.groupby("date", sort=True):
        chosen = day_df.iloc[0].copy()
        chosen_ts = chosen.get("_measurement_ts")
        for field in BODY_COMP_FIELDS:
            if field not in day_df.columns:
                continue
            if pd.notna(chosen.get(field)):
                continue
            candidates = day_df[day_df[field].notna()].copy()
            if candidates.empty:
                continue
            if pd.notna(chosen_ts):
                candidates["_distance"] = (candidates["_measurement_ts"] - chosen_ts).abs()
            else:
                candidates["_distance"] = pd.Timedelta.max
            candidates = candidates.sort_values(["_source_rank", "_distance", "_measurement_ts"], kind="stable")
            chosen[field] = candidates.iloc[0][field]
        chosen_rows.append(chosen)

    result = pd.DataFrame(chosen_rows).drop(columns=["_measurement_ts", "_source_rank", "_date_ts"], errors="ignore")
    return result.sort_values("date", kind="stable").reset_index(drop=True)


def canonical_bodyweight_debug(body_metrics_df) -> dict:
    """Return counts explaining the lowest-weight-per-day analytics rule."""
    raw = pd.DataFrame(body_metrics_df).copy() if body_metrics_df is not None else pd.DataFrame()
    if raw.empty or "date" not in raw.columns or "bodyweight" not in raw.columns:
        return {
            "raw_body_metric_row_count": int(len(raw)),
            "raw_body_metric_rows": int(len(raw)),
            "canonical_daily_weight_count": 0,
            "canonical_daily_weight_rows": 0,
            "dates_with_multiple_weigh_ins": 0,
            "dates_with_multiple_weighins": 0,
            "dropped_invalid_rows": 0,
            "withings_rows": 0,
            "manual_rows": 0,
            "date_min": "",
            "date_max": "",
            "rule": "lowest_weight_per_day",
        }
    prepared = raw.copy()
    excluded_count = 0
    if "excluded_from_analytics" in prepared.columns:
        excluded = prepared["excluded_from_analytics"].fillna(False).astype(str).str.lower().isin({"true", "1", "yes"})
        excluded_count = int(excluded.sum())
        prepared = prepared[~excluded].copy()
    source_series = prepared.get("source", pd.Series("", index=prepared.index)).fillna("").astype(str).str.lower()
    notes_series = prepared.get("notes", pd.Series("", index=prepared.index)).fillna("").astype(str).str.lower()
    withings_mask = source_series.str.contains("withings") | notes_series.str.contains("source=withings")
    manual_rows = int((~withings_mask).sum())
    prepared["date"] = pd.to_datetime(prepared["date"], errors="coerce").dt.normalize()
    prepared["bodyweight"] = pd.to_numeric(prepared["bodyweight"], errors="coerce")
    candidate_count = int(len(prepared))
    prepared = prepared.dropna(subset=["date", "bodyweight"])
    prepared = prepared[prepared["bodyweight"] > 0]
    dropped_invalid = candidate_count - int(len(prepared))
    counts = prepared.groupby("date").size() if not prepared.empty else pd.Series(dtype=int)
    canonical = canonical_daily_bodyweights(prepared)
    date_min = prepared["date"].min().date().isoformat() if not prepared.empty else ""
    date_max = prepared["date"].max().date().isoformat() if not prepared.empty else ""
    return {
        "raw_body_metric_row_count": int(len(raw)),
        "raw_body_metric_rows": int(len(raw)),
        "valid_bodyweight_row_count": int(len(prepared)),
        "canonical_daily_weight_count": int(len(canonical)),
        "canonical_daily_weight_rows": int(len(canonical)),
        "dates_with_multiple_weigh_ins": int((counts > 1).sum()),
        "dates_with_multiple_weighins": int((counts > 1).sum()),
        "dropped_invalid_rows": int(dropped_invalid),
        "withings_rows": int(withings_mask.sum()),
        "manual_rows": manual_rows,
        "date_min": date_min,
        "date_max": date_max,
        "rule": "lowest_weight_per_day",
        "excluded_from_analytics_count": excluded_count,
    }


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
