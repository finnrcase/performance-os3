"""
Nutrition module for tracking dietary intake and macronutrient analysis.

This module handles:
- Logging food and meal data
- Calculating macronutrient totals
- Storing nutrition history
"""

import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from src.paths import processed_data_path
from src.storage import load_dataframe, save_dataframe

NUTRITION_COLUMNS = [
    "food_log_id",
    "date",
    "meal_type",
    "food_name",
    "iconType",
    "calories",
    "protein",
    "carbs",
    "fat",
    "serving_size_grams",
    "grams_consumed",
    "serving_multiplier",
    "calories_per_serving",
    "protein_per_serving",
    "carbs_per_serving",
    "fat_per_serving",
    "fiber",
    "sodium",
    "potassium",
    "source_label_file",
    "quantity",
    "unit",
    "serving_description",
    "sugar",
    "source",
    "source_id",
    "source_url",
    "confidence",
    "assumptions",
    "original_text",
    "needs_review",
    "reviewed_at",
    "created_via",
    "created_at",
    "updated_at",
]

FREQUENT_FOOD_COLUMNS = [
    "food_name",
    "calories",
    "protein",
    "carbs",
    "fat",
    "default_meal_type",
    "is_favorite",
]

MEAL_TEMPLATE_COLUMNS = [
    "template_name",
    "default_meal_type",
    "food_name",
    "calories",
    "protein",
    "carbs",
    "fat",
]

FOOD_SHORTCUT_COLUMNS = [
    "shortcut_id",
    "shortcut_name",
    "calories",
    "protein",
    "carbs",
    "fat",
    "fiber",
    "sodium",
    "potassium",
    "serving_size_grams",
    "default_grams_consumed",
    "calories_per_serving",
    "protein_per_serving",
    "carbs_per_serving",
    "fat_per_serving",
    "notes",
    "created_at",
    "source",
]

NUTRITION_LOG_PATH = processed_data_path("nutrition_log.csv")
FREQUENT_FOODS_PATH = processed_data_path("frequent_foods.csv")
MEAL_TEMPLATES_PATH = processed_data_path("meal_templates.csv")
FOOD_SHORTCUTS_PATH = processed_data_path("food_shortcuts.csv")

FOOD_ICON_TYPES = {"bagel", "protein_bar", "oats", "protein_shake", "chicken"}


def normalize_food_icon(icon_type) -> str:
    """Return a persisted food icon key or an empty string."""
    selected_icon = str(icon_type or "").strip()
    return selected_icon if selected_icon in FOOD_ICON_TYPES else ""


def suggest_food_icon(food_name) -> str:
    """Pick a lightweight default icon from the food name when possible."""
    normalized_name = str(food_name or "").lower()
    if "bagel" in normalized_name:
        return "bagel"
    if "built bar" in normalized_name or "protein bar" in normalized_name or ("protein" in normalized_name and "bar" in normalized_name):
        return "protein_bar"
    if "oat" in normalized_name or "oatmeal" in normalized_name:
        return "oats"
    if "protein shake" in normalized_name or "shake" in normalized_name:
        return "protein_shake"
    if "chicken" in normalized_name:
        return "chicken"
    return ""


