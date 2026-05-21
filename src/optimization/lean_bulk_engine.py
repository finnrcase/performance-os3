"""Lean bulk calorie optimization engine.

This module makes conservative calorie decisions from smoothed trends. It does
not react to single weigh-ins; it combines bodyweight averages, nutrition
adherence, training performance, recovery, and optional waist/body-fat trends.
"""

from __future__ import annotations

import pandas as pd

from src.analytics.recovery_engine import analyze_recovery_signal
from src.analytics.training_workload import analyze_hevy_performance_signal
from src.analytics.strength_trends import calculate_strength_trend
from src.body_metrics import canonical_daily_bodyweights
from src.nutrition_targets import calculate_macro_targets


KEY_LIFT_GROUPS = {
    "bench": ["Bench Press (Barbell)", "Bench Press", "Barbell Bench Press", "Flat Bench Press", "Bench"],
    "squat_or_leg_press": ["Squat", "Back Squat", "Front Squat", "Leg Press", "Pendulum Squat (Machine)"],
    "deadlift_or_rdl": ["Deadlift", "Romanian Deadlift (Barbell)", "RDL"],
    "overhead_press": ["Overhead Press", "Shoulder Press (Dumbbell)", "Shoulder Press", "Military Press"],
    "pull_or_row": ["Pull Up", "Pull-ups", "Lat Pulldown (Cable)", "T Bar Row", "Row"],
}

TARGET_RATES = {
    "Conservative": 0.3,
    "Moderate": 0.55,
    "Aggressive": 0.65,
}

TARGET_RANGES = {
    "Conservative": (0.2, 0.4),
    "Moderate": (0.4, 0.7),
    "Aggressive": (0.5, 0.8),
}


def _empty_response(target_calories: int, reason: str) -> dict:
    return {
        "recommendation": "maintain",
        "calorie_change": 0,
        "new_target_calories": target_calories,
        "confidence": "low",
        "weekly_weight_change_pct": None,
        "fat_gain_risk_score": 0,
        "reasoning": [reason],
        "next_check_in_days": 7,
        "details": {
            "seven_day_avg_weight": None,
            "fourteen_day_avg_weight": None,
            "calorie_average": None,
            "protein_average": None,
            "protein_target": None,
            "training_trend": "insufficient data",
            "performance_signal": {
                "label": "insufficient data",
                "confidence": "low",
                "summary": "Need more comparable Hevy lifting history.",
                "recommendation": "Keep nutrition targets stable until more comparable sessions are available.",
                "drivers": [],
                "muscle_group_drivers": [],
            },
            "recovery_trend": "insufficient data",
            "recovery_signal": {
                "status": "insufficient data",
                "confidence": "low",
                "score": None,
                "summary": "Log recovery or connect wearable data to personalize nutrition recovery adjustments.",
                "nutrition_implication": "Keep nutrition targets stable until recovery data is available.",
                "suggested_action": "Log sleep, fatigue, soreness, HRV, or resting heart rate.",
                "drivers": [],
                "metrics": {},
            },
            "target_weekly_gain_pct": None,
        },
    }


def _clean_bodyweight(body_metrics_df: pd.DataFrame) -> pd.DataFrame:
    if body_metrics_df is None or body_metrics_df.empty:
        return pd.DataFrame(columns=["date", "bodyweight", "waist", "estimated_body_fat"])
    df = canonical_daily_bodyweights(body_metrics_df)
    for column in ["bodyweight", "waist", "estimated_body_fat"]:
        if column not in df.columns:
            df[column] = None
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df.dropna(subset=["date", "bodyweight"]).sort_values("date")


def _window_average(df: pd.DataFrame, value_col: str, days: int) -> float | None:
    if df.empty or value_col not in df.columns:
        return None
    latest = df["date"].max()
    window = df[df["date"] >= latest - pd.Timedelta(days=days - 1)]
    values = pd.to_numeric(window[value_col], errors="coerce").dropna()
    if values.empty:
        return None
    return round(float(values.mean()), 2)


