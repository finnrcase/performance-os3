"""OpenAI-assisted food parsing for Performance OS.

This module only parses natural-language food text into editable structured
macro estimates. It does not save nutrition logs; the UI/backend confirmation
flow handles persistence after the user reviews the parsed rows.
"""

from __future__ import annotations

import json
import base64
import hashlib
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

import pandas as pd
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

from src.ai.nutrition_verifier import should_verify_food, verify_food_online
from src.integrations.usda_client import search_food_macros
from src.paths import PROJECT_ROOT, processed_data_path
from src.storage import load_dataframe, save_dataframe


load_dotenv(PROJECT_ROOT / ".env", override=False)

FOOD_CACHE_PATH = processed_data_path("ai_food_cache.csv")
FOOD_CACHE_COLUMNS = [
    "query",
    "foods_json",
    "food_name",
    "normalized_name",
    "quantity",
    "calories",
    "protein",
    "carbs",
    "fat",
    "confidence",
    "verification_needed",
    "verification_reason",
    "source",
    "verification_status",
    "source_url",
    "notes",
    "last_used_at",
]

# Food parsing runs as a staged pipeline: exact local matches first, a fast
# structured parser second, and a stronger parser only for ambiguous input.
FOOD_ANALYSIS_DEFAULT_MODEL = "gpt-5.4-mini"
FOOD_ANALYSIS_ESCALATION_DEFAULT_MODEL = "gpt-5.5"
FOOD_ANALYSIS_REASONING_EFFORT = "low"
FOOD_ANALYSIS_ESCALATION_REASONING_EFFORT = "medium"
DEPRECATED_OR_LOW_ACCURACY_MODELS = {
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-4-turbo",
    "gpt-4.5-preview",
    "gpt-4o-mini",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.4-nano",
}
CONFIDENCE_VALUES = {"low", "medium", "high"}
CONFIDENCE_SCORES = {"low": 0.55, "medium": 0.72, "high": 0.92}
LOW_CONFIDENCE_THRESHOLD = 0.75
AMBIGUOUS_FOOD_TERMS = {
    "beans",
    "bowl",
    "sandwich",
    "shake",
    "smoothie",
    "wrap",
    "salad",
    "pasta",
    "rice",
    "chicken",
    "beef",
    "taco",
    "burrito",
    "plate",
    "meal",
}
BRANDED_FOOD_HINTS = {
    "built",
    "nurri",
    "oats overnight",
    "kirkland",
    "fairlife",
    "chipotle",
    "bibigo",
    "quest",
    "barebells",
    "rxbar",
}
DEFAULT_SAVED_FOOD_SHORTCUTS: list[dict[str, Any]] = [
    {"shortcut_id": "default-preset-built-puff-bar", "shortcut_name": "Built Puff Bar", "calories": 140, "protein": 17, "carbs": 15, "fat": 3, "fiber": 0, "notes": "Seed preset. Edit to match your label.", "source": "default_preset"},
    {"shortcut_id": "default-preset-nurri-shake", "shortcut_name": "Nurri Shake", "calories": 150, "protein": 30, "carbs": 3, "fat": 3, "fiber": 0, "notes": "Seed preset. Edit to match your label.", "source": "default_preset"},
    {"shortcut_id": "default-preset-oats-overnight", "shortcut_name": "Oats Overnight", "calories": 280, "protein": 20, "carbs": 35, "fat": 7, "fiber": 6, "notes": "Seed preset. Edit to match your label.", "source": "default_preset"},
    {"shortcut_id": "default-preset-chicken-bowl", "shortcut_name": "Chicken Bowl", "calories": 650, "protein": 45, "carbs": 70, "fat": 20, "fiber": 8, "notes": "Seed preset. Edit to match your usual bowl.", "source": "default_preset"},
    {"shortcut_id": "default-preset-banana", "shortcut_name": "Banana", "calories": 105, "protein": 1, "carbs": 27, "fat": 0, "fiber": 3, "notes": "Seed preset. Edit to match your usual serving.", "source": "default_preset"},
]
MODEL_COST_PER_MILLION_TOKENS = {
    # Conservative estimates for internal cost visibility only.
    "gpt-5.4-mini": {"input": 0.80, "output": 3.20},
    "gpt-5.5": {"input": 5.00, "output": 15.00},
}
logger = logging.getLogger(__name__)

_TITLE_MINOR_WORDS = {"of", "and", "with", "the", "a", "an", "in", "on", "to", "for"}
_LEADING_QUANTITY_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*"
    r"(?:oz|ounces?|g|grams?|lbs?|kg|cups?|tbsp|tsp|ml|l|servings?|scoops?|slices?|pieces?|pcs?|x)?\s*"
    r"(?:of\s+)?",
    re.IGNORECASE,
)


def _configured_food_model(env_name: str, fallback: str) -> str:
    model = os.getenv(env_name, "").strip() or fallback
    if model in DEPRECATED_OR_LOW_ACCURACY_MODELS:
        raise ValueError(
            f"{env_name}={model} is not allowed for nutrition parsing. "
            f"Use {fallback} or another current structured-output model."
        )
    return model


def food_analysis_model() -> str:
    """Return the configured fast/default OpenAI model for food text analysis."""
    return _configured_food_model("FOOD_ANALYSIS_MODEL", FOOD_ANALYSIS_DEFAULT_MODEL)


def food_analysis_escalation_model() -> str:
    """Return the configured stronger model used only for low-confidence parses."""
    return _configured_food_model("FOOD_ANALYSIS_ESCALATION_MODEL", FOOD_ANALYSIS_ESCALATION_DEFAULT_MODEL)


def food_analysis_model_info(stage: str = "default") -> dict[str, Any]:
    """Return non-secret model configuration metadata for logs/debug."""
    is_escalation = stage == "escalation"
    env_name = "FOOD_ANALYSIS_ESCALATION_MODEL" if is_escalation else "FOOD_ANALYSIS_MODEL"
    configured = os.getenv(env_name, "").strip()
    model = food_analysis_escalation_model() if is_escalation else food_analysis_model()
    reasoning_env = "FOOD_ANALYSIS_ESCALATION_REASONING_EFFORT" if is_escalation else "FOOD_ANALYSIS_REASONING_EFFORT"
    fallback_effort = FOOD_ANALYSIS_ESCALATION_REASONING_EFFORT if is_escalation else FOOD_ANALYSIS_REASONING_EFFORT
    return {
        "stage": stage,
        "model": model,
        "default_model": food_analysis_model(),
        "escalation_model": food_analysis_escalation_model(),
        "model_source": "env" if configured else "default",
        "fallback_model_used": False,
        "reasoning_effort": os.getenv(reasoning_env, "").strip() or fallback_effort,
        "escalation_reasoning_effort": os.getenv("FOOD_ANALYSIS_ESCALATION_REASONING_EFFORT", "").strip() or FOOD_ANALYSIS_ESCALATION_REASONING_EFFORT,
        "supports_structured_outputs": True,
        "supports_image_input": True,
    }


def _clean_display_name(raw: str, fallback: str = "") -> str:
    """Title-case a food name, stripping leading quantity/unit noise."""
    text = _LEADING_QUANTITY_RE.sub("", str(raw or "").strip())
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    cleaned: list[str] = []
    for index, word in enumerate(words):
        if not word:
            continue
        lowered = word.lower()
        if index != 0 and lowered in _TITLE_MINOR_WORDS:
            cleaned.append(lowered)
        elif word.isupper() and len(word) <= 4:
            cleaned.append(word)  # preserve short acronyms / brand stylings
        else:
            cleaned.append(word[:1].upper() + word[1:].lower())
    return " ".join(cleaned) or str(fallback or "").strip()