def create_food_entry(
    food_name,
    calories,
    protein,
    carbs,
    fat,
    meal_type,
    date,
    iconType=None,
    serving_size_grams=None,
    grams_consumed=None,
    serving_multiplier=None,
    calories_per_serving=None,
    protein_per_serving=None,
    carbs_per_serving=None,
    fat_per_serving=None,
    fiber=None,
    sodium=None,
    potassium=None,
    source_label_file="",
    quantity=None,
    unit="",
    serving_description="",
    sugar=None,
    source="manual",
    source_id=None,
    source_url=None,
    confidence="high",
    assumptions=None,
    original_text="",
    needs_review=False,
    reviewed_at=None,
    created_via="manual",
) -> dict:
    """Create a normalized food log entry."""
    now = datetime.now(timezone.utc).isoformat()
    assumptions_json = assumptions if isinstance(assumptions, str) else json.dumps(assumptions or [])
    return {
        "food_log_id": str(uuid4()),
        "date": str(date),
        "meal_type": str(meal_type),
        "food_name": str(food_name).strip(),
        "iconType": normalize_food_icon(iconType) or suggest_food_icon(food_name),
        "calories": float(calories),
        "protein": float(protein),
        "carbs": float(carbs),
        "fat": float(fat),
        "serving_size_grams": np.nan if serving_size_grams in [None, ""] else float(serving_size_grams),
        "grams_consumed": np.nan if grams_consumed in [None, ""] else float(grams_consumed),
        "serving_multiplier": np.nan if serving_multiplier in [None, ""] else float(serving_multiplier),
        "calories_per_serving": np.nan if calories_per_serving in [None, ""] else float(calories_per_serving),
        "protein_per_serving": np.nan if protein_per_serving in [None, ""] else float(protein_per_serving),
        "carbs_per_serving": np.nan if carbs_per_serving in [None, ""] else float(carbs_per_serving),
        "fat_per_serving": np.nan if fat_per_serving in [None, ""] else float(fat_per_serving),
        "fiber": np.nan if fiber in [None, ""] else float(fiber),
        "sodium": np.nan if sodium in [None, ""] else float(sodium),
        "potassium": np.nan if potassium in [None, ""] else float(potassium),
        "source_label_file": str(source_label_file or ""),
        "quantity": np.nan if quantity in [None, ""] else float(quantity),
        "unit": str(unit or ""),
        "serving_description": str(serving_description or ""),
        "sugar": np.nan if sugar in [None, ""] else float(sugar),
        "source": str(source or "manual"),
        "source_id": str(source_id or ""),
        "source_url": str(source_url or ""),
        "confidence": str(confidence or "medium"),
        "assumptions": assumptions_json,
        "original_text": str(original_text or ""),
        "needs_review": bool(needs_review),
        "reviewed_at": str(reviewed_at or (now if not needs_review else "")),
        "created_via": str(created_via or "manual"),
        "created_at": now,
        "updated_at": now,
    }


def _empty_nutrition_log() -> pd.DataFrame:
    """Return an empty nutrition log with the expected columns."""
    return pd.DataFrame(columns=NUTRITION_COLUMNS)


def calculate_daily_totals(entries_df, date) -> dict:
    """Calculate daily calories and macro totals for a given date."""
    totals = {
        "calories": 0.0,
        "protein": 0.0,
        "carbs": 0.0,
        "fat": 0.0,
    }

    if entries_df.empty:
        return totals

    selected_date = str(date)
    daily_entries = entries_df[entries_df["date"].astype(str) == selected_date]

    if daily_entries.empty:
        return totals

    for column in totals:
        totals[column] = float(pd.to_numeric(daily_entries[column], errors="coerce").fillna(0).sum())

    return totals


