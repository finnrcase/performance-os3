"""Daily nutrition history aggregation for Performance OS.

Detailed food items stay in ``nutrition_log.csv``. This module builds a
separate day-level summary so dashboards, history views, and optimization
engines can reason about adherence without reimplementing aggregation logic.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.paths import processed_data_path

DAILY_NUTRITION_SUMMARY_PATH = processed_data_path("daily_nutrition_summary.csv")

SUMMARY_COLUMNS = [
    "date",
    "total_calories",
    "total_protein",
    "total_carbs",
    "total_fat",
    "fiber",
    "sodium",
    "potassium",
    "magnesium",
    "calcium",
    "iron",
    "zinc",
    "vitamin_d",
    "omega_3",
    "target_calories",
    "target_protein",
    "target_carbs",
    "target_fat",
    "calories_delta",
    "protein_delta",
    "carbs_delta",
    "fat_delta",
    "adherence_score",
    "notes",
]

OPTIONAL_MICROS = [
    "fiber",
    "sodium",
    "potassium",
    "magnesium",
    "calcium",
    "iron",
    "zinc",
    "vitamin_d",
    "omega_3",
]


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SUMMARY_COLUMNS)


def _target_value(targets: dict | None, key: str) -> float | None:
    if not targets:
        return None
    value = targets.get(key)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _adherence_score(row: pd.Series) -> float | None:
    target_map = {
        "total_calories": "target_calories",
        "total_protein": "target_protein",
        "total_carbs": "target_carbs",
        "total_fat": "target_fat",
    }
    component_scores = []
    for actual_col, target_col in target_map.items():
        target = row.get(target_col)
        actual = row.get(actual_col)
        if pd.isna(target) or not target or float(target) <= 0:
            continue
        deviation = abs(float(actual or 0) - float(target)) / float(target)
        component_scores.append(max(0, 100 - deviation * 100))
    if not component_scores:
        return None
    return round(float(sum(component_scores) / len(component_scores)), 1)


def build_daily_nutrition_summary(nutrition_log_df: pd.DataFrame, targets: dict | None = None) -> pd.DataFrame:
    """Aggregate individual food entries into date-level nutrition summaries."""
    if nutrition_log_df.empty:
        return _empty_summary()

    df = nutrition_log_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return _empty_summary()

    for column in ["calories", "protein", "carbs", "fat", *OPTIONAL_MICROS]:
        if column not in df.columns:
            df[column] = pd.NA
        if column in ["calories", "protein", "carbs", "fat"]:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
        else:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    grouped = (
        df.groupby(df["date"].dt.date)
        .agg(
            total_calories=("calories", "sum"),
            total_protein=("protein", "sum"),
            total_carbs=("carbs", "sum"),
            total_fat=("fat", "sum"),
            fiber=("fiber", "sum"),
            sodium=("sodium", "sum"),
            potassium=("potassium", "sum"),
            magnesium=("magnesium", "sum"),
            calcium=("calcium", "sum"),
            iron=("iron", "sum"),
            zinc=("zinc", "sum"),
            vitamin_d=("vitamin_d", "sum"),
            omega_3=("omega_3", "sum"),
        )
        .reset_index()
        .rename(columns={"date": "date"})
    )

    grouped["date"] = pd.to_datetime(grouped["date"]).dt.date.astype(str)
    grouped["target_calories"] = _target_value(targets, "target_calories")
    grouped["target_protein"] = _target_value(targets, "protein_grams")
    grouped["target_carbs"] = _target_value(targets, "carb_grams")
    grouped["target_fat"] = _target_value(targets, "fat_grams")
    grouped["calories_delta"] = grouped["total_calories"] - grouped["target_calories"]
    grouped["protein_delta"] = grouped["total_protein"] - grouped["target_protein"]
    grouped["carbs_delta"] = grouped["total_carbs"] - grouped["target_carbs"]
    grouped["fat_delta"] = grouped["total_fat"] - grouped["target_fat"]
    grouped["adherence_score"] = grouped.apply(_adherence_score, axis=1)
    grouped["notes"] = ""

    for column in OPTIONAL_MICROS:
        grouped[column] = grouped[column].where(grouped[column] > 0, pd.NA)

    return grouped[SUMMARY_COLUMNS].sort_values("date").reset_index(drop=True)


def save_daily_nutrition_summary(summary_df: pd.DataFrame) -> None:
    """Persist daily nutrition summaries locally."""
    DAILY_NUTRITION_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary_df = summary_df.copy() if summary_df is not None else _empty_summary()
    for column in SUMMARY_COLUMNS:
        if column not in summary_df.columns:
            summary_df[column] = pd.NA
    summary_df[SUMMARY_COLUMNS].to_csv(DAILY_NUTRITION_SUMMARY_PATH, index=False)


def load_daily_nutrition_summary() -> pd.DataFrame:
    """Load persisted daily nutrition summary data."""
    if not DAILY_NUTRITION_SUMMARY_PATH.exists():
        return _empty_summary()
    summary_df = pd.read_csv(DAILY_NUTRITION_SUMMARY_PATH)
    for column in SUMMARY_COLUMNS:
        if column not in summary_df.columns:
            summary_df[column] = pd.NA
    return summary_df[SUMMARY_COLUMNS]


def get_nutrition_history(days: int = 30) -> pd.DataFrame:
    """Return recent day-level nutrition summaries."""
    summary_df = load_daily_nutrition_summary()
    if summary_df.empty:
        return summary_df
    summary_df = summary_df.copy()
    summary_df["date"] = pd.to_datetime(summary_df["date"], errors="coerce")
    summary_df = summary_df.dropna(subset=["date"]).sort_values("date", ascending=False)
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=max(days, 1) - 1)
    summary_df = summary_df[summary_df["date"] >= cutoff]
    summary_df["date"] = summary_df["date"].dt.date.astype(str)
    return summary_df.sort_values("date").reset_index(drop=True)


def calculate_calorie_adherence(summary_df: pd.DataFrame, days: int = 7) -> dict:
    """Summarize recent calorie and protein target adherence."""
    if summary_df.empty:
        return {
            "average_calories": None,
            "average_target_calories": None,
            "average_calories_delta": None,
            "average_protein": None,
            "average_target_protein": None,
            "average_protein_delta": None,
            "days_over_target": 0,
            "days_under_target": 0,
            "consistency_score": None,
        }

    df = summary_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").tail(max(days, 1))
    for column in ["total_calories", "target_calories", "total_protein", "target_protein", "adherence_score"]:
        df[column] = pd.to_numeric(df.get(column), errors="coerce")
    with_targets = df.dropna(subset=["target_calories"])
    protein_targets = df.dropna(subset=["target_protein"])

    return {
        "average_calories": round(float(df["total_calories"].mean()), 0) if not df.empty else None,
        "average_target_calories": round(float(with_targets["target_calories"].mean()), 0) if not with_targets.empty else None,
        "average_calories_delta": round(float((with_targets["total_calories"] - with_targets["target_calories"]).mean()), 0) if not with_targets.empty else None,
        "average_protein": round(float(df["total_protein"].mean()), 1) if not df.empty else None,
        "average_target_protein": round(float(protein_targets["target_protein"].mean()), 1) if not protein_targets.empty else None,
        "average_protein_delta": round(float((protein_targets["total_protein"] - protein_targets["target_protein"]).mean()), 1) if not protein_targets.empty else None,
        "days_over_target": int((with_targets["total_calories"] > with_targets["target_calories"]).sum()) if not with_targets.empty else 0,
        "days_under_target": int((with_targets["total_calories"] < with_targets["target_calories"]).sum()) if not with_targets.empty else 0,
        "consistency_score": round(float(df["adherence_score"].dropna().mean()), 1) if not df["adherence_score"].dropna().empty else None,
    }


def get_food_history_for_optimization(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Return compact summary fields used by calorie optimization engines."""
    if summary_df.empty:
        return pd.DataFrame(columns=["date", "calories", "protein", "target_calories", "target_protein", "calories_delta", "protein_delta", "adherence_score"])
    df = summary_df.copy()
    return pd.DataFrame(
        {
            "date": df["date"],
            "calories": pd.to_numeric(df["total_calories"], errors="coerce").fillna(0),
            "protein": pd.to_numeric(df["total_protein"], errors="coerce").fillna(0),
            "target_calories": pd.to_numeric(df["target_calories"], errors="coerce"),
            "target_protein": pd.to_numeric(df["target_protein"], errors="coerce"),
            "calories_delta": pd.to_numeric(df["calories_delta"], errors="coerce"),
            "protein_delta": pd.to_numeric(df["protein_delta"], errors="coerce"),
            "adherence_score": pd.to_numeric(df["adherence_score"], errors="coerce"),
        }
    )
