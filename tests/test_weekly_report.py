import unittest

import pandas as pd

from src.analytics.weekly_report import generate_weekly_performance_report


class WeeklyPerformanceReportTests(unittest.TestCase):
    def test_empty_report_handles_missing_data(self):
        report = generate_weekly_performance_report(
            body_metrics_df=pd.DataFrame(),
            nutrition_df=pd.DataFrame(),
            training_df=pd.DataFrame(),
            recovery_df=pd.DataFrame(),
            sleep_df=pd.DataFrame(),
            today="2026-05-13",
        )

        self.assertEqual(report["status"], "learning")
        self.assertTrue(report["rows"])
        self.assertIn("Keep targets stable", report["recommendation"])

    def test_report_summarizes_weight_nutrition_training_and_recovery(self):
        dates = pd.date_range("2026-04-30", periods=14, freq="D")
        body = pd.DataFrame({"date": dates.astype(str), "bodyweight": [180 + index * 0.05 for index in range(14)]})
        nutrition = pd.DataFrame(
            {
                "date": dates[-7:].astype(str),
                "total_calories": [2820, 2850, 2810, 2875, 2840, 2860, 2830],
                "total_protein": [188, 190, 184, 192, 186, 190, 189],
                "total_carbs": [350, 360, 342, 365, 355, 358, 352],
                "total_fat": [72, 74, 71, 75, 73, 74, 72],
            }
        )
        training = pd.DataFrame(
            [
                {"date": "2026-05-06", "workout_id": "old-1", "workout_type": "strength", "exercise": "Bench Press", "sets": 1, "reps": 5, "weight": 200, "duration_minutes": 60, "notes": "", "source": "hevy"},
                {"date": "2026-05-12", "workout_id": "new-1", "workout_type": "strength", "exercise": "Bench Press", "sets": 1, "reps": 5, "weight": 210, "duration_minutes": 62, "notes": "", "source": "hevy"},
                {"date": "2026-05-13", "workout_id": "run-1", "workout_type": "run", "exercise": "Run", "sets": 0, "reps": 0, "weight": 0, "duration_minutes": 30, "notes": "distance_miles=3.1|pace_min_per_mile=8.5", "source": "strava"},
            ]
        )
        sleep = pd.DataFrame(
            {
                "date": dates[-7:].astype(str),
                "durationMinutes": [450, 460, 470, 455, 465, 480, 475],
                "efficiencyPercent": [91, 90, 92, 88, 89, 93, 91],
            }
        )

        report = generate_weekly_performance_report(
            body_metrics_df=body,
            nutrition_df=nutrition,
            training_df=training,
            recovery_df=pd.DataFrame(),
            sleep_df=sleep,
            today="2026-05-13",
        )

        labels = {row["label"] for row in report["rows"]}
        self.assertEqual(report["status"], "ready")
        self.assertIn("Weight", labels)
        self.assertIn("Calories", labels)
        self.assertIn("Macros", labels)
        self.assertIn("Training", labels)
        self.assertIn("Sleep/recovery", labels)
        self.assertIn("Bench Press", report["best_trend"])
        self.assertTrue(report["recommendation"])


if __name__ == "__main__":
    unittest.main()
