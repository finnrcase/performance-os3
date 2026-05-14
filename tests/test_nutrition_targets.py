import unittest

import pandas as pd

from src.nutrition_targets import align_macro_calories, analyze_weight_trend, calculate_bodyweight_trend_signal, calculate_macro_targets


class NutritionTargetTest(unittest.TestCase):
    def test_lean_bulk_targets_are_protein_first_and_performance_carbed(self):
        goals = {
            "current_bodyweight": 160,
            "goal_bodyweight": 168,
            "timeline_weeks": 24,
            "goal_type": "Lean Bulk",
            "training_frequency_per_week": 4,
            "cardio_frequency_per_week": 2,
            "estimated_body_fat": None,
            "activity_level": "Moderate",
            "aggressiveness": "Conservative",
        }

        targets = calculate_macro_targets(goals)

        self.assertGreaterEqual(targets["target_calories"], 2750)
        self.assertLessEqual(targets["target_calories"], 2850)
        self.assertGreaterEqual(targets["protein_grams"], 175)
        self.assertLessEqual(targets["protein_grams"], 185)
        self.assertGreaterEqual(targets["fat_grams"], 65)
        self.assertGreaterEqual(targets["carb_grams"], 320)
        self.assertIn("High-carb", targets["carb_emphasis"])
        macro_calories = (targets["protein_grams"] * 4) + (targets["carb_grams"] * 4) + (targets["fat_grams"] * 9)
        self.assertEqual(targets["macro_calories"], macro_calories)
        self.assertLessEqual(abs(targets["calorie_macro_delta"]), 2)

    def test_macro_alignment_adjusts_carbs_to_closest_calorie_match(self):
        targets = align_macro_calories(target_calories=2838, protein_grams=176, fat_grams=69)

        macro_calories = (targets["protein_grams"] * 4) + (targets["carb_grams"] * 4) + (targets["fat_grams"] * 9)
        self.assertEqual(targets["macro_calories"], macro_calories)
        self.assertEqual(targets["carb_grams"], 378)
        self.assertLessEqual(abs(targets["calorie_macro_delta"]), 2)

    def test_weight_trend_uses_lean_bulk_target_range_for_adjustment(self):
        dates = pd.date_range("2026-05-01", periods=14, freq="D")
        body_metrics = pd.DataFrame(
            {
                "date": dates.astype(str),
                "bodyweight": [160.0 + (index * 0.02) for index in range(14)],
            }
        )
        goals = {
            "current_bodyweight": 160,
            "goal_bodyweight": 168,
            "timeline_weeks": 24,
            "goal_type": "Lean Bulk",
            "training_frequency_per_week": 4,
            "cardio_frequency_per_week": 2,
            "activity_level": "Moderate",
            "aggressiveness": "Conservative",
        }

        feedback = analyze_weight_trend(body_metrics, goals)

        self.assertEqual(feedback["status"], "Gaining too slowly")
        self.assertIn("150", feedback["suggested_adjustment"])
        self.assertEqual(feedback["confidence"], "high")
        self.assertIsNotNone(feedback["current_7_day_avg"])
        self.assertIsNotNone(feedback["previous_7_day_avg"])
        self.assertEqual(feedback["target_weekly_change_low"], 0.2)
        self.assertEqual(feedback["target_weekly_change_high"], 0.4)

    def test_weight_trend_reduces_calories_when_gain_is_too_fast(self):
        dates = pd.date_range("2026-05-01", periods=14, freq="D")
        body_metrics = pd.DataFrame(
            {
                "date": dates.astype(str),
                "bodyweight": [160.0 + (index * 0.18) for index in range(14)],
            }
        )
        goals = {
            "current_bodyweight": 160,
            "goal_bodyweight": 164.8,
            "timeline_weeks": 24,
            "goal_type": "Lean Bulk",
            "training_frequency_per_week": 4,
            "cardio_frequency_per_week": 2,
            "activity_level": "Moderate",
            "aggressiveness": "Conservative",
        }

        signal = calculate_bodyweight_trend_signal(body_metrics, goals)
        targets = calculate_macro_targets(goals, body_metrics_df=body_metrics)

        self.assertEqual(signal["status"], "gaining too fast")
        self.assertLess(signal["calorie_adjustment"], 0)
        self.assertLess(targets["target_calories"], 2750)


if __name__ == "__main__":
    unittest.main()
