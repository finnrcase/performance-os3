"""Daily nutrition history aggregation for Performance OS.

Detailed food items stay in ``nutrition_log.csv``. This module builds a
separate day-level summary so dashboards, history views, and optimization
engines can reason about adherence without reimplementing aggregation logic.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.paths import processed_data_path
from src.storage import load_dataframe, save_dataframe

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
    "nutrition_logged",
    "logged_day",
    "finalized",
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


def _boolish(value) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "logged", "finalized"}


def _target_value(targets: dict | None, key: str) -> float | None:
    if not targets:
        return None
    value = targets.get(key)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def is_missing_nutrition_day(total_calories) -> bool:
    """A day with no real calorie intake is a missing food log, not a true 0.

    0-calorie days are assumed to be days the user forgot to log, unless a
    future explicit fasting/zero-day feature marks them as intentional.
    """
    try:
        return float(total_calories or 0) <= 0
    except (TypeError, ValueError):
        return True


def _adherence_score(row: pd.Series) -> float | None:
    # A missing food-log day has no real intake — it has no adherence score
    # rather than a misleading 0%.
    if is_missing_nutrition_day(row.get("total_calories")):
        return None
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
    grouped["nutrition_logged"] = ~grouped["total_calories"].apply(is_missing_nutrition_day)
    grouped["logged_day"] = grouped["nutrition_logged"]
    grouped["finalized"] = False
    grouped["notes"] = ""

    for column in OPTIONAL_MICROS:
        grouped[column] = grouped[column].where(grouped[column] > 0, pd.NA)

    return grouped[SUMMARY_COLUMNS].sort_values("date").reset_index(drop=True)


def save_daily_nutrition_summary(summary_df: pd.DataFrame) -> None:
    """Persist daily nutrition summaries locally."""
    summary_df = summary_df.copy() if summary_df is not None else _empty_summary()
    for column in SUMMARY_COLUMNS:
        if column not in summary_df.columns:
            summary_df[column] = pd.NA
    summary_df.attrs["replace_all"] = True
    save_dataframe("daily_nutrition_summary", DAILY_NUTRITION_SUMMARY_PATH, summary_df, SUMMARY_COLUMNS)


def load_daily_nutrition_summary() -> pd.DataFrame:
    """Load persisted daily nutrition summary data."""
    summary_df = load_dataframe("daily_nutrition_summary", DAILY_NUTRITION_SUMMARY_PATH, SUMMARY_COLUMNS)
    for column in SUMMARY_COLUMNS:
        if column not in summary_df.columns:
            summary_df[column] = pd.NA
    # Always recompute the missing-log flag from calories so historical rows
    # (saved before this flag existed) are backfilled correctly on read.
    summary_df["nutrition_logged"] = ~pd.to_numeric(
        summary_df["total_calories"], errors="coerce"
    ).apply(is_missing_nutrition_day)
    if "logged_day" not in summary_df.columns or summary_df["logged_day"].isna().all():
        summary_df["logged_day"] = summary_df["nutrition_logged"]
    else:
        summary_df["logged_day"] = summary_df["logged_day"].apply(_boolish)
    if "finalized" not in summary_df.columns or summary_df["finalized"].isna().all():
        # Legacy persisted summary rows predate the explicit finalized flag. Treat
        # real logged summaries as finalized so historical coaching data survives
        # the migration without rereading raw food rows.
        summary_df["finalized"] = summary_df["nutrition_logged"]
    else:
        summary_df["finalized"] = summary_df["finalized"].apply(_boolish)
    return summary_df[SUMMARY_COLUMNS]


def _calendarized_summary(summary_df: pd.DataFrame, days: int, today: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Return an explicit daily window where absent food rows are missing logs."""
    day_count = max(int(days or 1), 1)
    end = pd.to_datetime(today, errors="coerce").normalize() if today is not None else pd.Timestamp.today().normalize()
    if pd.isna(end):
        end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=day_count - 1)
    calendar = pd.DataFrame({"date": pd.date_range(start=start, end=end, freq="D")})

    if summary_df.empty:
        merged = calendar
    else:
        df = summary_df.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
        merged = calendar.merge(df, on="date", how="left")

    for column in SUMMARY_COLUMNS:
        if column not in merged.columns:
            merged[column] = pd.NA
    for column in ["total_calories", "total_protein", "total_carbs", "total_fat"]:
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0)
    for column in ["target_calories", "target_protein", "target_carbs", "target_fat", "adherence_score"]:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged["nutrition_logged"] = ~merged["total_calories"].apply(is_missing_nutrition_day)
    if "logged_day" not in merged.columns or merged["logged_day"].isna().all():
        merged["logged_day"] = merged["nutrition_logged"]
    else:
        merged["logged_day"] = merged["logged_day"].apply(_boolish)
    if "finalized" not in merged.columns or merged["finalized"].isna().all():
        merged["finalized"] = False
    else:
        merged["finalized"] = merged["finalized"].apply(_boolish)
    missing_mask = merged["total_calories"].apply(is_missing_nutrition_day)
    merged.loc[missing_mask, ["nutrition_logged", "logged_day"]] = False
    merged["date"] = merged["date"].dt.date.astype(str)
    return merged[SUMMARY_COLUMNS]


