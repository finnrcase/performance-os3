import unittest

import pandas as pd

from src.optimization.adaptive_nutrition_engine import build_adaptive_nutrition_recommendation


GOALS = {
    "current_bodyweight": 160,
    "goal_bodyweight": 168,
    "timeline_weeks": 24,
    "goal_type": "Lean Bulk",
    "training_frequency_per_week": 4,
    "cardio_frequency_per_week": 1,
    "activity_level": "Moderate",
    "aggressiveness": "Conservative",
}


def _body(step: float) -> pd.DataFrame:
    dates = pd.date_range("2026-05-01", periods=14, freq="D")
    return pd.DataFrame({"date": dates.astype(str), "bodyweight": [160 + index * step for index in range(14)]})


def _declining_training() -> pd.DataFrame:
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
    return pd.DataFrame(rows)


class AdaptiveNutritionEngineTest(unittest.TestCase):
    def test_declining_performance_and_slow_gain_increases_carbs(self):
        current = {"target_calories": 2750, "protein_grams": 176, "carb_grams": 360, "fat_grams": 68}

        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body(0.02),
            nutrition_df=pd.DataFrame(),
            training_df=_declining_training(),
            recovery_df=pd.DataFrame(),
            current_targets=current,
        )

        self.assertEqual(recommendation["signals"]["weight"]["status"], "gaining too slowly")
        self.assertEqual(recommendation["signals"]["performance"]["label"], "declining")
        self.assertGreaterEqual(recommendation["calorieAdjustment"], 100)
        self.assertGreater(recommendation["macroChanges"]["carbs"], 0)

    def test_fast_gain_blocks_performance_driven_increase(self):
        current = {"target_calories": 2850, "protein_grams": 176, "carb_grams": 385, "fat_grams": 68}

        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body(0.18),
            nutrition_df=pd.DataFrame(),
            training_df=_declining_training(),
            recovery_df=pd.DataFrame(),
            current_targets=current,
        )

        self.assertEqual(recommendation["signals"]["weight"]["status"], "gaining too fast")
        self.assertLessEqual(recommendation["calorieAdjustment"], 0)
        self.assertTrue(any("blocked" in reason for reason in recommendation["reasoning"]))

    def test_low_confidence_keeps_targets_stable(self):
        current = {"target_calories": 2800, "protein_grams": 176, "carb_grams": 376, "fat_grams": 68}

        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=pd.DataFrame([{"date": "2026-05-01", "bodyweight": 160}]),
            nutrition_df=pd.DataFrame(),
            training_df=pd.DataFrame(),
            recovery_df=pd.DataFrame(),
            current_targets=current,
        )

        self.assertEqual(recommendation["confidence"], "low")
        self.assertEqual(recommendation["calorieAdjustment"], 0)
        self.assertEqual(recommendation["caloriesTarget"], current["target_calories"])


if __name__ == "__main__":
    unittest.main()
