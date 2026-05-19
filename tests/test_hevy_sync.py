import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os

import pandas as pd
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.main import app
from src import training as training_module
from src.integrations import hevy_client
from tests.auth_helpers import configure_test_auth


SAMPLE_WORKOUT = {
    "id": "hevy-workout-1",
    "title": "Upper Strength",
    "created_at": "2026-05-13T15:00:00Z",
    "updated_at": "2026-05-13T16:00:00Z",
    "start_time": "2026-05-13T15:00:00Z",
    "end_time": "2026-05-13T16:00:00Z",
    "exercises": [
        {
            "id": "bench-press",
            "title": "Bench Press",
            "sets": [
                {"index": 0, "reps": 5, "weight_kg": 100, "rpe": 8},
                {"index": 1, "reps": 5, "weight_kg": 102.5, "rpe": 8.5},
            ],
        }
    ],
}

SUNDAY_RUN_WORKOUT = {
    "id": "hevy-run-1",
    "title": "Sunday Treadmill Run",
    "created_at": "2026-04-26T15:00:00Z",
    "updated_at": "2026-04-26T15:35:00Z",
    "start_time": "2026-04-26T15:00:00Z",
    "end_time": "2026-04-26T15:30:00Z",
    "exercises": [
        {
            "id": "treadmill-run",
            "title": "Treadmill Run",
            "sets": [
                {"index": 0, "duration_seconds": 1800, "distance_meters": 4828},
            ],
        }
    ],
}


class HevySyncTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        configure_test_auth(self.client)

    def test_upsert_hevy_workout_replaces_existing_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "training_log.csv"
            with patch.dict(os.environ, {"DATABASE_URL": ""}), patch.object(training_module, "TRAINING_LOG_PATH", temp_path):
                first = hevy_client.upsert_hevy_workout(SAMPLE_WORKOUT, sync_source="test")
                second = hevy_client.upsert_hevy_workout(SAMPLE_WORKOUT, sync_source="test")
                saved = training_module.load_training_log()

        self.assertEqual(first["saved_rows"], 2)
        self.assertEqual(second["replaced_rows"], 2)
        self.assertEqual(len(saved), 2)
        self.assertEqual(saved["hevy_workout_id"].iloc[0], "hevy-workout-1")
        self.assertEqual(saved["sync_source"].iloc[0], "test")

    def test_sunday_hevy_run_normalizes_as_cardio_workout(self):
        rows = hevy_client.normalize_hevy_workout(SUNDAY_RUN_WORKOUT)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["workout_type"], "Run")
        self.assertEqual(rows[0]["muscle_group"], "Cardio")
        self.assertEqual(rows[0]["sets"], 0)
        self.assertIn("classification=running_cardio", rows[0]["notes"])
        self.assertIn("distance_miles=3.0", rows[0]["notes"])
        self.assertEqual(rows[0]["source"], "hevy")

    def test_sync_endpoint_returns_polled_result_without_real_hevy_call(self):
        training_log = pd.DataFrame(columns=training_module.TRAINING_COLUMNS)
        with patch(
            "backend.routes.training.sync_hevy_events",
            return_value={
                "events": 1,
                "saved_workouts": 1,
                "deleted_rows": 0,
                "failures": [],
                "training_log": training_log,
                "last_synced_at": "2026-05-13T16:05:00+00:00",
            },
        ):
            response = self.client.post("/api/training/sync/hevy")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["saved_workouts"], 1)
        self.assertEqual(data["last_synced_at"], "2026-05-13T16:05:00+00:00")

    def test_backend_does_not_register_background_hevy_poller(self):
        self.assertFalse(hasattr(backend_main, "_hevy_poll_loop"))
        self.assertFalse(hasattr(backend_main, "start_hevy_polling"))
        self.assertFalse(hasattr(backend_main, "_hevy_poll_thread_started"))

    def test_hevy_sync_state_uses_safe_fallback_on_storage_failure(self):
        with patch("src.integrations.hevy_client.load_document", side_effect=RuntimeError("AdminShutdown: terminating connection")):
            state = hevy_client.load_hevy_sync_state()

        self.assertEqual(state["last_sync_at"], "")
        self.assertEqual(state["last_event_cursor"], "")
        self.assertIn("AdminShutdown", state["last_error"])
        self.assertEqual(state["last_result"], {})
        self.assertTrue(state["safe_mode"])

    def test_sync_endpoint_catches_unexpected_hevy_failures(self):
        with patch("backend.routes.training.sync_hevy_events", side_effect=RuntimeError("database connection reset")), patch(
            "backend.routes.training.save_hevy_sync_state",
            return_value={"last_sync_at": "", "last_error": "database connection reset", "last_result": {"status": "error"}},
        ), patch("backend.routes.training.load_training_log", return_value=pd.DataFrame(columns=training_module.TRAINING_COLUMNS)):
            response = self.client.post("/api/training/sync/hevy")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("database connection reset", data["message"])

    def test_webhook_requires_secret_and_processes_valid_payload(self):
        response = self.client.post("/api/hevy/webhook", json={"workout_id": "hevy-workout-1"})
        self.assertEqual(response.status_code, 401)

        with patch("backend.routes.training.verify_webhook_token", return_value=True), patch(
            "backend.routes.training.handle_hevy_webhook",
            return_value={
                "status": "ok",
                "action": "upsert",
                "workout_id": "hevy-workout-1",
                "saved_rows": 2,
                "replaced_rows": 0,
            },
        ):
            response = self.client.post(
                "/api/hevy/webhook",
                headers={"x-hevy-webhook-secret": "test-secret"},
                json={"workout_id": "hevy-workout-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["saved_rows"], 2)


if __name__ == "__main__":
    unittest.main()
