"""OpenAI-assisted food parsing for Performance OS.

This module only parses natural-language food text into editable structured
macro estimates. It does not save nutrition logs; the UI/backend confirmation
flow handles persistence after the user reviews the parsed rows.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError

from src.ai.nutrition_verifier import should_verify_food, verify_food_online
from src.integrations.usda_client import search_food_macros
from src.paths import PROJECT_ROOT, processed_data_path


load_dotenv(PROJECT_ROOT / ".env", override=False)

FOOD_CACHE_PATH = processed_data_path("ai_food_cache.csv")
FOOD_CACHE_COLUMNS = [
    "query",
    "foods_json",
    "food_name",
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
]

# Low-cost model for structured food parsing.
OPENAI_MODEL = "gpt-4.1-nano"
CONFIDENCE_VALUES = {"low", "medium", "high"}


def _normalize_query(food_text: str) -> str:
    """Normalize cache keys so repeated foods avoid API calls."""
    return " ".join(str(food_text).strip().lower().split())


def _empty_cache() -> pd.DataFrame:
    return pd.DataFrame(columns=FOOD_CACHE_COLUMNS)


def _load_food_cache() -> pd.DataFrame:
    if not FOOD_CACHE_PATH.exists():
        return _empty_cache()

    cache_df = pd.read_csv(FOOD_CACHE_PATH)
    for column in FOOD_CACHE_COLUMNS:
        if column not in cache_df.columns:
            cache_df[column] = ""
    cache_df = cache_df[FOOD_CACHE_COLUMNS]
    for column in ["calories", "protein", "carbs", "fat"]:
        cache_df[column] = pd.to_numeric(cache_df[column], errors="coerce").fillna(0)
    for column in ["query", "foods_json", "food_name", "quantity", "confidence", "verification_needed", "verification_reason", "source", "verification_status", "source_url", "notes"]:
        cache_df[column] = cache_df[column].fillna("").astype(str)
    return cache_df


def _save_food_cache(cache_df: pd.DataFrame) -> None:
    FOOD_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache_df.reindex(columns=FOOD_CACHE_COLUMNS).to_csv(FOOD_CACHE_PATH, index=False)


def _read_settings_key() -> str:
    """Read the saved OpenAI key from local settings as a fallback."""
    try:
        from src.config import load_settings

        return str(load_settings().get("integrations", {}).get("openai_api_key", "")).strip()
    except Exception:
        return ""


def get_openai_key_status() -> bool:
    """Return whether an OpenAI key is configured without exposing it."""
    return bool(os.getenv("OPENAI_API_KEY", "").strip() or _read_settings_key())


def _get_openai_api_key() -> str:
    """Read OpenAI key from environment first, then local settings fallback."""
    return os.getenv("OPENAI_API_KEY", "").strip() or _read_settings_key()


def _to_float(value: Any) -> float:
    try:
        return round(max(float(value or 0), 0.0), 1)
    except (TypeError, ValueError):
        return 0.0


def _optional_float(value: Any) -> float | None:
    try:
        if value in [None, ""]:
            return None
        return round(max(float(value), 0.0), 1)
    except (TypeError, ValueError):
        return None


def _split_fallback_foods(food_text: str) -> list[str]:
    parts = [
        part.strip()
        for part in re.split(r",|\band\b", str(food_text).strip(), flags=re.IGNORECASE)
        if part.strip()
    ]
    return parts or [str(food_text).strip()]


def _local_saved_food_response(query: str) -> dict | None:
    """Check reusable local foods before calling OpenAI."""
    normalized_query = _normalize_query(query)
    try:
        from src.ai.nutrition_verifier import load_verified_food_cache
        from src.nutrition import load_food_shortcuts, load_frequent_foods

        shortcuts = load_food_shortcuts()
        for _, row in shortcuts.iterrows():
            name = _normalize_query(row.get("shortcut_name", ""))
            if name and (name in normalized_query or normalized_query in name):
                food = {
                    "food_name": row.get("shortcut_name", ""),
                    "quantity": "",
                    "calories": row.get("calories", 0),
                    "protein": row.get("protein", 0),
                    "carbs": row.get("carbs", 0),
                    "fat": row.get("fat", 0),
                    "confidence": "high",
                    "verification_needed": False,
                    "verification_reason": "Matched saved shortcut before OpenAI.",
                    "source": "saved_shortcut",
                    "verification_status": "cached",
                    "source_url": "",
                    "notes": "Loaded from saved food shortcut.",
                }
                return _response(foods=[food], source="saved_shortcut", cached=True, success=True, message="Loaded from saved shortcut.")

        frequent = load_frequent_foods()
        for _, row in frequent.iterrows():
            name = _normalize_query(row.get("food_name", ""))
            if name and (name in normalized_query or normalized_query in name):
                food = {
                    "food_name": row.get("food_name", ""),
                    "quantity": "",
                    "calories": row.get("calories", 0),
                    "protein": row.get("protein", 0),
                    "carbs": row.get("carbs", 0),
                    "fat": row.get("fat", 0),
                    "confidence": "high",
                    "verification_needed": False,
                    "verification_reason": "Matched frequent food before OpenAI.",
                    "source": "saved_shortcut",
                    "verification_status": "cached",
                    "source_url": "",
                    "notes": "Loaded from frequent food.",
                }
                return _response(foods=[food], source="saved_shortcut", cached=True, success=True, message="Loaded from frequent food.")

        verified = load_verified_food_cache()
        for _, row in verified.iterrows():
            name = _normalize_query(row.get("food_name", ""))
            if name and (name in normalized_query or normalized_query in name):
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
                return _response(foods=[food], source="verified_cache", cached=True, success=True, message="Loaded from verified food cache.")
    except Exception:
        return None
    return None


def _normalize_food(food: dict[str, Any], fallback_name: str) -> dict:
    """Validate and normalize one parsed food row."""
    notes = []
    food_name = str(food.get("food_name") or fallback_name).strip() or fallback_name
    quantity_raw = food.get("quantity")
    quantity = str(quantity_raw or "").strip()
    confidence = str(food.get("confidence") or "medium").strip().lower()
    if confidence not in CONFIDENCE_VALUES:
        confidence = "medium"
        notes.append("Confidence was normalized to medium.")
    verification_needed = bool(food.get("verification_needed", False))
    heuristic_needed, heuristic_reason = should_verify_food(food_name, confidence, verification_needed)

    normalized = {
        "food_name": food_name,
        "original_text": str(food.get("original_text") or food_name).strip(),
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
        "needs_review": bool(food.get("needs_review", heuristic_needed or confidence != "high")),
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
) -> dict:
    normalized_foods = [_normalize_food(food, food.get("food_name", "")) for food in foods or []]
    return {
        "foods": normalized_foods,
        "total": _total(normalized_foods),
        "source": source,
        "cached": cached,
        "success": success,
        "error_code": error_code,
        "message": message,
        "debug": {
            "backend_endpoint_reached": True,
            "openai_key_configured": get_openai_key_status(),
            "model": OPENAI_MODEL,
            "parsing_status": "success" if success else "failure",
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


def _cache_result(query: str, result: dict) -> None:
    foods = result.get("foods", [])
    first = foods[0] if foods else {}
    cache_df = _load_food_cache()
    cache_df = cache_df[cache_df["query"] != query]
    cache_entry = {
        "query": query,
        "foods_json": json.dumps(foods),
        "food_name": first.get("food_name", ""),
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
        raise ValueError("OpenAI returned no text output.")
    return json.loads(output_text)


def _call_openai(food_text: str, api_key: str) -> dict:
    """Call OpenAI with a strict JSON schema using the current Python SDK."""
    client = OpenAI(api_key=api_key)
    schema = {
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
    response = client.responses.create(
        model=OPENAI_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You are a nutrition parsing assistant for a personal health dashboard. "
                    "Convert messy free-form food logs into structured food items. Extract "
                    "individual foods, quantities, units, preparation details, and likely serving "
                    "sizes. If quantity is missing, estimate a reasonable default serving but mark "
                    "it as an assumption and set needs_review=true. Do not claim exactness. Prefer "
                    "conservative estimates. Return only valid JSON matching the schema. Use "
                    "OpenAI estimates only here; downstream code may replace sources with USDA. "
                    "Avoid medical claims. Split combined entries where it is useful for review, "
                    "for example toast with butter can be one item if the butter amount is included "
                    "in the serving description, while a protein shake with banana may be split."
                ),
            },
            {"role": "user", "content": food_text},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "performance_os_food_parse",
                "schema": schema,
                "strict": True,
            }
        },
        max_output_tokens=800,
    )
    return _parse_model_json(response)


def _food_to_api_item(food: dict) -> dict:
    assumptions = list(food.get("assumptions") or [])
    if food.get("verification_reason") and food.get("verification_reason") not in assumptions:
        assumptions.append(str(food.get("verification_reason")))
    return {
        "name": food.get("food_name", ""),
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


def analyze_food_text(food_text: str) -> dict:
    """Return the richer Food tab analyze response shape."""
    parsed = parse_food_text(food_text)
    warnings = []
    api_items = []
    for food in parsed.get("foods", []):
        normalized = _normalize_food(food, food.get("food_name", ""))
        usda_match = search_food_macros(normalized["food_name"])
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
        elif normalized.get("source") in {"saved_shortcut", "verified_cache"}:
            normalized["source"] = "existing_database"
        else:
            normalized["source"] = "openai_estimate"
            if normalized["confidence"] != "high":
                warnings.append(f"Review {normalized['food_name']}: no confident nutrition database match was found.")
        api_items.append(_food_to_api_item(normalized))

    return {
        "items": api_items,
        "totals": _api_totals(api_items),
        "warnings": warnings,
        "success": bool(parsed.get("success")),
        "message": parsed.get("message", ""),
        "error_code": parsed.get("error_code"),
        "debug": parsed.get("debug", {}),
    }


def parse_food_text(food_text: str) -> dict:
    """Parse natural-language food text into structured editable food rows."""
    cleaned_text = str(food_text or "").strip()
    if not cleaned_text:
        return _response(
            foods=[],
            source="validation",
            cached=False,
            success=False,
            message="Food text is required.",
            error_code="missing_text",
        )

    query = _normalize_query(cleaned_text)
    local_match = _local_saved_food_response(cleaned_text)
    if local_match:
        return local_match

    cached = _cached_response(query)
    if cached:
        refreshed = _verify_uncertain_foods(cached)
        if refreshed != cached:
            _cache_result(query, refreshed)
        return refreshed

    api_key = _get_openai_api_key()
    if not api_key:
        return _fallback_response(
            cleaned_text,
            "OpenAI API key is not configured. Add OPENAI_API_KEY to .env or local settings.",
            "missing_api_key",
        )

    try:
        parsed = _call_openai(cleaned_text, api_key)
        foods = parsed.get("foods", [])
        if not isinstance(foods, list) or not foods:
            raise ValueError("Model response did not include a non-empty foods array.")

        result = _response(
            foods=foods,
            source="openai",
            cached=False,
            success=True,
            message=f"Parsed with {OPENAI_MODEL}. Review before saving.",
        )
        result = _verify_uncertain_foods(result)
        _cache_result(query, result)
        return result
    except AuthenticationError:
        return _fallback_response(cleaned_text, "OpenAI API key is invalid.", "invalid_api_key")
    except RateLimitError:
        return _fallback_response(
            cleaned_text,
            "OpenAI quota or rate limit reached. Check billing/quota and try again.",
            "quota_or_rate_limit",
        )
    except APIConnectionError:
        return _fallback_response(
            cleaned_text,
            "Could not reach OpenAI. Check network connectivity and try again.",
            "network_error",
        )
    except APIStatusError as exc:
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
        return _fallback_response(
            cleaned_text,
            f"OpenAI returned a malformed response: {exc}",
            "malformed_response",
        )


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
            verification = verify_food_online(normalized["food_name"], normalized.get("quantity"))
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
    if any(food.get("source") == "verified_online" for food in updated_foods):
        result["message"] = "Parsed with AI and verified uncertain foods where reliable online sources were available."
    elif any(food.get("verification_status") == "verification_unavailable" for food in updated_foods):
        result["message"] = "Parsed with AI. Some foods need review because online verification was unavailable."
    return result
