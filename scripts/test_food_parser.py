"""Smoke checks for the Performance OS food parser API.

This script avoids live OpenAI calls by patching the backend route parser with
a deterministic response. It verifies request validation and response schema.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from backend.main import app
import backend.routes.nutrition as nutrition_routes


def _fake_parse_food_text(text: str) -> dict:
    return {
        "foods": [
            {
                "food_name": "Eggs",
                "quantity": "3 large",
                "calories": 210,
                "protein": 18,
                "carbs": 1,
                "fat": 15,
                "confidence": "medium",
                "notes": "Estimate based on large eggs.",
            },
            {
                "food_name": "Banana",
                "quantity": "1 medium",
                "calories": 105,
                "protein": 1,
                "carbs": 27,
                "fat": 0,
                "confidence": "medium",
                "notes": "Estimate based on a medium banana.",
            },
        ],
        "total": {"calories": 315, "protein": 19, "carbs": 28, "fat": 15},
        "source": "test",
        "cached": False,
        "success": True,
        "error_code": None,
        "message": "Parsed with test fixture.",
        "debug": {
            "backend_endpoint_reached": True,
            "openai_key_configured": False,
            "model": "test-model",
            "parsing_status": "success",
        },
    }


def main() -> int:
    client = TestClient(app)

    missing = client.post("/api/nutrition/ai/parse", json={})
    assert missing.status_code == 422, f"expected 422 for missing text, got {missing.status_code}"

    blank = client.post("/api/nutrition/ai/parse", json={"text": ""})
    assert blank.status_code == 422, f"expected 422 for blank text, got {blank.status_code}"

    original_parser = nutrition_routes.parse_food_text
    nutrition_routes.parse_food_text = _fake_parse_food_text
    try:
        response = client.post(
            "/api/nutrition/ai/parse",
            json={"text": "3 eggs, a banana, and a protein shake"},
        )
    finally:
        nutrition_routes.parse_food_text = original_parser

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert isinstance(payload["foods"], list) and payload["foods"]
    assert {"food_name", "quantity", "calories", "protein", "carbs", "fat", "confidence", "notes"} <= set(payload["foods"][0])
    assert {"calories", "protein", "carbs", "fat"} <= set(payload["total"])
    assert payload["debug"]["backend_endpoint_reached"] is True

    print("Food parser smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