def _normalized_name(display_name: str) -> str:
    """Lowercase snake_case key derived from a display name."""
    return re.sub(r"[^a-z0-9]+", "_", str(display_name or "").strip().lower()).strip("_")


def _normalize_query(food_text: str) -> str:
    """Normalize cache keys so repeated foods avoid API calls."""
    return " ".join(str(food_text).strip().lower().split())


def _empty_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=FOOD_CACHE_COLUMNS)


def _load_food_cache() -> pd.DataFrame:
    cache_df = load_dataframe("ai_food_cache", FOOD_CACHE_PATH, FOOD_CACHE_COLUMNS)
    for column in FOOD_CACHE_COLUMNS:
        if column not in cache_df.columns:
            cache_df[column] = ""
    cache_df = cache_df[FOOD_CACHE_COLUMNS]
    for column in ["calories", "protein", "carbs", "fat"]:
        cache_df[column] = pd.to_numeric(cache_df[column], errors="coerce").fillna(0)
    for column in ["query", "foods_json", "food_name", "normalized_name", "quantity", "confidence", "verification_needed", "verification_reason", "source", "verification_status", "source_url", "notes", "last_used_at"]:
        cache_df[column] = cache_df[column].fillna("").astype(str)
    return cache_df


def _save_food_cache(cache_df: pd.DataFrame) -> None:
    save_dataframe("ai_food_cache", FOOD_CACHE_PATH, cache_df, FOOD_CACHE_COLUMNS)


def _read_settings_key() -> str:
    """Read the saved OpenAI key from the same settings document backend_new uses."""
    try:
        from backend_new.db import fetch_latest_document

        stored = fetch_latest_document("api_connections", {})
        integrations = stored.get("integrations") if isinstance(stored, dict) and isinstance(stored.get("integrations"), dict) else {}
        value = str(integrations.get("openai_api_key") or "").strip()
        if value and not value.startswith(("••••", "***")):
            return value
    except Exception:
        pass
    try:
        from src.config import load_settings

        value = str(load_settings().get("integrations", {}).get("openai_api_key", "")).strip()
        return "" if value.startswith(("••••", "***")) else value
    except Exception:
        return ""


def get_openai_key_status() -> bool:
    """Return whether an OpenAI key is configured without exposing it."""
    return bool(os.getenv("OPENAI_API_KEY", "").strip() or _read_settings_key())


def _get_openai_api_key() -> str:
    """Read OpenAI key from environment first, then local settings fallback."""
    return os.getenv("OPENAI_API_KEY", "").strip() or _read_settings_key()


def openai_analyzer_config() -> dict[str, Any]:
    """Return the canonical non-secret OpenAI analyzer configuration."""
    try:
        model_info = food_analysis_model_info()
        model_error = ""
    except Exception as exc:
        model_info = {
            "model": "",
            "model_source": "invalid",
            "fallback_model_used": False,
            "reasoning_effort": "",
            "supports_structured_outputs": True,
            "supports_image_input": True,
        }
        model_error = str(exc)
    return {
        "openai_key_configured": get_openai_key_status(),
        "api_key_source": "environment" if os.getenv("OPENAI_API_KEY", "").strip() else "settings" if _read_settings_key() else "missing",
        "model": model_info.get("model") or FOOD_ANALYSIS_DEFAULT_MODEL,
        "default_model": model_info.get("default_model") or FOOD_ANALYSIS_DEFAULT_MODEL,
        "escalation_model": model_info.get("escalation_model") or FOOD_ANALYSIS_ESCALATION_DEFAULT_MODEL,
        "model_source": model_info.get("model_source", "default"),
        "fallback_model_used": bool(model_info.get("fallback_model_used", False)),
        "reasoning_effort": model_info.get("reasoning_effort", FOOD_ANALYSIS_REASONING_EFFORT),
        "escalation_reasoning_effort": model_info.get("escalation_reasoning_effort", FOOD_ANALYSIS_ESCALATION_REASONING_EFFORT),
        "supports_structured_outputs": bool(model_info.get("supports_structured_outputs", True)),
        "supports_image_input": bool(model_info.get("supports_image_input", True)),
        "model_error": model_error,
    }


def _to_float(value: Any) -> float:
    try:
        parsed = float(value or 0)
        if not pd.notna(parsed):
            return 0.0
        return round(max(parsed, 0.0), 1)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    try:
        if value in [None, ""]:
            return None
        parsed = float(value)
        if not pd.notna(parsed):
            return None
        return round(max(parsed, 0.0), 1)
    except (TypeError, ValueError):
        return None


def _confidence_score(confidence: str | None, explicit_score: Any = None) -> float:
    parsed = _optional_float(explicit_score)
    if parsed is not None:
        return round(min(max(parsed, 0.0), 1.0), 2)
    return CONFIDENCE_SCORES.get(str(confidence or "medium").strip().lower(), CONFIDENCE_SCORES["medium"])