def _weekly_weight_change_pct(weight_df: pd.DataFrame) -> tuple[float | None, float | None, float | None]:
    if weight_df.empty or len(weight_df) < 7:
        return None, None, None
    latest = weight_df["date"].max()
    recent_7 = weight_df[weight_df["date"] >= latest - pd.Timedelta(days=6)]["bodyweight"].dropna()
    previous_7 = weight_df[
        (weight_df["date"] < latest - pd.Timedelta(days=6))
        & (weight_df["date"] >= latest - pd.Timedelta(days=13))
    ]["bodyweight"].dropna()
    seven_avg = round(float(recent_7.mean()), 2) if len(recent_7) else None
    fourteen_avg = _window_average(weight_df, "bodyweight", 14)
    if len(recent_7) >= 3 and len(previous_7) >= 3:
        previous_avg = float(previous_7.mean())
        if previous_avg > 0:
            return round(((seven_avg - previous_avg) / previous_avg) * 100, 3), seven_avg, fourteen_avg

    if len(weight_df) >= 2:
        window = weight_df[weight_df["date"] >= latest - pd.Timedelta(days=13)].copy()
        first = window.iloc[0]
        last = window.iloc[-1]
        elapsed = max((last["date"] - first["date"]).days, 1)
        weekly_gain = (float(last["bodyweight"]) - float(first["bodyweight"])) / elapsed * 7
        if float(first["bodyweight"]) > 0:
            return round((weekly_gain / float(first["bodyweight"])) * 100, 3), seven_avg, fourteen_avg
    return None, seven_avg, fourteen_avg


def _nutrition_averages(nutrition_df: pd.DataFrame, days: int = 14) -> tuple[float | None, float | None]:
    if nutrition_df.empty:
        return None, None
    df = nutrition_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    if df.empty:
        return None, None
    latest = df["date"].max()
    recent = df[df["date"] >= latest - pd.Timedelta(days=days - 1)].copy()
    if {"total_calories", "total_protein"}.issubset(recent.columns):
        daily = recent.copy()
        daily["calories"] = pd.to_numeric(daily["total_calories"], errors="coerce").fillna(0)
        daily["protein"] = pd.to_numeric(daily["total_protein"], errors="coerce").fillna(0)
    else:
        for column in ["calories", "protein"]:
            recent[column] = pd.to_numeric(recent.get(column, 0), errors="coerce").fillna(0)
        daily = recent.groupby("date", as_index=False).agg(calories=("calories", "sum"), protein=("protein", "sum"))
    if daily.empty:
        return None, None
    return round(float(daily["calories"].mean()), 0), round(float(daily["protein"].mean()), 1)


def _nutrition_adherence(nutrition_df: pd.DataFrame, days: int = 7) -> tuple[float | None, float | None, int | None, int | None]:
    if nutrition_df.empty or "target_calories" not in nutrition_df.columns:
        return None, None, None, None
    df = nutrition_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").tail(days)
    actual_col = "total_calories" if "total_calories" in df.columns else "calories"
    protein_col = "total_protein" if "total_protein" in df.columns else "protein"
    for column in [actual_col, protein_col, "target_calories", "target_protein"]:
        df[column] = pd.to_numeric(df.get(column), errors="coerce")
    with_targets = df.dropna(subset=["target_calories"])
    protein_targets = df.dropna(subset=["target_protein"])
    if with_targets.empty:
        return None, None, None, None
    calorie_delta = float((with_targets[actual_col] - with_targets["target_calories"]).mean())
    protein_hit_rate = None
    if not protein_targets.empty:
        protein_hit_rate = float((protein_targets[protein_col] >= protein_targets["target_protein"] * 0.9).mean() * 100)
    return (
        round(calorie_delta, 0),
        round(protein_hit_rate, 1) if protein_hit_rate is not None else None,
        int((with_targets[actual_col] > with_targets["target_calories"]).sum()),
        int((with_targets[actual_col] < with_targets["target_calories"]).sum()),
    )