def load_nutrition_log() -> pd.DataFrame:
    """Load the local nutrition log, creating an empty frame if needed."""
    entries_df = load_dataframe("nutrition_log", NUTRITION_LOG_PATH, NUTRITION_COLUMNS)

    needs_id_backfill = False
    for column in NUTRITION_COLUMNS:
        if column not in entries_df.columns:
            entries_df[column] = np.nan
            needs_id_backfill = needs_id_backfill or column == "food_log_id"

    entries_df = entries_df[NUTRITION_COLUMNS]

    numeric_columns = [
        "calories",
        "protein",
        "carbs",
        "fat",
        "serving_size_grams",
        "grams_consumed",
        "serving_multiplier",
        "calories_per_serving",
        "protein_per_serving",
        "carbs_per_serving",
        "fat_per_serving",
        "fiber",
        "sodium",
        "potassium",
        "quantity",
        "sugar",
    ]
    for column in numeric_columns:
        entries_df[column] = pd.to_numeric(entries_df[column], errors="coerce")
    for column in ["calories", "protein", "carbs", "fat"]:
        entries_df[column] = entries_df[column].fillna(0)

    entries_df["food_log_id"] = entries_df["food_log_id"].fillna("").astype(str)
    missing_id_mask = entries_df["food_log_id"].str.strip().isin(["", "nan", "None", "<NA>"])
    if missing_id_mask.any():
        entries_df.loc[missing_id_mask, "food_log_id"] = [str(uuid4()) for _ in range(int(missing_id_mask.sum()))]
        needs_id_backfill = True

    entries_df["date"] = entries_df["date"].astype(str)
    entries_df["meal_type"] = entries_df["meal_type"].astype(str)
    entries_df["food_name"] = entries_df["food_name"].astype(str)
    for column in [
        "iconType",
        "source_label_file",
        "unit",
        "serving_description",
        "source",
        "source_id",
        "source_url",
        "confidence",
        "assumptions",
        "original_text",
        "reviewed_at",
        "created_via",
        "created_at",
        "updated_at",
    ]:
        entries_df[column] = entries_df[column].fillna("").astype(str)
    entries_df["iconType"] = entries_df["iconType"].apply(normalize_food_icon)
    entries_df["needs_review"] = (
        entries_df["needs_review"]
        .fillna(False)
        .astype(str)
        .str.lower()
        .isin(["true", "1", "yes"])
    )

    if needs_id_backfill:
        save_nutrition_log(entries_df)

    return entries_df


def save_nutrition_log(entries_df) -> None:
    """Save the nutrition log locally."""
    save_dataframe("nutrition_log", NUTRITION_LOG_PATH, entries_df, NUTRITION_COLUMNS)


def delete_food_log_entry(food_log_id: str) -> dict:
    """Delete a single detailed food log entry by stable ID."""
    entries_df = load_nutrition_log()
    selected_id = str(food_log_id or "").strip()
    if not selected_id:
        raise ValueError("Food log ID is required.")
    match = entries_df["food_log_id"].astype(str) == selected_id
    if entries_df.empty or not match.any():
        raise ValueError(f"Food log entry not found: {food_log_id}")
    deleted_entry = entries_df.loc[match].iloc[0].to_dict()
    entries_df = entries_df.loc[~match].reset_index(drop=True)
    save_nutrition_log(entries_df)
    return deleted_entry


def update_food_log_entry(food_log_id: str, updates: dict) -> dict:
    """Update editable fields on a detailed food log entry by stable ID."""
    entries_df = load_nutrition_log()
    selected_id = str(food_log_id or "").strip()
    if not selected_id:
        raise ValueError("Food log ID is required.")
    match = entries_df["food_log_id"].astype(str) == selected_id
    if entries_df.empty or not match.any():
        raise ValueError(f"Food log entry not found: {food_log_id}")

    row_index = entries_df.index[match][0]
    if "iconType" in updates:
        entries_df.at[row_index, "iconType"] = normalize_food_icon(updates.get("iconType"))
    entries_df.at[row_index, "updated_at"] = datetime.now(timezone.utc).isoformat()
    save_nutrition_log(entries_df)
    return load_nutrition_log().loc[lambda df: df["food_log_id"].astype(str) == selected_id].iloc[0].to_dict()


def clear_food_logs_for_date(date: str) -> dict:
    """Remove detailed food intake rows for one date without touching other logs."""
    entries_df = load_nutrition_log()
    selected_date = str(date)
    if entries_df.empty:
        return {"date": selected_date, "removed": 0, "items": []}
    match = entries_df["date"].astype(str) == selected_date
    removed_items = entries_df.loc[match].to_dict(orient="records")
    entries_df = entries_df.loc[~match].reset_index(drop=True)
    save_nutrition_log(entries_df)
    return {"date": selected_date, "removed": len(removed_items), "items": removed_items}


def _empty_frequent_foods() -> pd.DataFrame:
    """Return an empty frequent foods table with the expected columns."""
    return pd.DataFrame(columns=FREQUENT_FOOD_COLUMNS)


