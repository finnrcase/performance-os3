"""Export local CSV/JSON history into one importable JSON bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paths import PROJECT_ROOT, processed_data_path


DATASETS = {
    "nutrition_log": "nutrition_log.csv",
    "frequent_foods": "frequent_foods.csv",
    "food_shortcuts": "food_shortcuts.csv",
    "meal_templates": "meal_templates.csv",
    "body_metrics": "body_metrics.csv",
    "training_log": "training_log.csv",
    "recovery_log": "recovery_log.csv",
    "sleep_entries": "sleep_entries.csv",
    "daily_nutrition_summary": "daily_nutrition_summary.csv",
}

DOCUMENTS = {
    "user_settings": "user_settings.json",
    "user_goals": "user_goals.json",
    "nutrition_targets": "nutrition_targets.json",
    "personal_records": "personal_records.json",
    "hevy_sync_state": "hevy_sync_state.json",
}


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    df = pd.read_csv(path)
    return json.loads(df.where(pd.notna(df), None).to_json(orient="records"))


def _document(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    output = PROJECT_ROOT / "outputs" / "performance-os-local-export.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "version": 1,
        "dataframes": {name: _records(processed_data_path(filename)) for name, filename in DATASETS.items()},
        "documents": {name: _document(processed_data_path(filename)) for name, filename in DOCUMENTS.items()},
    }
    output.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Exported local Performance OS data to {output}")


if __name__ == "__main__":
    main()
