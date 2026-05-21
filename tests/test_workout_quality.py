import unittest

import pandas as pd

from src.analytics.workout_quality import calculate_workout_quality


class WorkoutQualityTest(unittest.TestCase):
    def test_missing_workout_state(self):
        result = calculate_workout_quality(pd.DataFrame(), today="2026-05-14")

        self.assertEqual(result["status"], "missing")
        self.assertIsNone(result["score"])
        self.assertEqual(result["color"], "gray")

    def test_low_history_hevy_workout_gets_score_with_low_confidence(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": "today",
                    "date": "2026-05-14",
                    "workout_type": "Strength",
                    "exercise": "Bench Press",
                    "sets": 1,
                    "reps": 8,
                    "weight": 185,
                    "duration_minutes": 60,
                    "notes": "Imported from Hevy | hevy_workout_id=today | workout_title=Push",
                    "source": "hevy",
                    "muscle_group": "Chest",
                }
            ]
        )

        result = calculate_workout_quality(training, today="2026-05-14")

        self.assertEqual(result["status"], "low_history")
        self.assertEqual(result["score"], 6.0)
        self.assertEqual(result["confidence"], "low")

    def test_hevy_quality_scores_improved_similar_session(self):
        rows = []
        for workout_id, date, bench, row in [
            ("old-1", "2026-04-23", 185, 155),
            ("old-2", "2026-04-30", 190, 160),
            ("old-3", "2026-05-07", 190, 160),
            ("today", "2026-05-14", 205, 175),
        ]:
            rows.extend(
                [
                    {
                        "workout_id": workout_id,
                        "date": date,
                        "workout_type": "Strength",
                        "exercise": "Bench Press",
                        "sets": 1,
                        "reps": 8,
                        "weight": bench,
                        "duration_minutes": 60,
                        "notes": f"Imported from Hevy | hevy_workout_id={workout_id} | workout_title=Push",
                        "source": "hevy",
                        "muscle_group": "Chest",
                    },
                    {
                        "workout_id": workout_id,
                        "date": date,
                        "workout_type": "Strength",
                        "exercise": "Barbell Row",
                        "sets": 1,
                        "reps": 8,
                        "weight": row,
                        "duration_minutes": 0,
                        "notes": f"Imported from Hevy | hevy_workout_id={workout_id} | workout_title=Push",
                        "source": "hevy",
                        "muscle_group": "Back",
                    },
                ]
            )
        training = pd.DataFrame(rows)

        result = calculate_workout_quality(training, today="2026-05-14")

        self.assertEqual(result["status"], "scored")
        self.assertGreaterEqual(result["score"], 7)
        self.assertIn(result["color"], {"green", "bright_green"})
        self.assertIn("improved", result["explanation"])

    def test_strava_quality_scores_faster_run(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": f"run-{index}",
                    "date": date,
                    "workout_type": "Run",
                    "exercise": "Easy Run",
                    "sets": 0,
                    "reps": 0,
                    "weight": 0,
                    "duration_minutes": duration,
                    "notes": f"Imported from Strava | strava_activity_id=run-{index} | distance_miles=3.0 | pace_min_per_mile={pace}",
                    "source": "strava",
                    "muscle_group": "Cardio",
                }
                for index, (date, duration, pace) in enumerate(
                    [
                        ("2026-05-01", 30, 10.0),
                        ("2026-05-05", 30, 10.0),
                        ("2026-05-10", 30, 10.0),
                        ("2026-05-14", 27, 9.0),
                    ]
                )
            ]
        )

        result = calculate_workout_quality(training, today="2026-05-14")

        self.assertEqual(result["source"], "strava")
        self.assertGreater(result["score"], 7)
        self.assertIn("pace improved", result["explanation"])

    def test_sunday_hevy_run_counts_as_workout_quality(self):
        training = pd.DataFrame(
            [
                {
                    "workout_id": "hevy-run",
                    "date": "2026-04-26",
                    "workout_type": "Strength",
                    "exercise": "Treadmill",
                    "sets": 1,
                    "reps": 1,
                    "weight": 0,
                    "duration_minutes": 30,
                    "notes": "Imported from Hevy | hevy_workout_id=hevy-run | workout_title=Sunday Run | distance_miles=3.0 | pace_min_per_mile=10.0",
                    "source": "hevy",
                    "muscle_group": "",
                }
            ]
        )

        result = calculate_workout_quality(training, today="2026-04-26")

        self.assertEqual(result["status"], "low_history")
        self.assertEqual(result["source"], "hevy")
        self.assertEqual(result["score"], 6.0)


if __name__ == "__main__":
    unittest.main()
