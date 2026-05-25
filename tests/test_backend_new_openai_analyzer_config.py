from __future__ import annotations

from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

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
        "source": "openai",
        "cached": False,
        "message": "Parsed with gpt-5.5. Review before saving.",
        "success": True,
        "error_code": None,
        "debug": {"backend_endpoint_reached": True, "openai_key_configured": True, "model": "gpt-5.5", "parsing_status": "success", "parser_source": "openai", "parser_cached": False},
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
        patch("src.ai.food_parser._local_saved_food_response", return_value=None),
        patch("src.ai.food_parser._cached_response", return_value=None),
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
    assert analyzed.json()["status"] == "ok"
    assert len(analyzed.json()["items"]) == 2
    assert len(analyzed.json()["foods"]) == 2
    assert analyzed.json()["totals"] == analyzed.json()["total"]
    assert analyzed.json()["steps"]["route_entered"] is True
    assert analyzed.json()["steps"]["returned_items"] == 2
    assert saved.status_code == 200
    assert saved.json()["status"] == "ok"
    assert saved.json()["created"] == 2
    assert saved.json()["requested"] == 2


def test_debug_food_parser_test_uses_same_parser_path():
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
            }
        ],
        "totals": {"calories": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.4, "fiber_g": 3, "sugar_g": 14, "sodium_mg": 1},
        "warnings": [],
        "source": "openai",
        "cached": False,
        "message": "Parsed with gpt-5.5. Review before saving.",
        "success": True,
        "error_code": None,
        "debug": {"backend_endpoint_reached": True, "openai_key_configured": True, "model": "gpt-5.5", "parsing_status": "success", "parser_source": "openai", "parser_cached": False},
    }
    with (
        patch("src.ai.food_parser.openai_analyzer_config", return_value=config),
        patch("src.ai.food_parser.get_openai_key_status", return_value=True),
        patch("src.ai.food_parser.analyze_food_text", return_value=analyze_result),
    ):
        response = client.post("/api/debug/food-parser-test", json={"text": "banana and protein shake"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["openai_connected"] is True
    assert data["endpoint_called"] == "/api/food/analyze-text"
    assert data["request_body_received"] == {"text": "banana and protein shake"}
    assert data["diagnostic_force_openai"] is True
    assert data["openai_called"] is True
    assert data["model_used"] == "gpt-5.5"
    assert data["raw_items_count"] == 1
    assert data["normalized_items_count"] == 1
    assert data["response_shape"]["has_items"] is True
    assert data["response_shape"]["has_foods"] is True
    assert data["frontend_received_items"] is False
    assert data["log_insert_attempted"] is False
    assert data["log_insert_success"] is False
    assert data["items"][0]["display_name"] == "Banana"
    assert data["steps"]["route_entered"] is True
    assert data["steps"]["returned_items"] == 1
    assert "sk-" not in str(data)


def test_food_log_bulk_rejects_empty_parsed_items():
    response = client.post("/api/food/log-bulk", json={"date": "2026-05-22", "items": []})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "empty_food_bulk"


def test_food_analyze_text_uses_openai_when_external_lookup_403s():
    from src.ai import food_parser

    openai_payload = {
        "foods": [
            {
                "food_name": "Beans",
                "display_name": "Beans",
                "normalized_name": "beans",
                "original_text": "beans",
                "quantity": 1,
                "unit": "cup",
                "serving_description": "1 cup cooked beans",
                "calories": 240,
                "protein": 15,
                "carbs": 44,
                "fat": 1,
                "fiber": 15,
                "sugar": 1,
                "sodium": 5,
                "confidence": "medium",
                "source": "openai_estimate",
                "source_id": None,
                "source_url": None,
                "assumptions": ["Assumed one cup cooked beans."],
                "needs_review": True,
                "verification_needed": False,
                "verification_reason": "",
                "notes": "Estimate.",
            }
        ]
    }
    forbidden = HTTPError("https://api.nal.usda.gov/fdc/v1/foods/search", 403, "Forbidden", hdrs=None, fp=BytesIO(b""))

    with (
        patch("src.ai.food_parser._get_openai_api_key", return_value="sk-test"),
        patch("src.ai.food_parser._call_openai", return_value=openai_payload),
        patch("src.ai.food_parser.search_food_macros", side_effect=forbidden),
    ):
        result = food_parser.analyze_food_text("beans", force_openai=True)

    assert result["success"] is True
    assert result["items"][0]["display_name"] == "Beans"
    assert result["parser_source"] == "openai"
    assert result["external_lookup_status"] == "failed_403"
    assert "external nutrition lookup failed: 403" in result["warnings"]


def test_food_route_uses_saved_food_first_then_openai_when_no_match():
    config = {
        "openai_key_configured": True,
        "api_key_source": "environment",
        "model": "gpt-4.1",
        "model_source": "env",
        "fallback_model_used": False,
        "reasoning_effort": "medium",
        "supports_structured_outputs": True,
        "supports_image_input": True,
        "model_error": "",
    }
    analyze_result = {
        "items": [
            {
                "name": "Beans",
                "display_name": "Beans",
                "normalized_name": "beans",
                "original_text": "beans",
                "quantity": 1,
                "unit": "cup",
                "serving_description": "1 cup cooked beans",
                "calories": 240,
                "protein_g": 15,
                "carbs_g": 44,
                "fat_g": 1,
                "fiber_g": 15,
                "sugar_g": 1,
                "sodium_mg": 5,
                "confidence": "medium",
                "source": "openai_estimate",
                "source_id": None,
                "source_url": None,
                "assumptions": ["Assumed one cup cooked beans."],
                "needs_review": True,
            }
        ],
        "totals": {"calories": 240, "protein_g": 15, "carbs_g": 44, "fat_g": 1, "fiber_g": 15, "sugar_g": 1, "sodium_mg": 5},
        "warnings": ["external nutrition lookup failed: 403"],
        "parser_source": "openai",
        "external_lookup_status": "failed_403",
        "source": "openai",
        "cached": False,
        "message": "Parsed with gpt-4.1. Review before saving.",
        "success": True,
        "error_code": None,
        "debug": {"backend_endpoint_reached": True, "openai_key_configured": True, "model": "gpt-4.1", "parsing_status": "success", "parser_source": "openai", "external_lookup_status": "failed_403"},
    }
    with (
        patch("src.ai.food_parser.openai_analyzer_config", return_value=config),
        patch("src.ai.food_parser.get_openai_key_status", return_value=True),
        patch("src.ai.food_parser.analyze_food_text", return_value=analyze_result) as analyze_mock,
    ):
        response = client.post("/api/food/analyze-text", json={"date": "2026-05-21", "text": "beans"})

    data = response.json()
    assert response.status_code == 200
    assert data["status"] == "ok"
    assert data["success"] is True
    assert data["items"][0]["display_name"] == "Beans"
    assert data["steps"]["openai_called"] is True
    assert data["steps"]["force_openai"] is False
    assert data["parser_source"] == "openai"
    assert data["external_lookup_status"] == "failed_403"
    assert "external nutrition lookup failed: 403" in data["warnings"]
    analyze_mock.assert_called_once_with("beans", force_openai=False)


def test_saved_food_match_does_not_hijack_multi_food_ai_parse():
    from src.ai.food_parser import _saved_food_match

    assert _saved_food_match("banana", "banana") is True
    assert _saved_food_match("banana and protein shake", "banana") is False
    assert _saved_food_match("banana, protein shake", "banana") is False


def test_default_saved_food_shortcut_skips_openai():
    from src.ai import food_parser

    with (
        patch("src.ai.food_parser.get_openai_key_status", return_value=False),
        patch("src.ai.food_parser._call_openai") as openai_mock,
        patch("src.ai.food_parser.search_food_macros") as usda_mock,
    ):
        result = food_parser.analyze_food_text("Built Puff Bar")

    assert result["success"] is True
    assert result["parser_source"] == "saved_shortcut"
    assert result["items"][0]["display_name"] == "Built Puff Bar"
    assert result["items"][0]["source"] == "existing_database"
    assert result["items"][0]["calories"] == 140
    assert result["parser"]["default_model_used"] is False
    assert result["parser"]["escalated"] is False
    openai_mock.assert_not_called()
    usda_mock.assert_not_called()


def test_ambiguous_food_escalates_after_default_parse():
    from src.ai import food_parser

    default_payload = {
        "foods": [
            {
                "food_name": "Beans",
                "display_name": "Beans",
                "normalized_name": "beans",
                "original_text": "beans",
                "quantity": 1,
                "unit": "cup",
                "serving_description": "1 cup cooked beans",
                "calories": 240,
                "protein": 15,
                "carbs": 44,
                "fat": 1,
                "fiber": 15,
                "sugar": 1,
                "sodium": 5,
                "confidence": "medium",
                "source": "openai_estimate",
                "source_id": None,
                "source_url": None,
                "assumptions": ["Assumed one cup cooked beans."],
                "needs_review": True,
                "verification_needed": False,
                "verification_reason": "",
                "notes": "Estimate.",
            }
        ]
    }
    escalated_payload = {
        "foods": [
            {
                **default_payload["foods"][0],
                "confidence": "low",
                "assumptions": ["Assumed cooked black beans, 1 cup."],
                "needs_review": True,
            }
        ]
    }

    with (
        patch("src.ai.food_parser.get_openai_key_status", return_value=True),
        patch("src.ai.food_parser._get_openai_api_key", return_value="sk-test"),
        patch("src.ai.food_parser._call_openai", side_effect=[default_payload, escalated_payload]) as openai_mock,
        patch("src.ai.food_parser.search_food_macros", return_value=None),
        patch("src.ai.food_parser.verify_food_online", return_value={"verified": False, "macros": {}, "source": "test", "confidence": "low", "message": "No confident external match."}),
    ):
        result = food_parser.analyze_food_text("beans", force_openai=True)

    assert result["success"] is True
    assert result["parser"]["default_model_used"] is True
    assert result["parser"]["escalated"] is True
    assert "Ambiguous" in result["parser"]["escalation_reason"]
    assert result["items"][0]["needs_confirmation"] is True
    assert result["items"][0]["confidence"] == "low"
    assert openai_mock.call_count == 2