def _estimated_token_count(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return max(1, int(len(text) / 4))


def _usage_value(usage: Any, *names: str) -> int | None:
    for name in names:
        value = getattr(usage, name, None)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(usage, dict) and isinstance(usage.get(name), (int, float)):
            return int(usage[name])
    return None


def _estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_COST_PER_MILLION_TOKENS.get(model, MODEL_COST_PER_MILLION_TOKENS.get(FOOD_ANALYSIS_ESCALATION_DEFAULT_MODEL, {"input": 0, "output": 0}))
    cost = ((input_tokens / 1_000_000) * float(rates.get("input", 0))) + ((output_tokens / 1_000_000) * float(rates.get("output", 0)))
    return round(cost, 6)


def _call_cost_metadata(*, model: str, input_payload: Any, output_payload: Any, response: Any | None, stage: str, latency_ms: float) -> dict[str, Any]:
    usage = getattr(response, "usage", None) if response is not None else None
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens") or _estimated_token_count(input_payload)
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens") or _estimated_token_count(output_payload)
    return {
        "stage": stage,
        "model_used": model,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": _estimate_cost_usd(model, input_tokens, output_tokens),
        "latency_ms": round(latency_ms, 1),
    }


def _parser_summary(calls: list[dict[str, Any]], *, escalated: bool, escalation_reason: str = "", final_model: str = "") -> dict[str, Any]:
    final = final_model or (calls[-1].get("model_used") if calls else "")
    return {
        "default_model_used": any(call.get("stage") == "default" for call in calls),
        "escalated": escalated,
        "escalation_reason": escalation_reason,
        "final_model": final,
        "model_used": final,
        "estimated_input_tokens": int(sum(int(call.get("estimated_input_tokens") or 0) for call in calls)),
        "estimated_output_tokens": int(sum(int(call.get("estimated_output_tokens") or 0) for call in calls)),
        "estimated_cost_usd": round(sum(float(call.get("estimated_cost_usd") or 0) for call in calls), 6),
        "calls": calls,
    }


def _non_openai_parser_summary(source: str) -> dict[str, Any]:
    return _parser_summary([], escalated=False, final_model=source)


def _split_fallback_foods(food_text: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.split(r",|\band\b", str(food_text).strip(), flags=re.IGNORECASE)
        if part.strip()
    ]
    return parts or [str(food_text).strip()]


def _looks_like_multi_food_query(query: str) -> bool:
    text = str(query or "").strip().lower()
    return bool(re.search(r",|/|\+|&|\n|\b(and|plus|with)\b", text))


def _saved_food_match(query: str, candidate_name: str) -> bool:
    """Only short-circuit OpenAI when the saved item represents the whole query."""
    normalized_query = _normalize_query(query)
    normalized_name = _normalize_query(candidate_name)
    if not normalized_query or not normalized_name:
        return False
    if normalized_query == normalized_name:
        return True
    if _looks_like_multi_food_query(query):
        return False
    return normalized_query in normalized_name


def _shortcut_food(row: dict[str, Any], *, source_label: str, note: str) -> dict[str, Any]:
    name = str(row.get("shortcut_name") or row.get("food_name") or row.get("name") or "").strip()
    source_id = str(row.get("shortcut_id") or row.get("source_id") or "").strip() or None
    return {
        "food_name": name,
        "display_name": name,
        "normalized_name": _normalized_name(name),
        "original_text": name,
        "quantity": 1,
        "unit": "serving",
        "serving_description": str(row.get("serving_description") or "1 saved serving").strip(),
        "calories": row.get("calories", 0),
        "protein": row.get("protein", row.get("protein_g", 0)),
        "carbs": row.get("carbs", row.get("carbs_g", 0)),
        "fat": row.get("fat", row.get("fat_g", 0)),
        "fiber": row.get("fiber", row.get("fiber_g")),
        "sugar": row.get("sugar", row.get("sugar_g")),
        "sodium": row.get("sodium", row.get("sodium_mg")),
        "confidence": "high",
        "confidence_score": 1,
        "verification_needed": False,
        "verification_reason": note,
        "source": source_label,
        "source_id": source_id,
        "verification_status": "ready",
        "source_url": str(row.get("source_url") or "").strip(),
        "assumptions": [note],
        "needs_review": False,
        "needs_confirmation": False,
        "notes": str(row.get("notes") or note).strip(),
    }


def _shortcut_response(row: dict[str, Any], *, source_label: str, note: str, message: str) -> dict[str, Any]:
    return _response(
        foods=[_shortcut_food(row, source_label=source_label, note=note)],
        source=source_label,
        cached=True,
        success=True,
        message=message,
        parser=_non_openai_parser_summary(source_label),
    )


def _local_saved_food_response(query: str) -> dict | None:
    """Check reusable local foods before calling OpenAI."""
    try:
        from src.ai.nutrition_verifier import load_verified_food_cache
        from src.nutrition import load_food_shortcuts, load_frequent_foods

        try:
            from backend_new.db import fetch_json_rows

            for row in fetch_json_rows("food_shortcuts", limit=500):
                if not isinstance(row, dict) or row.get("_db_error"):
                    continue
                name = _normalize_query(row.get("shortcut_name", ""))
                if _saved_food_match(query, name):
                    return _shortcut_response(
                        row,
                        source_label="saved_shortcut",
                        note="Matched saved shortcut before AI parsing.",
                        message="Loaded exact macros from saved shortcut.",
                    )
        except Exception:
            pass

        shortcuts = load_food_shortcuts()
        for _, row in shortcuts.iterrows():
            name = _normalize_query(row.get("shortcut_name", ""))
            if _saved_food_match(query, name):
                return _shortcut_response(
                    row.to_dict(),
                    source_label="saved_shortcut",
                    note="Matched saved shortcut before AI parsing.",
                    message="Loaded exact macros from saved shortcut.",
                )

        frequent = load_frequent_foods()
        for _, row in frequent.iterrows():
            name = _normalize_query(row.get("food_name", ""))
            if _saved_food_match(query, name):
                return _shortcut_response(
                    row.to_dict(),
                    source_label="existing_database",
                    note="Matched frequent food before AI parsing.",
                    message="Loaded exact macros from frequent food.",
                )

        for row in DEFAULT_SAVED_FOOD_SHORTCUTS:
            name = _normalize_query(row.get("shortcut_name", ""))
            if _saved_food_match(query, name):
                return _shortcut_response(
                    row,
                    source_label="saved_shortcut",
                    note="Matched built-in food shortcut before AI parsing.",
                    message="Loaded exact macros from built-in shortcut.",
                )

        verified = load_verified_food_cache()
        for _, row in verified.iterrows():
            name = _normalize_query(row.get("food_name", ""))
            if _saved_food_match(query, name):
                food = {
                    "food_name": row.get("food_name", ""),
                    "quantity": row.get("serving_size", ""),
                    "calories": row.get("calories", 0),
                    "protein": row.get("protein", 0),
                    "carbs": row.get("carbs", 0),
                    "fat": row.get("fat", 0),
                    "confidence": row.get("confidence", "high") or "high",
                    "verification_needed": False,
                    "verification_reason": "Matched verified online cache before OpenAI.",
                    "source": "verified_online",
                    "verification_status": "cached",
                    "source_url": row.get("source_url", ""),
                    "notes": "Loaded from verified food cache.",
                }
                return _response(
                    foods=[food],
                    source="verified_cache",
                    cached=True,
                    success=True,
                    message="Loaded from verified food cache.",
                    parser=_non_openai_parser_summary("verified_cache"),
                )
    except Exception:
        return None
    return None


def _normalize_food(food: dict[str, Any], fallback_name: str) -> dict:
    """Validate and normalize one parsed food row."""
    notes = []
    raw_name = str(food.get("food_name") or fallback_name).strip() or fallback_name
    model_display = str(food.get("display_name") or "").strip()
    display_name = _clean_display_name(model_display or raw_name, fallback=raw_name)
    if not display_name:
        display_name = _clean_display_name(fallback_name) or str(fallback_name or "").strip()
    normalized_name = _normalized_name(str(food.get("normalized_name") or "").strip() or display_name)
    # The clean display name is the canonical title used everywhere downstream.
    food_name = display_name or raw_name
    quantity_raw = food.get("quantity")
    quantity = str(quantity_raw or "").strip()
    confidence = str(food.get("confidence") or "medium").strip().lower()
    if confidence not in CONFIDENCE_VALUES:
        confidence = "medium"
        notes.append("Confidence was normalized to medium.")
    confidence_score = _confidence_score(confidence, food.get("confidence_score"))
    verification_needed = bool(food.get("verification_needed", False))
    heuristic_needed, heuristic_reason = should_verify_food(food_name, confidence, verification_needed)
    needs_review = bool(food.get("needs_review", food.get("needs_confirmation", heuristic_needed or confidence_score < LOW_CONFIDENCE_THRESHOLD)))

    normalized = {
        "food_name": food_name,
        "display_name": display_name,
        "normalized_name": normalized_name,
        "original_text": str(food.get("original_text") or raw_name).strip(),
        "quantity": quantity,
        "quantity_value": _optional_float(quantity_raw),
        "unit": str(food.get("unit") or "").strip(),
        "serving_description": str(food.get("serving_description") or quantity).strip(),
        "calories": _to_float(food.get("calories")),
        "protein": _to_float(food.get("protein")),
        "carbs": _to_float(food.get("carbs")),
        "fat": _to_float(food.get("fat")),
        "fiber": _optional_float(food.get("fiber") if "fiber" in food else food.get("fiber_g")),
        "sugar": _optional_float(food.get("sugar") if "sugar" in food else food.get("sugar_g")),
        "sodium": _optional_float(food.get("sodium") if "sodium" in food else food.get("sodium_mg")),
        "confidence": confidence,
        "verification_needed": heuristic_needed,
        "verification_reason": str(food.get("verification_reason") or heuristic_reason).strip(),
        "source": str(food.get("source") or "ai_estimate").strip(),
        "source_id": str(food.get("source_id") or "").strip(),
        "verification_status": str(food.get("verification_status") or ("needed" if heuristic_needed else "not_needed")).strip(),
        "source_url": str(food.get("source_url") or "").strip(),
        "assumptions": food.get("assumptions") if isinstance(food.get("assumptions"), list) else [],
        "confidence_score": confidence_score,
        "needs_review": needs_review,
        "needs_confirmation": needs_review,
        "notes": str(food.get("notes") or "").strip(),
    }

    for macro in ["calories", "protein", "carbs", "fat"]:
        if macro not in food:
            notes.append(f"{macro} missing; defaulted to 0.")

    if notes:
        normalized["notes"] = " ".join([normalized["notes"], *notes]).strip()
    if not normalized["notes"]:
        normalized["notes"] = "Estimate. Review and edit before saving."

    return normalized


def _total(foods: list[dict]) -> dict:
    totals = {
        "calories": round(sum(float(food.get("calories", 0) or 0) for food in foods), 1),
        "protein": round(sum(float(food.get("protein", 0) or 0) for food in foods), 1),
        "carbs": round(sum(float(food.get("carbs", 0) or 0) for food in foods), 1),
        "fat": round(sum(float(food.get("fat", 0) or 0) for food in foods), 1),
    }
    for key in ["fiber", "sugar", "sodium"]:
        values = [food.get(key) for food in foods if food.get(key) is not None]
        totals[key] = round(sum(float(value or 0) for value in values), 1) if values else None
    return totals


def _response(
    *,
    foods: list[dict] | None = None,
    source: str,
    cached: bool,
    success: bool,
    message: str,
    error_code: str | None = None,
    parser: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    normalized_foods = [_normalize_food(food, food.get("food_name", "")) for food in foods or []]
    parser_payload = parser or _non_openai_parser_summary(source)
    return {
        "foods": normalized_foods,
        "total": _total(normalized_foods),
        "source": source,
        "cached": cached,
        "success": success,
        "error_code": error_code,
        "message": message,
        "warnings": warnings or [],
        "parser": parser_payload,
        "debug": {
            "backend_endpoint_reached": True,
            **openai_analyzer_config(),
            "parsing_status": "success" if success else "failure",
            "parser": parser_payload,
            "openai_called": bool(parser_payload.get("default_model_used") or parser_payload.get("escalated")),
            "escalated": bool(parser_payload.get("escalated")),
            "escalation_reason": parser_payload.get("escalation_reason", ""),
            "final_model": parser_payload.get("final_model", ""),
            "estimated_input_tokens": parser_payload.get("estimated_input_tokens", 0),
            "estimated_output_tokens": parser_payload.get("estimated_output_tokens", 0),
            "estimated_cost_usd": parser_payload.get("estimated_cost_usd", 0),
        },
    }


def _fallback_response(food_text: str, message: str, error_code: str) -> dict:
    foods = [
        {
            "food_name": part,
            "quantity": "",
            "calories": 0,
            "protein": 0,
            "carbs": 0,
            "fat": 0,
            "confidence": "low",
            "verification_needed": True,
            "verification_reason": "AI parsing unavailable.",
            "source": "manual",
            "verification_status": "not_verified",
            "source_url": "",
            "notes": "AI parsing unavailable. Edit macros manually before saving.",
        }
        for part in _split_fallback_foods(food_text)
    ]
    return _response(
        foods=foods,
        source="fallback",
        cached=False,
        success=False,
        message=message,
        error_code=error_code,
    )


def _external_lookup_status_from_exception(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        return f"failed_{exc.code}"
    match = re.search(r"\bHTTP Error\s+(\d{3})\b", str(exc), flags=re.IGNORECASE)
    if match:
        return f"failed_{match.group(1)}"
    return "failed"


def _external_lookup_warning(exc: Exception) -> str:
    status = _external_lookup_status_from_exception(exc).replace("failed_", "")
    return f"external nutrition lookup failed: {status}"


def _cache_result(query: str, result: dict) -> None:
    foods = result.get("foods", [])
    first = foods[0] if foods else {}
    cache_df = _load_food_cache()
    cache_df = cache_df[cache_df["query"] != query]
    cache_entry = {
        "query": query,
        "foods_json": json.dumps(foods),
        "food_name": first.get("food_name", ""),
        "normalized_name": first.get("normalized_name", "") or _normalized_name(first.get("food_name", "")),
        "quantity": first.get("quantity", ""),
        "calories": first.get("calories", 0),
        "protein": first.get("protein", 0),
        "carbs": first.get("carbs", 0),
        "fat": first.get("fat", 0),
        "confidence": first.get("confidence", ""),
        "verification_needed": first.get("verification_needed", ""),
        "verification_reason": first.get("verification_reason", ""),
        "source": first.get("source", ""),
        "verification_status": first.get("verification_status", ""),
        "source_url": first.get("source_url", ""),
        "notes": first.get("notes", ""),
        "last_used_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_df = pd.concat([cache_df, pd.DataFrame([cache_entry])], ignore_index=True)
    _save_food_cache(cache_df)


def _cached_response(query: str) -> dict | None:
    cache_df = _load_food_cache()
    match = cache_df[cache_df["query"] == query]
    if match.empty:
        return None

    row = match.iloc[0]
    try:
        foods = json.loads(row["foods_json"]) if row["foods_json"] else []
    except json.JSONDecodeError:
        foods = []

    if not foods:
        foods = [
            {
                "food_name": row["food_name"],
                "quantity": row["quantity"],
                "calories": row["calories"],
                "protein": row["protein"],
                "carbs": row["carbs"],
                "fat": row["fat"],
                "confidence": row["confidence"] or "medium",
                "verification_needed": str(row.get("verification_needed", "")).lower() == "true",
                "verification_reason": row.get("verification_reason", ""),
                "source": row.get("source", "ai_estimate") or "ai_estimate",
                "verification_status": row.get("verification_status", "cached") or "cached",
                "source_url": row.get("source_url", ""),
                "notes": row["notes"] or "Loaded from cache.",
            }
        ]

    return _response(
        foods=foods,
        source="cache",
        cached=True,
        success=True,
        message="Loaded from local AI food cache.",
    )


def _parse_model_json(response: Any) -> dict:
    output_text = getattr(response, "output_text", "") or ""
    if not output_text:
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", "")
                if text:
                    output_text = text
                    break
            if output_text:
                break
    if not output_text:
        logger.warning("[food_ai] failed step=json_extract error_type=EmptyOpenAIOutput message=OpenAI returned no text output")
        raise ValueError("OpenAI returned no text output.")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        logger.exception(
            "[food_ai] failed step=json_parse error_type=%s message=%s raw_excerpt=%s",
            type(exc).__name__,
            exc,
            output_text[:240],
        )
        raise
    logger.info("[food_ai] json_parse_success")
    return parsed


def _response_text(response: Any) -> str:
    output_text = str(getattr(response, "output_text", "") or "")
    if output_text:
        return output_text.strip()
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = str(getattr(content, "text", "") or "")
            if text:
                return text.strip()
    return ""


def test_openai_connection() -> dict[str, Any]:
    """Run a tiny backend-only OpenAI check without exposing secrets."""
    config = openai_analyzer_config()
    result = {
        "configured": bool(config.get("openai_key_configured")),
        "client_initialized": False,
        "test_status": "error",
        "error_type": "",
        "message": "",
        "model": config.get("model", ""),
        "api_key_source": config.get("api_key_source", "unknown"),
        "model_source": config.get("model_source", "unknown"),
        "fallback_model_used": bool(config.get("fallback_model_used", False)),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if config.get("model_error"):
        result["error_type"] = "ModelConfigurationError"
        result["message"] = str(config["model_error"])
        return result
    api_key = _get_openai_api_key() if get_openai_key_status() else ""
    if not api_key:
        result["error_type"] = "MissingApiKey"
        result["message"] = "OPENAI_API_KEY is not configured. Manual food logging still works."
        return result
    started = time.perf_counter()
    try:
        client = OpenAI(api_key=api_key, timeout=10)
        result["client_initialized"] = True
        kwargs: dict[str, Any] = {
            "model": str(config.get("model") or food_analysis_model()),
            "input": "Respond with the word OK.",
            "max_output_tokens": 16,
        }
        if str(kwargs["model"]).startswith("gpt-5"):
            kwargs["reasoning"] = {"effort": str(config.get("reasoning_effort") or FOOD_ANALYSIS_REASONING_EFFORT)}
        logger.info(
            "[openai_debug] test_call_start model=%s source=%s fallback_model_used=%s",
            kwargs["model"],
            config.get("model_source"),
            config.get("fallback_model_used"),
        )
        response = client.responses.create(**kwargs)
        text = _response_text(response)
        if not text:
            raise ValueError("OpenAI returned no text output.")
        result["test_status"] = "ok"
        result["message"] = f"OpenAI test call succeeded with {kwargs['model']}."
        response_ms = round((time.perf_counter() - started) * 1000, 1)
        result["response_ms"] = response_ms
        result["latency_ms"] = response_ms
        logger.info("[openai_debug] test_call_ok model=%s response_ms=%s", kwargs["model"], response_ms)
        return result
    except AuthenticationError as exc:
        result["error_type"] = type(exc).__name__
        result["message"] = "OpenAI rejected the API key. Replace OPENAI_API_KEY and redeploy."
    except RateLimitError as exc:
        result["error_type"] = type(exc).__name__
        result["message"] = f"OpenAI quota or rate limit error: {exc}"
    except APIConnectionError as exc:
        result["error_type"] = type(exc).__name__
        result["message"] = f"Could not reach OpenAI: {exc}"
    except APIStatusError as exc:
        text = str(exc)
        if exc.status_code in {400, 404} and "model" in text.lower():
            result["error_type"] = "ModelInvalidError"
            result["message"] = f"OpenAI model {result.get('model') or 'unknown'} is invalid or unavailable: {text}"
        else:
            result["error_type"] = type(exc).__name__
            result["message"] = f"OpenAI API returned status {exc.status_code}: {exc}"
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["message"] = str(exc) or "OpenAI test call failed."
    response_ms = round((time.perf_counter() - started) * 1000, 1)
    result["response_ms"] = response_ms
    result["latency_ms"] = response_ms
    logger.warning("[openai_debug] test_call_failed model=%s error_type=%s message=%s", result.get("model"), result["error_type"], result["message"])
    return result


def _food_parse_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "foods": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "food_name": {"type": "string"},
                        "display_name": {"type": "string"},
                        "normalized_name": {"type": "string"},
                        "original_text": {"type": "string"},
                        "quantity": {"type": "number"},
                        "unit": {"type": "string"},
                        "serving_description": {"type": "string"},
                        "calories": {"type": "number"},
                        "protein": {"type": "number"},
                        "carbs": {"type": "number"},
                        "fat": {"type": "number"},
                        "fiber": {"type": ["number", "null"]},
                        "sugar": {"type": ["number", "null"]},
                        "sodium": {"type": ["number", "null"]},
                        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                        "source": {"type": "string", "enum": ["openai_estimate"]},
                        "source_id": {"type": ["string", "null"]},
                        "source_url": {"type": ["string", "null"]},
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "needs_review": {"type": "boolean"},
                        "verification_needed": {"type": "boolean"},
                        "verification_reason": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "food_name",
                        "display_name",
                        "normalized_name",
                        "original_text",
                        "quantity",
                        "unit",
                        "serving_description",
                        "calories",
                        "protein",
                        "carbs",
                        "fat",
                        "fiber",
                        "sugar",
                        "sodium",
                        "confidence",
                        "source",
                        "source_id",
                        "source_url",
                        "assumptions",
                        "needs_review",
                        "verification_needed",
                        "verification_reason",
                        "notes",
                    ],
                },
            }
        },
        "required": ["foods"],
    }


