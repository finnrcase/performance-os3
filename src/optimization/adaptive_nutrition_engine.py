"""Closed-loop adaptive nutrition recommendation engine.

This module is intentionally deterministic: it turns logged body composition,
nutrition, Hevy, Strava, sleep, and recovery history into conservative macro
recommendations without hiding the reason for each decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

import pandas as pd

from src.analytics.recovery_engine import analyze_recovery_signal
from src.analytics.training_workload import analyze_hevy_performance_signal, analyze_training_workload
from src.body_metrics import canonical_daily_bodyweights
from src.nutrition_targets import (
    CUT_RATE_RANGES,
    align_macro_calories,
    calculate_bodyweight_trend_signal,
    calculate_macro_targets,
)
from src.paths import processed_data_path
from src.storage import load_document, save_document
from src.training_schedule import is_run_row, is_strength_row, load_training_schedule_profile, planned_training_for_date


NUTRITION_RECOMMENDATION_HISTORY_PATH = processed_data_path("nutrition_recommendation_history.json")

LEAN_GAIN_THRESHOLD_LB_PER_WEEK = 0.08
FAT_GAIN_RISK_THRESHOLD_LB_PER_WEEK = 0.25
BODY_FAT_GAIN_RISK_THRESHOLD_PCT_PER_WEEK = 0.2
FAT_STABLE_THRESHOLD_LB_PER_WEEK = 0.18
BODY_FAT_STABLE_THRESHOLD_PCT_PER_WEEK = 0.12
BODY_COMP_OUTLIER_MAX_DAILY_PCT_CHANGE = 4.0
NUTRITION_TARGET_BAND_CALORIES = 125
NUTRITION_OVER_UNDER_THRESHOLD_CALORIES = 150


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    number = _to_float(value)
    return int(round(number)) if number is not None else default


def _current_value(targets: dict | None, key: str, fallback: int) -> int:
    value = _to_int((targets or {}).get(key), fallback)
    return value if value > 0 else fallback


def _first_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    return next((column for column in candidates if column in df.columns), None)


def _date_clean(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame()
    output = df.copy()
    output["date"] = pd.to_datetime(output["date"], errors="coerce").dt.normalize()
    return output.dropna(subset=["date"]).sort_values("date")


def _analysis_date(today: str | None, *frames: pd.DataFrame | None) -> pd.Timestamp:
    if today:
        parsed = pd.to_datetime(today, errors="coerce")
        if not pd.isna(parsed):
            return parsed.normalize()
    dates = []
    for frame in frames:
        cleaned = _date_clean(frame)
        if not cleaned.empty:
            dates.append(cleaned["date"].max())
    if dates:
        return max(dates).normalize()
    return pd.Timestamp.today().normalize()


def _days_since_latest(df: pd.DataFrame, analysis_day: pd.Timestamp) -> int | None:
    if df.empty:
        return None
    return int((analysis_day - df["date"].max()).days)


def _confidence_from_weeks(weeks: int) -> str:
    if weeks >= 8:
        return "high"
    if weeks >= 4:
        return "medium"
    return "low"


def load_nutrition_recommendation_history() -> dict:
    """Load saved adaptive recommendation history."""
    return load_document("nutrition_recommendation_history", NUTRITION_RECOMMENDATION_HISTORY_PATH, {"items": []})


def save_nutrition_recommendation_history(history: dict) -> dict:
    """Persist adaptive recommendation history."""
    items = history.get("items", [])
    if not isinstance(items, list):
        items = []
    return save_document("nutrition_recommendation_history", NUTRITION_RECOMMENDATION_HISTORY_PATH, {"items": items[-250:]})


def append_nutrition_recommendation_history(entry: dict) -> dict:
    """Append one target-change event while preserving previous target context."""
    history = load_nutrition_recommendation_history()
    items = history.get("items", [])
    if not isinstance(items, list):
        items = []
    safe_entry = json.loads(json.dumps(entry, default=str))
    items.append({**safe_entry, "recorded_at": safe_entry.get("recorded_at") or datetime.now(timezone.utc).isoformat()})
    return save_nutrition_recommendation_history({"items": items})


def _daily_nutrition(nutrition_df: pd.DataFrame | None, days: int | None = None) -> pd.DataFrame:
    columns = ["date", "calories", "protein", "carbs", "fat", "fiber", "sodium"]
    df = _date_clean(nutrition_df)
    if df.empty:
        return pd.DataFrame(columns=columns)
    if days is not None:
        latest = df["date"].max()
        df = df[df["date"] >= latest - pd.Timedelta(days=days - 1)].copy()
    source_map = {
        "calories": ["total_calories", "calories"],
        "protein": ["total_protein", "protein"],
        "carbs": ["total_carbs", "carbs"],
        "fat": ["total_fat", "fat"],
        "fiber": ["fiber", "total_fiber"],
        "sodium": ["sodium", "total_sodium"],
    }
    prepared = pd.DataFrame({"date": df["date"]})
    for target, candidates in source_map.items():
        source = _first_column(df, candidates)
        prepared[target] = pd.to_numeric(df[source], errors="coerce").fillna(0) if source else 0
    return (
        prepared.groupby("date", as_index=False)
        .agg(
            calories=("calories", "sum"),
            protein=("protein", "sum"),
            carbs=("carbs", "sum"),
            fat=("fat", "sum"),
            fiber=("fiber", "sum"),
            sodium=("sodium", "sum"),
        )
        .sort_values("date")
    )


def _nutrition_average(nutrition_df: pd.DataFrame | None, days: int = 14) -> dict:
    daily = _daily_nutrition(nutrition_df, days=days)
    if daily.empty:
        return {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None}
    return {
        "days": int(len(daily)),
        "calories": round(float(daily["calories"].mean()), 0),
        "protein": round(float(daily["protein"].mean()), 1),
        "carbs": round(float(daily["carbs"].mean()), 1),
        "fat": round(float(daily["fat"].mean()), 1),
    }


def _clean_body_composition(body_metrics_df: pd.DataFrame | None, user_goals: dict) -> pd.DataFrame:
    df = canonical_daily_bodyweights(body_metrics_df)
    if df.empty:
        return pd.DataFrame(columns=["date", "bodyweight", "body_fat_percent", "lean_mass", "fat_mass", "body_comp_outlier"])
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df["bodyweight"] = pd.to_numeric(df.get("bodyweight"), errors="coerce")
    body_fat_column = _first_column(df, ["estimated_body_fat", "body_fat_percent", "bodyfat", "body_fat"])
    if body_fat_column:
        df["body_fat_percent"] = pd.to_numeric(df[body_fat_column], errors="coerce")
    else:
        df["body_fat_percent"] = pd.NA
    df = df.dropna(subset=["bodyweight"]).copy()
    df["body_fat_percent"] = pd.to_numeric(df["body_fat_percent"], errors="coerce")
    df.loc[df["body_fat_percent"] <= 1, "body_fat_percent"] = df["body_fat_percent"] * 100
    valid_body_fat = df["body_fat_percent"].between(3, 60)
    df.loc[~valid_body_fat, "body_fat_percent"] = pd.NA
    df["body_comp_outlier"] = False
    if df["body_fat_percent"].notna().sum() >= 3:
        body_fat_change = df["body_fat_percent"].diff().abs()
        outliers = body_fat_change > BODY_COMP_OUTLIER_MAX_DAILY_PCT_CHANGE
        df.loc[outliers, ["body_fat_percent"]] = pd.NA
        df.loc[outliers, "body_comp_outlier"] = True
    lean_mass_column = _first_column(df, ["lean_mass", "fat_free_mass"])
    fat_mass_column = _first_column(df, ["fat_mass"])
    measured_lean = pd.to_numeric(df[lean_mass_column], errors="coerce") if lean_mass_column else pd.Series(float("nan"), index=df.index, dtype="float64")
    measured_fat = pd.to_numeric(df[fat_mass_column], errors="coerce") if fat_mass_column else pd.Series(float("nan"), index=df.index, dtype="float64")
    df["lean_mass"] = measured_lean.combine_first(df["bodyweight"] * (1 - (df["body_fat_percent"] / 100)))
    df["fat_mass"] = measured_fat.combine_first(df["bodyweight"] * (df["body_fat_percent"] / 100))
    return df[["date", "bodyweight", "body_fat_percent", "lean_mass", "fat_mass", "body_comp_outlier"]].sort_values("date")


def _window_average(df: pd.DataFrame, column: str, days: int) -> float | None:
    if df.empty or column not in df.columns:
        return None
    latest = df["date"].max()
    values = pd.to_numeric(df[df["date"] >= latest - pd.Timedelta(days=days - 1)][column], errors="coerce").dropna()
    return round(float(values.mean()), 2) if not values.empty else None


def _window_weekly_delta(df: pd.DataFrame, column: str, days: int) -> float | None:
    if df.empty or column not in df.columns:
        return None
    latest = df["date"].max()
    current = pd.to_numeric(df[df["date"] >= latest - pd.Timedelta(days=days - 1)][column], errors="coerce").dropna()
    previous = pd.to_numeric(
        df[(df["date"] < latest - pd.Timedelta(days=days - 1)) & (df["date"] >= latest - pd.Timedelta(days=(days * 2) - 1))][column],
        errors="coerce",
    ).dropna()
    if len(current) < max(2, min(days // 2, 4)) or len(previous) < max(2, min(days // 2, 4)):
        return None
    return round((float(current.mean()) - float(previous.mean())) * (7 / days), 3)


def _body_composition_trends(body_metrics_df: pd.DataFrame | None, user_goals: dict, weight_signal: dict) -> dict:
    df = _clean_body_composition(body_metrics_df, user_goals)
    empty = {
        "status": "insufficient data",
        "data_points": 0,
        "body_fat_data_points": 0,
        "latest_bodyweight": None,
        "latest_body_fat_percent": None,
        "latest_lean_mass": None,
        "latest_fat_mass": None,
        "weight_7_day_average": None,
        "weight_14_day_average": None,
        "weight_28_day_average": None,
        "weight_gain_rate_lb_per_week": weight_signal.get("weekly_change_lb"),
        "weight_gain_rate_pct_per_week": weight_signal.get("weekly_change_pct"),
        "lean_mass_trend_7": None,
        "lean_mass_trend_14": None,
        "lean_mass_trend_28": None,
        "fat_mass_trend_7": None,
        "fat_mass_trend_14": None,
        "fat_mass_trend_28": None,
        "body_fat_percent_trend_14": None,
        "body_fat_percent_trend_28": None,
        "lean_gain_quality": "unknown",
        "body_comp_confidence": "low",
        "body_fat_trend_source": "measured_body_metric_rows",
        "saved_body_fat_estimate": _to_float(user_goals.get("estimated_body_fat")),
        "saved_body_fat_used_for_trend": False,
        "dropped_body_comp_outliers": 0,
        "thresholds": {
            "lean_gain_threshold_lb_per_week": LEAN_GAIN_THRESHOLD_LB_PER_WEEK,
            "fat_gain_risk_threshold_lb_per_week": FAT_GAIN_RISK_THRESHOLD_LB_PER_WEEK,
            "body_fat_gain_risk_threshold_pct_per_week": BODY_FAT_GAIN_RISK_THRESHOLD_PCT_PER_WEEK,
            "fat_stable_threshold_lb_per_week": FAT_STABLE_THRESHOLD_LB_PER_WEEK,
            "body_fat_stable_threshold_pct_per_week": BODY_FAT_STABLE_THRESHOLD_PCT_PER_WEEK,
        },
    }
    if df.empty:
        return empty
    latest = df.iloc[-1]
    output = {
        **empty,
        "data_points": int(len(df)),
        "body_fat_data_points": int(df["body_fat_percent"].notna().sum()),
        "dropped_body_comp_outliers": int(df.get("body_comp_outlier", pd.Series(dtype=bool)).fillna(False).sum()),
        "latest_bodyweight": round(float(latest["bodyweight"]), 2),
        "latest_body_fat_percent": round(float(latest["body_fat_percent"]), 2) if pd.notna(latest["body_fat_percent"]) else None,
        "latest_lean_mass": round(float(latest["lean_mass"]), 2) if pd.notna(latest["lean_mass"]) else None,
        "latest_fat_mass": round(float(latest["fat_mass"]), 2) if pd.notna(latest["fat_mass"]) else None,
        "weight_7_day_average": _window_average(df, "bodyweight", 7),
        "weight_14_day_average": _window_average(df, "bodyweight", 14),
        "weight_28_day_average": _window_average(df, "bodyweight", 28),
        "lean_mass_trend_7": _window_weekly_delta(df, "lean_mass", 7),
        "lean_mass_trend_14": _window_weekly_delta(df, "lean_mass", 14),
        "lean_mass_trend_28": _window_weekly_delta(df, "lean_mass", 28),
        "fat_mass_trend_7": _window_weekly_delta(df, "fat_mass", 7),
        "fat_mass_trend_14": _window_weekly_delta(df, "fat_mass", 14),
        "fat_mass_trend_28": _window_weekly_delta(df, "fat_mass", 28),
        "body_fat_percent_trend_14": _window_weekly_delta(df, "body_fat_percent", 14),
        "body_fat_percent_trend_28": _window_weekly_delta(df, "body_fat_percent", 28),
    }
    lean_trend = output["lean_mass_trend_14"] if output["lean_mass_trend_14"] is not None else output["lean_mass_trend_28"]
    fat_trend = output["fat_mass_trend_14"] if output["fat_mass_trend_14"] is not None else output["fat_mass_trend_28"]
    body_fat_trend = output["body_fat_percent_trend_14"] if output["body_fat_percent_trend_14"] is not None else output["body_fat_percent_trend_28"]

    if output["body_fat_data_points"] >= 10:
        output["body_comp_confidence"] = "high"
    elif output["body_fat_data_points"] >= 4:
        output["body_comp_confidence"] = "medium"
    else:
        output["body_comp_confidence"] = "low"

    if output["body_fat_data_points"] < 4:
        quality = "body fat missing"
        status = "body composition incomplete"
    elif (lean_trend or 0) > LEAN_GAIN_THRESHOLD_LB_PER_WEEK and (fat_trend or 0) <= FAT_STABLE_THRESHOLD_LB_PER_WEEK and (body_fat_trend or 0) <= BODY_FAT_STABLE_THRESHOLD_PCT_PER_WEEK:
        quality = "lean mass improving"
        status = "lean gain"
    elif (fat_trend or 0) >= FAT_GAIN_RISK_THRESHOLD_LB_PER_WEEK or (body_fat_trend or 0) >= BODY_FAT_GAIN_RISK_THRESHOLD_PCT_PER_WEEK:
        quality = "fat gain rising"
        status = "fat gain risk"
    elif (lean_trend or 0) <= -0.05 and (fat_trend or 0) >= 0.1:
        quality = "poor partitioning"
        status = "fat gain risk"
    elif output["body_fat_data_points"] >= 4:
        quality = "stable composition"
        status = "stable"
    else:
        quality = "unknown"
        status = "insufficient data"
    output["lean_gain_quality"] = quality
    output["status"] = status
    return output


def _training_load_signal(workload: dict) -> dict:
    current = workload.get("current", {})
    windows = workload.get("windows", {})
    hevy = windows.get("28", {}).get("hevy", {})
    sets = float(hevy.get("hard_sets_per_week") or hevy.get("total_sets_per_week") or 0)
    minutes = float(current.get("weekly_training_minutes") or 0)
    if sets >= 95 or minutes >= 450:
        status = "unusually high"
    elif sets >= 65 or minutes >= 300:
        status = "high"
    elif sets >= 25 or minutes >= 120:
        status = "normal"
    else:
        status = "low"
    return {
        "status": status,
        "hard_sets_per_week": round(sets, 1),
        "weekly_training_minutes": round(minutes, 1),
        "summary": f"{round(sets, 1)} hard sets/week and {round(minutes, 1)} training minutes/week.",
    }


def _running_load_signal(workload: dict, performance_signal: dict | None = None) -> dict:
    current = workload.get("current", {})
    miles = float(current.get("weekly_mileage") or 0)
    runs = float(current.get("runs_per_week") or 0)
    performance_label = str((performance_signal or {}).get("label") or "insufficient data")
    if miles >= 25 or runs >= 5:
        status = "unusually high"
    elif miles >= 14 or runs >= 3:
        status = "high"
    elif miles >= 4 or runs >= 1:
        status = "normal"
    else:
        status = "low"
    interference = status in {"high", "unusually high"} and performance_label in {"declining", "fatigue/performance stagnation"}
    return {
        "status": status,
        "runs_per_week": round(runs, 2),
        "weekly_mileage": round(miles, 1),
        "interference_risk": "elevated" if interference else "low",
        "summary": f"{round(runs, 2)} runs/week and {round(miles, 1)} miles/week.",
    }


def _is_hevy_row(row: pd.Series, profile: dict | None = None) -> bool:
    return is_strength_row(row, profile=profile)


def _is_run_row(row: pd.Series, profile: dict | None = None) -> bool:
    return is_run_row(row, profile=profile)


def _is_lower_body_training(df: pd.DataFrame) -> bool:
    lower_terms = [
        "leg",
        "quad",
        "hamstring",
        "glute",
        "calf",
        "squat",
        "deadlift",
        "lunge",
        "lower",
    ]
    text = " ".join(
        str(value).lower()
        for column in ["exercise", "muscle_group", "workout_type", "title", "notes"]
        if column in df.columns
        for value in df[column].fillna("").tolist()
    )
    return any(term in text for term in lower_terms)


def _detect_day_type(training_df: pd.DataFrame | None, workload: dict, recovery_signal: dict, analysis_day: pd.Timestamp) -> dict:
    profile = load_training_schedule_profile()
    planned = planned_training_for_date(analysis_day, profile=profile)
    df = _date_clean(training_df)
    today_rows = df[df["date"] == analysis_day].copy() if not df.empty else pd.DataFrame()
    lift_rows = today_rows[today_rows.apply(lambda row: _is_hevy_row(row, profile=profile), axis=1)] if not today_rows.empty else pd.DataFrame()
    run_rows = today_rows[today_rows.apply(lambda row: _is_run_row(row, profile=profile), axis=1)] if not today_rows.empty else pd.DataFrame()
    for column in ["sets", "duration_minutes"]:
        if column not in lift_rows.columns:
            lift_rows[column] = 0
        if column not in run_rows.columns:
            run_rows[column] = 0
    hard_sets_today = float(pd.to_numeric(lift_rows.get("sets", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not lift_rows.empty else 0
    run_minutes_today = float(pd.to_numeric(run_rows.get("duration_minutes", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()) if not run_rows.empty else 0
    training_load = _training_load_signal(workload)
    running_current = (workload.get("current") or {}).get("weekly_mileage") or 0
    recovery_status = str(recovery_signal.get("status") or "insufficient data")

    if recovery_status == "poor":
        return {
            "type": "High fatigue day",
            "reason": "Recovery is poor, so the engine keeps calories conservative and biases carbs around training.",
            "calorie_delta": 0,
            "carb_delta": 20,
            "fat_delta": -5,
            "confidence": recovery_signal.get("confidence", "low"),
        }
    if not lift_rows.empty and _is_lower_body_training(lift_rows):
        return {
            "type": "Leg day",
            "reason": "Lower-body Hevy work is logged today, so carbs get the largest training-day lift.",
            "calorie_delta": 150,
            "carb_delta": 55,
            "fat_delta": -8,
            "confidence": "high" if hard_sets_today >= 10 else "medium",
        }
    if hard_sets_today >= 14 or training_load["status"] in {"high", "unusually high"} and not lift_rows.empty:
        return {
            "type": "Heavy lifting day",
            "reason": "Today has high lifting demand, so the daily target shifts toward carbs.",
            "calorie_delta": 125,
            "carb_delta": 35,
            "fat_delta": -4,
            "confidence": "medium",
        }
    if not lift_rows.empty:
        return {
            "type": "Moderate lifting day",
            "reason": "A lifting session is logged today, so carbs are nudged up without changing protein.",
            "calorie_delta": 75,
            "carb_delta": 22,
            "fat_delta": -2,
            "confidence": "medium",
        }
    if not run_rows.empty or float(running_current) >= 8 or run_minutes_today >= 30:
        return {
            "type": "Run/cardio-focused day",
            "reason": "Run/cardio load is the main workload signal, so the day gets a smaller carb-focused bump.",
            "calorie_delta": 75,
            "carb_delta": 30,
            "fat_delta": -5,
            "confidence": "medium" if not run_rows.empty else "low",
        }
    if recovery_status == "strained":
        return {
            "type": "High fatigue day",
            "reason": "Recovery is strained and no hard session is logged, so the target avoids a bigger surplus.",
            "calorie_delta": -50,
            "carb_delta": -10,
            "fat_delta": 0,
            "confidence": recovery_signal.get("confidence", "low"),
        }
    if planned["is_leg_day"]:
        return {
            "type": "Leg day",
            "reason": f"{planned['display_label']} is planned in the recurring split, so carbs are biased toward lower-body demand.",
            "calorie_delta": int(planned.get("calorie_delta") or 150),
            "carb_delta": int(planned.get("carb_delta") or 55),
            "fat_delta": -8,
            "confidence": "low",
        }
    if planned["is_run_day"]:
        return {
            "type": "Run/cardio-focused day",
            "reason": f"{planned['display_label']} is planned in the recurring split, so the day gets a carb-focused run adjustment.",
            "calorie_delta": int(planned.get("calorie_delta") or 75),
            "carb_delta": int(planned.get("carb_delta") or 30),
            "fat_delta": -5,
            "confidence": "low",
        }
    if planned["is_strength_day"]:
        return {
            "type": "Moderate lifting day",
            "reason": f"{planned['display_label']} is planned in the recurring split, so the day gets a moderate lifting adjustment.",
            "calorie_delta": int(planned.get("calorie_delta") or 75),
            "carb_delta": int(planned.get("carb_delta") or 22),
            "fat_delta": -2,
            "confidence": "low",
        }
    return {
        "type": "Recovery/rest day",
        "reason": "No hard lifting or run is logged today, so calories and carbs can sit slightly below training days.",
        "calorie_delta": -100,
        "carb_delta": -25,
        "fat_delta": 0,
        "confidence": "medium",
    }


def _daily_training(training_df: pd.DataFrame | None) -> pd.DataFrame:
    df = _date_clean(training_df)
    if df.empty:
        return pd.DataFrame(columns=["date", "weekday", "volume", "sets", "duration_minutes", "run_only", "has_lift", "has_run", "lower_body"])
    for column in ["sets", "reps", "weight", "duration_minutes"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    profile = load_training_schedule_profile()
    df["is_lift"] = df.apply(lambda row: _is_hevy_row(row, profile=profile), axis=1)
    df["is_run"] = df.apply(lambda row: _is_run_row(row, profile=profile), axis=1)
    df["volume"] = df["sets"].clip(lower=0) * df["reps"].clip(lower=0) * df["weight"].clip(lower=0)
    rows = []
    for date_value, day_df in df.groupby("date"):
        has_lift = bool(day_df["is_lift"].any())
        has_run = bool(day_df["is_run"].any())
        rows.append(
            {
                "date": date_value,
                "weekday": date_value.day_name(),
                "volume": float(day_df.loc[day_df["is_lift"], "volume"].sum()),
                "sets": float(day_df.loc[day_df["is_lift"], "sets"].sum()),
                "duration_minutes": float(day_df["duration_minutes"].sum()),
                "run_only": has_run and not has_lift,
                "has_lift": has_lift,
                "has_run": has_run,
                "lower_body": bool(has_lift and _is_lower_body_training(day_df)),
            }
        )
    return pd.DataFrame(rows).sort_values("date")


def _day_of_week_learning(
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    analysis_day: pd.Timestamp,
) -> tuple[dict, str, list[str]]:
    daily_nutrition = _daily_nutrition(nutrition_df)
    daily_training = _daily_training(training_df)
    weekday = analysis_day.day_name()
    default = {
        "weekday": weekday,
        "calorie_delta": 0,
        "carb_delta": 0,
        "confidence": "low",
        "reason": "Need at least three comparable weeks before day-specific macro learning is trusted.",
        "comparable_weeks": 0,
    }
    if daily_training.empty:
        return default, "Place most carbs in the meals before and after harder sessions once workout patterns are available.", []

    trends: list[str] = []
    daily = daily_training.merge(daily_nutrition[["date", "calories", "carbs"]], on="date", how="left")
    weekday_rows = daily[daily["weekday"] == weekday].copy()
    comparable_weeks = int(weekday_rows["date"].dt.isocalendar().week.nunique()) if not weekday_rows.empty else 0
    confidence = _confidence_from_weeks(comparable_weeks)
    adjustment = {**default, "confidence": confidence, "comparable_weeks": comparable_weeks}
    timing = "Keep carbs near training; the engine will sharpen timing once comparable weeks accumulate."

    if comparable_weeks >= 3 and not weekday_rows.empty:
        run_only_ratio = float(weekday_rows["run_only"].mean())
        if weekday == "Sunday" and run_only_ratio >= 0.6:
            adjustment.update(
                {
                    "calorie_delta": -125,
                    "carb_delta": -20,
                    "reason": "Sunday is usually run-only/no-lift, so baseline calories can sit 100-150 lower while protein stays stable.",
                }
            )
            trends.append("Sunday is usually run-only, so calories can be 100-150 lower while protein stays stable.")
            timing = "Use carbs before the run and keep the rest of the day protein-forward."

        if "carbs" in weekday_rows.columns and weekday_rows["carbs"].notna().sum() >= 3 and weekday_rows["has_lift"].any():
            overall_carb_average = float(daily["carbs"].dropna().mean()) if daily["carbs"].notna().any() else 0
            weekday_carb_average = float(weekday_rows["carbs"].dropna().mean())
            weekday_volume = float(weekday_rows["volume"].mean())
            overall_volume = float(daily[daily["has_lift"]]["volume"].mean()) if daily["has_lift"].any() else 0
            if weekday_carb_average >= overall_carb_average + 25 and weekday_volume >= overall_volume * 1.05:
                threshold = int(round(weekday_carb_average / 10) * 10)
                adjustment.update(
                    {
                        "carb_delta": max(int(adjustment["carb_delta"]), 25),
                        "reason": f"{weekday} sessions have performed better when carbs are around {threshold}g+.",
                    }
                )
                trends.append(f"{weekday} sessions perform better when carbs are above {threshold}g.")
                timing = f"For {weekday} lifting, bias carbs before training and keep total carbs near {threshold}g+ when recovery is normal."

        leg_rows = daily[daily["lower_body"]].copy()
        if len(leg_rows) >= 3 and not daily_nutrition.empty:
            previous_carbs = []
            for date_value in leg_rows["date"]:
                previous_day = date_value - pd.Timedelta(days=1)
                previous = daily_nutrition[daily_nutrition["date"] == previous_day]
                if not previous.empty:
                    previous_carbs.append(float(previous.iloc[-1]["carbs"]))
            if len(previous_carbs) >= 3:
                avg_previous = sum(previous_carbs) / len(previous_carbs)
                avg_daily = float(daily_nutrition["carbs"].mean()) if not daily_nutrition.empty else 0
                if avg_previous >= avg_daily + 20:
                    trends.append(f"Leg days tend to follow higher-carb days; previous-day carbs average about {avg_previous:.0f}g.")
                    if weekday_rows["lower_body"].any():
                        timing = "Keep carbs high the day before and the day of lower-body sessions."

    return adjustment, timing, trends


def _sleep_available(sleep_df: pd.DataFrame | None, recovery_df: pd.DataFrame | None) -> bool:
    sleep_clean = _date_clean(sleep_df)
    if not sleep_clean.empty:
        return True
    recovery_clean = _date_clean(recovery_df)
    return not recovery_clean.empty and "sleep_hours" in recovery_clean.columns and pd.to_numeric(recovery_clean["sleep_hours"], errors="coerce").notna().any()


def _data_quality_score(
    body_metrics_df: pd.DataFrame | None,
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None,
    sleep_df: pd.DataFrame | None,
    user_goals: dict,
    analysis_day: pd.Timestamp,
) -> dict:
    body = _clean_body_composition(body_metrics_df, user_goals)
    nutrition = _daily_nutrition(nutrition_df)
    training = _date_clean(training_df)
    recovery = _date_clean(recovery_df)
    score = 0
    warnings: list[str] = []

    recent_body = body[body["date"] >= analysis_day - pd.Timedelta(days=6)]
    body_days = int(recent_body["date"].nunique()) if not recent_body.empty else 0
    score += min(25, round(body_days / 5 * 25))
    last_weigh_in = _days_since_latest(body, analysis_day)
    if last_weigh_in is None:
        warnings.append("No bodyweight data is logged yet.")
    elif last_weigh_in >= 3:
        warnings.append(f"No weigh-in for {last_weigh_in} days.")

    body_fat_recent = body[(body["date"] >= analysis_day - pd.Timedelta(days=13)) & body["body_fat_percent"].notna()]
    score += 15 if len(body_fat_recent) >= 2 else 7 if body["body_fat_percent"].notna().any() else 0
    if body_fat_recent.empty:
        warnings.append("No body fat data in the last 14 days.")

    recent_food = nutrition[nutrition["date"] >= analysis_day - pd.Timedelta(days=6)]
    food_days = int(recent_food[recent_food["calories"] > 0]["date"].nunique()) if not recent_food.empty else 0
    score += min(20, round(food_days / 5 * 20))
    if food_days == 0:
        warnings.append("No food logs in the last 7 days.")
    elif food_days < 5:
        warnings.append("Food logging is incomplete this week.")
    yesterday = analysis_day - pd.Timedelta(days=1)
    if nutrition.empty or nutrition[nutrition["date"] == yesterday].empty:
        warnings.append("No food log yesterday.")

    recent_training = training[training["date"] >= analysis_day - pd.Timedelta(days=13)] if not training.empty else pd.DataFrame()
    profile = load_training_schedule_profile()
    hevy_recent = recent_training[recent_training.apply(lambda row: _is_hevy_row(row, profile=profile), axis=1)] if not recent_training.empty else pd.DataFrame()
    hevy_days = int(hevy_recent["date"].nunique()) if not hevy_recent.empty and "date" in hevy_recent.columns else 0
    score += 15 if hevy_days >= 2 else 8 if hevy_days else 0
    if hevy_recent.empty and int(user_goals.get("training_frequency_per_week") or 0) > 0:
        warnings.append("No recent Hevy/lifting sync found.")

    run_recent = recent_training[recent_training.apply(lambda row: _is_run_row(row, profile=profile), axis=1)] if not recent_training.empty else pd.DataFrame()
    expected_cardio = int(user_goals.get("cardio_frequency_per_week") or 0)
    if expected_cardio <= 0:
        score += 8
    else:
        score += 8 if not run_recent.empty else 0
        if run_recent.empty:
            warnings.append("No recent Strava/cardio data found.")

    if _sleep_available(sleep_df, recovery_df):
        score += 9
    else:
        warnings.append("Sleep data is unavailable.")

    recent_recovery = recovery[recovery["date"] >= analysis_day - pd.Timedelta(days=6)] if not recovery.empty else pd.DataFrame()
    score += 8 if len(recent_recovery) >= 2 else 4 if not recent_recovery.empty else 0
    if recent_recovery.empty:
        warnings.append("No recovery/readiness check-ins this week.")

    label = "high" if score >= 75 else "medium" if score >= 40 else "low"
    return {"score": int(min(100, max(0, score))), "confidence": label, "missingDataWarnings": warnings[:8]}


def _confidence_label(points: int, high: int, medium: int) -> str:
    if points >= high:
        return "high"
    if points >= medium:
        return "medium"
    return "low"


def _structured_confidence(
    *,
    body_metrics_df: pd.DataFrame | None,
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None,
    sleep_df: pd.DataFrame | None,
    user_goals: dict,
    analysis_day: pd.Timestamp,
    data_quality: dict,
) -> dict:
    nutrition = _daily_nutrition(nutrition_df)
    body = _clean_body_composition(body_metrics_df, user_goals)
    training = _date_clean(training_df)
    recovery = _date_clean(recovery_df)
    sleep = _date_clean(sleep_df)
    missing: list[str] = list(data_quality.get("missingDataWarnings") or [])

    recent_food = nutrition[nutrition["date"] >= analysis_day - pd.Timedelta(days=13)] if not nutrition.empty else pd.DataFrame()
    food_days = int(recent_food[recent_food["calories"] > 0]["date"].nunique()) if not recent_food.empty else 0
    nutrition_confidence = _confidence_label(food_days, high=10, medium=5)
    if food_days < 10:
        missing.append(f"Only {food_days}/14 recent finalized nutrition days are available.")

    recent_body = body[body["date"] >= analysis_day - pd.Timedelta(days=27)] if not body.empty else pd.DataFrame()
    body_days = int(recent_body["date"].nunique()) if not recent_body.empty else 0
    body_comp_days = int(recent_body["body_fat_percent"].notna().sum()) if not recent_body.empty and "body_fat_percent" in recent_body.columns else 0
    body_score = body_days + min(body_comp_days * 2, 10)
    body_confidence = _confidence_label(body_score, high=24, medium=10)
    if body_days < 10:
        missing.append(f"Only {body_days}/28 recent canonical weigh-ins are available.")
    if body_comp_days < 4:
        missing.append("Body composition trend is sparse.")

    recent_training = training[training["date"] >= analysis_day - pd.Timedelta(days=27)] if not training.empty else pd.DataFrame()
    profile = load_training_schedule_profile()
    lift_rows = recent_training[recent_training.apply(lambda row: _is_hevy_row(row, profile=profile), axis=1)] if not recent_training.empty else pd.DataFrame()
    lift_days = int(lift_rows["date"].nunique()) if not lift_rows.empty and "date" in lift_rows.columns else 0
    training_confidence = _confidence_label(lift_days, high=8, medium=3)
    if lift_days < 3 and int(user_goals.get("training_frequency_per_week") or 0) > 0:
        missing.append("Recent Hevy lifting history is limited.")

    recent_recovery = recovery[recovery["date"] >= analysis_day - pd.Timedelta(days=13)] if not recovery.empty else pd.DataFrame()
    recent_sleep = sleep[sleep["date"] >= analysis_day - pd.Timedelta(days=13)] if not sleep.empty else pd.DataFrame()
    recovery_days = int(recent_recovery["date"].nunique()) if not recent_recovery.empty else 0
    sleep_days = int(recent_sleep["date"].nunique()) if not recent_sleep.empty else 0
    if sleep_days == 0 and not recent_recovery.empty and "sleep_hours" in recent_recovery.columns:
        sleep_days = int(recent_recovery[pd.to_numeric(recent_recovery["sleep_hours"], errors="coerce").notna()]["date"].nunique())
    recovery_confidence = _confidence_label(max(recovery_days, sleep_days), high=10, medium=4)
    if recovery_confidence == "low":
        missing.append("Recovery or sleep trend is sparse.")

    labels = [nutrition_confidence, body_confidence, training_confidence, recovery_confidence]
    high_count = labels.count("high")
    low_count = labels.count("low")
    overall = "high" if high_count >= 3 and low_count == 0 and data_quality.get("score", 0) >= 75 else "medium" if low_count <= 1 and data_quality.get("score", 0) >= 40 else "low"
    return {
        "nutrition": nutrition_confidence,
        "body": body_confidence,
        "training": training_confidence,
        "recovery": recovery_confidence,
        "overall": overall,
        "missing_data": list(dict.fromkeys(missing))[:10],
    }


def _nutrition_signal(nutrition_average: dict, current: dict, analysis_day: pd.Timestamp, nutrition_df: pd.DataFrame | None) -> dict:
    daily = _daily_nutrition(nutrition_df, days=14)
    logged_days = int(nutrition_average.get("days") or 0)
    target_calories = float(current.get("target_calories") or 0)
    avg_calories = _to_float(nutrition_average.get("calories"))
    avg_protein = _to_float(nutrition_average.get("protein"))
    avg_carbs = _to_float(nutrition_average.get("carbs"))
    avg_fat = _to_float(nutrition_average.get("fat"))
    calorie_delta = round(avg_calories - target_calories, 0) if avg_calories is not None and target_calories else None
    target_protein = float(current.get("protein_grams") or 0)
    protein_hit_rate = None
    if not daily.empty and target_protein:
        protein_hit_rate = round(float((daily["protein"] >= target_protein * 0.9).mean()), 2)
    missing_days = max(0, 14 - logged_days)
    adherence = "unknown"
    if calorie_delta is not None:
        if abs(calorie_delta) <= 125 and (protein_hit_rate is None or protein_hit_rate >= 0.7):
            adherence = "consistent"
        elif abs(calorie_delta) <= 250:
            adherence = "mixed"
        else:
            adherence = "inconsistent"
    return {
        "logged_days_14": logged_days,
        "missing_days_14": missing_days,
        "average_calories": avg_calories,
        "average_protein": avg_protein,
        "average_carbs": avg_carbs,
        "average_fat": avg_fat,
        "target_calories": current.get("target_calories"),
        "target_protein": current.get("protein_grams"),
        "target_carbs": current.get("carb_grams"),
        "target_fat": current.get("fat_grams"),
        "calorie_delta_vs_target": calorie_delta,
        "protein_hit_rate": protein_hit_rate,
        "adherence": adherence,
        "source": "finalized_daily_nutrition_summaries",
        "missing_days_are_zero": False,
    }


def _goal_family(user_goals: dict) -> str:
    normalized = str(user_goals.get("goal_type") or "lean bulk").replace("_", " ").strip().lower()
    if normalized in {"lean bulk", "bulk", "gain", "gain weight"}:
        return "lean_bulk"
    if normalized in {"cut", "fat loss", "lose weight", "weight loss"}:
        return "cut"
    if normalized in {"recomposition", "recomp", "body recomposition"}:
        return "recomp"
    if normalized in {"maintenance", "maintain", "hold"}:
        return "maintenance"
    return "performance" if "performance" in normalized else "maintenance"


def _goal_weight_signal(base_signal: dict, user_goals: dict) -> dict:
    family = _goal_family(user_goals)
    weekly_pct = _to_float(base_signal.get("weekly_change_pct"))
    signal = {**base_signal, "goal_type": family}
    if weekly_pct is None:
        return signal

    if family == "cut":
        aggressiveness = str(user_goals.get("aggressiveness") or "Conservative").title()
        cut_range = CUT_RATE_RANGES.get(aggressiveness, CUT_RATE_RANGES["Conservative"])
        faster_loss = min(cut_range)
        slower_loss = max(cut_range)
        signal["target_weekly_change_low"] = faster_loss
        signal["target_weekly_change_high"] = slower_loss
        if weekly_pct < faster_loss:
            signal.update(
                {
                    "status": "losing too fast",
                    "calorie_adjustment": 100,
                    "reason": f"Loss is faster than the cut target range of {faster_loss:.2f}% to {slower_loss:.2f}%/week.",
                }
            )
        elif weekly_pct > slower_loss:
            signal.update(
                {
                    "status": "losing too slowly",
                    "calorie_adjustment": -100,
                    "reason": f"Loss is slower than the cut target range of {faster_loss:.2f}% to {slower_loss:.2f}%/week.",
                }
            )
        else:
            signal.update(
                {
                    "status": "losing in target range",
                    "calorie_adjustment": 0,
                    "reason": f"Loss is inside the cut target range of {faster_loss:.2f}% to {slower_loss:.2f}%/week.",
                }
            )
    elif family in {"recomp", "maintenance", "performance"}:
        stable_band = 0.2 if family == "recomp" else 0.25
        signal["target_weekly_change_low"] = -stable_band
        signal["target_weekly_change_high"] = stable_band
        if weekly_pct > stable_band:
            signal.update(
                {
                    "status": "gaining too fast",
                    "calorie_adjustment": -75,
                    "reason": f"Weight is rising faster than the {family.replace('_', ' ')} stability band of ±{stable_band:.2f}%/week.",
                }
            )
        elif weekly_pct < -stable_band:
            signal.update(
                {
                    "status": "losing too fast",
                    "calorie_adjustment": 75,
                    "reason": f"Weight is falling faster than the {family.replace('_', ' ')} stability band of ±{stable_band:.2f}%/week.",
                }
            )
        else:
            signal.update(
                {
                    "status": "stable in target range",
                    "calorie_adjustment": 0,
                    "reason": f"Weight is inside the {family.replace('_', ' ')} stability band of ±{stable_band:.2f}%/week.",
                }
            )
    return signal


def _nutrition_state(nutrition_signal: dict, confidence_info: dict) -> str:
    logged_days = int(nutrition_signal.get("logged_days_14") or 0)
    missing_days = int(nutrition_signal.get("missing_days_14") or 0)
    delta = _to_float(nutrition_signal.get("calorie_delta_vs_target"))
    adherence = str(nutrition_signal.get("adherence") or "unknown")
    if logged_days < 5:
        return "insufficient_data"
    if confidence_info.get("nutrition") == "low" or missing_days > 5:
        return "inconsistent"
    if delta is None:
        return "insufficient_data"
    if delta >= NUTRITION_OVER_UNDER_THRESHOLD_CALORIES:
        return "over_target"
    if delta <= -NUTRITION_OVER_UNDER_THRESHOLD_CALORIES:
        return "under_target"
    if adherence == "inconsistent":
        return "inconsistent"
    return "on_target" if abs(delta) <= NUTRITION_TARGET_BAND_CALORIES else "inconsistent"


def _training_state(performance_signal: dict) -> str:
    label = str(performance_signal.get("label") or "insufficient data")
    if label in {"improving", "strong"}:
        return "improving"
    if label in {"declining", "fatigue/performance stagnation"}:
        return "declining"
    if label in {"stable"}:
        return "stable"
    return "insufficient_data"


def _recovery_state(recovery_signal: dict) -> str:
    status = str(recovery_signal.get("status") or "insufficient data")
    if status in {"good", "normal"}:
        return "good"
    if status == "strained":
        return "strained"
    if status == "poor":
        return "poor"
    return "insufficient_data"


def _body_comp_state(
    *,
    body_composition: dict,
    weight_status: str,
    performance_label: str,
    fat_gain_rising: bool,
    lean_mass_improving: bool,
    fat_stable: bool,
) -> str:
    if fat_gain_rising:
        return "fat_gain_risk"
    if lean_mass_improving and fat_stable:
        return "recomp_success" if weight_status in {"stable in target range", "gaining in target range"} else "lean_gain"
    if weight_status in {"gaining too slowly", "losing too fast"} and performance_label in {"declining", "fatigue/performance stagnation", "stable"}:
        return "underfueling"
    if body_composition.get("body_fat_data_points", 0) < 4:
        return "insufficient_data"
    if weight_status in {"stable in target range", "gaining too slowly", "losing too slowly"} and performance_label == "stable":
        return "plateau"
    return "lean_gain" if str(body_composition.get("status")) == "lean gain" else "insufficient_data"


def _decision_states(
    *,
    goal_type: str,
    body_comp_state: str,
    nutrition_state: str,
    training_state: str,
    recovery_state: str,
    calorie_delta: int,
) -> dict:
    return {
        "goal_type": goal_type,
        "body_comp_state": body_comp_state,
        "nutrition_state": nutrition_state,
        "training_state": training_state,
        "recovery_state": recovery_state,
        "decision": "increase" if calorie_delta > 0 else "decrease" if calorie_delta < 0 else "hold",
    }


def _trace_thresholds(
    *,
    weight_signal: dict,
    body_composition: dict,
    nutrition_signal: dict,
) -> dict:
    return {
        "weekly_weight_change_pct": weight_signal.get("weekly_change_pct"),
        "target_weekly_change_pct_range": [
            weight_signal.get("target_weekly_change_low"),
            weight_signal.get("target_weekly_change_high"),
        ],
        "fat_mass_trend_lb_per_week": body_composition.get("fat_mass_trend_14") if body_composition.get("fat_mass_trend_14") is not None else body_composition.get("fat_mass_trend_28"),
        "fat_gain_risk_threshold": FAT_GAIN_RISK_THRESHOLD_LB_PER_WEEK,
        "body_fat_percent_trend_pct_per_week": body_composition.get("body_fat_percent_trend_14") if body_composition.get("body_fat_percent_trend_14") is not None else body_composition.get("body_fat_percent_trend_28"),
        "body_fat_gain_risk_threshold": BODY_FAT_GAIN_RISK_THRESHOLD_PCT_PER_WEEK,
        "lean_mass_trend_lb_per_week": body_composition.get("lean_mass_trend_14") if body_composition.get("lean_mass_trend_14") is not None else body_composition.get("lean_mass_trend_28"),
        "lean_gain_threshold": LEAN_GAIN_THRESHOLD_LB_PER_WEEK,
        "actual_avg_calories": nutrition_signal.get("average_calories"),
        "target_calories": nutrition_signal.get("target_calories"),
        "nutrition_logged_days_14": nutrition_signal.get("logged_days_14"),
        "nutrition_missing_days_14": nutrition_signal.get("missing_days_14"),
    }


def _build_recommendation_trace(
    *,
    changes: dict,
    reasoning: list[str],
    states: dict,
    thresholds: dict,
    body_composition: dict,
    weight_signal: dict,
    nutrition_signal: dict,
    performance_signal: dict,
    recovery_signal: dict,
    running_load: dict,
    confidence: dict,
) -> dict:
    calorie_change = int(changes.get("calories") or 0)
    decision = "increase" if calorie_change > 0 else "decrease" if calorie_change < 0 else "hold"
    what_would_change = []
    if decision == "hold":
        what_would_change.append("More consistent nutrition, weigh-ins, body-comp, training, and recovery data would raise confidence for a target change.")
        what_would_change.append("A sustained lean-mass gain with stable fat mass supports holding; rising fat mass without performance payoff would trigger a reduction.")
    elif decision == "increase":
        what_would_change.append("Rising body fat/fat mass or poor recovery without performance improvement would stop the calorie increase.")
    else:
        what_would_change.append("Stable/down body fat with improving lean mass and performance would move the system back toward holding calories.")
    if confidence.get("overall") == "low":
        what_would_change.insert(0, "Higher confidence would require enough finalized food days, canonical weigh-ins, recent Hevy data, and recovery/sleep logs.")
    return {
        **states,
        "decision": decision,
        "calorie_change": calorie_change,
        "main_reasons": reasoning[:5],
        "thresholds": thresholds,
        "body_comp_signal": body_composition,
        "weight_signal": weight_signal,
        "nutrition_signal": nutrition_signal,
        "training_signal": performance_signal,
        "recovery_signal": recovery_signal,
        "cardio_signal": running_load,
        "what_would_change_decision": what_would_change[:5],
    }


def _workout_recovery_suggestions(
    *,
    performance_signal: dict,
    recovery_signal: dict,
    running_load: dict,
    fat_gain_rising: bool,
    calorie_delta: int,
) -> list[dict]:
    suggestions: list[dict] = []
    recovery_status = str(recovery_signal.get("status") or "insufficient data")
    performance_label = str(performance_signal.get("label") or "insufficient data")
    if recovery_status in {"poor", "strained"}:
        suggestions.append(
            {
                "type": "recovery",
                "priority": "high",
                "title": "Reduce recovery debt before pushing volume",
                "detail": "Recovery is strained, so hold aggressive load increases and prioritize sleep/readiness before chasing heavier sessions.",
            }
        )
    if running_load.get("interference_risk") == "elevated":
        suggestions.append(
            {
                "type": "cardio_load",
                "priority": "medium",
                "title": "Separate harder runs from key lifts",
                "detail": "Running load is elevated while lifting output is soft; keep long or hard runs away from lower-body strength sessions when possible.",
            }
        )
    if fat_gain_rising and calorie_delta >= 0:
        suggestions.append(
            {
                "type": "nutrition_guardrail",
                "priority": "high",
                "title": "Do not add calories yet",
                "detail": "Fat gain is rising without a clear performance payoff, so the engine is guarding body composition first.",
            }
        )
    elif performance_label in {"declining", "fatigue/performance stagnation"} and not fat_gain_rising:
        suggestions.append(
            {
                "type": "training_fuel",
                "priority": "medium",
                "title": "Bias carbs around hard sessions",
                "detail": "Performance is soft without a fat-gain signal; place more carbs before and after lifting instead of making a large calorie jump.",
            }
        )
    for driver in (performance_signal.get("drivers") or [])[:4]:
        name = str(driver.get("name") or "Key lift")
        signal = str(driver.get("signal") or "")
        e1rm = _to_float(driver.get("estimated_1rm_change_pct"), 0) or 0
        reps_delta = _to_float(driver.get("reps_at_same_weight_delta"), 0) or 0
        if signal in {"improving", "strong"} or e1rm >= 1.5 or reps_delta >= 1:
            if recovery_status not in {"poor", "strained"} and not fat_gain_rising:
                suggestions.append(
                    {
                        "type": "go_heavier",
                        "priority": "medium",
                        "title": f"{name}: consider a small load increase",
                        "detail": "Recent performance is improving; add 5 lb, 5-10 lb on machines, or 1-2 reps next session if warmups feel good.",
                    }
                )
        elif signal in {"declining", "stalled"} or e1rm <= -2:
            suggestions.append(
                {
                    "type": "hold_load",
                    "priority": "medium",
                    "title": f"{name}: hold load for now",
                    "detail": "Recent performance is not consistently improving, so keep the load stable and rebuild reps before adding weight.",
                }
            )
    if not suggestions:
        suggestions.append(
            {
                "type": "maintain",
                "priority": "low",
                "title": "Keep the current plan steady",
                "detail": "No strong body-composition, performance, or recovery signal justifies a bigger change today.",
            }
        )
    return suggestions[:8]


def _build_targets_from_calories(
    calories: int,
    bodyweight: float,
    current: dict,
    base_targets: dict,
    composition_state: str,
    carb_bias_grams: int = 0,
    calorie_delta: int = 0,
) -> dict:
    if bodyweight <= 0:
        bodyweight = float(current.get("bodyweight") or base_targets.get("current_bodyweight") or 180)

    if composition_state in {"fat gain rising", "poor partitioning", "recomp guard"} or calorie_delta < 0:
        protein_min, protein_max = bodyweight * 1.1, bodyweight * 1.25
    else:
        protein_min, protein_max = bodyweight * 1.0, bodyweight * 1.15
    current_protein = float(current.get("protein_grams") or base_targets.get("protein_grams") or protein_min)
    protein = min(max(current_protein, protein_min), protein_max)

    fat_floor = max(bodyweight * 0.3, 45)
    fat_ceiling = bodyweight * 0.45
    current_fat = float(current.get("fat_grams") or base_targets.get("fat_grams") or bodyweight * 0.38)
    fat = min(max(current_fat, fat_floor), fat_ceiling)
    if calorie_delta < 0 and fat > bodyweight * 0.38:
        fat = max(fat_floor, fat - 6)
    if carb_bias_grams > 0:
        fat = max(fat_floor, fat - min(10, round(carb_bias_grams / 5)))

    aligned = align_macro_calories(calories, protein, fat)
    aligned["protein_per_lb"] = round(aligned["protein_grams"] / bodyweight, 2) if bodyweight > 0 else 0
    aligned["fat_per_lb"] = round(aligned["fat_grams"] / bodyweight, 2) if bodyweight > 0 else 0
    aligned["fat_floor_grams"] = int(round(fat_floor))
    return aligned


def _macro_changes(current: dict, recommended: dict) -> dict:
    return {
        "calories": int(recommended["target_calories"] - current["target_calories"]),
        "protein": int(recommended["protein_grams"] - current["protein_grams"]),
        "carbs": int(recommended["carb_grams"] - current["carb_grams"]),
        "fat": int(recommended["fat_grams"] - current["fat_grams"]),
    }


def _day_type_adjusted_targets(baseline: dict, day_type: dict, bodyweight: float) -> dict:
    target_calories = int(baseline["target_calories"] + int(day_type.get("calorie_delta") or 0))
    fat_floor = max(bodyweight * 0.3, baseline.get("fat_floor_grams") or 45)
    fat = max(fat_floor, float(baseline["fat_grams"]) + float(day_type.get("fat_delta") or 0))
    aligned = align_macro_calories(target_calories, baseline["protein_grams"], fat)
    return {
        **baseline,
        "target_calories": aligned["target_calories"],
        "protein_grams": aligned["protein_grams"],
        "carb_grams": aligned["carb_grams"],
        "fat_grams": aligned["fat_grams"],
        "macro_calories": aligned["macro_calories"],
        "calorie_macro_delta": aligned["calorie_macro_delta"],
    }


def _historical_learning(
    nutrition_df: pd.DataFrame | None,
    body_metrics_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None,
    sleep_df: pd.DataFrame | None,
    user_goals: dict,
    analysis_day: pd.Timestamp,
) -> list[str]:
    trends: list[str] = []
    nutrition = _daily_nutrition(nutrition_df)
    body = _clean_body_composition(body_metrics_df, user_goals)
    training = _daily_training(training_df)

    if len(nutrition) >= 21 and len(body[body["body_fat_percent"].notna()]) >= 6:
        merged = nutrition.merge(body[["date", "bodyweight", "body_fat_percent", "lean_mass", "fat_mass"]], on="date", how="inner")
        if len(merged) >= 14:
            merged["calories_7"] = merged["calories"].rolling(7, min_periods=4).mean()
            high_calorie = merged[merged["calories_7"] >= merged["calories_7"].quantile(0.75)]
            if len(high_calorie) >= 4 and high_calorie["body_fat_percent"].diff().mean() > 0.03:
                threshold = int(round(float(high_calorie["calories_7"].mean()) / 50) * 50)
                trends.append(f"Body fat has tended to rise faster when calories averaged above {threshold} kcal.")
            lean_positive = merged[merged["lean_mass"].diff() > 0]
            if len(lean_positive) >= 5:
                low = int(round(float(lean_positive["calories"].quantile(0.25)) / 50) * 50)
                high = int(round(float(lean_positive["calories"].quantile(0.75)) / 50) * 50)
                trends.append(f"Lean-mass gains have been associated with roughly {low}-{high} kcal days.")

    if len(nutrition) >= 14 and len(training[training["has_lift"]]) >= 6:
        training_days = training[training["has_lift"]].copy()
        merged = training_days.merge(nutrition[["date", "carbs"]], on="date", how="left")
        if merged["carbs"].notna().sum() >= 6 and merged["volume"].max() > 0:
            top = merged[merged["volume"] >= merged["volume"].quantile(0.75)]
            if len(top) >= 2:
                top_carbs = float(top["carbs"].mean())
                all_carbs = float(merged["carbs"].mean())
                if top_carbs >= all_carbs + 20:
                    trends.append(f"Your strongest lifting days have been associated with about {top_carbs:.0f}g carbs.")

    sleep_clean = _date_clean(sleep_df)
    recovery_clean = _date_clean(recovery_df)
    if sleep_clean.empty and not recovery_clean.empty and "sleep_hours" in recovery_clean.columns:
        sleep_clean = recovery_clean[["date", "sleep_hours"]].copy()
    if not sleep_clean.empty and not recovery_clean.empty and "recovery_score" in recovery_clean.columns:
        sleep_col = "duration_minutes" if "duration_minutes" in sleep_clean.columns else "sleep_hours"
        sleep_daily = sleep_clean[["date", sleep_col]].copy()
        sleep_daily["sleep_hours"] = pd.to_numeric(sleep_daily[sleep_col], errors="coerce")
        if sleep_col == "duration_minutes":
            sleep_daily["sleep_hours"] = sleep_daily["sleep_hours"] / 60
        recovery_daily = recovery_clean[["date", "recovery_score"]].copy()
        recovery_daily["recovery_score"] = pd.to_numeric(recovery_daily["recovery_score"], errors="coerce")
        merged = sleep_daily.merge(recovery_daily, on="date", how="inner").dropna()
        if len(merged) >= 10:
            low_sleep = merged[merged["sleep_hours"] < 7]
            normal_sleep = merged[merged["sleep_hours"] >= 7]
            if len(low_sleep) >= 3 and len(normal_sleep) >= 3 and low_sleep["recovery_score"].mean() + 5 < normal_sleep["recovery_score"].mean():
                trends.append("Sleep below 7h has been associated with lower recovery scores.")

    running_workload = analyze_training_workload(_date_clean(training_df), bodyweight=float(user_goals.get("current_bodyweight") or 180)) if training_df is not None else {}
    current = running_workload.get("current", {})
    if float(current.get("weekly_mileage") or 0) >= 14 and str(current.get("performance_signal", {}).get("label") or "") in {"declining", "fatigue/performance stagnation"}:
        trends.append("Elevated running mileage is currently associated with softer lifting performance.")

    if not trends:
        trends.append("Historical learning is active, but more overlapping weight, food, training, and recovery data is needed before stronger patterns are useful.")
    return trends[:8]


def build_adaptive_nutrition_recommendation(
    user_goals: dict,
    body_metrics_df: pd.DataFrame | None,
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None,
    current_targets: dict | None = None,
    sleep_df: pd.DataFrame | None = None,
    today: str | None = None,
) -> dict:
    """Build a conservative lean-mass-first nutrition recommendation."""
    bodyweight = float(user_goals.get("current_bodyweight") or 0)
    training_df = training_df if training_df is not None else pd.DataFrame()
    nutrition_df = nutrition_df if nutrition_df is not None else pd.DataFrame()
    recovery_df = recovery_df if recovery_df is not None else pd.DataFrame()
    sleep_df = sleep_df if sleep_df is not None else pd.DataFrame()
    analysis_day = _analysis_date(today, body_metrics_df, nutrition_df, training_df, recovery_df, sleep_df)

    workload = analyze_training_workload(training_df, bodyweight=bodyweight or 180.0)
    base_targets = calculate_macro_targets(
        user_goals,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        body_metrics_df=body_metrics_df,
        workload_data=workload,
    )
    current = {
        "target_calories": _current_value(current_targets, "target_calories", base_targets["target_calories"]),
        "protein_grams": _current_value(current_targets, "protein_grams", base_targets["protein_grams"]),
        "carb_grams": _current_value(current_targets, "carb_grams", base_targets["carb_grams"]),
        "fat_grams": _current_value(current_targets, "fat_grams", base_targets["fat_grams"]),
    }

    weight_signal = _goal_weight_signal(calculate_bodyweight_trend_signal(body_metrics_df, user_goals), user_goals)
    performance_signal = analyze_hevy_performance_signal(training_df)
    recovery_signal = analyze_recovery_signal(
        recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        target_calories=current["target_calories"],
        performance_signal=performance_signal,
        workload_data=workload,
    )
    training_load = _training_load_signal(workload)
    running_load = _running_load_signal(workload, performance_signal=performance_signal)
    nutrition_average = _nutrition_average(nutrition_df)
    body_composition = _body_composition_trends(body_metrics_df, user_goals, weight_signal)
    day_type = _detect_day_type(training_df, workload, recovery_signal, analysis_day)
    day_of_week_adjustment, carb_timing, weekday_trends = _day_of_week_learning(nutrition_df, training_df, analysis_day)
    data_quality = _data_quality_score(
        body_metrics_df=body_metrics_df,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        sleep_df=sleep_df,
        user_goals=user_goals,
        analysis_day=analysis_day,
    )
    confidence_info = _structured_confidence(
        body_metrics_df=body_metrics_df,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        sleep_df=sleep_df,
        user_goals=user_goals,
        analysis_day=analysis_day,
        data_quality=data_quality,
    )
    nutrition_signal = _nutrition_signal(nutrition_average, current, analysis_day, nutrition_df)
    historical_trends = _historical_learning(nutrition_df, body_metrics_df, training_df, recovery_df, sleep_df, user_goals, analysis_day)
    detected_trends = [*weekday_trends, *historical_trends]

    reasoning: list[str] = []
    warnings: list[str] = []
    calorie_delta = 0
    carb_bias_grams = 0

    weight_status = str(weight_signal.get("status") or "insufficient data")
    goal_type = _goal_family(user_goals)
    performance_label = str(performance_signal.get("label") or "insufficient data")
    recovery_status = str(recovery_signal.get("status") or "insufficient data")
    composition_quality = str(body_composition.get("lean_gain_quality") or "unknown")
    fat_gain_rising = composition_quality in {"fat gain rising", "poor partitioning"} or body_composition.get("status") == "fat gain risk"
    lean_mass_improving = (body_composition.get("lean_mass_trend_14") or body_composition.get("lean_mass_trend_28") or 0) > LEAN_GAIN_THRESHOLD_LB_PER_WEEK
    fat_stable = not fat_gain_rising and (body_composition.get("fat_mass_trend_14") is None or (body_composition.get("fat_mass_trend_14") or 0) <= FAT_STABLE_THRESHOLD_LB_PER_WEEK)
    recovery_good = recovery_status in {"good", "normal", "insufficient data"}
    recovery_poor = recovery_status in {"poor", "strained"}
    performance_soft = performance_label in {"declining", "fatigue/performance stagnation", "stable"}
    confidence_level = str(confidence_info.get("overall") or data_quality["confidence"])
    if recovery_status == "poor" and confidence_level == "high":
        confidence_level = "medium"
    if body_composition["body_fat_data_points"] < 4 and confidence_level == "high":
        confidence_level = "medium"
    confidence_info = {**confidence_info, "overall": confidence_level}
    nutrition_state_label = _nutrition_state(nutrition_signal, confidence_info)
    if nutrition_state_label == "inconsistent" and confidence_level == "high":
        confidence_level = "medium"
        confidence_info = {**confidence_info, "overall": confidence_level}
        warnings.append("Nutrition logging/adherence is inconsistent, so recommendation confidence is capped at medium.")

    if confidence_level == "low":
        calorie_delta = 0
        reasoning.append("Recommendation confidence is low, so active baseline targets stay stable while data quality improves.")
        warnings.append("Log more weight, food, lifting, recovery, and body fat data before larger calorie changes.")
    elif goal_type == "cut":
        if weight_status == "losing too fast" or (performance_label in {"declining", "fatigue/performance stagnation"} and recovery_poor):
            calorie_delta = 75
            carb_bias_grams += 15
            reasoning.append("Cut progress is too aggressive for performance/recovery, so calories rise slightly to protect lean mass.")
        elif weight_status == "losing too slowly" and nutrition_state_label not in {"under_target", "insufficient_data", "inconsistent"} and not recovery_poor:
            calorie_delta = -100
            reasoning.append("Cut progress is slower than target while logged intake is not below target, so calories come down slightly.")
        elif fat_gain_rising and nutrition_state_label == "over_target":
            calorie_delta = -125
            reasoning.append("Fat gain is rising during a cut and logged intake is over target, so calories decrease conservatively.")
        else:
            calorie_delta = 0
            reasoning.append("Cut targets hold because the system is prioritizing lean-mass retention and avoiding noisy overcorrection.")
    elif goal_type == "recomp":
        if fat_gain_rising and nutrition_state_label != "under_target":
            calorie_delta = -75
            reasoning.append("Recomp is drifting toward fat gain, so calories edge down while protein stays high.")
        elif weight_status == "losing too fast" and performance_soft and not fat_gain_rising:
            calorie_delta = 75
            carb_bias_grams += 20
            reasoning.append("Recomp weight loss is too fast with soft performance, so a small carb-biased increase protects training.")
        elif lean_mass_improving and fat_stable:
            calorie_delta = 0
            reasoning.append("Recomp signal is positive: lean mass is improving or stable while fat gain is controlled.")
        else:
            calorie_delta = 0
            reasoning.append("Recomp targets hold until body composition, adherence, and performance point clearly in one direction.")
    elif goal_type in {"maintenance", "performance"}:
        if fat_gain_rising or weight_status == "gaining too fast":
            calorie_delta = -75
            reasoning.append("Maintenance/performance weight or fat gain is drifting high, so calories reduce slightly.")
        elif weight_status == "losing too fast" and performance_soft:
            calorie_delta = 75
            carb_bias_grams += 15
            reasoning.append("Maintenance/performance intake looks low for current output, so calories rise slightly.")
        elif performance_label in {"declining", "fatigue/performance stagnation"} and recovery_good and not fat_gain_rising:
            calorie_delta = 75
            carb_bias_grams += 20
            reasoning.append("Performance is soft without fat gain, so the system nudges carbs before changing bodyweight goals.")
        else:
            calorie_delta = 0
            reasoning.append("Maintenance/performance targets hold because bodyweight and output do not justify a bigger change.")
    elif fat_gain_rising and performance_label in {"declining", "fatigue/performance stagnation", "stable", "insufficient data"}:
        calorie_delta = -150
        carb_bias_grams -= 10
        reasoning.append("Body fat/fat mass is rising without a clear strength payoff, so calories come down slightly.")
        warnings.append("Lean-bulk efficiency looks poor: weight gain is not clearly translating to better training output.")
    elif recovery_status == "poor" and fat_gain_rising:
        calorie_delta = -75
        reasoning.append("Recovery is poor while fat gain is rising, so the system avoids adding calories and flags recovery/load first.")
        warnings.append("Poor recovery plus fat gain points toward sleep, stress, or training load before more food.")
    elif weight_status == "gaining too fast":
        calorie_delta = -100 if performance_label == "improving" else -150
        reasoning.append("Fast weight gain has blocked performance-driven calorie increases to protect lean-gain quality.")
        if performance_label == "improving":
            reasoning.append("Strength is improving, but the scale is moving too quickly for a conservative lean bulk.")
    elif lean_mass_improving and fat_stable and performance_label in {"improving", "stable"}:
        calorie_delta = 0
        reasoning.append("Lean mass is improving, fat gain is controlled, and strength is not regressing, so baseline calories stay stable.")
    elif weight_status == "gaining too slowly" and performance_label == "improving" and fat_stable:
        calorie_delta = 50
        carb_bias_grams += 10
        reasoning.append("Strength is improving while gain is slow, so only a small carb-biased bump is suggested.")
    elif weight_status == "gaining too slowly" and performance_soft and recovery_good:
        calorie_delta = 125
        carb_bias_grams += 30
        reasoning.append("Weight gain is slow and lifting output is soft while recovery is adequate, so calories rise mostly through carbs.")
    elif weight_status == "gaining too slowly" and performance_soft and recovery_poor and not fat_gain_rising:
        calorie_delta = 75
        carb_bias_grams += 25
        reasoning.append("Progress is under-fueled but recovery is strained, so the increase is small and carb-focused.")
        warnings.append("Pair the calorie bump with sleep and workload management; food alone may not solve the recovery signal.")
    elif performance_label in {"declining", "fatigue/performance stagnation"} and recovery_good and not fat_gain_rising:
        calorie_delta = 100
        carb_bias_grams += 25
        reasoning.append("Hevy performance is down with normal recovery, so a conservative carb-focused increase is warranted.")
    elif weight_status == "gaining in target range":
        calorie_delta = 0
        reasoning.append("Weight gain is in the conservative target range, so the baseline target stays steady.")
    elif weight_status == "gaining too slowly":
        calorie_delta = 75
        carb_bias_grams += 15
        reasoning.append("Weight gain is below target, so the engine adds a small surplus.")
    else:
        calorie_delta = 0
        reasoning.append("No clear lean-mass or fat-gain signal justifies changing baseline calories today.")

    if calorie_delta > 0 and nutrition_state_label == "over_target":
        calorie_delta = 0
        carb_bias_grams = max(0, carb_bias_grams)
        reasoning.append("Logged calories are already above target, so the engine holds instead of adding more food.")
    if calorie_delta < 0 and nutrition_state_label in {"insufficient_data", "inconsistent"}:
        calorie_delta = 0
        reasoning.append("Nutrition data is incomplete/inconsistent, so the engine avoids cutting calories from uncertain intake data.")
        warnings.append("Finalize more nutrition days before using intake data to justify a calorie decrease.")

    if running_load.get("interference_risk") == "elevated":
        warnings.append("Running load may be interfering with lifting; watch long runs near lower-body sessions.")
        if not fat_gain_rising and weight_status != "gaining too fast" and confidence_level != "low":
            calorie_delta = max(calorie_delta, 75)
            carb_bias_grams += 20
            reasoning.append("Elevated running load with softer lifting adds a carb bias instead of a large surplus.")
    if training_load["status"] in {"high", "unusually high"} and recovery_status not in {"poor"} and confidence_level != "low":
        carb_bias_grams += 10
        reasoning.append("Recent Hevy workload is high enough to favor carbohydrate availability.")
    if calorie_delta > 0 and nutrition_state_label == "over_target":
        calorie_delta = 0
        reasoning.append("Even with workload demand, logged intake is already above target, so baseline calories hold.")
    if calorie_delta < 0 and nutrition_state_label in {"insufficient_data", "inconsistent"}:
        calorie_delta = 0
        reasoning.append("Even with risk signals, incomplete nutrition logging blocks a calorie decrease until intake confidence improves.")
    if body_composition["body_fat_data_points"] < 4:
        warnings.append("Body fat data is limited, so lean-mass versus fat-gain confidence is reduced.")

    if calorie_delta > 0:
        calorie_delta = max(50, min(150, int(round(calorie_delta / 25) * 25)))
    elif calorie_delta < 0:
        calorie_delta = -max(75, min(200, abs(int(round(calorie_delta / 25) * 25))))

    recommended_calories = max(1200, current["target_calories"] + calorie_delta)
    composition_state = composition_quality if fat_gain_rising else "lean bulk"
    aligned = _build_targets_from_calories(
        calories=recommended_calories,
        bodyweight=bodyweight or (body_composition.get("latest_bodyweight") or 180),
        current=current,
        base_targets=base_targets,
        composition_state=composition_state,
        carb_bias_grams=max(0, carb_bias_grams),
        calorie_delta=calorie_delta,
    )
    recommended = {
        **base_targets,
        "target_calories": aligned["target_calories"],
        "protein_grams": aligned["protein_grams"],
        "carb_grams": aligned["carb_grams"],
        "fat_grams": aligned["fat_grams"],
        "macro_calories": aligned["macro_calories"],
        "calorie_macro_delta": aligned["calorie_macro_delta"],
        "protein_per_lb": aligned["protein_per_lb"],
        "fat_per_lb": aligned["fat_per_lb"],
        "fat_floor_grams": aligned["fat_floor_grams"],
        "adaptive_strategy": "Closed-loop Lean Mass Optimization",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    day_adjusted = _day_type_adjusted_targets(recommended, day_type, bodyweight or (body_composition.get("latest_bodyweight") or 180))
    changes = _macro_changes(current, recommended)
    day_changes = _macro_changes(recommended, day_adjusted)
    if day_changes["carbs"]:
        day_type = {
            **day_type,
            "applied_delta": day_changes,
            "adjusted_targets": {
                "calories": day_adjusted["target_calories"],
                "protein": day_adjusted["protein_grams"],
                "carbs": day_adjusted["carb_grams"],
                "fat": day_adjusted["fat_grams"],
            },
        }

    signals = {
        "weight": weight_signal,
        "bodyComposition": body_composition,
        "performance": performance_signal,
        "recovery": recovery_signal,
        "trainingLoad": training_load,
        "runningLoad": running_load,
        "nutrition": nutrition_signal,
        "dataQuality": data_quality,
        "dayType": day_type,
        "historicalLearning": {"detectedTrends": detected_trends},
    }
    body_comp_state_label = _body_comp_state(
        body_composition=body_composition,
        weight_status=weight_status,
        performance_label=performance_label,
        fat_gain_rising=fat_gain_rising,
        lean_mass_improving=lean_mass_improving,
        fat_stable=fat_stable,
    )
    states = _decision_states(
        goal_type=goal_type,
        body_comp_state=body_comp_state_label,
        nutrition_state=nutrition_state_label,
        training_state=_training_state(performance_signal),
        recovery_state=_recovery_state(recovery_signal),
        calorie_delta=changes["calories"],
    )
    thresholds = _trace_thresholds(
        weight_signal=weight_signal,
        body_composition=body_composition,
        nutrition_signal=nutrition_signal,
    )
    signals["states"] = states
    signals["thresholds"] = thresholds
    next_review = (analysis_day + timedelta(days=7)).date().isoformat()
    confidence_message = (
        f"Recommendation confidence: {confidence_level.capitalize()}. "
        + (" ".join(confidence_info["missing_data"][:2]) if confidence_info["missing_data"] else "Core bodyweight, nutrition, training, and recovery inputs are available.")
    )
    if confidence_message not in reasoning:
        reasoning.append(confidence_message)
    trace = _build_recommendation_trace(
        changes=changes,
        reasoning=reasoning,
        states=states,
        thresholds=thresholds,
        body_composition=body_composition,
        weight_signal=weight_signal,
        nutrition_signal=nutrition_signal,
        performance_signal=performance_signal,
        recovery_signal=recovery_signal,
        running_load=running_load,
        confidence=confidence_info,
    )
    structured_suggestions = _workout_recovery_suggestions(
        performance_signal=performance_signal,
        recovery_signal=recovery_signal,
        running_load=running_load,
        fat_gain_rising=fat_gain_rising,
        calorie_delta=changes["calories"],
    )

    return {
        "recommendedCalories": recommended["target_calories"],
        "recommendedProtein": recommended["protein_grams"],
        "recommendedCarbs": recommended["carb_grams"],
        "recommendedFat": recommended["fat_grams"],
        "caloriesTarget": recommended["target_calories"],
        "proteinTarget": recommended["protein_grams"],
        "carbsTarget": recommended["carb_grams"],
        "fatTarget": recommended["fat_grams"],
        "calorieAdjustment": changes["calories"],
        "macroAdjustment": changes,
        "macroChanges": changes,
        "dayType": day_type["type"],
        "dayTypeAdjustment": day_type,
        "dayOfWeekAdjustment": day_of_week_adjustment,
        "carbTimingRecommendation": carb_timing,
        "confidence": confidence_info,
        "confidenceLevel": confidence_level,
        "dataQualityScore": data_quality["score"],
        "reasoning": reasoning[:8],
        "signals": signals,
        "states": states,
        "body_comp_state": states["body_comp_state"],
        "nutrition_state": states["nutrition_state"],
        "training_state": states["training_state"],
        "recovery_state": states["recovery_state"],
        "recommendation_trace": trace,
        "structured_suggestions": structured_suggestions,
        "workout_recovery_suggestions": structured_suggestions,
        "warnings": warnings[:6],
        "detectedTrends": detected_trends[:8],
        "missingDataWarnings": confidence_info["missing_data"][:8],
        "nextReviewDate": next_review,
        "currentTarget": {
            "calories": current["target_calories"],
            "protein": current["protein_grams"],
            "carbs": current["carb_grams"],
            "fat": current["fat_grams"],
        },
        "recommendedTargets": recommended,
        "baselineRecommendedTargets": recommended,
        "dayTypeAdjustedTargets": day_adjusted,
        "strategy": "Closed-loop Lean Mass Optimization",
    }