def load_frequent_foods() -> pd.DataFrame:
    """Load saved frequent foods, creating an empty frame if needed."""
    foods_df = load_dataframe("frequent_foods", FREQUENT_FOODS_PATH, FREQUENT_FOOD_COLUMNS)

    for column in FREQUENT_FOOD_COLUMNS:
        if column not in foods_df.columns:
            foods_df[column] = np.nan

    foods_df = foods_df[FREQUENT_FOOD_COLUMNS]

    for column in ["calories", "protein", "carbs", "fat"]:
        foods_df[column] = pd.to_numeric(foods_df[column], errors="coerce").fillna(0)

    foods_df["food_name"] = foods_df["food_name"].astype(str)
    foods_df["default_meal_type"] = foods_df["default_meal_type"].astype(str)
    foods_df["is_favorite"] = (
        foods_df["is_favorite"]
        .fillna(False)
        .astype(str)
        .str.lower()
        .isin(["true", "1", "yes"])
    )

    return foods_df


def save_frequent_foods(df) -> None:
    """Save frequent foods locally."""
    save_dataframe("frequent_foods", FREQUENT_FOODS_PATH, df, FREQUENT_FOOD_COLUMNS)


def add_frequent_food(
    food_name,
    calories,
    protein,
    carbs,
    fat,
    default_meal_type,
    is_favorite=False,
) -> pd.DataFrame:
    """Add or update a saved frequent food and return the updated table."""
    foods_df = load_frequent_foods()
    normalized_name = str(food_name).strip()

    food_entry = {
        "food_name": normalized_name,
        "calories": float(calories),
        "protein": float(protein),
        "carbs": float(carbs),
        "fat": float(fat),
        "default_meal_type": str(default_meal_type),
        "is_favorite": bool(is_favorite),
    }

    if not foods_df.empty:
        foods_df = foods_df[
            foods_df["food_name"].str.lower() != normalized_name.lower()
        ]

    foods_df = pd.concat([foods_df, pd.DataFrame([food_entry])], ignore_index=True)
    foods_df = foods_df.sort_values("food_name", kind="stable").reset_index(drop=True)
    save_frequent_foods(foods_df)

    return foods_df


def log_frequent_food(food_name, date, meal_type=None) -> dict:
    """Log a saved frequent food to the nutrition log."""
    foods_df = load_frequent_foods()
    normalized_name = str(food_name).strip()
    matching_foods = foods_df[
        foods_df["food_name"].str.lower() == normalized_name.lower()
    ]

    if matching_foods.empty:
        raise ValueError(f"Frequent food not found: {food_name}")

    food = matching_foods.iloc[0]
    selected_meal_type = meal_type or food["default_meal_type"]
    entry = create_food_entry(
        food_name=food["food_name"],
        calories=food["calories"],
        protein=food["protein"],
        carbs=food["carbs"],
        fat=food["fat"],
        meal_type=selected_meal_type,
        date=date,
    )

    entries_df = load_nutrition_log()
    entries_df = pd.concat([entries_df, pd.DataFrame([entry])], ignore_index=True)
    save_nutrition_log(entries_df)

    return entry


def _empty_food_shortcuts() -> pd.DataFrame:
    """Return an empty AI/manual food shortcut table."""
    return pd.DataFrame(columns=FOOD_SHORTCUT_COLUMNS)


def load_food_shortcuts() -> pd.DataFrame:
    """Load reusable food shortcuts, creating an empty frame if needed."""
    shortcuts_df = load_dataframe("food_shortcuts", FOOD_SHORTCUTS_PATH, FOOD_SHORTCUT_COLUMNS)
    for column in FOOD_SHORTCUT_COLUMNS:
        if column not in shortcuts_df.columns:
            shortcuts_df[column] = np.nan
    shortcuts_df = shortcuts_df[FOOD_SHORTCUT_COLUMNS]

    for column in [
        "calories",
        "protein",
        "carbs",
        "fat",
        "fiber",
        "sodium",
        "potassium",
        "serving_size_grams",
        "default_grams_consumed",
        "calories_per_serving",
        "protein_per_serving",
        "carbs_per_serving",
        "fat_per_serving",
    ]:
        shortcuts_df[column] = pd.to_numeric(shortcuts_df[column], errors="coerce")
    for column in ["shortcut_id", "shortcut_name", "notes", "created_at", "source"]:
        shortcuts_df[column] = shortcuts_df[column].fillna("").astype(str)

    return shortcuts_df


