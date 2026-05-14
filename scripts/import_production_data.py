"""Import a local export bundle into the DATABASE_URL Postgres database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analytics.food_history import SUMMARY_COLUMNS, DAILY_NUTRITION_SUMMARY_PATH
from src.body_metrics import BODY_METRICS_COLUMNS, BODY_METRICS_PATH
from src.config import SETTINGS_PATH
from src.goals import USER_GOALS_PATH
from src.integrations.hevy_client import HEVY_SYNC_STATE_PATH
from src.nutrition import (
    FOOD_SHORTCUTS_PATH,
    FOOD_SHORTCUT_COLUMNS,
    FREQUENT_FOODS_PATH,
    FREQUENT_FOOD_COLUMNS,
    MEAL_TEMPLATES_PATH,
    MEAL_TEMPLATE_COLUMNS,
    NUTRITION_LOG_PATH,
    NUTRITION_COLUMNS,
)
from src.nutrition_targets import NUTRITION_TARGETS_PATH
from src.paths import PROJECT_ROOT
from src.recovery import RECOVERY_COLUMNS, RECOVERY_LOG_PATH, SLEEP_ENTRIES_PATH, SLEEP_ENTRY_COLUMNS
from src.storage import ensure_database_schema, save_dataframe, save_document, use_database
from src.training import TRAINING_COLUMNS, TRAINING_LOG_PATH
from src.analytics.personal_records import PERSONAL_RECORDS_PATH


DATASETS = {
    "nutrition_log": (NUTRITION_LOG_PATH, NUTRITION_COLUMNS),
    "frequent_foods": (FREQUENT_FOODS_PATH, FREQUENT_FOOD_COLUMNS),
    "food_shortcuts": (FOOD_SHORTCUTS_PATH, FOOD_SHORTCUT_COLUMNS),
    "meal_templates": (MEAL_TEMPLATES_PATH, MEAL_TEMPLATE_COLUMNS),
    "body_metrics": (BODY_METRICS_PATH, BODY_METRICS_COLUMNS),
    "training_log": (TRAINING_LOG_PATH, TRAINING_COLUMNS),
    "recovery_log": (RECOVERY_LOG_PATH, RECOVERY_COLUMNS),
    "sleep_entries": (SLEEP_ENTRIES_PATH, SLEEP_ENTRY_COLUMNS),
    "daily_nutrition_summary": (DAILY_NUTRITION_SUMMARY_PATH, SUMMARY_COLUMNS),
}

DOCUMENTS = {
    "user_settings": SETTINGS_PATH,
    "user_goals": USER_GOALS_PATH,
    "nutrition_targets": NUTRITION_TARGETS_PATH,
    "personal_records": PERSONAL_RECORDS_PATH,
    "hevy_sync_state": HEVY_SYNC_STATE_PATH,
}


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    if not use_database():
        raise SystemExit("DATABASE_URL is required to import into production storage.")

    bundle_path = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "outputs" / "performance-os-local-export.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    ensure_database_schema()

    for name, (path, columns) in DATASETS.items():
        rows = bundle.get("dataframes", {}).get(name, [])
        save_dataframe(name, path, pd.DataFrame(rows), columns)
        print(f"Imported {len(rows)} rows into {name}.")

    for name, path in DOCUMENTS.items():
        document = bundle.get("documents", {}).get(name, {})
        if document:
            save_document(name, path, document)
            print(f"Imported document {name}.")

    print("Production import complete.")


if __name__ == "__main__":
    main()
