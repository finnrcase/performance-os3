import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from src import body_metrics as body_metrics_module
from src.integrations import withings_client
from tests.auth_helpers import configure_test_auth


WITHINGS_MEASURE_RESPONSE = {
    "status": 0,
    "body": {
        "measuregrps": [
            {
                "grpid": 123,
                "date": 1_715_769_600,
                "measures": [
                    {"type": 1, "value": 82500, "unit": -3},
                    {"type": 4, "value": 180, "unit": -2},
                    {"type": 5, "value": 67031, "unit": -3},
                    {"type": 6, "value": 1875, "unit": -2},
                    {"type": 8, "value": 15469, "unit": -3},
                    {"type": 76, "value": 62000, "unit": -3},
                    {"type": 77, "value": 45000, "unit": -3},
                ],
            }
        ]
    },
}


class WithingsSyncTest(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {"DATABASE_URL": ""})
        self.env_patch.start()
        self.client = TestClient(app)
        configure_test_auth(self.client)

    def tearDown(self):
        self.env_patch.stop()

    def test_sync_imports_scale_measurements_into_body_metrics_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "body_metrics.csv"
            with patch.object(body_metrics_module, "BODY_METRICS_PATH", metrics_path), patch(
                "src.integrations.withings_client.refresh_withings_token_if_needed",
                return_value={"access_token": "token"},
            ), patch("src.integrations.withings_client._post_form", return_value=WITHINGS_MEASURE_RESPONSE), patch(
                "src.integrations.withings_client._save_withings_sync_state",
                side_effect=lambda updates: updates,
            ):
                first = withings_client.sync_withings_measurements(days=30)
                second = withings_client.sync_withings_measurements(days=30)
                saved = body_metrics_module.load_body_metrics()

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["imported_measurements"], 1)
        self.assertEqual(len(saved), 1)
        self.assertAlmostEqual(float(saved["bodyweight"].iloc[0]), 181.88, places=2)
        self.assertAlmostEqual(float(saved["estimated_body_fat"].iloc[0]), 18.75, places=2)
        self.assertAlmostEqual(float(saved["body_fat_percent"].iloc[0]), 18.75, places=2)
        self.assertAlmostEqual(float(saved["fat_mass"].iloc[0]), 34.1, places=2)
        self.assertAlmostEqual(float(saved["lean_mass"].iloc[0]), 147.78, places=2)
        self.assertAlmostEqual(float(saved["muscle_mass"].iloc[0]), 136.69, places=2)
        self.assertAlmostEqual(float(saved["hydration"].iloc[0]), 99.21, places=2)
        self.assertAlmostEqual(float(saved["bmi"].iloc[0]), 25.46, places=2)
        self.assertIn("source=withings", saved["notes"].iloc[0])
        self.assertIn("withings_measure_group_id=123", saved["notes"].iloc[0])

    def test_connect_route_redirects_to_withings_authorization(self):
        with patch.dict(
            "os.environ",
            {
                "WITHINGS_CLIENT_ID": "client-id",
                "WITHINGS_CLIENT_SECRET": "secret",
                "WITHINGS_REDIRECT_URI": "https://example.com/api/withings/callback",
            },
            clear=False,
        ):
            response = self.client.get("/api/withings/connect", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertIn("https://account.withings.com/oauth2_user/authorize2", location)
        self.assertIn("client_id=client-id", location)
        self.assertIn("scope=user.metrics", location)

    def test_auth_url_route_returns_backend_generated_withings_authorization_url(self):
        with patch.dict(
            "os.environ",
            {
                "WITHINGS_CLIENT_ID": "client-id",
                "WITHINGS_CLIENT_SECRET": "secret",
                "WITHINGS_REDIRECT_URI": "https://api-production-b3ff.up.railway.app/api/withings/callback",
            },
            clear=False,
        ):
            response = self.client.get("/api/integrations/withings/auth-url")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["redirect_uri"], "https://api-production-b3ff.up.railway.app/api/withings/callback")
        self.assertIn("https://account.withings.com/oauth2_user/authorize2", data["auth_url"])
        self.assertIn("client_id=client-id", data["auth_url"])

    def test_callback_validation_methods_accept_empty_provider_checks(self):
        get_response = self.client.get("/api/withings/callback")
        post_response = self.client.post("/api/withings/callback")
        head_response = self.client.head("/api/withings/callback")
        options_response = self.client.options("/api/withings/callback")

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["provider"], "withings")
        self.assertIn("callback reachable", get_response.json()["message"])
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.json(), {"status": "ok", "provider": "withings"})
        self.assertEqual(head_response.status_code, 200)
        self.assertIn(options_response.status_code, {200, 204})

    def test_sync_route_returns_error_when_not_connected(self):
        with patch(
            "backend.routes.withings.sync_withings_measurements",
            side_effect=withings_client.WithingsIntegrationError("Withings is not connected."),
        ), patch("backend.routes.withings.save_withings_sync_error", return_value={"last_error": "Withings is not connected."}):
            response = self.client.post("/api/withings/sync")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "error")
        self.assertIn("not connected", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
