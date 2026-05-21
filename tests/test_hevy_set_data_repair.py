import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import training as training_module
from src.integrations import hevy_client


MISLEADING_LIFT_WORKOUT = {
    "id": "hevy-lift-1",
    "title": "Hevy run",
    "created_at": "2026-05-20T15:00:00Z",
    "updated_at": "2026-05-20T16:00:00Z",
    "start_time": "2026-05-20T15:00:00Z",
    "end_time": "2026-05-20T16:00:00Z",
    "exercises": [
        {
            "exercise_template_id": "bench-template",
            "title": "Bench Press (Barbell)",
            "sets": [
                {"index": 0, "type": "warmup", "weight_kg": 61.235, "reps": 10},
                {"index": 1, "type": "normal", "weight_kg": 102.058, "reps": 4},
            ],
        }
    ],
}


def _patched_training_paths(temp_dir: str):
    return patch.multiple(
        training_module,
        TRAINING_LOG_PATH=Path(temp_dir) / "training_log.csv",
        RAW_HEVY_WORKOUTS_PATH=Path(temp_dir) / "raw_hevy_workouts.csv",
        RAW_HEVY_SETS_PATH=Path(temp_dir) / "raw_hevy_sets.csv",
        TRAINING_CACHE_METADATA_PATH=Path(temp_dir) / "training_cache_metadata.json",
    )


def test_hevy_lift_with_run_title_preserves_sets_and_volume():
    rows = hevy_client.normalize_hevy_workout(MISLEADING_LIFT_WORKOUT)

    assert len(rows) == 2
    assert rows[0]["workout_type"] == "Strength"
    assert sum(row["sets"] for row in rows) == 2
    assert sum(row["sets"] * row["reps"] * row["weight"] for row in rows) > 0


def test_repair_hevy_set_data_replaces_zeroed_rows_and_preserves_local_date():
    zeroed = pd.DataFrame(
        [
            {
                "workout_id": "hevy-lift-1",
                "date": "2026-05-19",
                "workout_type": "Strength",
                "muscle_group": "",
                "exercise": "Bench Press (Barbell)",
                "set_number": 1,
                "sets": 0,
                "reps": 0,
                "weight": 0,
                "rpe": 0,
                "duration_minutes": 60,
                "notes": "Imported from Hevy | hevy_workout_id=hevy-lift-1 | workout_title=Hevy run",
                "source": "hevy",
                "external_id": "hevy-lift-1:bench-template:0",
                "hevy_workout_id": "hevy-lift-1",
                "updated_at": "2026-05-20T16:00:00Z",
                "sync_source": "old_import",
                "last_hevy_sync_at": "",
            }
        ]
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.dict(os.environ, {"DATABASE_URL": ""}), _patched_training_paths(temp_dir):
            training_module.save_training_log(zeroed)
            with patch.object(hevy_client, "fetch_workout_details", return_value=MISLEADING_LIFT_WORKOUT):
                result = hevy_client.repair_hevy_set_data(workout_ids=["hevy-lift-1"], fetch_missing=True)
            saved = training_module.load_training_log()

    assert result["repaired_workouts"] == 1
    assert result["saved_rows"] == 2
    assert set(saved["date"]) == {"2026-05-19"}
    assert int(saved["sets"].sum()) == 2
    assert float((saved["sets"] * saved["reps"] * saved["weight"]).sum()) > 0
