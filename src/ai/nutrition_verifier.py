"""Online nutrition verification for uncertain parsed foods.

The verifier is intentionally conservative. It only runs when the parser marks
an item as uncertain or brand/restaurant specific, prefers official sources,
and falls back cleanly when no search provider key is configured.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

import pandas as pd
from dotenv import load_dotenv

from src.paths import PROJECT_ROOT, processed_data_path

load_dotenv(PROJECT_ROOT / ".env", override=False)

VERIFIED_CACHE_PATH = processed_data_path("verified_food_cache.csv")
VERIFIED_CACHE_COLUMNS = [
    "food_name",
    "brand",
    "calories",
    "protein",
    "carbs",
    "fat",
    "fiber",
    "sodium",
    "serving_size",
    "source_url",
    "verified_at",
    "confidence",
]

BRAND_HINTS = [
    "kirkland",
    "costco",
    "built",
    "built puff",
    "in-n-out",
    "innout",
    "trader joe",
    "chipotle",
    "fairlife",
    "quest",
    "costco",
    "starbucks",
    "mcdonald",
    "taco bell",
    "chick-fil-a",
    "panera",
    "subway",
    "shake shack",
    "jersey mike",
]

GENERIC_SAFE_PATTERNS = [
    r"\b\d+\s*(g|gram|grams|oz|ounce|ounces|cup|cups|tbsp|tsp)\b",
    r"\b(egg|eggs|banana|apple|white rice|brown rice|chicken breast|ground beef|oats|potato|milk|greek yogurt)\b",
]

OFFICIAL_SOURCE_HINTS = [
    "nutrition",
    "menu",
    "restaurant",
    "brand",
    "usda",
    "fdc.nal.usda.gov",
    "fooddatacentral",
]


def _normalize(value: str) -> str:
    return " ".join(str(value or "").lower().split())


def _to_float(value: Any) -> float | None:
    try:
        return round(max(float(value), 0.0), 1)
    except (TypeError, ValueError):
        return None


def _empty_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=VERIFIED_CACHE_COLUMNS)


def load_verified_food_cache() -> pd.DataFrame:
    """Load verified food cache from local CSV."""
    if not VERIFIED_CACHE_PATH.exists():
        return _empty_cache()
    cache_df = pd.read_csv(VERIFIED_CACHE_PATH)
    for column in VERIFIED_CACHE_COLUMNS:
        if column not in cache_df.columns:
            cache_df[column] = ""
    cache_df = cache_df[VERIFIED_CACHE_COLUMNS]
    for column in ["calories", "protein", "carbs", "fat", "fiber", "sodium"]:
        cache_df[column] = pd.to_numeric(cache_df[column], errors="coerce")
    for column in ["food_name", "brand", "serving_size", "source_url", "verified_at", "confidence"]:
        cache_df[column] = cache_df[column].fillna("").astype(str)
    return cache_df


def save_verified_food_cache(cache_df: pd.DataFrame) -> None:
    """Persist verified food cache locally."""
    VERIFIED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache_df.reindex(columns=VERIFIED_CACHE_COLUMNS).to_csv(VERIFIED_CACHE_PATH, index=False)


def _cache_lookup(food_name: str, brand: str | None = None) -> dict | None:
    cache_df = load_verified_food_cache()
    if cache_df.empty:
        return None
    normalized_name = _normalize(food_name)
    normalized_brand = _normalize(brand or "")
    match = cache_df[cache_df["food_name"].map(_normalize) == normalized_name]
    if normalized_brand:
        brand_match = match[match["brand"].map(_normalize) == normalized_brand]
        if not brand_match.empty:
            match = brand_match
    if match.empty:
        return None
    row = match.iloc[-1]
    return {
        "verified": True,
        "cached": True,
        "source": "verified_cache",
        "source_url": row["source_url"],
        "macros": {
            "calories": _to_float(row["calories"]) or 0,
            "protein": _to_float(row["protein"]) or 0,
            "carbs": _to_float(row["carbs"]) or 0,
            "fat": _to_float(row["fat"]) or 0,
            "fiber": _to_float(row["fiber"]),
            "sodium": _to_float(row["sodium"]),
        },
        "serving_size": row["serving_size"],
        "confidence": row["confidence"] or "high",
        "message": "Loaded from verified food cache.",
    }


def _save_verified_result(food_name: str, brand: str | None, result: dict) -> None:
    macros = result.get("macros", {})
    cache_df = load_verified_food_cache()
    normalized_name = _normalize(food_name)
    normalized_brand = _normalize(brand or "")
    if not cache_df.empty:
        cache_df = cache_df[
            ~(
                (cache_df["food_name"].map(_normalize) == normalized_name)
                & (cache_df["brand"].map(_normalize) == normalized_brand)
            )
        ]
    row = {
        "food_name": food_name,
        "brand": brand or "",
        "calories": macros.get("calories"),
        "protein": macros.get("protein"),
        "carbs": macros.get("carbs"),
        "fat": macros.get("fat"),
        "fiber": macros.get("fiber"),
        "sodium": macros.get("sodium"),
        "serving_size": result.get("serving_size", ""),
        "source_url": result.get("source_url", ""),
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "confidence": result.get("confidence", "medium"),
    }
    cache_df = pd.concat([cache_df, pd.DataFrame([row])], ignore_index=True)
    save_verified_food_cache(cache_df)


def should_verify_food(food_name: str, confidence: str = "medium", verification_needed: bool = False) -> tuple[bool, str]:
    """Decide whether online verification is warranted."""
    name = _normalize(food_name)
    if verification_needed:
        return True, "Parser marked this item for verification."
    if confidence == "low":
        return True, "Parser confidence is low."
    if any(hint in name for hint in BRAND_HINTS):
        return True, "Food appears branded, packaged, or restaurant-specific."
    if any(re.search(pattern, name) for pattern in GENERIC_SAFE_PATTERNS):
        return False, "Generic food with clear quantity; online verification not needed."
    if any(char.isupper() for char in str(food_name)) and len(str(food_name).split()) >= 2:
        return True, "Food name may be brand or product specific."
    return False, "AI estimate is sufficient for a generic food."


def _search_api_key() -> tuple[str | None, str | None]:
    brave = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if brave:
        return "brave", brave
    serpapi = os.getenv("SERPAPI_API_KEY", "").strip()
    if serpapi:
        return "serpapi", serpapi
    return None, None


def _http_json(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers=headers or {"User-Agent": "PerformanceOS/0.1"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8", errors="ignore"))


def _search_web(query: str) -> list[dict]:
    provider, key = _search_api_key()
    if provider == "brave":
        url = f"https://api.search.brave.com/res/v1/web/search?{urlencode({'q': query, 'count': 6})}"
        data = _http_json(url, headers={"Accept": "application/json", "X-Subscription-Token": key or ""})
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            }
            for item in data.get("web", {}).get("results", [])
        ]
    if provider == "serpapi":
        url = f"https://serpapi.com/search.json?{urlencode({'engine': 'google', 'q': query, 'api_key': key or '', 'num': 6})}"
        data = _http_json(url)
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in data.get("organic_results", [])
        ]
    return []


def _source_score(result: dict, food_name: str) -> int:
    text = _normalize(" ".join([result.get("title", ""), result.get("url", ""), result.get("snippet", "")]))
    score = 0
    if any(hint in text for hint in OFFICIAL_SOURCE_HINTS):
        score += 10
    for token in _normalize(food_name).split():
        if len(token) > 2 and token in text:
            score += 1
    if any(low_quality in text for low_quality in ["reddit", "pinterest", "myfitnesspal", "fatsecret"]):
        score -= 5
    return score


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "PerformanceOS/0.1"})
    with urlopen(request, timeout=10) as response:
        content = response.read(250_000).decode("utf-8", errors="ignore")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content))


def _extract_macros(text: str) -> dict | None:
    lower = text.lower()
    patterns = {
        "calories": [r"calories[^0-9]{0,20}(\d{1,4})", r"(\d{1,4})\s*calories"],
        "protein": [r"protein[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*g", r"(\d{1,3}(?:\.\d+)?)\s*g\s*protein"],
        "carbs": [r"carb(?:ohydrate)?s?[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*g", r"(\d{1,3}(?:\.\d+)?)\s*g\s*carb"],
        "fat": [r"total fat[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*g", r"fat[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*g"],
        "fiber": [r"fiber[^0-9]{0,20}(\d{1,3}(?:\.\d+)?)\s*g"],
        "sodium": [r"sodium[^0-9]{0,20}(\d{1,5}(?:\.\d+)?)\s*mg"],
    }
    macros: dict[str, float | None] = {}
    for macro, macro_patterns in patterns.items():
        value = None
        for pattern in macro_patterns:
            match = re.search(pattern, lower)
            if match:
                value = _to_float(match.group(1))
                break
        macros[macro] = value

    if all(macros.get(key) is not None for key in ["calories", "protein", "carbs", "fat"]):
        return macros
    return None


def verify_food_online(food_name: str, quantity: str | None = None, brand: str | None = None) -> dict:
    """Verify macros online for one food when search credentials are configured."""
    cached = _cache_lookup(food_name, brand)
    if cached:
        return cached

    provider, key = _search_api_key()
    if not provider or not key:
        return {
            "verified": False,
            "cached": False,
            "source": "verification_unavailable",
            "source_url": "",
            "macros": {},
            "confidence": "low",
            "message": "Online verification unavailable because no search API key is configured.",
        }

    search_query = f"{brand or ''} {food_name} {quantity or ''} nutrition facts official USDA".strip()
    try:
        results = _search_web(search_query)
    except Exception as exc:
        return {
            "verified": False,
            "cached": False,
            "source": "search_error",
            "source_url": "",
            "macros": {},
            "confidence": "low",
            "message": f"Online verification search failed: {type(exc).__name__}.",
        }

    ranked = sorted(results, key=lambda item: _source_score(item, food_name), reverse=True)[:5]
    for result in ranked:
        text = " ".join([result.get("title", ""), result.get("snippet", "")])
        macros = _extract_macros(text)
        if macros is None and result.get("url"):
            try:
                macros = _extract_macros(_fetch_text(result["url"]))
            except Exception:
                macros = None
        if macros:
            verification = {
                "verified": True,
                "cached": False,
                "source": "verified_online",
                "source_url": result.get("url", ""),
                "macros": macros,
                "serving_size": quantity or "",
                "confidence": "high" if _source_score(result, food_name) >= 10 else "medium",
                "message": f"Verified from {result.get('title') or 'online nutrition source'}.",
            }
            _save_verified_result(food_name, brand, verification)
            return verification

    return {
        "verified": False,
        "cached": False,
        "source": "verification_failed",
        "source_url": ranked[0].get("url", "") if ranked else "",
        "macros": {},
        "confidence": "low",
        "message": "Online verification did not find a reliable macro source. Please review manually.",
    }