def save_food_shortcuts(df) -> None:
    """Persist food shortcuts locally."""
    save_dataframe("food_shortcuts", FOOD_SHORTCUTS_PATH, df, FOOD_SHORTCUT_COLUMNS)


def add_food_shortcut(
    shortcut_name,
    calories,
    protein,
    carbs,
    fat,
    fiber=None,
    sodium=None,
    potassium=None,
    serving_size_grams=None,
    default_grams_consumed=None,
    calories_per_serving=None,
    protein_per_serving=None,
    carbs_per_serving=None,
    fat_per_serving=None,
    notes="",
    source="ai_parse",
    shortcut_id=None,
) -> dict:
    """Create or update a reusable one-click food shortcut."""
    shortcuts_df = load_food_shortcuts()
    normalized_name = str(shortcut_name).strip()
    selected_id = str(shortcut_id or uuid4())
    shortcut = {
        "shortcut_id": selected_id,
        "shortcut_name": normalized_name,
        "calories": float(calories or 0),
        "protein": float(protein or 0),
        "carbs": float(carbs or 0),
        "fat": float(fat or 0),
        "fiber": np.nan if fiber in [None, ""] else float(fiber),
        "sodium": np.nan if sodium in [None, ""] else float(sodium),
        "potassium": np.nan if potassium in [None, ""] else float(potassium),
        "serving_size_grams": np.nan if serving_size_grams in [None, ""] else float(serving_size_grams),
        "default_grams_consumed": np.nan if default_grams_consumed in [None, ""] else float(default_grams_consumed),
        "calories_per_serving": np.nan if calories_per_serving in [None, ""] else float(calories_per_serving),
        "protein_per_serving": np.nan if protein_per_serving in [None, ""] else float(protein_per_serving),
        "carbs_per_serving": np.nan if carbs_per_serving in [None, ""] else float(carbs_per_serving),
        "fat_per_serving": np.nan if fat_per_serving in [None, ""] else float(fat_per_serving),
        "notes": str(notes or ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source or "manual"),
    }

    if not shortcuts_df.empty:
        shortcuts_df = shortcuts_df[
            (shortcuts_df["shortcut_id"].astype(str) != selected_id)
            & (shortcuts_df["shortcut_name"].str.lower() != normalized_name.lower())
        ]
    shortcuts_df = pd.concat([shortcuts_df, pd.DataFrame([shortcut])], ignore_index=True)
    shortcuts_df = shortcuts_df.sort_values("shortcut_name", kind="stable").reset_index(drop=True)
    save_food_shortcuts(shortcuts_df)
    return shortcut


def update_food_shortcut(shortcut_id, updates: dict) -> dict:
    """Update an existing shortcut by ID."""
    shortcuts_df = load_food_shortcuts()
    selected_id = str(shortcut_id)
    match = shortcuts_df["shortcut_id"].astype(str) == selected_id
    if shortcuts_df.empty or not match.any():
        raise ValueError(f"Food shortcut not found: {shortcut_id}")

    row_index = shortcuts_df.index[match][0]
    for column in FOOD_SHORTCUT_COLUMNS:
        if column in updates and column not in ["shortcut_id", "created_at"]:
            shortcuts_df.at[row_index, column] = updates[column]
    for column in [
        "calories",
        "protein",
        "carbs",
        "fat",
        "fiber",
        "sodium",
        "potassium",
        "serving_size_grams",
        "default_grams_consumed",
        "calories_per_serving",
        "protein_per_serving",
        "carbs_per_serving",
        "fat_per_serving",
    ]:
        shortcuts_df[column] = pd.to_numeric(shortcuts_df[column], errors="coerce")
    save_food_shortcuts(shortcuts_df)
    return shortcuts_df.loc[row_index, FOOD_SHORTCUT_COLUMNS].to_dict()


