"""
Deterministic performance optimization engine.

This module turns local recovery, training, nutrition, and bodyweight trends
into explainable action recommendations. It intentionally does not use LLMs.
"""

from __future__ import annotations

import pandas as pd

from src.analytics.recovery_engine import calculate_recovery_score
from src.body_metrics import canonical_daily_bodyweights
from src.nutrition import calculate_nutrition_analytics
from src.training import calculate_training_volume


def _empty_result() -> dict:
    """Return a stable empty recommendation shape."""
    return {
        "recommendation_summary": "Log more data to generate adaptive recommendations.",
        "confidence_level": "Low",
        "reasoning_explanation": "No local trend data is available yet.",
        "recommendations": [],
        "signals": {},
    }


def _bodyweight_change(body_metrics_df: pd.DataFrame, days=14) -> float | None:
    """Calculate bodyweight change over the recent trend window."""
    if body_metrics_df.empty:
        return None

    trend_df = canonical_daily_bodyweights(body_metrics_df)
    if len(trend_df) < 2:
        return None

    latest_date = trend_df["date"].max()
    recent_df = trend_df[trend_df["date"] >= latest_date - pd.Timedelta(days=days)]
    if len(recent_df) < 2:
        return None

    return float(recent_df.iloc[-1]["bodyweight"] - recent_df.iloc[0]["bodyweight"])


def _recent_training_signal(training_df: pd.DataFrame) -> dict:
    """Summarize recent strength volume and lower-body loading."""
    if training_df.empty:
        return {"volume_7d": 0.0, "volume_previous_7d": 0.0, "volume_change_pct": 0.0, "lower_body_share": 0.0}

    work_df = training_df.copy()
    work_df["date"] = pd.to_datetime(work_df["date"], errors="coerce")
    work_df = work_df.dropna(subset=["date"])
    if work_df.empty:
        return {"volume_7d": 0.0, "volume_previous_7d": 0.0, "volume_change_pct": 0.0, "lower_body_share": 0.0}

    latest_date = work_df["date"].max()
    recent = work_df[work_df["date"] >= latest_date - pd.Timedelta(days=6)].copy()
    previous = work_df[
        (work_df["date"] < latest_date - pd.Timedelta(days=6))
        & (work_df["date"] >= latest_date - pd.Timedelta(days=13))
    ].copy()

    recent_volume_df = calculate_training_volume(recent.assign(date=recent["date"].dt.date.astype(str)))
    previous_volume_df = calculate_training_volume(previous.assign(date=previous["date"].dt.date.astype(str)))
    volume_7d = float(recent_volume_df["volume"].sum()) if not recent_volume_df.empty else 0.0
    previous_volume = float(previous_volume_df["volume"].sum()) if not previous_volume_df.empty else 0.0
    volume_change_pct = ((volume_7d - previous_volume) / previous_volume * 100) if previous_volume > 0 else 0.0

    recent_strength = recent[recent["workout_type"].astype(str).str.lower() == "strength"].copy()
    for column in ["sets", "reps", "weight"]:
        recent_strength[column] = pd.to_numeric(recent_strength[column], errors="coerce").fillna(0)
    recent_strength["volume"] = recent_strength["sets"] * recent_strength["reps"] * recent_strength["weight"]
    lower_mask = recent_strength["muscle_group"].astype(str).str.lower().str.contains(
        "leg|quad|hamstring|glute|calf|lower"
    )
    lower_volume = float(recent_strength.loc[lower_mask, "volume"].sum())
    total_volume = float(recent_strength["volume"].sum())
    lower_body_share = (lower_volume / total_volume * 100) if total_volume > 0 else 0.0

    return {
        "volume_7d": volume_7d,
        "volume_previous_7d": previous_volume,
        "volume_change_pct": volume_change_pct,
        "lower_body_share": lower_body_share,
    }


