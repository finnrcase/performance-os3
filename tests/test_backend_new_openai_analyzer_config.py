from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_new.main import app


client = TestClient(app)


def test_openai_config_agrees_across_settings_status_and_analyzer_when_configured():
    config = {
        "openai_key_configured": True,
        "api_key_source": "environment",
        "model": "gpt-5.5",
        "model_source": "default",
        "fallback_model_used": False,
        "reasoning_effort": "medium",
        "supports_structured_outputs": True,
        "supports_image_input": True,
        "model_error": "",
    }
    analyze_result = {
        "items": [],
        "totals": {"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0, "fiber_g": None, "sugar_g": None, "sodium_mg": None},
        "warnings": [],
        "message": "Parsed with gpt-5.5. Review before saving.",
        "success": True,
        "error_code": None,
        "debug": {"backend_endpoint_reached": True, "openai_key_configured": True, "model": "gpt-5.5", "parsing_status": "success"},
    }
    with (
        patch("src.ai.food_parser.openai_analyzer_config", return_value=config),
        patch("src.ai.food_parser.get_openai_key_status", return_value=True),
        patch("src.ai.food_parser.analyze_food_text", return_value=analyze_result),
    ):
        settings = client.get("/api/settings").json()
        integrations = client.get("/api/integrations/status?external_checks=false").json()
        analyze = client.post("/api/food/analyze-text", json={"text": "1 large egg"}).json()

    assert settings["statuses"]["openai_api_key"] == "Configured"
    assert settings["services"]["openai"]["model"] == "gpt-5.5"
    assert integrations["statuses"]["openai_api_key"] == "Configured"
    assert integrations["services"]["openai"]["model"] == "gpt-5.5"
    assert analyze["debug"]["openai_key_configured"] is True
    assert analyze["debug"]["model"] == "gpt-5.5"


def test_openai_config_agrees_across_settings_status_and_analyzer_when_missing():
    config = {
        "openai_key_configured": False,
        "api_key_source": "missing",
        "model": "gpt-5.5",
        "model_source": "default",
        "fallback_model_used": False,
        "reasoning_effort": "medium",
        "supports_structured_outputs": True,
        "supports_image_input": True,
        "model_error": "",
    }
    with (
        patch("src.ai.food_parser.openai_analyzer_config", return_value=config),
        patch("src.ai.food_parser.get_openai_key_status", return_value=False),
    ):
        settings = client.get("/api/settings").json()
        integrations = client.get("/api/integrations/status?external_checks=false").json()
        analyze = client.post("/api/food/analyze-text", json={"text": "1 large egg"}).json()

    assert settings["statuses"]["openai_api_key"] == "Not configured"
    assert integrations["statuses"]["openai_api_key"] == "Not configured"
    assert analyze["success"] is False
    assert analyze["error_code"] == "openai_not_configured"
    assert analyze["message"] == "AI food parsing is not configured yet. You can still log foods manually."
    assert analyze["debug"]["openai_key_configured"] is False
    assert analyze["debug"]["model"] == "gpt-5.5"