def delete_food_shortcut(shortcut_id) -> None:
    """Delete a shortcut by ID."""
    shortcuts_df = load_food_shortcuts()
    selected_id = str(shortcut_id)
    shortcuts_df = shortcuts_df[shortcuts_df["shortcut_id"].astype(str) != selected_id]
    save_food_shortcuts(shortcuts_df)


def log_food_shortcut(shortcut_id, date, meal_type="Snack") -> dict:
    """Log a saved shortcut to the detailed nutrition log."""
    shortcuts_df = load_food_shortcuts()
    selected_id = str(shortcut_id)
    match = shortcuts_df[shortcuts_df["shortcut_id"].astype(str) == selected_id]
    if match.empty:
        raise ValueError(f"Food shortcut not found: {shortcut_id}")

    shortcut = match.iloc[0]
    entry = create_food_entry(
        food_name=shortcut["shortcut_name"],
        calories=shortcut["calories"],
        protein=shortcut["protein"],
        carbs=shortcut["carbs"],
        fat=shortcut["fat"],
        meal_type=meal_type,
        date=date,
    )
    entries_df = load_nutrition_log()
    entries_df = pd.concat([entries_df, pd.DataFrame([entry])], ignore_index=True)
    save_nutrition_log(entries_df)
    return entry


def load_meal_templates() -> pd.DataFrame:
    """Load saved meal templates from local CSV."""
    templates_df = load_dataframe("meal_templates", MEAL_TEMPLATES_PATH, MEAL_TEMPLATE_COLUMNS)

    for column in MEAL_TEMPLATE_COLUMNS:
        if column not in templates_df.columns:
            templates_df[column] = np.nan

    templates_df = templates_df[MEAL_TEMPLATE_COLUMNS]

    for column in ["calories", "protein", "carbs", "fat"]:
        templates_df[column] = pd.to_numeric(templates_df[column], errors="coerce").fillna(0)

    for column in ["template_name", "default_meal_type", "food_name"]:
        templates_df[column] = templates_df[column].fillna("").astype(str)

    return templates_df


def save_meal_templates(df) -> None:
    """Save meal templates locally."""
    save_dataframe("meal_templates", MEAL_TEMPLATES_PATH, df, MEAL_TEMPLATE_COLUMNS)


def add_meal_template(
    template_name,
    food_name,
    calories,
    protein,
    carbs,
    fat,
    default_meal_type,
) -> pd.DataFrame:
    """Add or update a one-click meal template."""
    templates_df = load_meal_templates()
    normalized_name = str(template_name).strip()
    template_entry = {
        "template_name": normalized_name,
        "default_meal_type": str(default_meal_type),
        "food_name": str(food_name).strip(),
        "calories": float(calories),
        "protein": float(protein),
        "carbs": float(carbs),
        "fat": float(fat),
    }

    if not templates_df.empty:
        templates_df = templates_df[
            templates_df["template_name"].str.lower() != normalized_name.lower()
        ]

    templates_df = pd.concat([templates_df, pd.DataFrame([template_entry])], ignore_index=True)
    templates_df = templates_df.sort_values("template_name", kind="stable").reset_index(drop=True)
    save_meal_templates(templates_df)

    return templates_df


def add_meal_template_items(template_name, foods, default_meal_type="Breakfast") -> pd.DataFrame:
    """Save multiple parsed foods under one reusable meal template name."""
    templates_df = load_meal_templates()
    normalized_name = str(template_name).strip()
    if not templates_df.empty:
        templates_df = templates_df[
            templates_df["template_name"].str.lower() != normalized_name.lower()
        ]

    rows = []
    for food in foods:
        rows.append(
            {
                "template_name": normalized_name,
                "default_meal_type": str(default_meal_type),
                "food_name": str(food.get("food_name", "")).strip(),
                "calories": float(food.get("calories") or 0),
                "protein": float(food.get("protein") or 0),
                "carbs": float(food.get("carbs") or 0),
                "fat": float(food.get("fat") or 0),
            }
        )

    if rows:
        templates_df = pd.concat([templates_df, pd.DataFrame(rows)], ignore_index=True)
    templates_df = templates_df.sort_values(["template_name", "food_name"], kind="stable").reset_index(drop=True)
    save_meal_templates(templates_df)
    return templates_df


