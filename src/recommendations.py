"""
Recommendations module for providing personalized optimization suggestions.

This module generates recommendations based on:
- Logged nutrition, training, and recovery data
- Fitness goals and current performance
- Recovery readiness and fatigue levels
"""

import pandas as pd
import numpy as np
from pathlib import Path

from src.body_metrics import canonical_daily_bodyweights
from src.recovery import calculate_recovery_score
from src.training import calculate_training_volume


def _today_string() -> str:
    """Return today's date in the app's CSV format."""
    return pd.Timestamp.today().date().isoformat()


def _get_today_nutrition(nutrition_df) -> dict:
    """Summarize today's calories and protein from the nutrition log."""
    totals = {"calories": 0.0, "protein": 0.0}
    if nutrition_df.empty:
        return totals

    today = _today_string()
    todays_entries = nutrition_df[nutrition_df["date"].astype(str) == today]
    if todays_entries.empty:
        return totals

    totals["calories"] = float(
        pd.to_numeric(todays_entries["calories"], errors="coerce").fillna(0).sum()
    )
    totals["protein"] = float(
        pd.to_numeric(todays_entries["protein"], errors="coerce").fillna(0).sum()
    )

    return totals


def _get_latest_recovery_score(recovery_df) -> float | None:
    """Return the latest recovery score, or None if no check-in exists."""
    if recovery_df.empty:
        return None

    latest_row = recovery_df.sort_values("date").iloc[-1]
    return calculate_recovery_score(latest_row)


def _get_bodyweight_change(body_metrics_df, days=7) -> float | None:
    """Return bodyweight change over the recent window, or None if unavailable."""
    if body_metrics_df.empty:
        return None

    trend_df = canonical_daily_bodyweights(body_metrics_df)

    if len(trend_df) < 2:
        return None

    latest_date = trend_df["date"].max()
    cutoff = latest_date - pd.Timedelta(days=days)
    recent_df = trend_df[trend_df["date"] >= cutoff]

    if len(recent_df) < 2:
        return None

    return float(recent_df.iloc[-1]["bodyweight"] - recent_df.iloc[0]["bodyweight"])


def _get_recent_training_volume(training_df, days=7) -> float:
    """Return total strength volume over the recent window."""
    if training_df.empty:
        return 0.0

    recent_df = training_df.copy()
    recent_df["date"] = pd.to_datetime(recent_df["date"], errors="coerce")
    recent_df = recent_df.dropna(subset=["date"])

    if recent_df.empty:
        return 0.0

    latest_date = recent_df["date"].max()
    cutoff = latest_date - pd.Timedelta(days=days)
    recent_df = recent_df[recent_df["date"] >= cutoff].copy()
    recent_df["date"] = recent_df["date"].dt.date.astype(str)

    volume_df = calculate_training_volume(recent_df)
    if volume_df.empty:
        return 0.0

    return float(volume_df["volume"].sum())


