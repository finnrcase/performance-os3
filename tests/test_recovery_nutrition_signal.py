import unittest

import pandas as pd

from src.analytics.recovery_engine import analyze_recovery_signal
from src.nutrition_targets import calculate_macro_targets
from src.optimization.lean_bulk_engine import generate_lean_bulk_calorie_recommendation


class RecoveryNutritionSignalTest(unittest.TestCase):
    def test_recovery_signal_classifies_poor_with_sleep_hrv_and_fatigue_drivers(self):
        dates = pd.date_range("2026-05-01", periods=14, freq="D")
        recovery = pd.DataFrame(
            {
                "date": dates.astype(str),
                "sleep_hours": [7.8] * 7 + [5.9] * 7,
                "sleep_quality": [8] * 7 + [4] * 7,
                "fatigue": [4] * 7 + [8] * 7,
                "soreness": [4] * 7 + [8] * 7,
                "stress": [4] * 7 + [7] * 7,
                "motivation": [8] * 7 + [4] * 7,
                "resting_hr": [55] * 7 + [63] * 7,
                "hrv": [70] * 7 + [54] * 7,
            }
        )

        signal = analyze_recovery_signal(recovery)

        self.assertEqual(signal["status"], "poor")
        self.assertIn(signal["confidence"], {"medium", "high"})
        driver_names = {driver["name"] for driver in signal["drivers"]}
        self.assertIn("Sleep duration", driver_names)
        self.assertIn("HRV", driver_names)
        self.assertIn("Resting heart rate", driver_names)
        self.assertIn("carb-focused", signal["nutrition_implication"])

    def test_poor_recovery_slow_gain_can_support_small_carb_focused_increase(self):
        dates = pd.date_range("2026-05-01", periods=14, freq="D")
        body = pd.DataFrame({"date": dates.astype(str), "bodyweight": [160 + index * 0.02 for index in range(14)]})
        recovery = pd.DataFrame(
            {
                "date": dates.astype(str),
                "sleep_hours": [5.8] * 14,
                "sleep_quality": [4] * 14,
                "fatigue": [8] * 14,
                "soreness": [8] * 14,
                "stress": [7] * 14,
                "motivation": [4] * 14,
                "resting_hr": [63] * 14,
                "hrv": [55] * 14,
            }
        )
        goals = {
            "current_bodyweight": 160,
            "goal_bodyweight": 168,
            "timeline_weeks": 24,
            "goal_type": "Lean Bulk",
            "training_frequency_per_week": 4,
            "cardio_frequency_per_week": 1,
            "activity_level": "Moderate",
            "aggressiveness": "Conservative",
        }

        targets = calculate_macro_targets(goals, body_metrics_df=body, recovery_df=recovery)

        self.assertEqual(targets["recovery_signal"]["status"], "poor")
        self.assertGreaterEqual(targets["historical_calorie_adjustment"], 150)
        self.assertIn("Poor recovery", targets["carb_emphasis"])

    def test_poor_recovery_fast_gain_does_not_add_calories_automatically(self):
        dates = pd.date_range("2026-05-01", periods=14, freq="D")
        body = pd.DataFrame({"date": dates.astype(str), "bodyweight": [160 + index * 0.18 for index in range(14)]})
        recovery = pd.DataFrame(
            {
                "date": dates.astype(str),
                "sleep_hours": [5.8] * 14,
                "sleep_quality": [4] * 14,
                "fatigue": [8] * 14,
                "soreness": [8] * 14,
                "stress": [7] * 14,
                "motivation": [4] * 14,
            }
        )
        goals = {
            "current_bodyweight": 160,
            "goal_bodyweight": 168,
            "timeline_weeks": 24,
            "goal_type": "Lean Bulk",
            "training_frequency_per_week": 4,
            "cardio_frequency_per_week": 1,
            "activity_level": "Moderate",
            "aggressiveness": "Conservative",
        }

        decision = generate_lean_bulk_calorie_recommendation(
            body_metrics_df=body,
            nutrition_df=pd.DataFrame(),
            training_df=pd.DataFrame(),
            recovery_df=recovery,
            user_goals=goals,
        )

        self.assertEqual(decision["details"]["recovery_signal"]["status"], "poor")
        self.assertNotEqual(decision["recommendation"], "increase")
        self.assertLessEqual(decision["calorie_change"], 0)


if __name__ == "__main__":
    unittest.main()