def update_meal_template_name(template_name, new_template_name) -> pd.DataFrame:
    """Rename a saved meal template while preserving its foods."""
    templates_df = load_meal_templates()
    current_name = str(template_name).strip()
    normalized_name = str(new_template_name).strip()

    if not normalized_name:
        raise ValueError("Meal template name cannot be empty.")

    if templates_df.empty:
        raise ValueError(f"Meal template not found: {template_name}")

    current_match = templates_df["template_name"].str.lower() == current_name.lower()
    if not current_match.any():
        raise ValueError(f"Meal template not found: {template_name}")

    existing_match = templates_df["template_name"].str.lower() == normalized_name.lower()
    if existing_match.any() and current_name.lower() != normalized_name.lower():
        raise ValueError(f"Meal template already exists: {new_template_name}")

    templates_df.loc[current_match, "template_name"] = normalized_name
    templates_df = templates_df.sort_values(["template_name", "food_name"], kind="stable").reset_index(drop=True)
    save_meal_templates(templates_df)
    return templates_df


def log_meal_template(template_name, date, meal_type=None) -> dict:
    """Log a saved meal template to the nutrition log."""
    templates_df = load_meal_templates()
    normalized_name = str(template_name).strip()
    matching_templates = templates_df[
        templates_df["template_name"].str.lower() == normalized_name.lower()
    ]

    if matching_templates.empty:
        raise ValueError(f"Meal template not found: {template_name}")

    selected_meal_type = meal_type or matching_templates.iloc[0]["default_meal_type"]
    entries_df = load_nutrition_log()
    entries = [
        create_food_entry(
            food_name=row["food_name"],
            calories=row["calories"],
            protein=row["protein"],
            carbs=row["carbs"],
            fat=row["fat"],
            meal_type=selected_meal_type,
            date=date,
        )
        for _, row in matching_templates.iterrows()
    ]
    entries_df = pd.concat([entries_df, pd.DataFrame(entries)], ignore_index=True)
    save_nutrition_log(entries_df)

    return {"template_name": normalized_name, "entries": entries}


def get_recent_foods(entries_df, limit=8) -> pd.DataFrame:
    """Return recently logged unique foods with their latest macros."""
    if entries_df.empty:
        return pd.DataFrame(columns=NUTRITION_COLUMNS)

    recent_df = entries_df.copy()
    recent_df["date_sort"] = pd.to_datetime(recent_df["date"], errors="coerce")
    recent_df = recent_df.sort_values("date_sort", ascending=False)
    recent_df = recent_df.drop_duplicates(subset=["food_name"], keep="first")

    return recent_df[NUTRITION_COLUMNS].head(limit).reset_index(drop=True)


def get_most_common_foods(entries_df, limit=10) -> pd.DataFrame:
    """Return most commonly logged foods."""
    if entries_df.empty:
        return pd.DataFrame(columns=["food_name", "log_count"])

    return (
        entries_df["food_name"]
        .fillna("")
        .astype(str)
        .loc[lambda foods: foods.str.len() > 0]
        .value_counts()
        .head(limit)
        .rename_axis("food_name")
        .reset_index(name="log_count")
    )


