import unittest

import pandas as pd

from src.analytics.personal_response_learning import generate_personal_response_learning


class PersonalResponseLearningTest(unittest.TestCase):
    def test_low_data_returns_learning_state(self):
        result = generate_personal_response_learning(
            body_metrics_df=pd.DataFrame([{"date": "2026-05-01", "bodyweight": 160}]),
            nutrition_df=pd.DataFrame(),
            training_df=pd.DataFrame(),
            recovery_df=pd.DataFrame(),
            sleep_df=pd.DataFrame(),
            current_targets={"target_calories": 2800},
        )

        self.assertEqual(result["status"], "learning")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["insights"], [])

    def test_detects_personal_carb_strength_pattern(self):
        nutrition_rows = []
        training_rows = []
        body_rows = []
        recovery_rows = []
        sleep_rows = []
        for week in range(8):
            date = pd.Timestamp("2026-03-02") + pd.Timedelta(days=week * 7)
            high_carb = week % 2 == 1
            carbs = 380 if high_carb else 260
            bench_weight = 210 if high_carb else 185
            nutrition_rows.append(
                {
                    "date": date.date().isoformat(),
                    "total_calories": 2850,
                    "total_protein": 185,
                    "total_carbs": carbs,
                    "total_fat": 72,
                    "adherence_score": 90,
                }
            )
            training_rows.append(
                {
                    "workout_id": f"w-{week}",
                    "date": date.date().isoformat(),
                    "workout_type": "Strength",
                    "exercise": "Bench Press",
                    "sets": 3,
                    "reps": 6,
                    "weight": bench_weight,
                    "duration_minutes": 60,
                    "notes": "Imported from Hevy | hevy_workout_id=test",
                    "source": "hevy",
                }
            )
            body_rows.append({"date": date.date().isoformat(), "bodyweight": 160 + week * 0.25})
            recovery_rows.append(
                {
                    "date": date.date().isoformat(),
                    "sleep_hours": 7.5,
                    "sleep_quality": 8,
                    "fatigue": 4,
                    "soreness": 4,
                    "stress": 4,
                    "motivation": 8,
                    "resting_hr": 55,
                    "hrv": 70,
                }
            )
            sleep_rows.append(
                {
                    "date": date.date().isoformat(),
                    "durationMinutes": 450,
                    "hrv": 70,
                }
            )

        result = generate_personal_response_learning(
            body_metrics_df=pd.DataFrame(body_rows),
            nutrition_df=pd.DataFrame(nutrition_rows),
            training_df=pd.DataFrame(training_rows),
            recovery_df=pd.DataFrame(recovery_rows),
            sleep_df=pd.DataFrame(sleep_rows),
            current_targets={"target_calories": 2850},
        )

        self.assertEqual(result["status"], "ready")
        titles = [insight["title"] for insight in result["insights"]]
        self.assertIn("Carbs and lifting response", titles)
        carb_insight = next(insight for insight in result["insights"] if insight["title"] == "Carbs and lifting response")
        self.assertIn("above", carb_insight["explanation"])
        self.assertIn(carb_insight["confidence"], {"medium", "high"})


if __name__ == "__main__":
    unittest.main()
