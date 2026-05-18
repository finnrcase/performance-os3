import unittest

import pandas as pd

from backend.main import _lift_performance_tile
from src.training_schedule import DEFAULT_RECURRING_SCHEDULE_PROFILE, planned_training_for_date, summarize_training_day


class TrainingScheduleTest(unittest.TestCase):
    def test_default_split_profile_matches_requested_schedule(self):
        profile = DEFAULT_RECURRING_SCHEDULE_PROFILE
        self.assertEqual(planned_training_for_date("2026-05-18", profile=profile)["label"], "Pull")
        self.assertEqual(planned_training_for_date("2026-05-19", profile=profile)["label"], "Legs")
        self.assertEqual(planned_training_for_date("2026-05-20", profile=profile)["label"], "Push")
        self.assertEqual(planned_training_for_date("2026-05-23", profile=profile)["label"], "Chest")
        sunday = planned_training_for_date("2026-05-24", profile=profile)
        self.assertEqual(sunday["label"], "Run")
        self.assertTrue(sunday["is_run_day"])

    def test_dashboard_summary_treats_sunday_hevy_as_completed_run(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": "hevy-run",
                    "date": "2026-05-24",
                    "workout_type": "Strength",
                    "exercise": "Workout",
                    "sets": 1,
                    "reps": 1,
                    "weight": 0,
                    "duration_minutes": 28,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-run",
                    "source": "hevy",
                    "muscle_group": "",
                }
            ]
        )

        summary = summarize_training_day(training, "2026-05-24", profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)
        tile = _lift_performance_tile(training, "2026-05-24")

        self.assertEqual(summary["planned_workout"], "Sunday Run")
        self.assertEqual(summary["completed_summary"], "Run")
        self.assertEqual(summary["schedule_match"], "matched")
        self.assertTrue(tile["has_run"])
        self.assertFalse(tile["has_lift"])
        self.assertEqual(tile["sources"], ["Hevy"])
        self.assertIn("Completed: Run", tile["summary"])


if __name__ == "__main__":
    unittest.main()