def _recovery_trend(recovery_df: pd.DataFrame) -> tuple[str, float | None]:
    if recovery_df.empty:
        return "insufficient data", None
    df = recovery_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return "insufficient data", None
    if "recovery_score" in df.columns:
        scores = pd.to_numeric(df["recovery_score"], errors="coerce").dropna()
    else:
        # Simple fallback readiness proxy using available subjective recovery fields.
        for column in ["sleep_quality", "fatigue", "soreness", "stress", "motivation"]:
            df[column] = pd.to_numeric(df.get(column, 5), errors="coerce").fillna(5)
        scores = (
            (df["sleep_quality"] * 10)
            + ((11 - df["fatigue"]) * 10)
            + ((11 - df["soreness"]) * 10)
            + ((11 - df["stress"]) * 10)
            + (df["motivation"] * 10)
        ) / 5
    if scores.empty:
        return "insufficient data", None
    latest_avg = float(scores.tail(min(7, len(scores))).mean())
    if latest_avg < 60:
        return "poor", round(latest_avg, 1)
    if latest_avg < 75:
        return "moderate", round(latest_avg, 1)
    return "good", round(latest_avg, 1)


def _find_exercise(training_df: pd.DataFrame, candidates: list[str]) -> str | None:
    if training_df.empty or "exercise" not in training_df.columns:
        return None
    exercises = training_df["exercise"].fillna("").astype(str).unique()
    lower_map = {exercise.lower(): exercise for exercise in exercises}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    for exercise in exercises:
        name = exercise.lower()
        if any(candidate.lower() in name for candidate in candidates):
            return exercise
    return None


def _training_performance(training_df: pd.DataFrame) -> tuple[str, dict]:
    trends = {}
    labels = []
    for group, candidates in KEY_LIFT_GROUPS.items():
        exercise = _find_exercise(training_df, candidates)
        if not exercise:
            trends[group] = {"exercise": None, "label": "insufficient data"}
            continue
        trend = calculate_strength_trend(training_df, exercise)
        trends[group] = {"exercise": exercise, "label": trend.get("label", "insufficient data")}
        labels.append(trend.get("label", "insufficient data"))

    if not labels or all(label == "insufficient data" for label in labels):
        return "insufficient data", trends
    improving = labels.count("improving")
    declining = labels.count("declining")
    if improving >= max(1, declining + 1):
        return "improving", trends
    if declining >= max(1, improving + 1):
        return "declining", trends
    return "stable", trends


def _nutrition_performance_label(performance_signal: dict, fallback_label: str) -> str:
    label = str(performance_signal.get("label") or fallback_label)
    if label == "fatigue/performance stagnation":
        return label
    return label if label != "insufficient data" else fallback_label


def _trend_rate(df: pd.DataFrame, column: str) -> float:
    values = pd.to_numeric(df.get(column, pd.Series(dtype=float)), errors="coerce")
    dates = pd.to_datetime(df.get("date", pd.Series(dtype=str)), errors="coerce")
    trend = pd.DataFrame({"date": dates, "value": values}).dropna().sort_values("date")
    if len(trend) < 2:
        return 0.0
    first = trend.iloc[0]
    last = trend.iloc[-1]
    elapsed = max((last["date"] - first["date"]).days, 1)
    return float(last["value"] - first["value"]) / elapsed * 7


def _fat_gain_risk(weight_pct: float, target_pct: float, body_df: pd.DataFrame, training_trend: str, recovery_trend: str) -> int:
    risk = 0
    if weight_pct > target_pct:
        risk += min(35, int((weight_pct - target_pct) / max(target_pct, 0.1) * 25))
    body_fat_rate = _trend_rate(body_df.tail(28), "estimated_body_fat")
    waist_rate = _trend_rate(body_df.tail(28), "waist")
    if body_fat_rate > 0.2:
        risk += 20
    if waist_rate > 0.1:
        risk += 20
    if weight_pct > target_pct and training_trend in {"declining", "stable"}:
        risk += 15
    if recovery_trend == "poor":
        risk += 10
    return max(0, min(100, risk))


