import unittest

import pandas as pd

from src.analytics.food_history import calculate_calorie_adherence


class FoodHistoryMissingDaysTest(unittest.TestCase):
    def test_adherence_counts_calendar_days_without_rows_as_missing_logs(self):
        summary = pd.DataFrame(
            [
                {
                    "date": "2026-05-12",
                    "total_calories": 2800,
                    "total_protein": 180,
                    "target_calories": 3000,
                    "target_protein": 170,
                    "adherence_score": 92,
                },
                {
                    "date": "2026-05-14",
                    "total_calories": 0,
                    "total_protein": 0,
                    "target_calories": 3000,
                    "target_protein": 170,
                    "adherence_score": None,
                },
            ]
        )

        adherence = calculate_calorie_adherence(summary, days=4, today="2026-05-15")

        self.assertEqual(adherence["logged_days"], 1)
        self.assertEqual(adherence["missing_days"], 3)
        self.assertEqual(adherence["average_calories"], 2800)
        self.assertEqual(adherence["confidence"], "low")
        self.assertIn("3 missing food log", adherence["data_quality_note"])


if __name__ == "__main__":
    unittest.main()
