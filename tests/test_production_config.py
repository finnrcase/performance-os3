import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app


class ProductionConfigTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_integration_status_reports_backend_env_without_leaking_secrets(self):
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "sk-production-secret",
                "HEVY_API_KEY": "hevy-production-secret",
                "STRAVA_CLIENT_ID": "strava-client-id",
                "STRAVA_CLIENT_SECRET": "strava-client-secret",
                "STRAVA_ACCESS_TOKEN": "strava-access-token",
                "STRAVA_REFRESH_TOKEN": "strava-refresh-token",
            },
            clear=False,
        ):
            response = self.client.get("/api/integrations/status?external_checks=false")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["overall_status"], {"ok", "degraded", "error"})
        self.assertIn("checked_at", payload)
        self.assertEqual(payload["openai"]["required_env_vars"], ["OPENAI_API_KEY"])
        self.assertIn("DATABASE_URL", payload["database"]["required_env_vars"])
        self.assertEqual(payload["services"]["openai"]["status"], "ok")
        self.assertEqual(payload["services"]["hevy"]["status"], "ok")
        self.assertEqual(payload["services"]["strava"]["status"], "ok")
        serialized = str(payload)
        self.assertNotIn("sk-production-secret", serialized)
        self.assertNotIn("hevy-production-secret", serialized)
        self.assertNotIn("strava-client-secret", serialized)
        self.assertNotIn("strava-access-token", serialized)
        self.assertNotIn("strava-refresh-token", serialized)

    def test_food_parse_returns_503_when_openai_is_not_configured(self):
        with patch(
            "backend.routes.nutrition.parse_food_text",
            return_value={
                "foods": [],
                "total": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
                "source": "fallback",
                "cached": False,
                "success": False,
                "error_code": "missing_api_key",
                "message": "OpenAI API key is not configured.",
                "debug": {},
            },
        ):
            response = self.client.post("/api/nutrition/ai/parse", json={"text": "3 eggs"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "openai_not_configured")


if __name__ == "__main__":
    unittest.main()
