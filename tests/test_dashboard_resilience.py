import os
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend.main import app
from src.body_metrics import BODY_METRICS_COLUMNS
from src.nutrition import NUTRITION_COLUMNS
from src.recovery import RECOVERY_COLUMNS, SLEEP_ENTRY_COLUMNS
from src.training import TRAINING_COLUMNS
from tests.auth_helpers import ACCESS_COOKIE, TEST_APP_PASSWORD, TEST_SESSION_SECRET, create_session_token


class DashboardResilienceTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_dashboard_returns_core_payload_when_advanced_analytics_fail(self):
        with (
            patch.dict(os.environ, {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True),
            patch("backend.main.load_nutrition_log", return_value=pd.DataFrame(columns=NUTRITION_COLUMNS)),
            patch("backend.main.load_body_metrics", return_value=pd.DataFrame(columns=BODY_METRICS_COLUMNS)),
            patch("backend.main.load_recovery_log", return_value=pd.DataFrame(columns=RECOVERY_COLUMNS)),
            patch("backend.main.load_sleep_entries", return_value=pd.DataFrame(columns=SLEEP_ENTRY_COLUMNS)),
            patch("backend.main.load_training_log", return_value=pd.DataFrame(columns=TRAINING_COLUMNS)),
            patch("backend.main.build_adaptive_nutrition_recommendation", side_effect=RuntimeError("adaptive boom")),
        ):
            self.client.cookies.set(ACCESS_COOKIE, create_session_token(TEST_SESSION_SECRET))
            response = self.client.get("/api/dashboard")
            debug = self.client.get("/api/dashboard/debug")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("food", payload)
        self.assertIn("targets", payload)
        self.assertIn("errors", payload)
        self.assertTrue(any(error["block"] == "adaptive_recommendation" for error in payload["errors"]))
        self.assertEqual(payload["debug"]["status"]["adaptive_recommendation"], False)

        self.assertEqual(debug.status_code, 200)
        self.assertEqual(debug.json()["adaptive_recommendation_ok"], False)


if __name__ == "__main__":
    unittest.main()