def generate_daily_recommendation(
    nutrition_df,
    body_metrics_df,
    recovery_df,
    training_df,
    target_calories=2850,
    target_protein=160,
    goal="lean bulk",
) -> dict:
    """Generate simple daily recommendations from local logs."""
    today_nutrition = _get_today_nutrition(nutrition_df)
    calorie_gap = today_nutrition["calories"] - float(target_calories)
    protein_gap = today_nutrition["protein"] - float(target_protein)

    if calorie_gap < -150:
        calorie_recommendation = (
            f"You are {abs(calorie_gap):.0f} calories under target today. "
            "Add a meal or snack if appetite and digestion feel good."
        )
    elif calorie_gap > 150:
        calorie_recommendation = (
            f"You are {calorie_gap:.0f} calories over target today. "
            "Keep the rest of the day lighter unless this was planned."
        )
    else:
        calorie_recommendation = "Calories are close to target today."

    if protein_gap < -20:
        protein_recommendation = (
            f"You are {abs(protein_gap):.0f}g protein under target. "
            "Prioritize a lean protein serving in the next meal."
        )
    elif protein_gap > 20:
        protein_recommendation = "Protein target is covered today."
    else:
        protein_recommendation = "Protein is close to target today."

    recovery_score = _get_latest_recovery_score(recovery_df)
    recent_volume = _get_recent_training_volume(training_df)

    if recovery_score is None:
        recovery_status = "No recovery check-in yet."
        training_recommendation = (
            "Log a recovery check-in before making a hard training decision. "
            f"Recent 7-day strength volume: {recent_volume:.0f}."
        )
    elif recovery_score >= 80:
        recovery_status = f"Green ({recovery_score:.1f}/100)"
        training_recommendation = (
            "Recovery looks strong. Push normal training if the session plan is appropriate. "
            f"Recent 7-day strength volume: {recent_volume:.0f}."
        )
    elif recovery_score >= 60:
        recovery_status = f"Moderate ({recovery_score:.1f}/100)"
        training_recommendation = (
            "Train, but avoid excessive volume or grinding sets today. "
            f"Recent 7-day strength volume: {recent_volume:.0f}."
        )
    else:
        recovery_status = f"Low ({recovery_score:.1f}/100)"
        training_recommendation = (
            "Reduce intensity or volume today and bias toward recovery work. "
            f"Recent 7-day strength volume: {recent_volume:.0f}."
        )

    bodyweight_change = _get_bodyweight_change(body_metrics_df)
    normalized_goal = str(goal).strip().lower()
    if bodyweight_change is None:
        calorie_recommendation += " Add more bodyweight entries to tune calorie adjustments."
    elif normalized_goal == "lean bulk":
        if bodyweight_change <= 0:
            calorie_recommendation += (
                " Bodyweight is not increasing over the recent trend, so consider "
                "adding 100 to 150 calories per day."
            )
        elif bodyweight_change > 1.0:
            calorie_recommendation += (
                " Bodyweight is rising quickly, so consider reducing intake by "
                "100 to 150 calories per day."
            )
        else:
            calorie_recommendation += " Bodyweight gain looks controlled for a lean bulk."

    short_summary = (
        f"{recovery_status} Calories: {today_nutrition['calories']:.0f}/"
        f"{float(target_calories):.0f}. Protein: {today_nutrition['protein']:.0f}/"
        f"{float(target_protein):.0f}g."
    )

    return {
        "recovery_status": recovery_status,
        "calorie_recommendation": calorie_recommendation,
        "protein_recommendation": protein_recommendation,
        "training_recommendation": training_recommendation,
        "short_summary": short_summary,
    }


class RecommendationEngine:
    """Generates personalized recommendations based on user data."""
    
    def __init__(self):
        """Initialize the recommendation engine."""
        self.recommendations = []
    
    def get_nutrition_recommendations(self, user_data: dict) -> list:
        """Generate nutrition recommendations.
        
        Args:
            user_data: Dictionary containing user's current nutrition and goals
            
        Returns:
            List of nutrition recommendations
        """
        recommendations = []
        # TODO: Implement nutrition recommendation logic
        return recommendations
    
    def get_training_recommendations(self, user_data: dict) -> list:
        """Generate training recommendations.
        
        Args:
            user_data: Dictionary containing user's training data and recovery status
            
        Returns:
            List of training recommendations
        """
        recommendations = []
        # TODO: Implement training recommendation logic
        return recommendations
    
    def get_recovery_recommendations(self, user_data: dict) -> list:
        """Generate recovery recommendations.
        
        Args:
            user_data: Dictionary containing user's recovery metrics and fatigue level
            
        Returns:
            List of recovery recommendations
        """
        recommendations = []
        # TODO: Implement recovery recommendation logic
        return recommendations
    
    def get_daily_summary(self, user_data: dict) -> dict:
        """Generate a daily summary with all recommendations.
        
        Args:
            user_data: Comprehensive user data dictionary
            
        Returns:
            Dictionary containing all daily recommendations and insights
        """
        summary = {
            "nutrition": self.get_nutrition_recommendations(user_data),
            "training": self.get_training_recommendations(user_data),
            "recovery": self.get_recovery_recommendations(user_data),
        }
        # TODO: Add daily insights and priority recommendations
        return summary
