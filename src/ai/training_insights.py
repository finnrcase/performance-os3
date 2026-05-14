"""OpenAI-assisted training insights grounded in supplied analytics only."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)

OPENAI_MODEL = "gpt-4.1-nano"


def _read_settings_key() -> str:
    try:
        from src.config import load_settings

        return str(load_settings().get("integrations", {}).get("openai_api_key", "")).strip()
    except Exception:
        return ""


def _get_openai_api_key() -> str:
    return os.getenv("OPENAI_API_KEY", "").strip() or _read_settings_key()


def _fallback(message: str, error_code: str = "unavailable") -> dict:
    return {
        "success": False,
        "message": message,
        "error_code": error_code,
        "model": OPENAI_MODEL,
        "top_insights": [],
        "possible_issues": [],
        "recommended_adjustments": [],
        "confidence_level": "low",
        "evidence": ["AI analysis was not completed."],
    }


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


def _normalize_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:6]


def _normalize_response(parsed: dict) -> dict:
    confidence = str(parsed.get("confidence_level") or "low").lower()
    if confidence not in {"low", "medium", "high"}:
        confidence = "low"
    return {
        "success": True,
        "message": "Training insights generated from supplied local summaries.",
        "error_code": None,
        "model": OPENAI_MODEL,
        "top_insights": _normalize_list(parsed.get("top_insights"))[:3],
        "possible_issues": _normalize_list(parsed.get("possible_issues")),
        "recommended_adjustments": _normalize_list(parsed.get("recommended_adjustments")),
        "confidence_level": confidence,
        "evidence": _normalize_list(parsed.get("evidence")),
    }


def generate_training_insights(
    *,
    recent_training_summary: dict,
    strength_trends: dict,
    muscle_balance: dict,
    recovery_score=None,
    nutrition_status: dict | None = None,
) -> dict:
    """Generate conservative AI insights from supplied analytics summaries."""
    if not recent_training_summary.get("workout_count") and not strength_trends.get("exercise"):
        return _fallback("Not enough training data to analyze yet.", "insufficient_data")

    api_key = _get_openai_api_key()
    if not api_key:
        return _fallback("OpenAI API key is not configured.", "missing_api_key")

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "top_insights": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "possible_issues": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "recommended_adjustments": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
            "confidence_level": {"type": "string", "enum": ["low", "medium", "high"]},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        },
        "required": [
            "top_insights",
            "possible_issues",
            "recommended_adjustments",
            "confidence_level",
            "evidence",
        ],
    }
    payload = {
        "recent_training_summary": recent_training_summary,
        "strength_trends": strength_trends,
        "muscle_balance": muscle_balance,
        "recovery_score": recovery_score,
        "nutrition_status": nutrition_status or {},
    }

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a conservative fitness training analyst. Only comment on the supplied JSON. "
                        "Do not invent exercises, PRs, diagnoses, injuries, missing data, or percentages that were "
                        "not supplied. Do not mention aesthetics. If data is limited, say confidence is low. Keep "
                        "recommendations practical, performance-oriented, conservative, and non-medical."
                    ),
                },
                {"role": "user", "content": json.dumps(payload)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "performance_os_training_insights",
                    "schema": schema,
                    "strict": True,
                }
            },
            max_output_tokens=900,
        )
        return _normalize_response(_parse_model_json(response))
    except AuthenticationError:
        return _fallback("OpenAI API key is invalid.", "invalid_api_key")
    except RateLimitError:
        return _fallback("OpenAI quota or rate limit reached.", "quota_or_rate_limit")
    except APIConnectionError:
        return _fallback("Could not reach OpenAI.", "network_error")
    except APIStatusError as exc:
        return _fallback(f"OpenAI request failed with status {exc.status_code}.", "api_error")
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return _fallback(f"OpenAI returned a malformed response: {exc}", "malformed_response")
