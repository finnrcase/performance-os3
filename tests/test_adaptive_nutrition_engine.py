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


CURRENT = {"target_calories": 2800, "protein_grams": 176, "carb_grams": 376, "fat_grams": 68}


def _body(step: float) -> pd.DataFrame:
    dates = pd.date_range("2026-05-01", periods=14, freq="D")
    return pd.DataFrame({"date": dates.astype(str), "bodyweight": [160 + index * step for index in range(14)]})


def _body_comp(weight_step: float, body_fat_step: float = 0, days: int = 28, start="2026-04-17") -> pd.DataFrame:
    dates = pd.date_range(start, periods=days, freq="D")
    return pd.DataFrame(
        {
            "date": dates.astype(str),
            "bodyweight": [160 + index * weight_step for index in range(days)],
            "estimated_body_fat": [12 + index * body_fat_step for index in range(days)],
        }
    )


def _nutrition(days: int = 28, start="2026-04-17", calories=2800, protein=178, carbs=360, fat=67) -> pd.DataFrame:
    dates = pd.date_range(start, periods=days, freq="D")
    return pd.DataFrame(
        {
            "date": dates.astype(str),
            "calories": [calories for _ in dates],
            "protein": [protein for _ in dates],
            "carbs": [carbs for _ in dates],
            "fat": [fat for _ in dates],
        }
    )


def _recovery(days: int = 14, start="2026-05-01", quality="normal") -> pd.DataFrame:
    dates = pd.date_range(start, periods=days, freq="D")
    if quality == "poor":
        values = {"sleep_hours": 5.2, "sleep_quality": 4, "fatigue": 9, "soreness": 8, "stress": 8, "motivation": 4}
    else:
        values = {"sleep_hours": 7.8, "sleep_quality": 8, "fatigue": 3, "soreness": 3, "stress": 3, "motivation": 8}
    return pd.DataFrame({"date": dates.astype(str), **{key: [value for _ in dates] for key, value in values.items()}})


def _training_series(kind: str = "declining") -> pd.DataFrame:
    if kind == "improving":
        values = [("2026-04-03", 185, 165), ("2026-04-10", 190, 170), ("2026-05-01", 205, 185), ("2026-05-08", 210, 190)]
    elif kind == "stable":
        values = [("2026-04-03", 205, 185), ("2026-04-10", 205, 185), ("2026-05-01", 205, 185), ("2026-05-08", 205, 185)]
    elif kind == "one_bad":
        values = [("2026-04-03", 200, 180), ("2026-04-10", 202, 182), ("2026-05-01", 204, 184), ("2026-05-08", 178, 160)]
    else:
        values = [("2026-04-03", 205, 185), ("2026-04-10", 210, 190), ("2026-05-01", 185, 165), ("2026-05-08", 180, 160)]
    rows = []
    for date, bench_weight, row_weight in values:
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


def _weekday_training() -> pd.DataFrame:
    rows = []
    for week in range(4):
        tuesday = pd.Timestamp("2026-04-07") + pd.Timedelta(days=week * 7)
        thursday = tuesday + pd.Timedelta(days=2)
        rows.append(
            {
                "workout_id": f"tue-{week}",
                "date": tuesday.date().isoformat(),
                "workout_type": "Strength",
                "exercise": "Squat",
                "sets": 5,
                "reps": 6,
                "weight": 225,
                "rpe": 8,
                "duration_minutes": 70,
                "source": "hevy",
                "notes": "Imported from Hevy | hevy_workout_id=tuesday",
            }
        )
        rows.append(
            {
                "workout_id": f"thu-{week}",
                "date": thursday.date().isoformat(),
                "workout_type": "Strength",
                "exercise": "Bench Press",
                "sets": 3,
                "reps": 6,
                "weight": 135,
                "rpe": 8,
                "duration_minutes": 50,
                "source": "hevy",
                "notes": "Imported from Hevy | hevy_workout_id=thursday",
            }
        )
    return pd.DataFrame(rows)


