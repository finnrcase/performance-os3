"""Shared API serialization helpers."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def clean_value(value: Any) -> Any:
    """Convert pandas/numpy missing values into JSON-safe None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def dataframe_records(df: pd.DataFrame) -> list[dict]:
    """Return JSON-safe records from a DataFrame."""
    if df.empty:
        return []
    return [
        {key: clean_value(value) for key, value in row.items()}
        for row in df.to_dict(orient="records")
    ]
