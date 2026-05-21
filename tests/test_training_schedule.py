import unittest

import pandas as pd

from src.training_schedule import DEFAULT_RECURRING_SCHEDULE_PROFILE, classify_workout, planned_training_for_date, summarize_training_day


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

    def test_dashboard_summary_does_not_treat_sunday_hevy_lift_as_run_without_cardio_evidence(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": "hevy-push",
                    "date": "2026-05-24",
                    "workout_type": "Run",
                    "exercise": "Overhead Press",
                    "sets": 1,
                    "reps": 8,
                    "weight": 95,
                    "duration_minutes": 28,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-push | classification=running_cardio",
                    "source": "hevy",
                    "muscle_group": "Shoulders",
                }
            ]
        )

        summary = summarize_training_day(training, "2026-05-24", profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)

        self.assertEqual(summary["planned_workout"], "Sunday Run")
        self.assertEqual(summary["completed_summary"], "Push")
        self.assertEqual(summary["schedule_match"], "different")
        self.assertFalse(summary["has_run"])
        self.assertTrue(summary["has_lift"])
        self.assertEqual(summary["sources"], ["Hevy"])

    def test_classifier_marks_hevy_run_only_with_clear_cardio_metadata(self):
        result = classify_workout(
            [
                {
                    "workout_id": "hevy-run",
                    "date": "2026-05-24",
                    "workout_type": "Sunday Run",
                    "exercise": "Treadmill Run",
                    "sets": 0,
                    "reps": 0,
                    "weight": 0,
                    "duration_minutes": 28,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-run | distance_miles=3.2 | pace_min_per_mile=8.75",
                    "source": "hevy",
                    "muscle_group": "Cardio",
                }
            ]
        )

        self.assertEqual(result["kind"], "run")
        self.assertTrue(result["has_run"])
        self.assertFalse(result["has_lift"])


if __name__ == "__main__":
    unittest.main()
