import pandas as pd

from src.nutrition import calculate_daily_totals
from src import workout_nutrition as wn


def test_workout_marker_create_load_and_window_split(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(wn, "WORKOUT_MARKERS_PATH", tmp_path / "workout_markers.csv")

    marker = wn.create_workout_marker(
        date="2026-05-24",
        workout_time="17:00",
        workout_type="Strength",
        notes="Push day",
        marker_sequence=2,
    )

    markers_df = wn.load_workout_markers()
    assert len(markers_df) == 1
    assert markers_df.iloc[0]["marker_id"] == marker["marker_id"]
    assert markers_df.iloc[0]["workout_time"] == "17:00"
    assert markers_df.iloc[0]["marker_sequence"] == 2

    nutrition_df = pd.DataFrame(
        [
            {
                "date": "2026-05-24",
                "food_name": "Bagel",
                "calories": 260,
                "carbs": 52,
                "protein": 10,
                "fat": 2,
                "logged_sequence": 1,
                "created_at": "2026-05-24T15:30:00",
            },
            {
                "date": "2026-05-24",
                "food_name": "Chicken rice bowl",
                "calories": 650,
                "carbs": 75,
                "protein": 45,
                "fat": 14,
                "logged_sequence": 3,
                "created_at": "2026-05-24T19:00:00",
            },
            {
                "date": "2026-05-24",
                "food_name": "Older untimed row",
                "calories": 100,
                "carbs": 10,
                "protein": 4,
                "fat": 4,
                "created_at": "",
            },
        ]
    )
    training_df = pd.DataFrame(
        [
            {
                "date": "2026-05-24",
                "workout_type": "Strength",
                "exercise": "Bench Press",
                "sets": 5,
                "reps": 5,
                "weight": 225,
                "rpe": 8,
            }
        ]
    )

    daily_totals = calculate_daily_totals(nutrition_df, "2026-05-24")
    windows_df = wn.calculate_workout_nutrition_windows(nutrition_df, training_df, markers_df)
    latest = windows_df.iloc[0]

    assert latest["pre_workout_carbs"] == 52
    assert latest["post_workout_protein"] == 45
    assert latest["unknown_timing_calories"] == 100
    assert latest["total_same_day_calories"] == daily_totals["calories"]
    assert latest["linked_training_session"] == "Strength"
    assert latest["estimated_workout_quality"] == "High stress"


def test_empty_markers_return_safe_recommendation():
    windows_df = wn.calculate_workout_nutrition_windows(
        nutrition_df=pd.DataFrame(),
        training_df=pd.DataFrame(),
        markers_df=pd.DataFrame(columns=wn.WORKOUT_MARKER_COLUMNS),
    )

    recommendation = wn.generate_workout_fueling_recommendations(windows_df, pd.DataFrame())

    assert windows_df.empty
    assert recommendation["status"] == "empty"
    assert recommendation["deload_status"] == "Normal"
    assert "Add a workout marker" in recommendation["pre_workout_carb_suggestion"]


def test_recommendations_flag_low_carbs_post_protein_and_deload():
    windows_df = pd.DataFrame(
        [
            {
                "date": f"2026-05-2{day}",
                "workout_time": "17:00",
                "pre_workout_carbs": 20,
                "pre_workout_fat": 28 if day == 4 else 10,
                "post_workout_protein": 18,
                "total_same_day_carbs": 150,
                "training_volume": 15000,
                "avg_rpe": 8,
            }
            for day in range(1, 5)
        ]
    )
    recovery_df = pd.DataFrame(
        [
            {"date": "2026-05-21", "recovery_score": 74},
            {"date": "2026-05-22", "recovery_score": 66},
            {"date": "2026-05-23", "recovery_score": 61},
            {"date": "2026-05-24", "recovery_score": 55},
        ]
    )

    recommendation = wn.generate_workout_fueling_recommendations(windows_df, recovery_df)

    assert recommendation["deload_status"] == "Deload Suggested"
    assert "40-60g carbs" in recommendation["pre_workout_carb_suggestion"]
    assert "fat was 28g" in recommendation["pre_workout_carb_suggestion"]
    assert "under 30g" in recommendation["post_workout_recovery_suggestion"]