def generate_lean_bulk_calorie_recommendation(
    body_metrics_df,
    nutrition_df,
    training_df,
    recovery_df,
    user_goals,
) -> dict:
    """Generate a lean-bulk calorie decision from smoothed local data."""
    targets = calculate_macro_targets(user_goals)
    target_calories = int(targets["target_calories"])
    goal_type = str(user_goals.get("goal_type", "Lean Bulk")).lower()
    if goal_type != "lean bulk":
        return _empty_response(target_calories, "Lean Bulk Calorie Decision activates when goal type is Lean Bulk.")

    body_df = _clean_bodyweight(body_metrics_df)
    if len(body_df) < 7:
        return _empty_response(target_calories, "Need more data before adjusting calories. Log at least 7 days of bodyweight entries.")

    weekly_pct, seven_avg, fourteen_avg = _weekly_weight_change_pct(body_df)
    if weekly_pct is None:
        return _empty_response(target_calories, "Need more data before adjusting calories. Current weigh-ins are too sparse for a smoothed trend.")

    calorie_avg, protein_avg = _nutrition_averages(nutrition_df)
    calorie_delta_avg, protein_hit_rate, days_over_target, days_under_target = _nutrition_adherence(nutrition_df)
    latest_weight = float(body_df.iloc[-1]["bodyweight"])
    protein_target = int(targets.get("protein_grams") or round(latest_weight * 1.1))
    recovery_label, recovery_avg = _recovery_trend(recovery_df)
    key_lift_label, key_lift_trends = _training_performance(training_df)
    performance_signal = analyze_hevy_performance_signal(training_df)
    training_label = _nutrition_performance_label(performance_signal, key_lift_label)
    recovery_signal = analyze_recovery_signal(
        recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        target_calories=target_calories,
        performance_signal=performance_signal,
    )
    recovery_status = str(recovery_signal.get("status") or recovery_label)
    if recovery_status != "insufficient data":
        recovery_label = recovery_status

    aggressiveness = user_goals.get("aggressiveness", "Conservative")
    target_rate = TARGET_RATES.get(aggressiveness, 0.25)
    ideal_low, ideal_high = TARGET_RANGES.get(aggressiveness, TARGET_RANGES["Conservative"])
    risk = _fat_gain_risk(weekly_pct, target_rate, body_df, training_label, recovery_label)

    reasoning = [
        f"Smoothed weekly weight trend is {weekly_pct:+.2f}%/week.",
        f"Lean bulk target range is {ideal_low:.2f}% to {ideal_high:.2f}%/week.",
    ]
    if calorie_avg is not None:
        reasoning.append(f"Recent calorie average is {int(calorie_avg)} kcal/day.")
    if calorie_delta_avg is not None:
        direction = "over" if calorie_delta_avg > 0 else "under"
        reasoning.append(f"7-day calories average {abs(int(calorie_delta_avg))} kcal/day {direction} target.")
    if protein_avg is not None:
        reasoning.append(f"Recent protein average is {protein_avg:g}g/day vs ~{protein_target}g target.")
    if protein_hit_rate is not None:
        reasoning.append(f"Protein target consistency is {protein_hit_rate:.0f}% over recent logged days.")
    if performance_signal.get("summary") and performance_signal.get("label") != "insufficient data":
        reasoning.append(f"Hevy performance signal: {performance_signal['summary']}")
    else:
        reasoning.append(f"Training trend is {training_label}.")
    if recovery_signal.get("summary") and recovery_status != "insufficient data":
        reasoning.append(f"Recovery signal: {recovery_signal['summary']}")
    else:
        reasoning.append(f"Recovery trend is {recovery_label}.")

    recommendation = "maintain"
    calorie_change = 0
    confidence = "medium"

    if protein_avg is not None and protein_avg < protein_target * 0.9:
        reasoning.append("Protein is below target; fix protein consistency before changing calories.")
        confidence = "medium"
    elif weekly_pct < ideal_low and recovery_label not in {"poor"}:
        recommendation = "increase"
        calorie_change = 125 if training_label in {"declining", "fatigue/performance stagnation"} else 100
        if training_label in {"declining", "fatigue/performance stagnation"}:
            reasoning.append("Weight gain is below lean-bulk pace while Hevy performance is soft, so add a small carb-focused increase.")
        else:
            reasoning.append("Weight gain is below lean-bulk pace and recovery is not poor, so a small calorie/carbohydrate increase is appropriate.")
    elif recovery_label == "poor" and (training_label in {"declining", "fatigue/performance stagnation"} or weekly_pct < ideal_low) and weekly_pct <= ideal_high:
        recommendation = "increase" if weekly_pct < ideal_low else "maintain"
        calorie_change = 125 if weekly_pct < ideal_low and training_label in {"declining", "fatigue/performance stagnation"} else 100 if weekly_pct < ideal_low else 0
        reasoning.append("Recovery is poor; prioritize sleep/readiness and use a small carb-focused increase only when weight gain is slow or performance is dropping.")
        if recovery_signal.get("suggested_action"):
            reasoning.append(str(recovery_signal["suggested_action"]))
    elif ideal_low <= weekly_pct <= ideal_high:
        reasoning.append("Weight gain is inside the lean-bulk target range, so calories should stay steady.")
    elif weekly_pct > ideal_high:
        if training_label == "improving" and risk < 55:
            calorie_change = 0
            reasoning.append("Weight is rising quickly, but strength is improving and fat-gain risk is not high; maintain for now.")
        elif training_label in {"declining", "fatigue/performance stagnation"}:
            recommendation = "decrease"
            calorie_change = -125
            reasoning.append("Performance is down even though weight gain is fast, so this looks more like fatigue, recovery, sleep, or programming than a need for more calories.")
        elif recovery_label == "poor":
            recommendation = "decrease"
            calorie_change = -100
            reasoning.append("Recovery is poor but weight gain is already fast, so do not add calories; review sleep, rest, and training load.")
        else:
            recommendation = "decrease"
            calorie_change = -150 if risk >= 60 else -125
            reasoning.append("Weight gain is above lean-bulk pace with elevated fat-gain risk, so reduce calories slightly.")
    elif training_label == "declining" and calorie_avg is not None and calorie_avg < target_calories:
        recommendation = "increase"
        calorie_change = 100
        reasoning.append("Strength is declining while intake appears below target; add calories or carbs conservatively.")

    if recovery_label == "poor" and recommendation == "decrease" and weekly_pct < 0.75 and training_label not in {"declining", "fatigue/performance stagnation"}:
        recommendation = "maintain"
        calorie_change = 0
        reasoning.append("Decrease suppressed because recovery is poor and weight gain is not clearly excessive.")

    calorie_change = max(-200, min(200, calorie_change))
    new_target = target_calories + calorie_change
    if len(body_df) >= 14 and calorie_avg is not None:
        confidence = "high" if training_label != "insufficient data" else "medium"
    if recovery_label == "insufficient data" or training_label == "insufficient data":
        confidence = "low" if len(body_df) < 14 else "medium"

    return {
        "recommendation": recommendation,
        "calorie_change": calorie_change,
        "new_target_calories": int(new_target),
        "confidence": confidence,
        "weekly_weight_change_pct": weekly_pct,
        "fat_gain_risk_score": risk,
        "reasoning": reasoning,
        "next_check_in_days": 7,
        "details": {
            "seven_day_avg_weight": seven_avg,
            "fourteen_day_avg_weight": fourteen_avg,
            "calorie_average": calorie_avg,
            "protein_average": protein_avg,
            "protein_target": protein_target,
            "calorie_target_delta_average": calorie_delta_avg,
            "protein_consistency": protein_hit_rate,
            "days_over_calorie_target": days_over_target,
            "days_under_calorie_target": days_under_target,
            "training_trend": training_label,
            "key_lift_trends": key_lift_trends,
            "performance_signal": performance_signal,
            "recovery_trend": recovery_label,
            "recovery_signal": recovery_signal,
            "recovery_average": recovery_avg,
            "target_weekly_gain_pct": target_rate,
        },
    }
