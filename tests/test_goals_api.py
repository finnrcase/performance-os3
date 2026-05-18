import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.main import app
from src import goals as goals_module
from src import nutrition as nutrition_module
from src import nutrition_targets as targets_module
from tests.auth_helpers import configure_test_auth


class GoalsApiTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        configure_test_auth(self.client)

    def test_apply_suggested_macros_persists_aligned_active_targets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            goals_path = temp_path / "user_goals.json"
            targets_path = temp_path / "nutrition_targets.json"
            nutrition_path = temp_path / "nutrition_log.csv"
            with patch.object(goals_module, "USER_GOALS_PATH", goals_path), patch.object(
                targets_module, "NUTRITION_TARGETS_PATH", targets_path
            ), patch.object(nutrition_module, "NUTRITION_LOG_PATH", nutrition_path):
                self.client.post(
                    "/api/goals",
                    json={
                        "current_bodyweight": 160,
                        "goal_bodyweight": 168,
                        "timeline_weeks": 24,
                        "goal_type": "Lean Bulk",
                        "training_frequency_per_week": 4,
                        "cardio_frequency_per_week": 2,
                        "estimated_body_fat": None,
                        "activity_level": "Moderate",
                        "aggressiveness": "Conservative",
                    },
                )
                response = self.client.post("/api/goals/apply-suggested-macros", json={})

                self.assertEqual(response.status_code, 200)
                targets = response.json()["targets"]
                macro_calories = (targets["protein_grams"] * 4) + (targets["carb_grams"] * 4) + (targets["fat_grams"] * 9)
                self.assertEqual(targets["macro_calories"], macro_calories)
                self.assertLessEqual(abs(targets["calorie_macro_delta"]), 2)
                self.assertTrue(targets_path.exists())


if __name__ == "__main__":
    unittest.main()