def _food_parse_system_prompt(*, includes_image: bool = False, escalation_reason: str = "") -> str:
    image_rules = (
        "\nIMAGE / LABEL RULES:\n"
        "- If an image is provided and it contains a Nutrition Facts label, prioritize exact label extraction over estimation.\n"
        "- Extract serving size, calories, protein, carbs, fat, fiber, sugar, and sodium from the visible label when readable.\n"
        "- If the front package/brand is visible, preserve the brand and product name.\n"
        "- If label values are partially unreadable, return best-estimate values, confidence='low', needs_review=true, and explain what was unreadable in assumptions.\n"
    ) if includes_image else ""
    escalation_rules = (
        "\nESCALATION PASS:\n"
        f"- This entry was escalated because: {escalation_reason}.\n"
        "- Be more conservative about serving size assumptions and ambiguity.\n"
        "- If the food remains ambiguous, keep confidence='low', needs_review=true, "
        "and put the exact assumption the user must confirm in assumptions.\n"
    ) if escalation_reason else ""
    return (
        "You are a precise nutrition analysis assistant for a personal health "
        "dashboard. Convert one messy free-form food log into structured, accurate "
        "food items.\n\n"
        "TITLE RULES — for each food set display_name:\n"
        "- Clean, readable, Title Case.\n"
        "- Remove all quantities, units, and macro notes (e.g. '4oz', '140 cal', "
        "'17p', '4g of protein').\n"
        "- Remove filler wording such as 'w', 'with a', 'of'.\n"
        "- Keep brand names when meaningful (Built, Kirkland, Fairlife).\n"
        "- Use the natural singular noun form (e.g. '2 kirkland bagels' -> "
        "'Kirkland Bagel').\n"
        "- Examples: '4oz of non fat milk w 4g of protein' -> 'Nonfat Milk'; "
        "'built puff bar 140 cal 17p' -> 'Built Puff Bar'; "
        "'chicken burrito bowl with rice beans and guac' -> 'Chicken Burrito Bowl'; "
        "'finn shake oats protein powder fairlife milk' -> 'Finn Shake'.\n"
        "Set food_name equal to display_name. Set normalized_name to a lowercase "
        "snake_case form of display_name.\n\n"
        "MACRO RULES:\n"
        "- If the user states an exact calorie or macro value, USE THAT EXACT VALUE; "
        "never override a user-provided number. Only estimate macros the user did "
        "NOT provide.\n"
        "- For every macro you estimated rather than took from the user, add a short "
        "entry to assumptions naming the field (e.g. 'Estimated carbs and fat from "
        "standard nonfat milk nutrition facts').\n"
        "- Scale all macros to the stated quantity/serving size.\n"
        "- If quantity is missing, assume a reasonable serving, record it in "
        "assumptions, and set needs_review=true.\n"
        "- Use realistic values from manufacturer labels/USDA/standard nutrition facts. "
        "Do not claim exactness unless exact label/user values are visible or provided.\n"
        "- confidence: 'high' only when the food is standard and unambiguous, the "
        "user supplied full macros, or a visible label clearly provides values; "
        "'low' for vague or uncertain brand items.\n\n"
        "Restaurant/menu items: preserve restaurant names when provided, decompose meals "
        "when useful, and estimate from typical published menu/macronutrient patterns.\n\n"
        f"{image_rules}"
        f"{escalation_rules}"
        "Always set source to 'openai_estimate' — downstream code may upgrade it "
        "after a database or USDA lookup. original_text must echo the user's wording "
        "for that item. Split combined entries when useful for review (a protein "
        "shake with banana may be split; toast with butter can stay as one item if "
        "the butter is in the serving description). Avoid medical claims. Return "
        "only valid JSON matching the schema."
    )