def _latest_recovery_signal(recovery_df: pd.DataFrame, training_df: pd.DataFrame, nutrition_df: pd.DataFrame, target_calories: float) -> dict:
    """Calculate latest recovery analytics signals."""
    recovery_analytics = calculate_recovery_score(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        target_calories=target_calories,
    )
    if recovery_analytics.empty:
        return {
            "score": None,
            "classification": "Unknown",
            "sleep_debt": 0.0,
            "fatigue_load": 0.0,
            "training_stress": 0.0,
        }

    latest = recovery_analytics.sort_values("date").iloc[-1]
    return {
        "score": float(latest["recovery_score"]),
        "classification": latest["classification"],
        "sleep_debt": float(latest["sleep_debt"]),
        "fatigue_load": float(latest["fatigue_load"]),
        "training_stress": float(latest["training_stress"]),
    }


def _latest_nutrition_signal(nutrition_df: pd.DataFrame, target_calories: float, target_protein: float) -> dict:
    """Calculate calorie and protein adherence signals."""
    nutrition_analytics = calculate_nutrition_analytics(
        nutrition_df,
        target_calories=target_calories,
        target_protein=target_protein,
    )
    if nutrition_analytics.empty:
        return {"calorie_adherence": None, "protein_consistency": None, "rolling_calories": None}

    latest = nutrition_analytics.iloc[-1]
    return {
        "calorie_adherence": float(latest["calorie_adherence"]),
        "protein_consistency": float(latest["protein_consistency"]),
        "rolling_calories": float(latest["rolling_calories"]),
    }


def _confidence_level(signals: dict) -> str:
    """Estimate confidence from available trend coverage."""
    available = 0
    available += signals["recovery"]["score"] is not None
    available += signals["bodyweight_change"] is not None
    available += signals["nutrition"]["calorie_adherence"] is not None
    available += signals["training"]["volume_7d"] > 0

    if available >= 4:
        return "High"
    if available >= 2:
        return "Moderate"
    return "Low"


def _add_recommendation(items: list[dict], category: str, action: str, reason: str, priority: str = "Medium") -> None:
    """Append a normalized recommendation item."""
    items.append(
        {
            "category": category,
            "action": action,
            "reason": reason,
            "priority": priority,
        }
    )


