import copy
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from src.config import default_settings
from tests.auth_helpers import TEST_APP_PASSWORD, TEST_SESSION_SECRET, configure_test_auth


class ProductionConfigTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        configure_test_auth(self.client)

    def test_integration_status_reports_backend_env_without_leaking_secrets(self):
        with patch.dict(
            "os.environ",
            {
                "APP_PASSWORD": TEST_APP_PASSWORD,
                "SESSION_SECRET": TEST_SESSION_SECRET,
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

    def test_settings_accent_color_persists_in_settings_document(self):
        stored_settings = default_settings()

        def load_fake_settings():
            return copy.deepcopy(stored_settings)

        def save_fake_settings(next_settings):
            stored_settings.clear()
            stored_settings.update(copy.deepcopy(next_settings))

        with patch("backend.routes.integrations.load_settings", side_effect=load_fake_settings), patch("backend.routes.integrations.save_settings", side_effect=save_fake_settings):
            response = self.client.put("/api/settings", json={"appearance": {"accent_color": "purple"}})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["appearance"]["accent_color"], "purple")

            persisted = self.client.get("/api/settings")
            self.assertEqual(persisted.status_code, 200)
            self.assertEqual(persisted.json()["appearance"]["accent_color"], "purple")

            fallback = self.client.put("/api/settings", json={"appearance": {"accent_color": "ultraviolet"}})
            self.assertEqual(fallback.status_code, 200)
            self.assertEqual(fallback.json()["appearance"]["accent_color"], "lime")

    def test_api_connection_test_reports_missing_configuration_without_secrets(self):
        with (
            patch.dict("os.environ", {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True),
            patch("backend.routes.integrations._read_dotenv_value", return_value=""),
            patch("backend.routes.integrations.load_settings", return_value=default_settings()),
        ):
            response = self.client.get("/api/integrations/test")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["hevy"]["status"], "missing_api_key")
        self.assertEqual(payload["openai"]["status"], "missing_api_key")
        self.assertEqual(payload["withings"]["status"], "missing_credentials")
        serialized = str(payload)
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("refresh_token", serialized)

    def test_api_connection_test_reports_connected_services(self):
        settings = default_settings()
        settings["integrations"].update(
            {
                "hevy_api_key": "hevy-secret",
                "openai_api_key": "openai-secret",
                "withings_client_id": "withings-client-id",
                "withings_client_secret": "withings-secret",
            }
        )
        settings["metadata"]["withings_tokens"] = {
            "access_token": "withings-access",
            "refresh_token": "withings-refresh",
            "expires_at": 9_999_999_999,
            "userid": "withings-user",
            "scopes": "user.metrics",
            "token_type": "Bearer",
        }

        def dotenv_value(key: str) -> str:
            return "https://example.com/api/withings/callback" if key == "WITHINGS_REDIRECT_URI" else ""

        with (
            patch.dict("os.environ", {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True),
            patch("backend.routes.integrations._read_dotenv_value", side_effect=dotenv_value),
            patch("backend.routes.integrations.load_settings", return_value=settings),
            patch("backend.routes.integrations._hevy_probe", return_value=None),
            patch("backend.routes.integrations._openai_probe", return_value=None),
            patch("backend.routes.integrations._withings_probe", return_value=None),
        ):
            response = self.client.get("/api/integrations/test")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["hevy"]["status"], "connected")
        self.assertEqual(payload["openai"]["status"], "connected")
        self.assertEqual(payload["withings"]["status"], "connected")
        serialized = str(payload)
        self.assertNotIn("hevy-secret", serialized)
        self.assertNotIn("openai-secret", serialized)
        self.assertNotIn("withings-secret", serialized)
        self.assertNotIn("withings-access", serialized)
        self.assertNotIn("withings-refresh", serialized)


if __name__ == "__main__":
    unittest.main()
