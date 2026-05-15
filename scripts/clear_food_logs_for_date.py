"""Remove food intake rows for a single date and rebuild nutrition history.

Usage:
    python3 scripts/clear_food_logs_for_date.py 2026-05-12
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analytics.food_history import build_daily_nutrition_summary, save_daily_nutrition_summary
from src.nutrition import clear_food_logs_for_date, load_nutrition_log
from src.nutrition_targets import load_nutrition_targets


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/clear_food_logs_for_date.py YYYY-MM-DD")
        return 2

    selected_date = sys.argv[1].strip()
    result = clear_food_logs_for_date(selected_date)
    summary = build_daily_nutrition_summary(load_nutrition_log(), load_nutrition_targets())
    save_daily_nutrition_summary(summary)
    print(f"Removed {result['removed']} food log entr{'y' if result['removed'] == 1 else 'ies'} for {selected_date}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