def generate_performance_recommendations(
    recovery_df: pd.DataFrame,
    training_df: pd.DataFrame,
    nutrition_df: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
    target_calories=0,
    target_protein=160,
    goal="lean bulk",
) -> dict:
    """Generate adaptive deterministic performance recommendations."""
    if recovery_df.empty and training_df.empty and nutrition_df.empty and body_metrics_df.empty:
        return _empty_result()

    signals = {
        "recovery": _latest_recovery_signal(recovery_df, training_df, nutrition_df, target_calories),
        "training": _recent_training_signal(training_df),
        "nutrition": _latest_nutrition_signal(nutrition_df, target_calories, target_protein),
        "bodyweight_change": _bodyweight_change(body_metrics_df),
        "goal": str(goal).strip().lower(),
    }
    recommendations = []
    reasoning = []

    recovery = signals["recovery"]
    training = signals["training"]
    nutrition = signals["nutrition"]
    bodyweight_change = signals["bodyweight_change"]
    normalized_goal = signals["goal"]

    if normalized_goal == "lean bulk":
        if bodyweight_change is None:
            _add_recommendation(
                recommendations,
                "Calories",
                "Maintain current calories until bodyweight trend is clearer",
                "At least two recent bodyweight entries are needed for calorie adjustment confidence.",
            )
        elif bodyweight_change <= 0.1 and (nutrition["calorie_adherence"] or 0) >= 90:
            _add_recommendation(
                recommendations,
                "Calories",
                "Increase calories by 150/day",
                f"Bodyweight is flat/down over the recent trend ({bodyweight_change:+.1f}) while calorie adherence is near target.",
                "High",
            )
        elif bodyweight_change > 1.2:
            _add_recommendation(
                recommendations,
                "Calories",
                "Reduce calories by 100-150/day",
                f"Bodyweight is rising quickly ({bodyweight_change:+.1f}), which may exceed a lean bulk pace.",
                "Medium",
            )
        else:
            _add_recommendation(
                recommendations,
                "Calories",
                "Maintain current bulk pace",
                f"Recent bodyweight change ({bodyweight_change:+.1f}) looks controlled.",
                "Medium",
            )

    if nutrition["protein_consistency"] is not None and nutrition["protein_consistency"] < 70:
        _add_recommendation(
            recommendations,
            "Nutrition",
            "Prioritize protein consistency before changing calories",
            f"Protein target has been hit on only {nutrition['protein_consistency']:.0f}% of recent logged days.",
        )

    if recovery["score"] is None:
        _add_recommendation(
            recommendations,
            "Training",
            "Keep normal training but log recovery before pushing volume",
            "No recovery score is available yet.",
        )
    elif recovery["score"] < 45:
        _add_recommendation(
            recommendations,
            "Training",
            "Reduce training intensity by 30-40% today",
            f"Recovery is {recovery['classification']} at {recovery['score']:.1f}/100.",
            "High",
        )
    elif recovery["score"] < 65:
        _add_recommendation(
            recommendations,
            "Training",
            "Reduce volume by 15-25% and avoid grinding sets",
            f"Recovery is {recovery['classification']} at {recovery['score']:.1f}/100.",
            "High",
        )
    elif recovery["score"] >= 80:
        _add_recommendation(
            recommendations,
            "Training",
            "Push normal planned training",
            f"Recovery is {recovery['classification']} at {recovery['score']:.1f}/100.",
            "Medium",
        )

    if training["lower_body_share"] >= 55 and recovery["fatigue_load"] >= 6:
        _add_recommendation(
            recommendations,
            "Training",
            "Reduce lower body volume by 20%",
            f"Lower-body work is {training['lower_body_share']:.0f}% of recent volume while fatigue load is elevated.",
            "High",
        )

    if recovery["sleep_debt"] >= 8:
        _add_recommendation(
            recommendations,
            "Recovery",
            "Add a sleep-focused recovery intervention tonight",
            f"Recovery debt accumulating: rolling sleep debt is {recovery['sleep_debt']:.1f} hours.",
            "High",
        )
    elif recovery["sleep_debt"] >= 4:
        _add_recommendation(
            recommendations,
            "Recovery",
            "Move bedtime earlier and keep caffeine earlier in the day",
            f"Sleep debt is building ({recovery['sleep_debt']:.1f} hours).",
            "Medium",
        )

    if recovery["training_stress"] >= 35 or (training["volume_change_pct"] >= 35 and recovery["score"] is not None and recovery["score"] < 65):
        _add_recommendation(
            recommendations,
            "Deload",
            "Schedule a 3-5 day deload or reduce weekly volume by 25%",
            f"Training stress is high ({recovery['training_stress']:.1f}) and recovery is not keeping pace.",
            "High",
        )

    if recovery["score"] is not None and recovery["score"] >= 70 and training["volume_7d"] > 0:
        _add_recommendation(
            recommendations,
            "Cardio",
            "Keep cardio easy Zone 2 and avoid adding hard intervals this week",
            "Strength volume is present and recovery is adequate; cardio should support conditioning without stealing recovery.",
            "Low",
        )
    elif recovery["score"] is not None and recovery["score"] < 60:
        _add_recommendation(
            recommendations,
            "Cardio",
            "Use walking or very easy cardio only",
            "Recovery is suppressed, so cardio should help circulation without adding meaningful fatigue.",
            "Medium",
        )

    if not recommendations:
        _add_recommendation(
            recommendations,
            "Plan",
            "Maintain current plan",
            "No major negative trend is present in the available local data.",
        )

    if recovery["score"] is not None:
        reasoning.append(f"Latest recovery score is {recovery['score']:.1f}/100 ({recovery['classification']}).")
    if bodyweight_change is not None:
        reasoning.append(f"Recent bodyweight change is {bodyweight_change:+.1f}.")
    if nutrition["calorie_adherence"] is not None:
        reasoning.append(f"Calorie adherence is {nutrition['calorie_adherence']:.0f}% of target.")
    if training["volume_7d"] > 0:
        reasoning.append(f"Recent 7-day strength volume is {training['volume_7d']:.0f}.")
    if recovery["sleep_debt"] > 0:
        reasoning.append(f"Rolling sleep debt is {recovery['sleep_debt']:.1f} hours.")

    confidence = _confidence_level(signals)
    top_action = recommendations[0]["action"]
    summary = f"{top_action}. Confidence: {confidence}."

    return {
        "recommendation_summary": summary,
        "confidence_level": confidence,
        "reasoning_explanation": " ".join(reasoning) if reasoning else "Limited data available; recommendations are conservative.",
        "recommendations": recommendations,
        "signals": signals,
    }
