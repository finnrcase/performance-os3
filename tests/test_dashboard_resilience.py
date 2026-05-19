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

    def test_dashboard_empty_data_returns_200_with_debug_payload(self):
        with (
            patch.dict(os.environ, {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True),
            patch("backend.main.load_nutrition_log", return_value=pd.DataFrame(columns=NUTRITION_COLUMNS)),
            patch("backend.main.load_body_metrics", return_value=pd.DataFrame(columns=BODY_METRICS_COLUMNS)),
            patch("backend.main.load_recovery_log", return_value=pd.DataFrame(columns=RECOVERY_COLUMNS)),
            patch("backend.main.load_sleep_entries", return_value=pd.DataFrame(columns=SLEEP_ENTRY_COLUMNS)),
            patch("backend.main.load_training_log", return_value=pd.DataFrame(columns=TRAINING_COLUMNS)),
            patch("backend.main.load_hevy_sync_state", return_value={"last_sync_at": "", "last_event_cursor": "", "last_error": "AdminShutdown", "last_result": {}, "safe_mode": True}),
        ):
            self.client.cookies.set(ACCESS_COOKIE, create_session_token(TEST_SESSION_SECRET))
            response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["debug"]["dashboard_status"], {"ok", "degraded"})
        self.assertIn("blocks", payload["debug"])
        self.assertEqual(payload["counts"]["nutrition"], 0)
        self.assertEqual(payload["counts"]["sleep"], 0)
        self.assertIn("food", payload)
        self.assertIn("weight", payload)
        self.assertEqual(payload["debug"]["hevy_sync"]["status"], "error")
        self.assertTrue(payload["debug"]["hevy_sync"]["safe_mode"])

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
        self.assertEqual(debug.json()["status"], "degraded")
        self.assertTrue(any(block["block"] == "adaptive_recommendation" for block in debug.json()["blocks"]))

    def test_dashboard_malformed_rows_do_not_500(self):
        nutrition_row = {column: None for column in NUTRITION_COLUMNS}
        nutrition_row.update({"date": "not-a-date", "food_name": "bad row", "calories": "NaN-ish", "protein": object()})
        training_row = {column: None for column in TRAINING_COLUMNS}
        training_row.update({"date": "bad-date", "exercise": object(), "source": None, "weight": "heavy"})

        with (
            patch.dict(os.environ, {"APP_PASSWORD": TEST_APP_PASSWORD, "SESSION_SECRET": TEST_SESSION_SECRET}, clear=True),
            patch("backend.main.load_nutrition_log", return_value=pd.DataFrame([nutrition_row], columns=NUTRITION_COLUMNS)),
            patch("backend.main.load_body_metrics", return_value=pd.DataFrame(columns=BODY_METRICS_COLUMNS)),
            patch("backend.main.load_recovery_log", return_value=pd.DataFrame(columns=RECOVERY_COLUMNS)),
            patch("backend.main.load_sleep_entries", return_value=pd.DataFrame(columns=SLEEP_ENTRY_COLUMNS)),
            patch("backend.main.load_training_log", return_value=pd.DataFrame([training_row], columns=TRAINING_COLUMNS)),
        ):
            self.client.cookies.set(ACCESS_COOKIE, create_session_token(TEST_SESSION_SECRET))
            response = self.client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn(payload["debug"]["dashboard_status"], {"ok", "degraded"})
        self.assertIn("debug", payload)
        self.assertIn("blocks", payload["debug"])


if __name__ == "__main__":
    unittest.main()