def _response_input(food_text: str, image_data_url: str | None = None) -> list[dict[str, Any]]:
    if not image_data_url:
        return [{"role": "user", "content": food_text}]
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": food_text or "Extract this nutrition label or food package into structured macros."},
                {"type": "input_image", "image_url": image_data_url, "detail": "high"},
            ],
        }
    ]


def _call_openai(
    food_text: str,
    api_key: str,
    *,
    image_data_url: str | None = None,
    stage: str = "default",
    escalation_reason: str = "",
) -> dict:
    """Call OpenAI with a strict JSON schema using the current Python SDK."""
    client = OpenAI(api_key=api_key)
    model_info = food_analysis_model_info(stage)
    model = str(model_info["model"])
    reasoning_effort = str(model_info["reasoning_effort"])
    started = time.perf_counter()
    input_payload = [
        {"role": "system", "content": _food_parse_system_prompt(includes_image=bool(image_data_url), escalation_reason=escalation_reason)},
        *_response_input(food_text, image_data_url=image_data_url),
    ]
    kwargs: dict[str, Any] = {
        "model": model,
        "input": input_payload,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "performance_os_food_parse",
                "schema": _food_parse_schema(),
                "strict": True,
            }
        },
        "max_output_tokens": 1800 if stage == "escalation" else 1500,
    }
    if model.startswith("gpt-5"):
        kwargs["reasoning"] = {"effort": reasoning_effort}
    logger.info(
        "[food_ai] openai_request_start stage=%s model=%s model_source=%s fallback_model_used=%s reasoning_effort=%s image_input=%s",
        stage,
        model,
        model_info["model_source"],
        model_info["fallback_model_used"],
        reasoning_effort if model.startswith("gpt-5") else "not_supported",
        bool(image_data_url),
    )
    try:
        response = client.responses.create(**kwargs)
    except Exception as exc:
        logger.exception(
            "[food_ai] failed step=openai_request error_type=%s message=%s model=%s fallback_model_used=%s latency_ms=%s",
            type(exc).__name__,
            exc,
            model,
            model_info["fallback_model_used"],
            round((time.perf_counter() - started) * 1000, 1),
        )
        raise
    logger.info(
        "[food_ai] openai_request_success stage=%s model=%s fallback_model_used=%s latency_ms=%s",
        stage,
        model,
        model_info["fallback_model_used"],
        round((time.perf_counter() - started) * 1000, 1),
    )
    parsed = _parse_model_json(response)
    parsed["_parser_call"] = _call_cost_metadata(
        model=model,
        input_payload=input_payload,
        output_payload=parsed,
        response=response,
        stage=stage,
        latency_ms=(time.perf_counter() - started) * 1000,
    )
    return parsed


