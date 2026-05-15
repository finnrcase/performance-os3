"""Calorie, macro, and bodyweight trend target engine."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.analytics.recovery_engine import analyze_recovery_signal
from src.goals import calculate_goal_feasibility
from src.paths import processed_data_path
from src.storage import load_document, save_document


NUTRITION_TARGETS_PATH = processed_data_path("nutrition_targets.json")

ACTIVITY_MULTIPLIERS = {
    "Low": 13.0,
    "Moderate": 14.2,
    "High": 14.8,
    "Very High": 15.5,
}

LEAN_BULK_RATE_RANGES = {
    "Conservative": (0.2, 0.4),
    "Moderate": (0.4, 0.7),
    "Aggressive": (0.5, 0.8),
}

LEAN_BULK_BASELINE_CALORIES = 2500

CUT_RATE_RANGES = {
    "Conservative": (-0.5, -0.75),
    "Moderate": (-0.75, -1.0),
    "Aggressive": (-1.0, -1.25),
}


def _normalize_goal_type(goal_type: str) -> str:
    return str(goal_type).strip().lower()


def estimate_maintenance_calories(user_goals: dict) -> float:
    """Estimate maintenance using bodyweight and activity.

    This avoids pretending precision we do not have yet. A future version can
    incorporate age, height, sex, measured TDEE, and wearable energy estimates.
    """
    bodyweight = float(user_goals.get("current_bodyweight") or 0)
    activity_level = user_goals.get("activity_level", "Moderate")
    base_multiplier = ACTIVITY_MULTIPLIERS.get(activity_level, ACTIVITY_MULTIPLIERS["Moderate"])
    training_frequency = int(user_goals.get("training_frequency_per_week") or 0)
    cardio_frequency = int(user_goals.get("cardio_frequency_per_week") or 0)

    training_adjustment = min(training_frequency, 6) * 35
    cardio_adjustment = min(cardio_frequency, 6) * 25

    return round(bodyweight * base_multiplier + training_adjustment + cardio_adjustment, -1)


def _clean_daily_nutrition(nutrition_df: pd.DataFrame | None, days: int = 28) -> pd.DataFrame:
    if nutrition_df is None or nutrition_df.empty:
        return pd.DataFrame(columns=["date", "calories", "protein", "carbs", "fat"])
    df = nutrition_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return pd.DataFrame(columns=["date", "calories", "protein", "carbs", "fat"])
    latest = df["date"].max()
    df = df[df["date"] >= latest - pd.Timedelta(days=days - 1)].copy()
    column_map = {
        "calories": "total_calories" if "total_calories" in df.columns else "calories",
        "protein": "total_protein" if "total_protein" in df.columns else "protein",
        "carbs": "total_carbs" if "total_carbs" in df.columns else "carbs",
        "fat": "total_fat" if "total_fat" in df.columns else "fat",
    }
    if all(source in df.columns for source in column_map.values()):
        daily = pd.DataFrame({"date": df["date"]})
        for target, source in column_map.items():
            daily[target] = pd.to_numeric(df[source], errors="coerce").fillna(0)
        if len(daily["date"]) == len(daily["date"].drop_duplicates()):
            return daily
    for column in ["calories", "protein", "carbs", "fat"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    return df.groupby("date", as_index=False).agg(
        calories=("calories", "sum"),
        protein=("protein", "sum"),
        carbs=("carbs", "sum"),
        fat=("fat", "sum"),
    )


def _latest_recovery_average(recovery_df: pd.DataFrame | None) -> float | None:
    if recovery_df is None or recovery_df.empty:
        return None
    df = recovery_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return None
    if "recovery_score" in df.columns:
        values = pd.to_numeric(df["recovery_score"], errors="coerce").dropna().tail(7)
        return round(float(values.mean()), 1) if not values.empty else None
    for column in ["sleep_quality", "fatigue", "soreness", "stress", "motivation"]:
        df[column] = pd.to_numeric(df.get(column, 5), errors="coerce").fillna(5)
    values = (
        (df["sleep_quality"] * 10)
        + ((11 - df["fatigue"]) * 10)
        + ((11 - df["soreness"]) * 10)
        + ((11 - df["stress"]) * 10)
        + (df["motivation"] * 10)
    ) / 5
    return round(float(values.tail(7).mean()), 1) if not values.empty else None


def _weekly_weight_pct(body_metrics_df: pd.DataFrame | None) -> float | None:
    if body_metrics_df is None or body_metrics_df.empty:
        return None
    df = body_metrics_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df["bodyweight"] = pd.to_numeric(df.get("bodyweight"), errors="coerce")
    df = df.dropna(subset=["date", "bodyweight"]).sort_values("date")
    if len(df) < 2:
        return None
    weekly_pct_14 = _weekly_rate_from_window(df, 14)
    return weekly_pct_14 if weekly_pct_14 is not None else _weekly_rate_from_window(df, 7)


def _clean_bodyweight_trend(body_metrics_df: pd.DataFrame | None) -> pd.DataFrame:
    if body_metrics_df is None or body_metrics_df.empty:
        return pd.DataFrame(columns=["date", "bodyweight"])
    df = body_metrics_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df["bodyweight"] = pd.to_numeric(df.get("bodyweight"), errors="coerce")
    df = df.dropna(subset=["date", "bodyweight"]).sort_values("date")
    if df.empty:
        return pd.DataFrame(columns=["date", "bodyweight"])
    return df.groupby("date", as_index=False)["bodyweight"].mean().sort_values("date")


def calculate_bodyweight_trend_signal(body_metrics_df: pd.DataFrame | None, user_goals: dict) -> dict:
    """Return a conservative lean-bulk weight trend signal using rolling averages."""
    target_low, target_high = LEAN_BULK_RATE_RANGES.get(
        user_goals.get("aggressiveness", "Conservative"),
        LEAN_BULK_RATE_RANGES["Conservative"],
    )
    empty = {
        "status": "insufficient data",
        "current_7_day_avg": None,
        "previous_7_day_avg": None,
        "fourteen_day_avg": None,
        "weekly_change_lb": None,
        "weekly_change_pct": None,
        "calorie_adjustment": 0,
        "confidence": "low",
        "reason": "Log at least 7 daily weigh-ins to estimate the lean-bulk trend.",
        "data_points": 0,
        "target_weekly_change_low": target_low,
        "target_weekly_change_high": target_high,
    }
    df = _clean_bodyweight_trend(body_metrics_df)
    if df.empty:
        return empty
    latest = df["date"].max()
    recent = df[df["date"] >= latest - pd.Timedelta(days=13)].copy()
    data_points = int(len(recent))
    if data_points < 7:
        return {**empty, "data_points": data_points}

    current_window = recent[recent["date"] >= latest - pd.Timedelta(days=6)]["bodyweight"]
    previous_window = recent[
        (recent["date"] < latest - pd.Timedelta(days=6))
        & (recent["date"] >= latest - pd.Timedelta(days=13))
    ]["bodyweight"]
    current_avg = float(current_window.mean())
    previous_avg = float(previous_window.mean()) if len(previous_window) >= 3 else None
    fourteen_avg = float(recent["bodyweight"].mean()) if data_points >= 14 else None

    confidence = "high" if data_points >= 14 else "low"
    if previous_avg is not None:
        weekly_change_lb = current_avg - previous_avg
        baseline = previous_avg
        window_used = "current 7-day average vs previous 7-day average"
    else:
        first = recent.iloc[0]
        elapsed_days = max((latest - first["date"]).days, 1)
        weekly_change_lb = (current_avg - float(first["bodyweight"])) / elapsed_days * 7
        baseline = float(first["bodyweight"])
        window_used = "partial 7-day trend"

    weekly_pct = (weekly_change_lb / baseline * 100) if baseline > 0 else 0
    daily_changes = recent["bodyweight"].diff().dropna()
    noisy = bool(len(daily_changes) >= 4 and daily_changes.std() > 1.25 and confidence == "low")

    status = "gaining in target range"
    adjustment = 0
    reason = f"Weight trend is {weekly_change_lb:+.2f} lb/week ({weekly_pct:+.2f}%/week) using {window_used}."

    if noisy:
        status = "noisy"
        reason = "Recent weigh-ins are noisy, so targets should stay stable until the 14-day average is clearer."
    elif weekly_pct < target_low:
        status = "gaining too slowly"
        adjustment = 150 if confidence == "high" and weekly_pct < target_low / 2 else 75
        reason = f"Gain is below the conservative lean-bulk target of {target_low:.2f}% to {target_high:.2f}%/week."
    elif weekly_pct <= target_high:
        status = "gaining in target range"
        reason = f"Gain is inside the conservative lean-bulk target of {target_low:.2f}% to {target_high:.2f}%/week."
    else:
        status = "gaining too fast"
        adjustment = -200 if confidence == "high" and weekly_pct > target_high * 1.5 else -100
        reason = f"Gain is above the conservative lean-bulk ceiling of {target_high:.2f}%/week."

    return {
        "status": status,
        "current_7_day_avg": round(current_avg, 2),
        "previous_7_day_avg": round(previous_avg, 2) if previous_avg is not None else None,
        "fourteen_day_avg": round(fourteen_avg, 2) if fourteen_avg is not None else None,
        "weekly_change_lb": round(weekly_change_lb, 2),
        "weekly_change_pct": round(weekly_pct, 3),
        "calorie_adjustment": adjustment,
        "confidence": confidence,
        "reason": reason,
        "data_points": data_points,
        "target_weekly_change_low": target_low,
        "target_weekly_change_high": target_high,
    }


def align_macro_calories(target_calories: float, protein_grams: float, fat_grams: float) -> dict:
    """Allocate carbs so rounded macro calories stay as close as possible to target calories."""
    calories = int(round(float(target_calories)))
    protein = max(0, int(round(float(protein_grams))))
    fat = max(0, int(round(float(fat_grams))))
    remaining_calories = calories - (protein * 4) - (fat * 9)
    carbs = max(0, int(round(remaining_calories / 4)))

    macro_calories = (protein * 4) + (carbs * 4) + (fat * 9)
    best_carbs = carbs
    best_delta = abs(macro_calories - calories)
    for candidate in range(max(0, carbs - 2), carbs + 3):
        candidate_calories = (protein * 4) + (candidate * 4) + (fat * 9)
        candidate_delta = abs(candidate_calories - calories)
        if candidate_delta < best_delta:
            best_carbs = candidate
            best_delta = candidate_delta
            macro_calories = candidate_calories

    return {
        "target_calories": calories,
        "protein_grams": protein,
        "carb_grams": best_carbs,
        "fat_grams": fat,
        "macro_calories": int(macro_calories),
        "calorie_macro_delta": int(macro_calories - calories),
    }


def calculate_macro_targets(
    user_goals: dict,
    nutrition_df: pd.DataFrame | None = None,
    training_df: pd.DataFrame | None = None,
    recovery_df: pd.DataFrame | None = None,
    body_metrics_df: pd.DataFrame | None = None,
    workload_data: dict | None = None,
) -> dict:
    """Calculate conservative calorie and macro targets from saved goals.

    Protein assumptions are based on common sports nutrition practice and ISSN
    protein/body composition guidance, which commonly supports roughly
    0.8-1.0 g/lb for resistance-trained athletes, with the higher end useful
    during cuts and recomposition phases.
    """
    goal_type = user_goals.get("goal_type", "Lean Bulk")
    normalized_goal = _normalize_goal_type(goal_type)
    aggressiveness = user_goals.get("aggressiveness", "Conservative")
    bodyweight = float(user_goals.get("current_bodyweight") or 0)
    maintenance = estimate_maintenance_calories(user_goals)

    surplus_ranges = {
        "Conservative": (150, 225),
        "Moderate": (225, 350),
        "Aggressive": (325, 450),
    }
    cut_deficits = {
        "Conservative": 250,
        "Moderate": 400,
        "Aggressive": 550,
    }

    workload_current = (workload_data or {}).get("current", {})
    training_frequency = float(workload_current.get("strength_workouts_per_week") or user_goals.get("training_frequency_per_week") or 0)
    cardio_frequency = float(workload_current.get("runs_per_week") or user_goals.get("cardio_frequency_per_week") or 0)
    weekly_mileage = float(workload_current.get("weekly_mileage") or 0)
    workload_calorie_adjustment = float(workload_current.get("calorie_adjustment") or 0)
    workload_carb_adjustment = int(round(float(workload_current.get("carb_adjustment_grams") or 0)))
    recovery_demand = str(workload_current.get("recovery_demand") or "low")
    performance_signal = workload_current.get("performance_signal") or {}
    performance_label = str(performance_signal.get("label") or "insufficient data")
    recovery_average = _latest_recovery_average(recovery_df)
    weight_signal = calculate_bodyweight_trend_signal(body_metrics_df, user_goals)
    weekly_weight_pct = weight_signal["weekly_change_pct"]
    historical_daily = _clean_daily_nutrition(nutrition_df)
    historical_note = "More logged nutrition/training data will personalize these targets further."

    calorie_adjustment = 0
    historical_calorie_adjustment = 0
    target_weekly_change_pct = 0.0
    target_description = "Maintain stable intake and monitor training performance."

    if normalized_goal == "lean bulk":
        low, high = surplus_ranges.get(aggressiveness, surplus_ranges["Conservative"])
        calorie_adjustment = round((low + high) / 2)
        target_low, target_high = LEAN_BULK_RATE_RANGES.get(aggressiveness, LEAN_BULK_RATE_RANGES["Conservative"])
        target_weekly_change_pct = round((target_low + target_high) / 2, 2)
        target_description = (
            "Protein-first lean bulk with a 2500 kcal conservative baseline, tighter surplus control, and carb support only when workload/recovery data justifies it."
        )
        if training_frequency >= 5:
            calorie_adjustment += 50
        if cardio_frequency >= 3 or weekly_mileage >= 12:
            calorie_adjustment += 50
        if workload_calorie_adjustment > 0:
            calorie_adjustment += min(175, max(0, workload_calorie_adjustment - 75))
        if weight_signal["status"] in {"gaining too slowly", "gaining too fast"}:
            historical_calorie_adjustment += int(weight_signal["calorie_adjustment"])
        if performance_label in {"declining", "fatigue/performance stagnation"}:
            if weight_signal["status"] == "gaining too slowly":
                historical_calorie_adjustment += max(0, 125 - int(weight_signal["calorie_adjustment"]))
                workload_carb_adjustment += 25
            elif weight_signal["status"] != "gaining too fast" and recovery_demand == "high":
                workload_carb_adjustment += 15
    elif normalized_goal == "cut":
        calorie_adjustment = -cut_deficits.get(aggressiveness, cut_deficits["Conservative"])
        cut_low, cut_high = CUT_RATE_RANGES.get(aggressiveness, CUT_RATE_RANGES["Conservative"])
        target_weekly_change_pct = round((cut_low + cut_high) / 2, 2)
        target_description = "Gradual fat-loss target with performance and lean-mass protection in mind."
    elif normalized_goal == "recomposition":
        calorie_adjustment = -100 if aggressiveness == "Aggressive" else 0
        target_weekly_change_pct = 0.0
        target_description = "Stable calories, high protein, and consistent training quality."
    elif normalized_goal == "performance / mile time":
        calorie_adjustment = 100 if user_goals.get("activity_level") in ["High", "Very High"] else 0
        target_weekly_change_pct = 0.0
        target_description = "Fuel training quality while avoiding large bodyweight swings."

    preliminary_target_calories = max(1200, maintenance + calorie_adjustment + historical_calorie_adjustment)
    recovery_signal = analyze_recovery_signal(
        recovery_df if recovery_df is not None else pd.DataFrame(),
        training_df=training_df,
        nutrition_df=nutrition_df,
        target_calories=preliminary_target_calories,
        performance_signal=performance_signal,
        workload_data=workload_data,
    )
    recovery_status = str(recovery_signal.get("status") or "insufficient data")

    if (recovery_average is not None and recovery_average < 60 or recovery_demand == "high") and normalized_goal in ["lean bulk", "performance / mile time"]:
        historical_calorie_adjustment += 50
    if normalized_goal in ["lean bulk", "performance / mile time"] and recovery_status in {"poor", "strained"}:
        if weight_signal["status"] == "gaining too slowly" or performance_label in {"declining", "fatigue/performance stagnation"}:
            desired_recovery_support = 150 if recovery_status == "poor" else 125
            historical_calorie_adjustment += max(0, desired_recovery_support - max(0, int(historical_calorie_adjustment)))
            workload_carb_adjustment += 20 if recovery_status == "poor" else 10
        elif weight_signal["status"] == "gaining too fast":
            workload_carb_adjustment += 0

    target_calories = max(1200, maintenance + calorie_adjustment + historical_calorie_adjustment)
    if normalized_goal == "lean bulk" and 145 <= bodyweight <= 175:
        target_calories = LEAN_BULK_BASELINE_CALORIES
        if weight_signal["status"] == "gaining too slowly":
            target_calories += min(150, max(50, int(weight_signal["calorie_adjustment"])))
        elif weight_signal["status"] == "gaining too fast":
            target_calories += max(-200, min(-75, int(weight_signal["calorie_adjustment"])))
        elif performance_label in {"declining", "fatigue/performance stagnation"} and recovery_demand == "high":
            target_calories += 75
    final_calorie_adjustment = target_calories - maintenance

    if normalized_goal == "cut":
        protein_per_lb = {"Conservative": 1.1, "Moderate": 1.2, "Aggressive": 1.3}.get(aggressiveness, 1.2)
    elif normalized_goal == "lean bulk":
        protein_per_lb = {"Conservative": 1.1, "Moderate": 1.05, "Aggressive": 1.0}.get(aggressiveness, 1.1)
    elif normalized_goal in ["recomposition"]:
        protein_per_lb = 1.05
    elif normalized_goal in ["maintain", "performance / mile time"]:
        protein_per_lb = 0.95
    else:
        protein_per_lb = 0.9

    protein_grams = round(bodyweight * protein_per_lb)

    if normalized_goal == "lean bulk":
        fat_per_lb = 0.4 if (recovery_average is None or recovery_average >= 65) and recovery_demand != "high" else 0.43
    elif normalized_goal == "cut":
        fat_per_lb = 0.32
    else:
        fat_per_lb = 0.35
    fat_per_lb += 0.03 if recovery_average is not None and recovery_average < 60 else 0
    fat_floor_grams = bodyweight * fat_per_lb
    fat_calories = max(target_calories * 0.22, fat_floor_grams * 9)
    fat_grams = round(fat_calories / 9)

    aligned_macros = align_macro_calories(target_calories, protein_grams, fat_grams)
    target_calories = aligned_macros["target_calories"]
    protein_grams = aligned_macros["protein_grams"]
    carb_grams = aligned_macros["carb_grams"]
    fat_grams = aligned_macros["fat_grams"]
    carb_emphasis = "Moderate carb baseline."
    if normalized_goal == "lean bulk":
        if training_frequency >= 5 or cardio_frequency >= 3 or weekly_mileage >= 12:
            carb_emphasis = "Conservative 2500 kcal baseline with training-day carb support for frequent lifting/cardio."
        else:
            carb_emphasis = "Conservative 2500 kcal lean-bulk baseline with carbs filling the remaining performance fuel."
    elif normalized_goal == "cut":
        carb_emphasis = "Carbs fill remaining calories after protein and fat floors."

    if not historical_daily.empty and len(historical_daily) >= 7:
        averages = historical_daily[["calories", "protein", "carbs", "fat"]].mean(numeric_only=True)
        historical_note = (
            f"Recent logged average: {averages['calories']:.0f} kcal, "
            f"{averages['protein']:.0f}g protein, {averages['carbs']:.0f}g carbs, {averages['fat']:.0f}g fat."
        )
        if normalized_goal == "lean bulk" and averages["carbs"] >= carb_grams * 0.9:
            carb_emphasis = "Historical logs support keeping carbs high for training output."
    if workload_carb_adjustment:
        carb_emphasis = f"{carb_emphasis} Workload analysis adds about {workload_carb_adjustment}g carbs for recent Hevy/Strava demand."
    if performance_label == "declining":
        if weight_signal["status"] == "gaining too fast":
            carb_emphasis = f"{carb_emphasis} Hevy performance is declining, but fast weight gain points toward fatigue/recovery/programming before adding calories."
        elif weight_signal["status"] == "gaining too slowly":
            carb_emphasis = f"{carb_emphasis} Hevy performance is declining while gain is slow, so the suggestion biases added calories toward carbs."
        else:
            carb_emphasis = f"{carb_emphasis} Hevy performance is declining; keep changes conservative and review recovery before adding a larger surplus."
    elif performance_label == "fatigue/performance stagnation":
        carb_emphasis = f"{carb_emphasis} Hevy volume looks high with flat/down performance, so prioritize recovery and training-day carbs."
    if recovery_status == "poor":
        if weight_signal["status"] == "gaining too fast":
            carb_emphasis = f"{carb_emphasis} Recovery is poor, but fast weight gain means the app is flagging sleep/readiness/load instead of adding calories."
        else:
            carb_emphasis = f"{carb_emphasis} Poor recovery biases any added calories toward carbs and highlights sleep/readiness first."
    elif recovery_status == "strained":
        carb_emphasis = f"{carb_emphasis} Strained recovery suggests keeping carbs near training and avoiding aggressive cuts."

    feasibility = calculate_goal_feasibility(user_goals)

    return {
        "target_calories": int(round(target_calories)),
        "maintenance_calories": int(round(maintenance)),
        "calorie_adjustment": int(round(final_calorie_adjustment)),
        "protein_grams": int(protein_grams),
        "carb_grams": int(carb_grams),
        "fat_grams": int(fat_grams),
        "macro_calories": aligned_macros["macro_calories"],
        "calorie_macro_delta": aligned_macros["calorie_macro_delta"],
        "protein_per_lb": round(protein_per_lb, 2),
        "fat_per_lb": round(fat_grams / bodyweight, 2) if bodyweight > 0 else 0,
        "fat_floor_grams": int(round(fat_floor_grams)) if bodyweight > 0 else 0,
        "carb_emphasis": carb_emphasis,
        "historical_note": historical_note,
        "historical_calorie_adjustment": int(round(historical_calorie_adjustment)),
        "workload_calorie_adjustment": int(round(workload_calorie_adjustment)),
        "workload_carb_adjustment_grams": workload_carb_adjustment,
        "training_workload": workload_data or {},
        "recovery_average": recovery_average,
        "recovery_signal": recovery_signal,
        "weekly_weight_change_pct": round(weekly_weight_pct, 3) if weekly_weight_pct is not None else None,
        "bodyweight_trend_signal": weight_signal,
        "target_weekly_change_pct": target_weekly_change_pct,
        "target_weekly_change_range": {
            "low": LEAN_BULK_RATE_RANGES.get(aggressiveness, LEAN_BULK_RATE_RANGES["Conservative"])[0] if normalized_goal == "lean bulk" else None,
            "high": LEAN_BULK_RATE_RANGES.get(aggressiveness, LEAN_BULK_RATE_RANGES["Conservative"])[1] if normalized_goal == "lean bulk" else None,
        },
        "expected_weekly_weight_change": round(bodyweight * target_weekly_change_pct / 100, 2),
        "target_description": target_description,
        "timeline_status": feasibility["status"],
        "timeline_warning": feasibility["warning"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_nutrition_targets() -> dict:
    """Load saved nutrition targets, returning an empty dict if missing."""
    return load_document("nutrition_targets", NUTRITION_TARGETS_PATH, {})


def save_nutrition_targets(targets: dict) -> dict:
    """Persist nutrition targets locally."""
    targets = {**targets, "updated_at": targets.get("updated_at") or datetime.now(timezone.utc).isoformat()}
    return save_document("nutrition_targets", NUTRITION_TARGETS_PATH, targets)


def _weekly_rate_from_window(trend_df: pd.DataFrame, days: int) -> float | None:
    """Return bodyweight percent change per week for a recent window."""
    if trend_df.empty or len(trend_df) < 2:
        return None

    latest_date = trend_df["date"].max()
    window_df = trend_df[trend_df["date"] >= latest_date - pd.Timedelta(days=days)].copy()
    if len(window_df) < 2:
        return None

    first = window_df.iloc[0]
    last = window_df.iloc[-1]
    elapsed_days = max((last["date"] - first["date"]).days, 1)
    weight_change = float(last["bodyweight"] - first["bodyweight"])
    weekly_change = weight_change / elapsed_days * 7
    baseline_weight = float(first["bodyweight"])

    if baseline_weight <= 0:
        return None

    return weekly_change / baseline_weight * 100


def analyze_weight_trend(body_metrics_df: pd.DataFrame, user_goals: dict) -> dict:
    """Analyze recent bodyweight trend and suggest calorie adjustments.

    Uses 7-day and 14-day windows when available. The output is intentionally
    conservative and intended for fitness-oriented feedback, not medical advice.
    """
    empty_response = {
        "status": "Not enough data",
        "weekly_change_pct": None,
        "weekly_change_lb": None,
        "suggested_adjustment": "Log at least two bodyweight entries to generate trend feedback.",
        "reason": "Bodyweight trend data is not available yet.",
        "window_used": "none",
        "current_7_day_avg": None,
        "previous_7_day_avg": None,
        "fourteen_day_avg": None,
        "confidence": "low",
        "calorie_adjustment": 0,
    }
    signal = calculate_bodyweight_trend_signal(body_metrics_df, user_goals)
    if signal["data_points"] < 7:
        return {**empty_response, "reason": signal["reason"], "target_weekly_change_low": signal["target_weekly_change_low"], "target_weekly_change_high": signal["target_weekly_change_high"]}

    status_map = {
        "gaining too slowly": "Gaining too slowly",
        "gaining in target range": "On track",
        "gaining too fast": "Gaining too quickly",
        "noisy": "Noisy trend",
    }
    calorie_adjustment = int(signal["calorie_adjustment"])
    if calorie_adjustment > 0:
        adjustment = f"Increase calories by {calorie_adjustment} kcal/day."
    elif calorie_adjustment < 0:
        adjustment = f"Reduce calories by {abs(calorie_adjustment)} kcal/day."
    else:
        adjustment = "Maintain current calories."

    return {
        "status": status_map.get(signal["status"], "Not enough data"),
        "weekly_change_pct": signal["weekly_change_pct"],
        "weekly_change_lb": signal["weekly_change_lb"],
        "suggested_adjustment": adjustment,
        "reason": signal["reason"],
        "window_used": "14 days" if signal["confidence"] == "high" else "7 days",
        "current_7_day_avg": signal["current_7_day_avg"],
        "previous_7_day_avg": signal["previous_7_day_avg"],
        "fourteen_day_avg": signal["fourteen_day_avg"],
        "confidence": signal["confidence"],
        "calorie_adjustment": calorie_adjustment,
        "target_weekly_change_low": signal["target_weekly_change_low"],
        "target_weekly_change_high": signal["target_weekly_change_high"],
    }