def _weekday_nutrition() -> pd.DataFrame:
    dates = pd.date_range("2026-04-07", periods=28, freq="D")
    rows = []
    for date in dates:
        is_tuesday = date.day_name() == "Tuesday"
        rows.append(
            {
                "date": date.date().isoformat(),
                "calories": 2950 if is_tuesday else 2750,
                "protein": 180,
                "carbs": 390 if is_tuesday else 285,
                "fat": 70,
            }
        )
    return pd.DataFrame(rows)


def _sunday_run_training() -> pd.DataFrame:
    rows = []
    for week in range(4):
        sunday = pd.Timestamp("2026-04-05") + pd.Timedelta(days=week * 7)
        rows.append(
            {
                "workout_id": f"run-{week}",
                "date": sunday.date().isoformat(),
                "workout_type": "Run",
                "exercise": "Run",
                "sets": 0,
                "reps": 0,
                "weight": 0,
                "rpe": 0,
                "duration_minutes": 45,
                "source": "strava",
                "notes": "strava_activity_id=test | distance_miles=5 | pace_min_per_mile=8.5 | calories=520",
            }
        )
    return pd.DataFrame(rows)


class AdaptiveNutritionEngineTest(unittest.TestCase):
    def test_macro_math_protein_first_fat_floor_and_carbs_remaining(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.06, 0),
            nutrition_df=_nutrition(),
            training_df=_training_series("improving"),
            recovery_df=_recovery(),
            current_targets=CURRENT,
            today="2026-05-14",
        )

        targets = recommendation["recommendedTargets"]
        self.assertLessEqual(abs(targets["macro_calories"] - targets["target_calories"]), 2)
        self.assertGreaterEqual(targets["protein_grams"], 160)
        self.assertGreaterEqual(targets["fat_grams"], 48)
        self.assertEqual(targets["carb_grams"], round((targets["target_calories"] - targets["protein_grams"] * 4 - targets["fat_grams"] * 9) / 4))

    def test_declining_performance_and_slow_gain_increases_carbs(self):
        current = {"target_calories": 2750, "protein_grams": 176, "carb_grams": 360, "fat_grams": 68}

        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body(0.02),
            nutrition_df=pd.DataFrame(),
            training_df=_training_series("declining"),
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
            training_df=_training_series("declining"),
            recovery_df=pd.DataFrame(),
            current_targets=current,
        )

        self.assertEqual(recommendation["signals"]["weight"]["status"], "gaining too fast")
        self.assertLessEqual(recommendation["calorieAdjustment"], 0)
        self.assertTrue(any("blocked" in reason for reason in recommendation["reasoning"]))

    def test_lean_mass_increase_fat_stable_strength_improving_maintains(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.06, 0),
            nutrition_df=_nutrition(),
            training_df=_training_series("improving"),
            recovery_df=_recovery(),
            current_targets=CURRENT,
            today="2026-05-14",
        )

        self.assertEqual(recommendation["calorieAdjustment"], 0)
        self.assertIn(recommendation["signals"]["bodyComposition"]["lean_gain_quality"], {"lean mass improving", "stable composition"})

    def test_fat_gain_with_flat_strength_reduces_calories(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.14, 0.08),
            nutrition_df=_nutrition(calories=3050, carbs=410),
            training_df=_training_series("stable"),
            recovery_df=_recovery(),
            current_targets={**CURRENT, "target_calories": 3000, "carb_grams": 425},
            today="2026-05-14",
        )

        self.assertLess(recommendation["calorieAdjustment"], 0)
        self.assertIn("fat gain", recommendation["signals"]["bodyComposition"]["lean_gain_quality"])

    def test_body_fat_missing_lowers_confidence_and_warns(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals={**GOALS, "estimated_body_fat": None},
            body_metrics_df=_body(0.06),
            nutrition_df=_nutrition(days=14, start="2026-05-01"),
            training_df=_training_series("improving"),
            recovery_df=_recovery(),
            current_targets=CURRENT,
        )

        self.assertNotEqual(recommendation["confidence"], "high")
        self.assertTrue(any("Body fat" in warning or "body fat" in warning for warning in recommendation["warnings"] + recommendation["missingDataWarnings"]))

    def test_isolated_bad_workout_does_not_trigger_major_change(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.05, 0),
            nutrition_df=_nutrition(),
            training_df=_training_series("one_bad"),
            recovery_df=_recovery(),
            current_targets=CURRENT,
            today="2026-05-14",
        )

        self.assertLessEqual(abs(recommendation["calorieAdjustment"]), 75)

    def test_poor_recovery_lowers_confidence_and_fat_gain_does_not_increase(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.14, 0.08),
            nutrition_df=_nutrition(calories=3050),
            training_df=_training_series("declining"),
            recovery_df=_recovery(quality="poor"),
            current_targets={**CURRENT, "target_calories": 3000},
            today="2026-05-14",
        )

        self.assertIn(recommendation["confidence"], {"low", "medium"})
        self.assertLessEqual(recommendation["calorieAdjustment"], 0)

    def test_poor_recovery_slow_gain_can_suggest_small_carb_bump(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.02, 0),
            nutrition_df=_nutrition(calories=2700, carbs=320),
            training_df=_training_series("declining"),
            recovery_df=_recovery(quality="poor"),
            current_targets=CURRENT,
            today="2026-05-14",
        )

        self.assertGreaterEqual(recommendation["calorieAdjustment"], 50)
        self.assertGreater(recommendation["macroChanges"]["carbs"], 0)
        self.assertTrue(any("recovery" in reason.lower() or "sleep" in reason.lower() for reason in recommendation["reasoning"] + recommendation["warnings"]))

    def test_tuesday_high_carb_response_detection_works(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.04, 0, days=28, start="2026-04-07"),
            nutrition_df=_weekday_nutrition(),
            training_df=_weekday_training(),
            recovery_df=_recovery(days=28, start="2026-04-07"),
            current_targets=CURRENT,
            today="2026-04-28",
        )

        self.assertGreaterEqual(recommendation["dayOfWeekAdjustment"]["carb_delta"], 25)
        self.assertTrue(any("Tuesday sessions" in trend for trend in recommendation["detectedTrends"]))

    def test_sunday_run_only_lower_calorie_logic_works(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=_body_comp(0.04, 0, days=28, start="2026-04-05"),
            nutrition_df=_nutrition(days=28, start="2026-04-05"),
            training_df=_sunday_run_training(),
            recovery_df=_recovery(days=28, start="2026-04-05"),
            current_targets=CURRENT,
            today="2026-04-26",
        )

        self.assertLessEqual(recommendation["dayOfWeekAdjustment"]["calorie_delta"], -100)
        self.assertTrue(any("Sunday is usually run-only" in trend for trend in recommendation["detectedTrends"]))

    def test_missing_data_warnings_are_explicit(self):
        recommendation = build_adaptive_nutrition_recommendation(
            user_goals=GOALS,
            body_metrics_df=pd.DataFrame([{"date": "2026-05-01", "bodyweight": 160}]),
            nutrition_df=pd.DataFrame(),
            training_df=pd.DataFrame(),
            recovery_df=pd.DataFrame(),
            current_targets=CURRENT,
            today="2026-05-14",
        )

        self.assertEqual(recommendation["confidence"], "low")
        self.assertEqual(recommendation["calorieAdjustment"], 0)
        self.assertEqual(recommendation["caloriesTarget"], CURRENT["target_calories"])
        self.assertTrue(any("food" in warning.lower() for warning in recommendation["missingDataWarnings"]))
        self.assertTrue(any("sleep" in warning.lower() for warning in recommendation["missingDataWarnings"]))
        self.assertTrue(any("hevy" in warning.lower() or "lifting" in warning.lower() for warning in recommendation["missingDataWarnings"]))


if __name__ == "__main__":
    unittest.main()