def _food_to_api_item(food: dict) -> dict:
    assumptions = list(food.get("assumptions") or [])
    if food.get("verification_reason") and food.get("verification_reason") not in assumptions:
        assumptions.append(str(food.get("verification_reason")))
    return {
        "name": food.get("food_name", ""),
        "display_name": food.get("display_name") or food.get("food_name", ""),
        "normalized_name": food.get("normalized_name") or _normalized_name(food.get("food_name", "")),
        "original_text": food.get("original_text") or food.get("food_name", ""),
        "quantity": food.get("quantity_value"),
        "unit": food.get("unit") or "",
        "serving_description": food.get("serving_description") or food.get("quantity") or "",
        "calories": food.get("calories", 0),
        "protein_g": food.get("protein", 0),
        "carbs_g": food.get("carbs", 0),
        "fat_g": food.get("fat", 0),
        "fiber_g": food.get("fiber"),
        "sugar_g": food.get("sugar"),
        "sodium_mg": food.get("sodium"),
        "confidence": food.get("confidence", "medium"),
        "source": food.get("source") or "openai_estimate",
        "source_id": food.get("source_id") or None,
        "source_url": food.get("source_url") or None,
        "assumptions": assumptions,
        "needs_review": bool(food.get("needs_review", True)),
        "needs_confirmation": bool(food.get("needs_confirmation", food.get("needs_review", True))),
        "confidence_score": food.get("confidence_score", _confidence_score(food.get("confidence", "medium"))),
    }


def _api_totals(items: list[dict]) -> dict:
    totals = {
        "calories": round(sum(float(item.get("calories", 0) or 0) for item in items), 1),
        "protein_g": round(sum(float(item.get("protein_g", 0) or 0) for item in items), 1),
        "carbs_g": round(sum(float(item.get("carbs_g", 0) or 0) for item in items), 1),
        "fat_g": round(sum(float(item.get("fat_g", 0) or 0) for item in items), 1),
    }
    for key in ["fiber_g", "sugar_g", "sodium_mg"]:
        values = [item.get(key) for item in items if item.get(key) is not None]
        totals[key] = round(sum(float(value or 0) for value in values), 1) if values else None
    return totals


def _contains_ambiguous_food_term(query: str) -> bool:
    text = _normalize_query(query)
    return any(re.search(rf"\b{re.escape(term)}\b", text) for term in AMBIGUOUS_FOOD_TERMS)


def _contains_branded_food_hint(query: str) -> bool:
    text = _normalize_query(query)
    if any(hint in text for hint in BRANDED_FOOD_HINTS):
        return True
    tokens = [token for token in re.split(r"\s+", str(query).strip()) if token]
    return any(token.isupper() and len(token) > 2 and token.lower() not in {"kcal", "cal", "oz", "tbsp", "tsp"} for token in tokens)


def _serving_size_unclear(food: dict[str, Any]) -> bool:
    quantity_value = _optional_float(food.get("quantity_value") if "quantity_value" in food else food.get("quantity"))
    unit = str(food.get("unit") or "").strip().lower()
    serving = str(food.get("serving_description") or "").strip().lower()
    assumptions = " ".join(str(item).lower() for item in food.get("assumptions", []) if item)
    if quantity_value is None or quantity_value <= 0:
        return True
    if not unit and not serving:
        return True
    return bool(re.search(r"\b(assum|unclear|unknown|typical|standard|estimated serving|reasonable serving)\b", serving + " " + assumptions))


def _macro_uncertainty_wide(food: dict[str, Any]) -> bool:
    assumptions = " ".join(str(item).lower() for item in food.get("assumptions", []) if item)
    notes = str(food.get("notes") or "").lower()
    return bool(re.search(r"\b(uncertain|wide|rough|guess|varies|depends|unknown)\b", assumptions + " " + notes))


def _escalation_reason(result: dict[str, Any], query: str) -> str:
    foods = result.get("foods", [])
    if not isinstance(foods, list) or not foods:
        return "No structured foods returned by default parser"
    if _looks_like_multi_food_query(query):
        return "Multiple foods are combined in one phrase"
    if _contains_ambiguous_food_term(query):
        return "Ambiguous food or serving size"
    if _contains_branded_food_hint(query) and all(str(food.get("source") or "").strip() == "openai_estimate" for food in foods):
        return "Branded food was not found in saved foods or database"
    for food in foods:
        score = _confidence_score(str(food.get("confidence") or "medium"), food.get("confidence_score"))
        if score < LOW_CONFIDENCE_THRESHOLD:
            return f"Parser confidence below {LOW_CONFIDENCE_THRESHOLD}"
        if _serving_size_unclear(food):
            return "Serving size is unclear"
        if _macro_uncertainty_wide(food):
            return "Macro estimate has wide uncertainty"
    return ""