def calculate_nutrition_analytics(
    entries_df,
    target_calories=2850,
    target_protein=160,
    rolling_window=7,
) -> pd.DataFrame:
    """Build daily nutrition analytics for charts and consistency metrics."""
    columns = [
        "date",
        "calories",
        "protein",
        "carbs",
        "fat",
        "rolling_calories",
        "rolling_protein",
        "protein_hit",
        "protein_consistency",
        "calorie_adherence",
        "protein_adherence",
        "carbs_pct",
        "protein_pct",
        "fat_pct",
    ]
    if entries_df.empty:
        return pd.DataFrame(columns=columns)

    daily_df = entries_df.copy()
    daily_df["date"] = pd.to_datetime(daily_df["date"], errors="coerce")
    daily_df = daily_df.dropna(subset=["date"])

    for column in ["calories", "protein", "carbs", "fat"]:
        daily_df[column] = pd.to_numeric(daily_df[column], errors="coerce").fillna(0)

    daily_df = (
        daily_df.groupby(daily_df["date"].dt.date)[["calories", "protein", "carbs", "fat"]]
        .sum()
        .reset_index()
    )
    daily_df["date"] = pd.to_datetime(daily_df["date"])
    daily_df = daily_df.sort_values("date")

    daily_df["rolling_calories"] = daily_df["calories"].rolling(rolling_window, min_periods=1).mean()
    daily_df["rolling_protein"] = daily_df["protein"].rolling(rolling_window, min_periods=1).mean()
    daily_df["protein_hit"] = daily_df["protein"] >= float(target_protein)
    daily_df["protein_consistency"] = (
        daily_df["protein_hit"].rolling(rolling_window, min_periods=1).mean() * 100
    )
    daily_df["calorie_adherence"] = (
        (daily_df["calories"] / max(float(target_calories), 1)) * 100
    ).clip(upper=200)
    daily_df["protein_adherence"] = (
        (daily_df["protein"] / max(float(target_protein), 1)) * 100
    ).clip(upper=200)

    macro_calories = (
        daily_df["carbs"] * 4
        + daily_df["protein"] * 4
        + daily_df["fat"] * 9
    ).replace(0, np.nan)
    daily_df["carbs_pct"] = ((daily_df["carbs"] * 4) / macro_calories * 100).fillna(0)
    daily_df["protein_pct"] = ((daily_df["protein"] * 4) / macro_calories * 100).fillna(0)
    daily_df["fat_pct"] = ((daily_df["fat"] * 9) / macro_calories * 100).fillna(0)
    daily_df["date"] = daily_df["date"].dt.date.astype(str)

    return daily_df[columns]


class NutritionTracker:
    """Tracks nutritional intake and provides macro analysis."""
    
    def __init__(self, data_dir: str = "data/processed"):
        """Initialize the nutrition tracker.
        
        Args:
            data_dir: Directory path for storing processed nutrition data
        """
        self.data_dir = Path(data_dir)
        self.nutrition_file = self.data_dir / "nutrition.csv"
    
    def log_meal(self, date: str, meal_type: str, food_items: list, 
                 calories: float, protein: float, carbs: float, fat: float) -> bool:
        """Log a meal with macronutrient information.
        
        Args:
            date: Date of the meal (YYYY-MM-DD format)
            meal_type: Type of meal (breakfast, lunch, dinner, snack)
            food_items: List of food items consumed
            calories: Total calories
            protein: Protein in grams
            carbs: Carbohydrates in grams
            fat: Fat in grams
            
        Returns:
            True if successfully logged, False otherwise
        """
        entries_df = load_nutrition_log()
        food_name = ", ".join(str(item) for item in food_items)
        entry = create_food_entry(
            food_name=food_name,
            calories=calories,
            protein=protein,
            carbs=carbs,
            fat=fat,
            meal_type=meal_type,
            date=date,
        )
        entries_df = pd.concat([entries_df, pd.DataFrame([entry])], ignore_index=True)
        save_nutrition_log(entries_df)
        return True
    
    def get_daily_totals(self, date: str) -> dict:
        """Get total macronutrients for a specific day.
        
        Args:
            date: Date to query (YYYY-MM-DD format)
            
        Returns:
            Dictionary with daily totals for calories, protein, carbs, fat
        """
        return calculate_daily_totals(load_nutrition_log(), date)
    
    def get_nutrition_history(self, days: int = 30) -> pd.DataFrame:
        """Get nutrition history for recent period.
        
        Args:
            days: Number of days to retrieve (default: 30)
            
        Returns:
            DataFrame with nutrition data
        """
        entries_df = load_nutrition_log()
        if entries_df.empty:
            return entries_df

        cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
        dates = pd.to_datetime(entries_df["date"], errors="coerce")
        return entries_df[dates >= cutoff].copy()
