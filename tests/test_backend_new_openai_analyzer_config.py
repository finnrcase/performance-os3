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

    assert settings["statuses"]["openai_api_key"] in {"Configured", "Connected"}
    assert settings["services"]["openai"]["model"] == "gpt-5.5"
    assert integrations["statuses"]["openai_api_key"] in {"Configured", "Connected"}
    assert integrations["services"]["openai"]["model"] == "gpt-5.5"
    assert analyze["debug"]["openai_key_configured"] is True
    assert analyze["debug"]["model"] == "gpt-5.5"
    assert settings["services"]["openai"]["status"] in {"configured", "connected"}


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

    assert settings["statuses"]["openai_api_key"] == "Missing"
    assert integrations["statuses"]["openai_api_key"] == "Missing"
    assert analyze["success"] is False
    assert analyze["error_code"] == "openai_not_configured"
    assert analyze["message"] == "AI food parsing is not configured yet. You can still log foods manually."
    assert analyze["debug"]["openai_key_configured"] is False
    assert analyze["debug"]["model"] == "gpt-5.5"


def test_debug_openai_returns_safe_working_status_without_exposing_key():
    debug_payload = {
        "configured": True,
        "client_initialized": True,
        "test_status": "ok",
        "error_type": "",
        "message": "OpenAI test call succeeded with gpt-5.5.",
        "model": "gpt-5.5",
        "api_key_source": "environment",
        "response_ms": 42.0,
        "latency_ms": 42.0,
    }
    with patch("src.ai.food_parser.test_openai_connection", return_value=debug_payload):
        response = client.get("/api/debug/openai")

    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["client_initialized"] is True
    assert data["test_status"] == "ok"
    assert data["model"] == "gpt-5.5"
    assert data["response_ms"] == 42.0
    assert "sk-" not in str(data)


def test_integrations_test_runs_direct_openai_probe():
    debug_payload = {
        "configured": True,
        "client_initialized": True,
        "test_status": "ok",
        "error_type": "",
        "message": "OpenAI test call succeeded with gpt-5.5.",
        "model": "gpt-5.5",
        "api_key_source": "environment",
    }
    with patch("src.ai.food_parser.test_openai_connection", return_value=debug_payload):
        data = client.get("/api/integrations/test").json()

    assert data["openai"]["status"] == "connected"
    assert "Working:" in data["openai"]["message"]
    assert data["openai"]["layers"]["configuration"]["status"] == "configured"
    assert data["openai"]["layers"]["client"]["status"] == "initialized"
    assert data["openai"]["layers"]["test_call"]["status"] == "ok"


def test_integrations_test_reports_openai_error_clearly():
    debug_payload = {
        "configured": True,
        "client_initialized": True,
        "test_status": "error",
        "error_type": "AuthenticationError",
        "message": "OpenAI rejected the API key. Replace OPENAI_API_KEY and redeploy.",
        "model": "gpt-5.5",
        "api_key_source": "environment",
    }
    with patch("src.ai.food_parser.test_openai_connection", return_value=debug_payload):
        data = client.get("/api/integrations/test").json()

    assert data["openai"]["status"] == "error"
    assert "rejected the API key" in data["openai"]["message"]
    assert data["openai"]["layers"]["test_call"]["status"] == "error"


def test_food_analyze_text_and_bulk_log_flow_uses_current_routes():
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
        "items": [
            {
                "name": "Banana",
                "display_name": "Banana",
                "normalized_name": "banana",
                "original_text": "banana",
                "quantity": 1,
                "unit": "medium",
                "serving_description": "1 medium banana",
                "calories": 105,
                "protein_g": 1.3,
                "carbs_g": 27,
                "fat_g": 0.4,
                "fiber_g": 3,
                "sugar_g": 14,
                "sodium_mg": 1,
                "confidence": "high",
                "source": "openai_estimate",
                "source_id": None,
                "source_url": None,
                "assumptions": [],
                "needs_review": False,
            },
            {
                "name": "Protein Shake",
                "display_name": "Protein Shake",
                "normalized_name": "protein_shake",
                "original_text": "protein shake",
                "quantity": 1,
                "unit": "shake",
                "serving_description": "1 protein shake",
                "calories": 160,
                "protein_g": 30,
                "carbs_g": 4,
                "fat_g": 3,
                "fiber_g": None,
                "sugar_g": None,
                "sodium_mg": None,
                "confidence": "medium",
                "source": "openai_estimate",
                "source_id": None,
                "source_url": None,
                "assumptions": ["Assumed one scoop whey protein with water."],
                "needs_review": True,
            },
        ],
        "totals": {"calories": 265, "protein_g": 31.3, "carbs_g": 31, "fat_g": 3.4, "fiber_g": 3, "sugar_g": 14, "sodium_mg": 1},
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
        patch("backend_new.routes.nutrition.insert_json_row", side_effect=lambda _table, data: data),
    ):
        analyzed = client.post("/api/food/analyze-text", json={"date": "2026-05-22", "text": "banana and protein shake"})
        saved = client.post(
            "/api/food/log-bulk",
            json={"date": "2026-05-22", "meal_type": "Food", "items": analyzed.json()["items"]},
        )

    assert analyzed.status_code == 200
    assert analyzed.json()["success"] is True
    assert len(analyzed.json()["items"]) == 2
    assert saved.status_code == 200
    assert saved.json()["status"] == "ok"
    assert saved.json()["created"] == 2
    assert saved.json()["requested"] == 2


def test_food_log_bulk_rejects_empty_parsed_items():
    response = client.post("/api/food/log-bulk", json={"date": "2026-05-22", "items": []})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_food_bulk"


def test_saved_food_match_does_not_hijack_multi_food_ai_parse():
    from src.ai.food_parser import _saved_food_match

    assert _saved_food_match("banana", "banana") is True
    assert _saved_food_match("banana and protein shake", "banana") is False
    assert _saved_food_match("banana, protein shake", "banana") is False