def _synthetic_call_metadata(stage: str, food_text: str, parsed: dict[str, Any]) -> dict[str, Any]:
    model_info = food_analysis_model_info(stage)
    model = str(model_info.get("model") or food_analysis_model())
    return _call_cost_metadata(
        model=model,
        input_payload=food_text,
        output_payload=parsed,
        response=None,
        stage=stage,
        latency_ms=0,
    )


def analyze_food_text(food_text: str, *, image_data_url: str | None = None, force_openai: bool = False) -> dict:
    """Return the richer Food tab analyze response shape."""
    parsed = parse_food_text(food_text, image_data_url=image_data_url, force_openai=force_openai)
    warnings = list(parsed.get("warnings") or []) if isinstance(parsed.get("warnings"), list) else []
    external_statuses = list(parsed.get("external_lookup_statuses") or []) if isinstance(parsed.get("external_lookup_statuses"), list) else []
    api_items = []
    for food in parsed.get("foods", []):
        normalized = _normalize_food(food, food.get("food_name", ""))
        usda_match = None
        if normalized.get("source") in {"saved_shortcut", "existing_database", "verified_cache"}:
            external_statuses.append("skipped")
            normalized["source"] = "existing_database"
            normalized["verification_needed"] = False
            normalized["needs_review"] = False
            normalized["needs_confirmation"] = False
        else:
            try:
                logger.info("[food_ai] external_lookup_started url_or_service=usda_fdc query=%s", normalized["food_name"])
                usda_match = search_food_macros(normalized["food_name"])
                external_statuses.append("ok" if usda_match else "skipped")
            except Exception as exc:
                status = _external_lookup_status_from_exception(exc)
                external_statuses.append(status)
                warnings.append(_external_lookup_warning(exc))
                logger.warning(
                    "[food_ai] external_lookup_failed status=%s url_or_service=usda_fdc error_type=%s message=%s openai_called=true",
                    status.replace("failed_", ""),
                    type(exc).__name__,
                    exc,
                )
        if usda_match:
            macros = usda_match.get("macros", {})
            for source_key, target_key in [
                ("fiber_g", "fiber"),
                ("sugar_g", "sugar"),
                ("sodium_mg", "sodium"),
            ]:
                if normalized.get(target_key) is None and macros.get(source_key) is not None:
                    normalized[target_key] = macros[source_key]
            normalized["source"] = "usda_fdc"
            normalized["source_id"] = usda_match.get("source_id", "")
            normalized["source_url"] = usda_match.get("source_url", "")
            normalized["serving_description"] = normalized["serving_description"] or usda_match.get("serving_description", "")
            normalized["assumptions"].append("Matched USDA FoodData Central for source context; review serving-size scaling before saving.")
        elif normalized.get("source") in {"verified_online", "web_source"}:
            normalized["source"] = "web_source"
        elif normalized.get("source") in {"saved_shortcut", "verified_cache", "existing_database"}:
            normalized["source"] = "existing_database"
        else:
            normalized["source"] = "openai_estimate"
            if normalized["confidence"] != "high":
                warnings.append(f"Review {normalized['food_name']}: no confident nutrition database match was found.")
        api_items.append(_food_to_api_item(normalized))

    totals = _api_totals(api_items)
    unique_statuses = [status for status in dict.fromkeys(external_statuses) if status]
    external_lookup_status = (
        "ok"
        if "ok" in unique_statuses and not any(status.startswith("failed") for status in unique_statuses)
        else next((status for status in unique_statuses if status.startswith("failed")), "skipped")
    )
    return {
        "items": api_items,
        "foods": api_items,
        "totals": totals,
        "total": totals,
        "warnings": warnings,
        "parser_source": parsed.get("source", ""),
        "external_lookup_status": external_lookup_status,
        "external_lookup_statuses": unique_statuses,
        "source": parsed.get("source", ""),
        "cached": bool(parsed.get("cached", False)),
        "success": bool(parsed.get("success")),
        "message": parsed.get("message", ""),
        "error_code": parsed.get("error_code"),
        "parser": parsed.get("parser") if isinstance(parsed.get("parser"), dict) else _non_openai_parser_summary(str(parsed.get("source") or "")),
        "debug": {
            **(parsed.get("debug", {}) if isinstance(parsed.get("debug"), dict) else {}),
            "parser_source": parsed.get("source", ""),
            "parser_cached": bool(parsed.get("cached", False)),
            "external_lookup_status": external_lookup_status,
            "external_lookup_statuses": unique_statuses,
            "parser": parsed.get("parser") if isinstance(parsed.get("parser"), dict) else {},
        },
    }


def parse_food_text(food_text: str, *, image_data_url: str | None = None, force_openai: bool = False) -> dict:
    """Parse natural-language food text into structured editable food rows."""
    cleaned_text = str(food_text or "").strip()
    if not cleaned_text and not image_data_url:
        return _response(
            foods=[],
            source="validation",
            cached=False,
            success=False,
            message="Food text is required.",
            error_code="missing_text",
        )

    query = _normalize_query(cleaned_text)
    if not image_data_url and not force_openai:
        local_match = _local_saved_food_response(cleaned_text)
        if local_match:
            return local_match

        cached = _cached_response(query)
        if cached and (not _escalation_reason(cached, cleaned_text) or not _get_openai_api_key()):
            refreshed = _verify_uncertain_foods(cached)
            if refreshed != cached:
                _cache_result(query, refreshed)
            return refreshed

    api_key = _get_openai_api_key() if get_openai_key_status() else ""
    if not api_key:
        return _fallback_response(
            cleaned_text,
            "AI food parsing is not configured yet. You can still log foods manually.",
            "openai_not_configured",
        )

    try:
        logger.info("[food_ai] pre_openai_step=openai_primary")
        parsed = _call_openai(cleaned_text, api_key, image_data_url=image_data_url, stage="default")
        parser_calls = [parsed.pop("_parser_call", None) or _synthetic_call_metadata("default", cleaned_text, parsed)]
        foods = parsed.get("foods", [])
        if not isinstance(foods, list) or not foods:
            raise ValueError("Model response did not include a non-empty foods array.")

        result = _response(
            foods=foods,
            source="openai",
            cached=False,
            success=True,
            message=f"Parsed with {food_analysis_model()}. Review before saving.",
            parser=_parser_summary(parser_calls, escalated=False),
        )
        escalation_reason = "" if image_data_url else _escalation_reason(result, cleaned_text)
        if escalation_reason:
            logger.info("[food_ai] escalation_triggered reason=%s", escalation_reason)
            escalated = _call_openai(
                cleaned_text,
                api_key,
                image_data_url=image_data_url,
                stage="escalation",
                escalation_reason=escalation_reason,
            )
            parser_calls.append(escalated.pop("_parser_call", None) or _synthetic_call_metadata("escalation", cleaned_text, escalated))
            escalated_foods = escalated.get("foods", [])
            if isinstance(escalated_foods, list) and escalated_foods:
                result = _response(
                    foods=escalated_foods,
                    source="openai",
                    cached=False,
                    success=True,
                    message=f"Parsed with {food_analysis_escalation_model()} after low-confidence escalation. Review before saving.",
                    parser=_parser_summary(parser_calls, escalated=True, escalation_reason=escalation_reason),
                )
            else:
                result["parser"] = _parser_summary(parser_calls, escalated=True, escalation_reason=escalation_reason, final_model=food_analysis_model())
                result["debug"]["parser"] = result["parser"]
        result = _verify_uncertain_foods(result)
        if not image_data_url and not force_openai:
            _cache_result(query, result)
        return result
    except AuthenticationError as exc:
        logger.warning("[food_ai] failed step=openai_auth error_type=%s message=%s", type(exc).__name__, exc)
        return _fallback_response(cleaned_text, "OpenAI API key is invalid.", "invalid_api_key")
    except RateLimitError as exc:
        logger.warning("[food_ai] failed step=openai_rate_limit error_type=%s message=%s", type(exc).__name__, exc)
        return _fallback_response(
            cleaned_text,
            "OpenAI quota or rate limit reached. Check billing/quota and try again.",
            "quota_or_rate_limit",
        )
    except APIConnectionError as exc:
        logger.warning("[food_ai] failed step=openai_network error_type=%s message=%s", type(exc).__name__, exc)
        return _fallback_response(
            cleaned_text,
            "Could not reach OpenAI. Check network connectivity and try again.",
            "network_error",
        )
    except APIStatusError as exc:
        logger.warning("[food_ai] failed step=openai_status error_type=%s status_code=%s message=%s", type(exc).__name__, exc.status_code, exc)
        if exc.status_code == 401:
            return _fallback_response(cleaned_text, "OpenAI API key is invalid.", "invalid_api_key")
        if exc.status_code == 429:
            return _fallback_response(
                cleaned_text,
                "OpenAI quota or billing limit reached. Check billing/quota and try again.",
                "quota_or_rate_limit",
            )
        return _fallback_response(
            cleaned_text,
            f"OpenAI request failed with status {exc.status_code}.",
            "api_error",
        )
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("[food_ai] failed step=json_parse error_type=%s message=%s", type(exc).__name__, exc)
        return _fallback_response(
            cleaned_text,
            f"OpenAI returned a malformed response: {exc}",
            "malformed_response",
        )