def get_nutrition_history(days: int = 30) -> pd.DataFrame:
    """Return recent day-level nutrition summaries."""
    summary_df = load_daily_nutrition_summary()
    if summary_df.empty:
        return summary_df
    return _calendarized_summary(summary_df, days).sort_values("date").reset_index(drop=True)


def finalized_nutrition_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Return only finalized real-food day summaries for coaching engines."""
    if summary_df is None or summary_df.empty:
        return _empty_summary()
    df = summary_df.copy()
    for column in SUMMARY_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df["total_calories"] = pd.to_numeric(df["total_calories"], errors="coerce").fillna(0)
    df["nutrition_logged"] = ~df["total_calories"].apply(is_missing_nutrition_day)
    df["logged_day"] = df.get("logged_day", df["nutrition_logged"]).apply(_boolish)
    df["finalized"] = df.get("finalized", False).apply(_boolish)
    df = df[df["finalized"] & df["nutrition_logged"] & df["logged_day"]].copy()
    if df.empty:
        return _empty_summary()
    return df[SUMMARY_COLUMNS].sort_values("date").reset_index(drop=True)


def get_finalized_nutrition_history(days: int = 60) -> pd.DataFrame:
    """Return a calendarized window backed only by finalized daily summaries."""
    finalized_df = finalized_nutrition_summary(load_daily_nutrition_summary())
    if finalized_df.empty:
        return _empty_summary()
    return _calendarized_summary(finalized_df, days).sort_values("date").reset_index(drop=True)


def calculate_calorie_adherence(summary_df: pd.DataFrame, days: int = 7, today: str | pd.Timestamp | None = None) -> dict:
    """Summarize recent calorie and protein adherence.

    0-calorie days are treated as missing food logs: they are excluded from
    every average and target count, and reduce the reported confidence.
    """
    empty = {
        "average_calories": None,
        "average_target_calories": None,
        "average_calories_delta": None,
        "average_protein": None,
        "average_target_protein": None,
        "average_protein_delta": None,
        "days_over_target": 0,
        "days_under_target": 0,
        "consistency_score": None,
        "logged_days": 0,
        "missing_days": 0,
        "confidence": "low",
        "data_quality_note": "No nutrition has been logged yet.",
    }
    has_finalized_column = summary_df is not None and "finalized" in summary_df.columns
    df = _calendarized_summary(summary_df, days, today=today)
    for column in ["total_calories", "target_calories", "total_protein", "target_protein", "adherence_score"]:
        df[column] = pd.to_numeric(df.get(column), errors="coerce")

    window_days = len(df)
    # Only finalized days with real intake count; 0-calorie or live days are
    # missing logs for long-term adherence and adaptive target decisions.
    if has_finalized_column and "finalized" in df.columns:
        finalized_mask = df["finalized"].apply(_boolish)
    else:
        finalized_mask = pd.Series(True, index=df.index)
    logged = df[finalized_mask & ~df["total_calories"].apply(is_missing_nutrition_day)]
    missing_days = window_days - len(logged)
    if logged.empty:
        result = dict(empty)
        result["missing_days"] = missing_days
        result["data_quality_note"] = (
            f"All {window_days} recent day(s) are missing a food log."
            if window_days
            else "No nutrition has been logged yet."
        )
        return result

    with_targets = logged.dropna(subset=["target_calories"])
    protein_targets = logged.dropna(subset=["target_protein"])
    confidence = "high" if missing_days == 0 else "medium" if missing_days <= 2 else "low"
    note = (
        f"{missing_days} missing food log(s) in the last {window_days} days."
        if missing_days
        else "All recent days have a food log."
    )

    return {
        "average_calories": round(float(logged["total_calories"].mean()), 0),
        "average_target_calories": round(float(with_targets["target_calories"].mean()), 0) if not with_targets.empty else None,
        "average_calories_delta": round(float((with_targets["total_calories"] - with_targets["target_calories"]).mean()), 0) if not with_targets.empty else None,
        "average_protein": round(float(logged["total_protein"].mean()), 1),
        "average_target_protein": round(float(protein_targets["target_protein"].mean()), 1) if not protein_targets.empty else None,
        "average_protein_delta": round(float((protein_targets["total_protein"] - protein_targets["target_protein"]).mean()), 1) if not protein_targets.empty else None,
        "days_over_target": int((with_targets["total_calories"] > with_targets["target_calories"]).sum()) if not with_targets.empty else 0,
        "days_under_target": int((with_targets["total_calories"] < with_targets["target_calories"]).sum()) if not with_targets.empty else 0,
        "consistency_score": round(float(logged["adherence_score"].dropna().mean()), 1) if not logged["adherence_score"].dropna().empty else None,
        "logged_days": int(len(logged)),
        "missing_days": int(missing_days),
        "confidence": confidence,
        "data_quality_note": note,
    }


def get_food_history_for_optimization(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Return compact summary fields used by calorie optimization engines.

    Missing food-log days (0 calories) are dropped so the adaptive nutrition,
    lean-bulk, baseline-learning and correlation engines never treat a forgotten
    log as a real under-eating day.
    """
    columns = ["date", "calories", "protein", "carbs", "fat", "target_calories", "target_protein", "calories_delta", "protein_delta", "adherence_score"]
    if summary_df.empty:
        return pd.DataFrame(columns=columns)
    df = summary_df.copy()
    df["total_calories"] = pd.to_numeric(df["total_calories"], errors="coerce")
    if "finalized" in df.columns:
        df["finalized"] = df["finalized"].apply(_boolish)
        df = df[df["finalized"]]
    df = df[~df["total_calories"].apply(is_missing_nutrition_day)]
    if df.empty:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(
        {
            "date": df["date"],
            "calories": pd.to_numeric(df["total_calories"], errors="coerce").fillna(0),
            "protein": pd.to_numeric(df["total_protein"], errors="coerce").fillna(0),
            "carbs": pd.to_numeric(df["total_carbs"], errors="coerce").fillna(0),
            "fat": pd.to_numeric(df["total_fat"], errors="coerce").fillna(0),
            "target_calories": pd.to_numeric(df["target_calories"], errors="coerce"),
            "target_protein": pd.to_numeric(df["target_protein"], errors="coerce"),
            "calories_delta": pd.to_numeric(df["calories_delta"], errors="coerce"),
            "protein_delta": pd.to_numeric(df["protein_delta"], errors="coerce"),
            "adherence_score": pd.to_numeric(df["adherence_score"], errors="coerce"),
        }
    )
