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
from src.nutrition_targets import align_macro_calories, calculate_bodyweight_trend_signal, calculate_macro_targets
from src.paths import processed_data_path
from src.storage import load_document, save_document
from src.training_schedule import is_run_row, is_strength_row, planned_training_for_date


NUTRITION_RECOMMENDATION_HISTORY_PATH = processed_data_path("nutrition_recommendation_history.json")


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
    df = _date_clean(body_metrics_df)
    if df.empty:
        return pd.DataFrame(columns=["date", "bodyweight", "body_fat_percent", "lean_mass", "fat_mass"])
    df["bodyweight"] = pd.to_numeric(df.get("bodyweight"), errors="coerce")
    body_fat_column = _first_column(df, ["estimated_body_fat", "body_fat_percent", "bodyfat", "body_fat"])
    if body_fat_column:
        df["body_fat_percent"] = pd.to_numeric(df[body_fat_column], errors="coerce")
    else:
        df["body_fat_percent"] = pd.NA
    fallback_body_fat = _to_float(user_goals.get("estimated_body_fat"))
    if fallback_body_fat is not None:
        df["body_fat_percent"] = df["body_fat_percent"].fillna(fallback_body_fat)
    df = df.dropna(subset=["bodyweight"]).copy()
    df["body_fat_percent"] = pd.to_numeric(df["body_fat_percent"], errors="coerce")
    df.loc[df["body_fat_percent"] <= 1, "body_fat_percent"] = df["body_fat_percent"] * 100
    valid_body_fat = df["body_fat_percent"].between(3, 60)
    df.loc[~valid_body_fat, "body_fat_percent"] = pd.NA
    lean_mass_column = _first_column(df, ["lean_mass", "fat_free_mass"])
    fat_mass_column = _first_column(df, ["fat_mass"])
    measured_lean = pd.to_numeric(df[lean_mass_column], errors="coerce") if lean_mass_column else pd.Series(float("nan"), index=df.index, dtype="float64")
    measured_fat = pd.to_numeric(df[fat_mass_column], errors="coerce") if fat_mass_column else pd.Series(float("nan"), index=df.index, dtype="float64")
    df["lean_mass"] = measured_lean.combine_first(df["bodyweight"] * (1 - (df["body_fat_percent"] / 100)))
    df["fat_mass"] = measured_fat.combine_first(df["bodyweight"] * (df["body_fat_percent"] / 100))
    return df[["date", "bodyweight", "body_fat_percent", "lean_mass", "fat_mass"]].sort_values("date")


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
    }
    if df.empty:
        return empty
    latest = df.iloc[-1]
    output = {
        **empty,
        "data_points": int(len(df)),
        "body_fat_data_points": int(df["body_fat_percent"].notna().sum()),
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

    if output["body_fat_data_points"] < 4:
        quality = "body fat missing"
        status = "body composition incomplete"
    elif (lean_trend or 0) > 0.08 and (fat_trend or 0) <= 0.18 and (body_fat_trend or 0) <= 0.12:
        quality = "lean mass improving"
        status = "lean gain"
    elif (fat_trend or 0) >= 0.25 or (body_fat_trend or 0) >= 0.2:
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


def _is_hevy_row(row: pd.Series) -> bool:
    return is_strength_row(row)


def _is_run_row(row: pd.Series) -> bool:
    return is_run_row(row)


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
    planned = planned_training_for_date(analysis_day)
    df = _date_clean(training_df)
    today_rows = df[df["date"] == analysis_day].copy() if not df.empty else pd.DataFrame()
    lift_rows = today_rows[today_rows.apply(_is_hevy_row, axis=1)] if not today_rows.empty else pd.DataFrame()
    run_rows = today_rows[today_rows.apply(_is_run_row, axis=1)] if not today_rows.empty else pd.DataFrame()
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
    df["is_lift"] = df.apply(_is_hevy_row, axis=1)
    df["is_run"] = df.apply(_is_run_row, axis=1)
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
    hevy_recent = recent_training[recent_training.apply(_is_hevy_row, axis=1)] if not recent_training.empty else pd.DataFrame()
    hevy_days = int(hevy_recent["date"].nunique()) if not hevy_recent.empty and "date" in hevy_recent.columns else 0
    score += 15 if hevy_days >= 2 else 8 if hevy_days else 0
    if hevy_recent.empty and int(user_goals.get("training_frequency_per_week") or 0) > 0:
        warnings.append("No recent Hevy/lifting sync found.")

    run_recent = recent_training[recent_training.apply(_is_run_row, axis=1)] if not recent_training.empty else pd.DataFrame()
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

    weight_signal = calculate_bodyweight_trend_signal(body_metrics_df, user_goals)
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
    historical_trends = _historical_learning(nutrition_df, body_metrics_df, training_df, recovery_df, sleep_df, user_goals, analysis_day)
    detected_trends = [*weekday_trends, *historical_trends]

    reasoning: list[str] = []
    warnings: list[str] = []
    calorie_delta = 0
    carb_bias_grams = 0

    weight_status = str(weight_signal.get("status") or "insufficient data")
    performance_label = str(performance_signal.get("label") or "insufficient data")
    recovery_status = str(recovery_signal.get("status") or "insufficient data")
    composition_quality = str(body_composition.get("lean_gain_quality") or "unknown")
    fat_gain_rising = composition_quality in {"fat gain rising", "poor partitioning"} or body_composition.get("status") == "fat gain risk"
    lean_mass_improving = (body_composition.get("lean_mass_trend_14") or body_composition.get("lean_mass_trend_28") or 0) > 0.08
    fat_stable = not fat_gain_rising and (body_composition.get("fat_mass_trend_14") is None or (body_composition.get("fat_mass_trend_14") or 0) <= 0.18)
    recovery_good = recovery_status in {"good", "normal", "insufficient data"}
    recovery_poor = recovery_status in {"poor", "strained"}
    performance_soft = performance_label in {"declining", "fatigue/performance stagnation", "stable"}
    confidence = data_quality["confidence"]
    if recovery_status == "poor" and confidence == "high":
        confidence = "medium"
    if body_composition["body_fat_data_points"] < 4 and confidence == "high":
        confidence = "medium"

    if confidence == "low":
        calorie_delta = 0
        reasoning.append("Recommendation confidence is low, so active baseline targets stay stable while data quality improves.")
        warnings.append("Log more weight, food, lifting, recovery, and body fat data before larger calorie changes.")
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

    if running_load.get("interference_risk") == "elevated":
        warnings.append("Running load may be interfering with lifting; watch long runs near lower-body sessions.")
        if not fat_gain_rising and weight_status != "gaining too fast" and confidence != "low":
            calorie_delta = max(calorie_delta, 75)
            carb_bias_grams += 20
            reasoning.append("Elevated running load with softer lifting adds a carb bias instead of a large surplus.")
    if training_load["status"] in {"high", "unusually high"} and recovery_status not in {"poor"} and confidence != "low":
        carb_bias_grams += 10
        reasoning.append("Recent Hevy workload is high enough to favor carbohydrate availability.")
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
        "nutrition": nutrition_average,
        "dataQuality": data_quality,
        "dayType": day_type,
        "historicalLearning": {"detectedTrends": detected_trends},
    }
    next_review = (analysis_day + timedelta(days=7)).date().isoformat()
    confidence_message = (
        f"Recommendation confidence: {confidence.capitalize()}. "
        + (" ".join(data_quality["missingDataWarnings"][:2]) if data_quality["missingDataWarnings"] else "Core bodyweight, nutrition, training, and recovery inputs are available.")
    )
    if confidence_message not in reasoning:
        reasoning.append(confidence_message)

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
        "confidence": confidence,
        "dataQualityScore": data_quality["score"],
        "reasoning": reasoning[:8],
        "signals": signals,
        "warnings": warnings[:6],
        "detectedTrends": detected_trends[:8],
        "missingDataWarnings": data_quality["missingDataWarnings"][:8],
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
