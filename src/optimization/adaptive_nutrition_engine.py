"""Unified adaptive nutrition recommendation engine."""

from __future__ import annotations

import pandas as pd

from src.analytics.recovery_engine import analyze_recovery_signal
from src.analytics.training_workload import analyze_hevy_performance_signal, analyze_training_workload
from src.nutrition_targets import align_macro_calories, calculate_bodyweight_trend_signal, calculate_macro_targets


def _current_value(targets: dict | None, key: str, fallback: int) -> int:
    if not targets:
        return fallback
    try:
        value = int(round(float(targets.get(key) or fallback)))
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _nutrition_average(nutrition_df: pd.DataFrame | None, days: int = 14) -> dict:
    if nutrition_df is None or nutrition_df.empty:
        return {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None}
    df = nutrition_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None}
    latest = df["date"].max()
    recent = df[df["date"] >= latest - pd.Timedelta(days=days - 1)].copy()
    column_map = {
        "calories": "total_calories" if "total_calories" in recent.columns else "calories",
        "protein": "total_protein" if "total_protein" in recent.columns else "protein",
        "carbs": "total_carbs" if "total_carbs" in recent.columns else "carbs",
        "fat": "total_fat" if "total_fat" in recent.columns else "fat",
    }
    for target, source in column_map.items():
        recent[target] = pd.to_numeric(recent.get(source, 0), errors="coerce").fillna(0)
    daily = recent.groupby("date", as_index=False).agg(
        calories=("calories", "sum"),
        protein=("protein", "sum"),
        carbs=("carbs", "sum"),
        fat=("fat", "sum"),
    )
    if daily.empty:
        return {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None}
    return {
        "days": int(len(daily)),
        "calories": round(float(daily["calories"].mean()), 0),
        "protein": round(float(daily["protein"].mean()), 1),
        "carbs": round(float(daily["carbs"].mean()), 1),
        "fat": round(float(daily["fat"].mean()), 1),
    }


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


def _running_load_signal(workload: dict) -> dict:
    current = workload.get("current", {})
    miles = float(current.get("weekly_mileage") or 0)
    runs = float(current.get("runs_per_week") or 0)
    if miles >= 25 or runs >= 5:
        status = "unusually high"
    elif miles >= 14 or runs >= 3:
        status = "high"
    elif miles >= 4 or runs >= 1:
        status = "normal"
    else:
        status = "low"
    return {
        "status": status,
        "runs_per_week": round(runs, 2),
        "weekly_mileage": round(miles, 1),
        "summary": f"{round(runs, 2)} runs/week and {round(miles, 1)} miles/week.",
    }


def _confidence(signals: dict, nutrition_average: dict) -> str:
    available = 0
    available += signals["weight"]["status"] not in {"insufficient data", "noisy"}
    available += signals["performance"]["label"] != "insufficient data"
    available += signals["recovery"]["status"] != "insufficient data"
    available += signals["trainingLoad"]["status"] != "low"
    available += nutrition_average["days"] >= 7
    if available >= 4:
        return "high"
    if available >= 2:
        return "medium"
    return "low"


def _macro_changes(current: dict, recommended: dict) -> dict:
    return {
        "calories": recommended["target_calories"] - current["target_calories"],
        "protein": recommended["protein_grams"] - current["protein_grams"],
        "carbs": recommended["carb_grams"] - current["carb_grams"],
        "fat": recommended["fat_grams"] - current["fat_grams"],
    }


