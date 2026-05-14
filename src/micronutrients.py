"""Food-first micronutrient suggestion engine for performance support."""

from __future__ import annotations

import pandas as pd


FRUIT_VEG_KEYWORDS = [
    "apple",
    "banana",
    "berries",
    "berry",
    "broccoli",
    "carrot",
    "greens",
    "kale",
    "orange",
    "potato",
    "salad",
    "spinach",
    "vegetable",
    "veggie",
]

FOOD_VARIETY_MINIMUM = 8


def _recent_rows(df: pd.DataFrame, date_column: str = "date", days: int = 7) -> pd.DataFrame:
    """Return rows from the most recent local data window."""
    if df.empty or date_column not in df.columns:
        return pd.DataFrame()

    recent_df = df.copy()
    recent_df[date_column] = pd.to_datetime(recent_df[date_column], errors="coerce")
    recent_df = recent_df.dropna(subset=[date_column]).sort_values(date_column)
    if recent_df.empty:
        return recent_df

    latest_date = recent_df[date_column].max()
    return recent_df[recent_df[date_column] >= latest_date - pd.Timedelta(days=days - 1)].copy()


def _food_variety_signal(nutrition_log_df: pd.DataFrame) -> dict:
    """Estimate food variety from recent food names."""
    recent = _recent_rows(nutrition_log_df)
    if recent.empty or "food_name" not in recent.columns:
        return {"unique_foods": 0, "fruit_veg_entries": 0, "low_variety": True, "low_fruit_veg": True}

    food_names = recent["food_name"].fillna("").astype(str).str.lower()
    unique_foods = int(food_names[food_names != ""].nunique())
    fruit_veg_entries = int(food_names.str.contains("|".join(FRUIT_VEG_KEYWORDS), regex=True).sum())

    return {
        "unique_foods": unique_foods,
        "fruit_veg_entries": fruit_veg_entries,
        "low_variety": unique_foods < FOOD_VARIETY_MINIMUM,
        "low_fruit_veg": fruit_veg_entries < 4,
    }


