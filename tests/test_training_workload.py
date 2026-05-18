import unittest

import pandas as pd

from src.analytics.training_workload import analyze_hevy_performance_signal, analyze_training_workload
from src.goals import build_automatic_goals
from src.nutrition_targets import calculate_macro_targets


class TrainingWorkloadTest(unittest.TestCase):
    def test_analyzes_hevy_and_strava_workload_for_nutrition_targets(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": "hevy-1",
                    "date": "2026-05-01",
                    "workout_type": "Strength",
                    "muscle_group": "",
                    "exercise": "Bench Press",
                    "sets": 1,
                    "reps": 8,
                    "weight": 185,
                    "rpe": 8,
                    "duration_minutes": 60,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-1",
                    "source": "hevy",
                },
                {
                    "workout_id": "hevy-1",
                    "date": "2026-05-01",
                    "workout_type": "Strength",
                    "muscle_group": "",
                    "exercise": "Lat Pulldown",
                    "sets": 1,
                    "reps": 10,
                    "weight": 160,
                    "rpe": 8,
                    "duration_minutes": 0,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-1",
                    "source": "hevy",
                },
                {
                    "workout_id": "run-1",
                    "date": "2026-05-03",
                    "workout_type": "Run",
                    "muscle_group": "Cardio",
                    "exercise": "Morning Run",
                    "sets": 0,
                    "reps": 0,
                    "weight": 0,
                    "rpe": 0,
                    "duration_minutes": 30,
                    "notes": "Imported from Strava | strava_activity_id=run-1 | distance_miles=3.0 | pace_min_per_mile=10.0",
                    "source": "strava",
                },
            ]
        )

        workload = analyze_training_workload(training, bodyweight=160)

        self.assertGreater(workload["current"]["strength_workouts_per_week"], 0)
        self.assertGreater(workload["current"]["runs_per_week"], 0)
        self.assertGreater(workload["current"]["weekly_mileage"], 0)
        self.assertGreater(workload["current"]["cardio_calorie_demand"], 0)
        self.assertIn("Chest", workload["windows"]["28"]["hevy"]["hard_sets_by_muscle_group"])

    def test_targets_use_workload_data_without_manual_frequency_inputs(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": f"run-{index}",
                    "date": f"2026-05-{index + 1:02d}",
                    "workout_type": "Run",
                    "exercise": "Run",
                    "sets": 0,
                    "reps": 0,
                    "weight": 0,
                    "duration_minutes": 40,
                    "notes": f"Imported from Strava | strava_activity_id=run-{index} | distance_miles=4.0 | pace_min_per_mile=10.0",
                    "source": "strava",
                }
                for index in range(4)
            ]
        )
        body = pd.DataFrame([{"date": "2026-05-05", "bodyweight": 160}])
        goals = build_automatic_goals({"training_frequency_per_week": 0, "cardio_frequency_per_week": 0}, body_metrics_df=body, training_df=training)
        workload = analyze_training_workload(training, bodyweight=160)
        targets = calculate_macro_targets(goals, training_df=training, body_metrics_df=body, workload_data=workload)

        self.assertEqual(goals["goal_type"], "Lean Bulk")
        self.assertEqual(goals["aggressiveness"], "Conservative")
        self.assertGreater(goals["cardio_frequency_per_week"], 0)
        self.assertGreater(targets["workload_calorie_adjustment"], 0)
        self.assertGreater(targets["carb_grams"], 300)

    def test_hevy_run_counts_as_cardio_not_strength_workload(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": "hevy-run",
                    "date": "2026-04-26",
                    "workout_type": "Strength",
                    "muscle_group": "",
                    "exercise": "Treadmill",
                    "sets": 1,
                    "reps": 1,
                    "weight": 0,
                    "rpe": 0,
                    "duration_minutes": 30,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-run | workout_title=Sunday Run | distance_miles=3.0",
                    "source": "hevy",
                }
            ]
        )

        workload = analyze_training_workload(training, bodyweight=160)

        self.assertEqual(workload["current"]["strength_workouts_per_week"], 0)
        self.assertGreater(workload["current"]["runs_per_week"], 0)
        self.assertGreater(workload["current"]["weekly_mileage"], 0)
        self.assertGreater(workload["current"]["cardio_calorie_demand"], 0)

    def test_hevy_performance_signal_detects_multi_exercise_decline(self):
        rows = []
        for date, bench_weight, row_weight in [
            ("2026-04-03", 205, 185),
            ("2026-04-10", 210, 190),
            ("2026-05-01", 185, 165),
            ("2026-05-08", 180, 160),
        ]:
            rows.extend(
                [
                    {
                        "workout_id": f"push-{date}",
                        "date": date,
                        "workout_type": "Strength",
                        "exercise": "Bench Press",
                        "sets": 3,
                        "reps": 6,
                        "weight": bench_weight,
                        "rpe": 8,
                        "duration_minutes": 60,
                        "notes": "Imported from Hevy | hevy_workout_id=test",
                        "source": "hevy",
                    },
                    {
                        "workout_id": f"pull-{date}",
                        "date": date,
                        "workout_type": "Strength",
                        "exercise": "Barbell Row",
                        "sets": 3,
                        "reps": 8,
                        "weight": row_weight,
                        "rpe": 8,
                        "duration_minutes": 0,
                        "notes": "Imported from Hevy | hevy_workout_id=test",
                        "source": "hevy",
                    },
                ]
            )

        signal = analyze_hevy_performance_signal(pd.DataFrame(rows))

        self.assertEqual(signal["label"], "declining")
        self.assertIn(signal["confidence"], {"medium", "high"})
        self.assertGreaterEqual(len(signal["drivers"]), 2)
        self.assertTrue(any(driver["name"] == "Bench Press" for driver in signal["drivers"]))

    def test_hevy_performance_signal_does_not_overreact_to_one_bad_exercise(self):
        rows = []
        for date, bench_weight, row_weight in [
            ("2026-04-03", 205, 175),
            ("2026-04-10", 205, 180),
            ("2026-05-01", 180, 190),
            ("2026-05-08", 180, 195),
        ]:
            rows.extend(
                [
                    {
                        "workout_id": f"push-{date}",
                        "date": date,
                        "workout_type": "Strength",
                        "exercise": "Bench Press",
                        "sets": 3,
                        "reps": 6,
                        "weight": bench_weight,
                        "rpe": 8,
                        "duration_minutes": 60,
                        "notes": "Imported from Hevy | hevy_workout_id=test",
                        "source": "hevy",
                    },
                    {
                        "workout_id": f"pull-{date}",
                        "date": date,
                        "workout_type": "Strength",
                        "exercise": "Barbell Row",
                        "sets": 3,
                        "reps": 8,
                        "weight": row_weight,
                        "rpe": 8,
                        "duration_minutes": 0,
                        "notes": "Imported from Hevy | hevy_workout_id=test",
                        "source": "hevy",
                    },
                ]
            )

        signal = analyze_hevy_performance_signal(pd.DataFrame(rows))

        self.assertNotEqual(signal["label"], "declining")
        self.assertTrue(any(driver["signal"] == "declining" for driver in signal["drivers"]))
        self.assertTrue(any(driver["signal"] == "improving" for driver in signal["drivers"]))


if __name__ == "__main__":
    unittest.main()
