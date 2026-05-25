import pandas as pd

from src.analytics.muscle_coverage import calculate_weekly_muscle_coverage


def _row(date, exercise, muscle_group="", sets=4, reps=10, weight=100, rpe=8, workout_type="Strength"):
    return {
        "date": date,
        "exercise": exercise,
        "muscle_group": muscle_group,
        "sets": sets,
        "reps": reps,
        "weight": weight,
        "rpe": rpe,
        "workout_type": workout_type,
    }


def test_weekly_muscle_coverage_flags_missed_and_met_groups():
    training = pd.DataFrame(
        [
            _row("2026-05-24", "Bench Press", "Chest", sets=8),
            _row("2026-05-23", "Lat Pulldown", "Back", sets=10),
            _row("2026-05-22", "Run", "Cardio", sets=99, workout_type="Run"),
        ]
    )

    coverage = calculate_weekly_muscle_coverage(training, reference_date="2026-05-24")
    by_group = coverage.set_index("muscle_group").to_dict(orient="index")

    assert by_group["Chest"]["status"] == "Good"
    assert by_group["Chest"]["color"] == "Green"
    assert by_group["Back"]["status"] == "Good"
    assert by_group["Quads"]["status"] == "Missed"
    assert by_group["Quads"]["color"] == "Purple"
    assert "Cardio" not in by_group


def test_weekly_muscle_coverage_uses_baseline_when_higher_than_minimum():
    training = pd.DataFrame(
        [
            _row("2026-04-28", "Bench Press", "Chest", sets=12),
            _row("2026-05-05", "Bench Press", "Chest", sets=12),
            _row("2026-05-12", "Bench Press", "Chest", sets=12),
            _row("2026-05-17", "Bench Press", "Chest", sets=12),
            _row("2026-05-24", "Bench Press", "Chest", sets=6),
        ]
    )

    coverage = calculate_weekly_muscle_coverage(training, reference_date="2026-05-24")
    chest = coverage.set_index("muscle_group").loc["Chest"]

    assert chest["baseline_weekly_hard_sets"] == 12
    assert chest["target_sets"] == 12
    assert chest["status"] == "Slightly lacking"
    assert chest["color"] == "Yellow"


def test_weekly_muscle_coverage_handles_empty_training_data():
    coverage = calculate_weekly_muscle_coverage(pd.DataFrame(), reference_date="2026-05-24")

    assert len(coverage) == 10
    assert set(coverage["color"]) == {"Purple"}
    assert float(coverage["hard_sets"].sum()) == 0
