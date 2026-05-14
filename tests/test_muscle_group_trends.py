import unittest

import pandas as pd

from src.analytics.exercise_muscle_map import get_exercise_muscle_group
from src.analytics.strength_trends import calculate_estimated_1rm, calculate_muscle_group_trend


def row(date, exercise, weight, reps, sets=1, muscle_group=""):
    return {
        "workout_id": f"{date}-{exercise}",
        "date": date,
        "workout_type": "Strength",
        "muscle_group": muscle_group,
        "exercise": exercise,
        "set_number": 1,
        "sets": sets,
        "reps": reps,
        "weight": weight,
        "rpe": 8,
        "duration_minutes": 0,
        "notes": "",
        "source": "hevy",
        "external_id": f"{date}-{exercise}",
    }


class MuscleGroupTrendTest(unittest.TestCase):
    def test_epley_estimated_1rm(self):
        self.assertEqual(calculate_estimated_1rm(100, 5), 116.7)
        self.assertEqual(calculate_estimated_1rm(0, 5), 0.0)

    def test_mapping_and_unknown_exercises(self):
        self.assertEqual(get_exercise_muscle_group("Bench Press")["primaryMuscleGroup"], "Chest")
        self.assertEqual(get_exercise_muscle_group("Lat Pulldown")["primaryMuscleGroup"], "Back")
        unknown = get_exercise_muscle_group("Mystery Machine Raise")
        self.assertEqual(unknown["primaryMuscleGroup"], "Other")
        self.assertEqual(unknown["muscleGroupSource"], "unknown")

    def test_hevy_muscle_group_metadata_wins_over_mapping(self):
        result = get_exercise_muscle_group("Bench Press", {"muscle_group": "Back"})
        self.assertEqual(result["primaryMuscleGroup"], "Back")
        self.assertEqual(result["muscleGroupSource"], "hevy")

    def test_muscle_group_index_normalizes_exercises_before_aggregation(self):
        training = pd.DataFrame(
            [
                row("2026-01-01", "Bench Press", 100, 5, sets=3),
                row("2026-01-01", "Chest Fly", 20, 12, sets=2),
                row("2026-01-08", "Bench Press", 100, 5, sets=3),
                row("2026-01-08", "Chest Fly", 20, 12, sets=2),
                row("2026-01-15", "Bench Press", 100, 5, sets=3),
                row("2026-01-15", "Chest Fly", 20, 12, sets=2),
                row("2026-02-01", "Bench Press", 110, 5, sets=3),
                row("2026-02-01", "Chest Fly", 22, 12, sets=2),
            ]
        )
        result = calculate_muscle_group_trend(training, date_range="all", muscle_group="Chest")
        chest = result["summary"][0]

        self.assertEqual(chest["muscle_group"], "Chest")
        self.assertAlmostEqual(chest["strength_index"], 110.0, delta=0.2)
        self.assertAlmostEqual(chest["strength_change_pct"], 10.0, delta=0.2)
        self.assertEqual(chest["hard_sets"], 20)

    def test_date_range_filters_old_training_out(self):
        training = pd.DataFrame(
            [
                row("2025-01-01", "Bench Press", 50, 5, sets=3),
                row("2026-04-01", "Bench Press", 100, 5, sets=3),
                row("2026-04-15", "Bench Press", 105, 5, sets=3),
            ]
        )
        result = calculate_muscle_group_trend(training, date_range="4w", muscle_group="Chest")

        self.assertEqual(len(result["history"]), 2)
        self.assertTrue(all(item["week"].startswith("2026") for item in result["history"]))


if __name__ == "__main__":
    unittest.main()
