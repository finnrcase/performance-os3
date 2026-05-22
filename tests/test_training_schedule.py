import unittest

import pandas as pd

from src.training_schedule import DEFAULT_RECURRING_SCHEDULE_PROFILE, classify_workout, planned_training_for_date, summarize_training_day


class TrainingScheduleTest(unittest.TestCase):
    def test_default_split_profile_matches_requested_schedule(self):
        profile = DEFAULT_RECURRING_SCHEDULE_PROFILE
        self.assertEqual(planned_training_for_date("2026-05-18", profile=profile)["label"], "Pull")
        tuesday = planned_training_for_date("2026-05-19", profile=profile)
        self.assertEqual(tuesday["label"], "Legs")
        self.assertEqual(tuesday["split_type"], "leg_day_quad")
        self.assertEqual(planned_training_for_date("2026-05-20", profile=profile)["label"], "Push")
        friday = planned_training_for_date("2026-05-22", profile=profile)
        self.assertEqual(friday["label"], "Legs")
        self.assertEqual(friday["split_type"], "leg_day_hamstring")
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

    def test_classifier_distinguishes_quad_and_hamstring_leg_days(self):
        quad = classify_workout(
            [
                {"workout_type": "Legs", "exercise": "Pendulum Squat", "muscle_group": "Quads", "sets": 4, "reps": 8, "weight": 270, "source": "hevy"},
                {"workout_type": "Legs", "exercise": "Leg Extension", "muscle_group": "Quads", "sets": 4, "reps": 12, "weight": 130, "source": "hevy"},
            ]
        )
        hamstring = classify_workout(
            [
                {"workout_type": "Legs", "exercise": "Romanian Deadlift", "muscle_group": "Hamstrings", "sets": 4, "reps": 8, "weight": 225, "source": "hevy"},
                {"workout_type": "Legs", "exercise": "Lying Leg Curl", "muscle_group": "Hamstrings", "sets": 4, "reps": 12, "weight": 95, "source": "hevy"},
            ]
        )

        self.assertEqual(quad["kind"], "lift")
        self.assertEqual(quad["split_type"], "leg_day_quad")
        self.assertGreaterEqual(quad["split_confidence"], 0.7)
        self.assertIn("Pendulum Squat", quad["classification_reason"])
        self.assertEqual(hamstring["kind"], "lift")
        self.assertEqual(hamstring["split_type"], "leg_day_hamstring")
        self.assertGreaterEqual(hamstring["split_confidence"], 0.7)
        self.assertIn("Romanian Deadlift", hamstring["classification_reason"])

    def test_dashboard_summary_keeps_quad_and_hamstring_leg_plans_distinct(self):
        hamstring_rows = [
            {
                "workout_id": "hevy-ham",
                "date": "2026-05-19",
                "workout_type": "Legs",
                "exercise": "Romanian Deadlift",
                "muscle_group": "Hamstrings",
                "sets": 4,
                "reps": 8,
                "weight": 225,
                "source": "hevy",
            },
            {
                "workout_id": "hevy-ham",
                "date": "2026-05-19",
                "workout_type": "Legs",
                "exercise": "Lying Leg Curl",
                "muscle_group": "Hamstrings",
                "sets": 4,
                "reps": 12,
                "weight": 95,
                "source": "hevy",
            },
        ]
        tuesday = summarize_training_day(pd.DataFrame(hamstring_rows), "2026-05-19", profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)
        friday_rows = [{**row, "date": "2026-05-22"} for row in hamstring_rows]
        friday = summarize_training_day(pd.DataFrame(friday_rows), "2026-05-22", profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)

        self.assertEqual(tuesday["planned_split_type"], "leg_day_quad")
        self.assertEqual(tuesday["completed_split_types"], ["leg_day_hamstring"])
        self.assertEqual(tuesday["schedule_match"], "different")
        self.assertFalse(tuesday["split_match"])
        self.assertEqual(friday["planned_split_type"], "leg_day_hamstring")
        self.assertEqual(friday["completed_split_types"], ["leg_day_hamstring"])
        self.assertEqual(friday["schedule_match"], "matched")
        self.assertTrue(friday["split_match"])


if __name__ == "__main__":
    unittest.main()
