"""USDA FoodData Central lookup helpers for nutrition estimates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from dotenv import load_dotenv

from src.paths import PROJECT_ROOT, processed_data_path
from src.storage import load_dataframe, save_dataframe

load_dotenv(PROJECT_ROOT / ".env", override=False)

USDA_CACHE_PATH = processed_data_path("usda_food_cache.csv")
USDA_CACHE_COLUMNS = [
    "query",
    "fdc_id",
    "description",
    "serving_description",
    "calories",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
]

NUTRIENT_KEYS = {
    "calories": {1008, 2047, 2048},
    "protein_g": {1003},
    "carbs_g": {1005},
    "fat_g": {1004},
    "fiber_g": {1079},
    "sugar_g": {2000, 1063},
    "sodium_mg": {1093},
}


def _api_key() -> str:
    return os.getenv("USDA_FDC_API_KEY", "").strip()


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _empty_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=USDA_CACHE_COLUMNS)


def _load_cache() -> pd.DataFrame:
    cache_df = load_dataframe("usda_food_cache", USDA_CACHE_PATH, USDA_CACHE_COLUMNS)
    for column in USDA_CACHE_COLUMNS:
        if column not in cache_df.columns:
            cache_df[column] = ""
    cache_df = cache_df[USDA_CACHE_COLUMNS]
    for column in ["fdc_id", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]:
        cache_df[column] = pd.to_numeric(cache_df[column], errors="coerce")
    for column in ["query", "description", "serving_description"]:
        cache_df[column] = cache_df[column].fillna("").astype(str)
    return cache_df


def _save_cache(cache_df: pd.DataFrame) -> None:
    save_dataframe("usda_food_cache", USDA_CACHE_PATH, cache_df, USDA_CACHE_COLUMNS)


def _http_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "PerformanceOS/0.1"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def _nutrient_value(food: dict[str, Any], key: str) -> float | None:
    nutrient_ids = NUTRIENT_KEYS[key]
    for nutrient in food.get("foodNutrients", []) or []:
        nutrient_id = nutrient.get("nutrientId") or nutrient.get("nutrient", {}).get("id")
        if nutrient_id in nutrient_ids:
            value = nutrient.get("value") if "value" in nutrient else nutrient.get("amount")
            try:
                return round(max(float(value), 0), 1)
            except (TypeError, ValueError):
                return None
    return None


def _serving_description(food: dict[str, Any]) -> str:
    size = food.get("servingSize")
    unit = food.get("servingSizeUnit")
    household = food.get("householdServingFullText")
    parts = [str(part).strip() for part in [household, f"{size:g} {unit}" if isinstance(size, (int, float)) and unit else ""] if str(part).strip()]
    return " / ".join(parts) or "100 g reference serving"


def _cache_lookup(query: str) -> dict | None:
    cache_df = _load_cache()
    match = cache_df[cache_df["query"].map(_normalize) == _normalize(query)]
    if match.empty:
        return None
    row = match.iloc[-1]
    return {
        "source": "usda_fdc",
        "source_id": str(int(row["fdc_id"])) if pd.notna(row["fdc_id"]) else "",
        "source_url": f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{int(row['fdc_id'])}/nutrients" if pd.notna(row["fdc_id"]) else "",
        "serving_description": row["serving_description"],
        "macros": {
            "calories": float(row["calories"] or 0),
            "protein_g": float(row["protein_g"] or 0),
            "carbs_g": float(row["carbs_g"] or 0),
            "fat_g": float(row["fat_g"] or 0),
            "fiber_g": None if pd.isna(row["fiber_g"]) else float(row["fiber_g"]),
            "sugar_g": None if pd.isna(row["sugar_g"]) else float(row["sugar_g"]),
            "sodium_mg": None if pd.isna(row["sodium_mg"]) else float(row["sodium_mg"]),
        },
        "description": row["description"],
        "cached": True,
    }


def search_food_macros(query: str) -> dict | None:
    """Return a best-effort USDA macro match for a food query."""
    cleaned_query = str(query or "").strip()
    if not cleaned_query:
        return None

    cached = _cache_lookup(cleaned_query)
    if cached:
        return cached

    key = _api_key()
    if not key:
        return None

    params = urlencode(
        {
            "api_key": key,
            "query": cleaned_query,
            "pageSize": 1,
            "dataType": ["Foundation", "SR Legacy", "Survey (FNDDS)", "Branded"],
        },
        doseq=True,
    )
    data = _http_json(f"https://api.nal.usda.gov/fdc/v1/foods/search?{params}")
    foods = data.get("foods", [])
    if not foods:
        return None

    food = foods[0]
    macros = {key_name: _nutrient_value(food, key_name) for key_name in NUTRIENT_KEYS}
    if not any(macros.get(key_name) for key_name in ["calories", "protein_g", "carbs_g", "fat_g"]):
        return None

    fdc_id = food.get("fdcId")
    result = {
        "source": "usda_fdc",
        "source_id": str(fdc_id or ""),
        "source_url": f"https://fdc.nal.usda.gov/fdc-app.html#/food-details/{fdc_id}/nutrients" if fdc_id else "",
        "serving_description": _serving_description(food),
        "macros": {
            "calories": macros.get("calories") or 0,
            "protein_g": macros.get("protein_g") or 0,
            "carbs_g": macros.get("carbs_g") or 0,
            "fat_g": macros.get("fat_g") or 0,
            "fiber_g": macros.get("fiber_g"),
            "sugar_g": macros.get("sugar_g"),
            "sodium_mg": macros.get("sodium_mg"),
        },
        "description": food.get("description", ""),
        "cached": False,
    }
    cache_df = _load_cache()
    cache_df = cache_df[cache_df["query"].map(_normalize) != _normalize(cleaned_query)]
    cache_df = pd.concat(
        [
            cache_df,
            pd.DataFrame(
                [
                    {
                        "query": cleaned_query,
                        "fdc_id": fdc_id,
                        "description": result["description"],
                        "serving_description": result["serving_description"],
                        **result["macros"],
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    _save_cache(cache_df)
    return result
