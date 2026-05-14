import unittest

import pandas as pd

from src.analytics.todays_action import generate_todays_action


def _base_action(**overrides):
    payload = {
        "workout_quality": {"status": "scored", "score": 7.0},
        "recovery_tile": {"latest_score": 72},
        "sleep_df": pd.DataFrame(),
        "weight_feedback": {"status": "insufficient data"},
        "nutrition_adherence": {"consistency_score": None, "average_calories_delta": None},
        "training_workload": {"current": {"recovery_demand": "normal"}},
        "adaptive_recommendation": {
            "signals": {
                "recovery": {"status": "normal"},
                "runningLoad": {"status": "normal"},
                "trainingLoad": {"status": "normal"},
                "performance": {"label": "stable"},
            }
        },
    }
    payload.update(overrides)
    return generate_todays_action(**payload)


class TodaysActionTests(unittest.TestCase):
    def test_missing_workout_prompts_completion(self):
        action = _base_action(workout_quality={"status": "missing", "score": None})

        self.assertEqual(action["color"], "gray")
        self.assertIn("Complete", action["headline"])
        self.assertIn("No Hevy or Strava", action["reason"])

    def test_poor_recovery_takes_priority(self):
        action = _base_action(
            adaptive_recommendation={
                "signals": {
                    "recovery": {"status": "poor"},
                    "runningLoad": {"status": "normal"},
                    "trainingLoad": {"status": "normal"},
                    "performance": {"label": "stable"},
                }
            }
        )

        self.assertEqual(action["color"], "red")
        self.assertEqual(action["headline"], "Prioritize recovery")

    def test_strong_workout_and_normal_recovery_pushes(self):
        action = _base_action(workout_quality={"status": "scored", "score": 8.6})

        self.assertEqual(action["color"], "green")
        self.assertEqual(action["headline"], "Push today")

    def test_on_track_weight_and_adherence_hold_macros(self):
        action = _base_action(
            weight_feedback={"status": "On track"},
            nutrition_adherence={"consistency_score": 88, "average_calories_delta": 95},
        )

        self.assertEqual(action["color"], "yellow")
        self.assertEqual(action["headline"], "Hold macros")


if __name__ == "__main__":
    unittest.main()