def build_adaptive_nutrition_recommendation(
    user_goals: dict,
    body_metrics_df: pd.DataFrame | None,
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None,
    current_targets: dict | None = None,
) -> dict:
    """Combine major local signals into one conservative lean-bulk recommendation."""
    bodyweight = float(user_goals.get("current_bodyweight") or 0)
    training_df = training_df if training_df is not None else pd.DataFrame()
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
        recovery_df if recovery_df is not None else pd.DataFrame(),
        training_df=training_df,
        nutrition_df=nutrition_df,
        target_calories=current["target_calories"],
        performance_signal=performance_signal,
        workload_data=workload,
    )
    training_load = _training_load_signal(workload)
    running_load = _running_load_signal(workload)
    nutrition_average = _nutrition_average(nutrition_df)

    signals = {
        "weight": weight_signal,
        "performance": performance_signal,
        "recovery": recovery_signal,
        "trainingLoad": training_load,
        "runningLoad": running_load,
        "nutrition": nutrition_average,
    }
    confidence = _confidence(signals, nutrition_average)
    reasoning = []
    warnings = []
    calorie_delta = int(base_targets["target_calories"] - current["target_calories"])
    carb_bias_grams = 0

    weight_status = str(weight_signal.get("status") or "insufficient data")
    performance_label = str(performance_signal.get("label") or "insufficient data")
    recovery_status = str(recovery_signal.get("status") or "insufficient data")
    high_training = training_load["status"] in {"high", "unusually high"}
    high_running = running_load["status"] in {"high", "unusually high"}

    if confidence == "low":
        calorie_delta = 0
        reasoning.append("Data confidence is low, so the recommendation keeps active targets stable.")
        warnings.append("Log more weigh-ins, food, workouts, and recovery data before making larger target changes.")
    elif weight_status == "gaining too fast":
        calorie_delta = min(calorie_delta, int(weight_signal.get("calorie_adjustment") or -100))
        reasoning.append("Weight gain is above the conservative lean-bulk range, so calorie increases are blocked.")
        if performance_label in {"declining", "fatigue/performance stagnation"} or recovery_status in {"poor", "strained"}:
            warnings.append("Performance/recovery issues during fast weight gain point toward fatigue, sleep, or training load before more calories.")
    elif recovery_status == "poor" and high_training:
        calorie_delta = min(max(calorie_delta, 0), 75)
        carb_bias_grams += 15
        reasoning.append("Recovery is poor with high training load; keep calories conservative and focus on recovery plus training-day carbs.")
        warnings.append("Review sleep, rest, accessory volume, and extra cardio before adding a larger surplus.")
    elif performance_label in {"declining", "fatigue/performance stagnation"} and weight_status == "gaining too slowly":
        calorie_delta = max(calorie_delta, 100)
        carb_bias_grams += 25
        reasoning.append("Hevy performance is soft while weight gain is slow, so increase calories mostly through carbs.")
    elif recovery_status == "poor" and (weight_status == "gaining too slowly" or performance_label in {"declining", "fatigue/performance stagnation"}):
        calorie_delta = max(calorie_delta, 75)
        carb_bias_grams += 20
        reasoning.append("Recovery is poor and progress is under-supported, so use a small carb-focused increase while prioritizing sleep.")
    elif performance_label == "improving" and weight_status == "gaining in target range":
        calorie_delta = 0
        reasoning.append("Performance is improving and weight gain is on target, so maintain macros.")
    elif weight_status == "gaining in target range":
        calorie_delta = 0
        reasoning.append("Weight gain is in the conservative lean-bulk target range, so keep targets steady.")
    elif weight_status == "gaining too slowly":
        calorie_delta = max(calorie_delta, int(weight_signal.get("calorie_adjustment") or 75))
        reasoning.append("Weight gain is below the target range, so add a conservative surplus.")
    else:
        reasoning.append("Recommendation follows the current protein-first lean-bulk target calculation.")

    if high_running:
        carb_bias_grams += 20 if running_load["status"] == "high" else 35
        reasoning.append("Running load is elevated, so any added fuel is biased toward carbs.")
    if high_training and recovery_status not in {"poor"}:
        carb_bias_grams += 10
        reasoning.append("Lifting workload is high enough to favor extra carbohydrate availability.")
    if recovery_status in {"strained", "poor"} and weight_status == "gaining too fast":
        warnings.append("Poor recovery does not trigger extra calories because weight gain is already too fast.")

    calorie_delta = max(-200, min(200, int(round(calorie_delta / 25) * 25)))
    recommended_calories = max(1200, current["target_calories"] + calorie_delta)
    protein = base_targets["protein_grams"]
    fat = max(base_targets["fat_grams"], base_targets.get("fat_floor_grams") or base_targets["fat_grams"])
    aligned = align_macro_calories(recommended_calories, protein, fat)
    if carb_bias_grams > 0 and aligned["carb_grams"] < base_targets["carb_grams"]:
        aligned = align_macro_calories(recommended_calories, protein, fat)

    recommended = {
        **base_targets,
        "target_calories": aligned["target_calories"],
        "protein_grams": aligned["protein_grams"],
        "carb_grams": aligned["carb_grams"],
        "fat_grams": aligned["fat_grams"],
        "macro_calories": aligned["macro_calories"],
        "calorie_macro_delta": aligned["calorie_macro_delta"],
    }
    changes = _macro_changes(current, recommended)

    return {
        "caloriesTarget": recommended["target_calories"],
        "proteinTarget": recommended["protein_grams"],
        "carbsTarget": recommended["carb_grams"],
        "fatTarget": recommended["fat_grams"],
        "calorieAdjustment": changes["calories"],
        "macroChanges": changes,
        "confidence": confidence,
        "reasoning": reasoning[:6],
        "signals": signals,
        "warnings": warnings[:5],
        "currentTarget": {
            "calories": current["target_calories"],
            "protein": current["protein_grams"],
            "carbs": current["carb_grams"],
            "fat": current["fat_grams"],
        },
        "recommendedTargets": recommended,
        "strategy": "Conservative Lean Bulk",
    }