def image_data_url(image_bytes: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    safe_mime = mime_type if mime_type in {"image/png", "image/jpeg", "image/webp"} else "image/jpeg"
    return f"data:{safe_mime};base64,{encoded}"


def analyze_food_label_image(image_bytes: bytes, mime_type: str, *, context: str = "") -> dict:
    """Analyze a nutrition label/package image with the same strict food schema."""
    digest = hashlib.sha256(image_bytes).hexdigest()[:12]
    logger.info(
        "[food_analyzer] label_image_received bytes=%s mime_type=%s sha256_prefix=%s",
        len(image_bytes),
        mime_type,
        digest,
    )
    prompt = (
        "Extract the visible packaged food or nutrition label. Prefer exact label values "
        "over estimates. If multiple serving columns are visible, use the primary per-serving "
        "column and note any ambiguity."
    )
    if context:
        prompt = f"{prompt}\nUser context: {context}"
    return analyze_food_text(prompt, image_data_url=image_data_url(image_bytes, mime_type))


def _macro_conflict(ai_food: dict, verified_macros: dict) -> bool:
    for macro in ["calories", "protein", "carbs", "fat"]:
        ai_value = float(ai_food.get(macro, 0) or 0)
        verified_value = float(verified_macros.get(macro, 0) or 0)
        if max(ai_value, verified_value) <= 0:
            continue
        if abs(ai_value - verified_value) / max(ai_value, verified_value) > 0.35:
            return True
    return False


def _verify_uncertain_foods(result: dict) -> dict:
    """Verify at most five low-confidence/brand-like foods."""
    foods = result.get("foods", [])
    warnings = list(result.get("warnings") or []) if isinstance(result.get("warnings"), list) else []
    external_statuses = list(result.get("external_lookup_statuses") or []) if isinstance(result.get("external_lookup_statuses"), list) else []
    verified_count = 0
    updated_foods = []
    for food in foods:
        normalized = _normalize_food(food, food.get("food_name", ""))
        needs_verification, reason = should_verify_food(
            normalized["food_name"],
            normalized.get("confidence", "medium"),
            bool(normalized.get("verification_needed", False)),
        )
        normalized["verification_needed"] = needs_verification
        normalized["verification_reason"] = normalized.get("verification_reason") or reason
        if needs_verification and verified_count < 5:
            verified_count += 1
            try:
                logger.info("[food_ai] external_lookup_started url_or_service=online_verification query=%s", normalized["food_name"])
                verification = verify_food_online(normalized["food_name"], normalized.get("quantity"))
                external_statuses.append("ok" if verification.get("verified") else "skipped")
            except Exception as exc:
                status = _external_lookup_status_from_exception(exc)
                external_statuses.append(status)
                warnings.append(_external_lookup_warning(exc))
                logger.warning(
                    "[food_ai] external_lookup_failed status=%s url_or_service=online_verification error_type=%s message=%s openai_called=true",
                    status.replace("failed_", ""),
                    type(exc).__name__,
                    exc,
                )
                verification = {
                    "verified": False,
                    "macros": {},
                    "source": status,
                    "confidence": "low",
                    "message": _external_lookup_warning(exc),
                }
            if verification.get("verified") and verification.get("macros"):
                conflict = _macro_conflict(normalized, verification["macros"])
                macros = verification["macros"]
                for macro in ["calories", "protein", "carbs", "fat"]:
                    normalized[macro] = _to_float(macros.get(macro))
                normalized["confidence"] = verification.get("confidence", "high")
                normalized["source"] = "verified_online"
                normalized["verification_status"] = "verified_conflict_review" if conflict else "verified"
                normalized["source_url"] = verification.get("source_url", "")
                normalized["notes"] = (
                    f"{verification.get('message', 'Verified online')} "
                    + ("AI estimate differed materially; please review. " if conflict else "")
                    + str(normalized.get("notes", ""))
                ).strip()
            else:
                normalized["source"] = "ai_estimate"
                normalized["verification_status"] = "verification_unavailable"
                normalized["confidence"] = "low"
                normalized["notes"] = f"{verification.get('message', 'Online verification unavailable.')} {normalized.get('notes', '')}".strip()
        elif needs_verification:
            normalized["verification_status"] = "verification_skipped_limit"
            normalized["notes"] = f"Verification skipped because this parse already checked 5 items. {normalized.get('notes', '')}".strip()
        updated_foods.append(normalized)

    result["foods"] = updated_foods
    result["total"] = _total(updated_foods)
    unique_statuses = [status for status in dict.fromkeys(external_statuses) if status]
    external_lookup_status = (
        "ok"
        if "ok" in unique_statuses and not any(status.startswith("failed") for status in unique_statuses)
        else next((status for status in unique_statuses if status.startswith("failed")), "skipped")
    )
    result["warnings"] = warnings
    result["external_lookup_status"] = external_lookup_status
    result["external_lookup_statuses"] = unique_statuses
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    result["debug"] = {
        **debug,
        "external_lookup_status": external_lookup_status,
        "external_lookup_statuses": unique_statuses,
    }
    if any(food.get("source") == "verified_online" for food in updated_foods):
        result["message"] = "Parsed with AI and verified uncertain foods where reliable online sources were available."
    elif any(food.get("verification_status") == "verification_unavailable" for food in updated_foods):
        result["message"] = "Parsed with AI. Some foods need review because online verification was unavailable."
    return result