def _training_signal(training_df: pd.DataFrame) -> dict:
    """Estimate whether recent training suggests sweat or electrolyte focus."""
    recent = _recent_rows(training_df)
    if recent.empty:
        return {"heavy_training": False, "cardio_days": 0, "long_sessions": 0}

    workout_type = recent.get("workout_type", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
    duration = pd.to_numeric(recent.get("duration_minutes", pd.Series(dtype=float)), errors="coerce").fillna(0)
    cardio_days = int(workout_type.str.contains("run|cardio").sum())
    long_sessions = int((duration >= 60).sum())

    return {
        "heavy_training": len(recent) >= 4 or long_sessions >= 2,
        "cardio_days": cardio_days,
        "long_sessions": long_sessions,
    }


def _recovery_signal(recovery_df: pd.DataFrame) -> dict:
    """Estimate if recent recovery is poor enough to emphasize food quality."""
    recent = _recent_rows(recovery_df)
    if recent.empty:
        return {"poor_recovery": False, "high_stress": False}

    fatigue = pd.to_numeric(recent.get("fatigue", pd.Series(dtype=float)), errors="coerce").dropna()
    stress = pd.to_numeric(recent.get("stress", pd.Series(dtype=float)), errors="coerce").dropna()
    sleep_quality = pd.to_numeric(recent.get("sleep_quality", pd.Series(dtype=float)), errors="coerce").dropna()

    poor_recovery = False
    if not fatigue.empty and fatigue.tail(3).mean() >= 7:
        poor_recovery = True
    if not sleep_quality.empty and sleep_quality.tail(3).mean() <= 5:
        poor_recovery = True

    return {
        "poor_recovery": poor_recovery,
        "high_stress": bool(not stress.empty and stress.tail(3).mean() >= 7),
    }


def _add_suggestion(items: list[dict], nutrient: str, focus: str, foods: str, why: str, note: str = "") -> None:
    """Append a stable food-first micronutrient suggestion."""
    items.append(
        {
            "nutrient": nutrient,
            "focus": focus,
            "food_first_options": foods,
            "why_it_matters": why,
            "note": note,
        }
    )


def generate_micronutrient_suggestions(
    nutrition_log_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    training_df: pd.DataFrame,
    user_goals: dict,
) -> list[dict]:
    """Generate conservative food-first micronutrient suggestions.

    This does not diagnose deficiencies, prescribe supplements, or replace
    medical guidance. Reference assumptions are aligned with NIH Office of
    Dietary Supplements fact sheets, Academy of Nutrition and Dietetics / ACSM
    sports nutrition guidance, and ISSN protein/body composition guidance.
    """
    variety = _food_variety_signal(nutrition_log_df)
    training = _training_signal(training_df)
    recovery = _recovery_signal(recovery_df)
    goal_type = str(user_goals.get("goal_type", "")).lower()

    suggestions: list[dict] = []

    if variety["low_variety"]:
        _add_suggestion(
            suggestions,
            "Fiber",
            "Increase food variety",
            "Fruits, vegetables, oats, beans, and whole grains",
            "Recent logs show limited food variety, so fiber-rich whole foods are a useful baseline.",
        )

    if variety["low_fruit_veg"]:
        _add_suggestion(
            suggestions,
            "Potassium",
            "Add fruit, potatoes, beans, or yogurt",
            "Potatoes, bananas, beans, yogurt, and fruit",
            "Low fruit/vegetable presence can make potassium-rich foods easy to miss.",
        )
        _add_suggestion(
            suggestions,
            "Magnesium",
            "Add mineral-dense plant foods",
            "Nuts, seeds, dark chocolate, and leafy greens",
            "Magnesium supports normal muscle and nerve function and is best approached food-first.",
        )

    if training["heavy_training"] or training["cardio_days"] >= 2 or training["long_sessions"] >= 2:
        _add_suggestion(
            suggestions,
            "Sodium / Electrolytes",
            "Match fluids and sodium to sweat losses",
            "Salted meals, electrolyte drinks when already useful, soups, and salty carb sources",
            "Hard training, running, and long sessions can increase sweat and sodium needs.",
            "Avoid extreme sodium changes if you have blood pressure or kidney concerns; use clinician guidance when relevant.",
        )
        _add_suggestion(
            suggestions,
            "Calcium",
            "Keep bone-supportive foods consistent",
            "Dairy, fortified alternatives, and leafy greens",
            "Frequent training raises the value of consistent calcium-rich foods.",
        )

    if recovery["poor_recovery"] or recovery["high_stress"]:
        _add_suggestion(
            suggestions,
            "Omega-3",
            "Include fatty fish if it fits your diet",
            "Salmon, sardines, tuna, or fish oil if already used",
            "Omega-3-rich foods can support a generally performance-focused eating pattern.",
            "Supplements are optional, not required.",
        )
        _add_suggestion(
            suggestions,
            "Vitamin D",
            "Prioritize routine food and sunlight sources",
            "Sunlight, fatty fish, fortified dairy, and eggs",
            "Poor recovery can be a reminder to cover basic health-supportive nutrition habits.",
            "Blood testing and clinician guidance are the right path for deficiency concerns.",
        )

    if "cut" in goal_type:
        _add_suggestion(
            suggestions,
            "Zinc",
            "Keep micronutrient-dense protein foods in the cut",
            "Meat, shellfish, dairy, and pumpkin seeds",
            "Lower calories can reduce room for nutrient-dense foods if planning is loose.",
        )
        _add_suggestion(
            suggestions,
            "Iron",
            "Include iron-rich foods, especially during lower-calorie phases",
            "Red meat, poultry, beans, and spinach",
            "Iron supports oxygen transport, but supplementation deserves extra caution.",
            "Do not supplement iron unless a clinician recommends it based on labs.",
        )

    if not suggestions:
        _add_suggestion(
            suggestions,
            "Micronutrient Baseline",
            "Maintain varied, food-first coverage",
            "Fruits, vegetables, lean proteins, dairy or fortified alternatives, beans, oats, potatoes, nuts, and seeds",
            "Current logs do not show an obvious food-variety or training-stress flag.",
        )

    return suggestions
