"""Debug Hevy workout fetching and normalization without printing secrets.

Run from the repo root:
    python scripts/debug_hevy_import.py
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.hevy_client import (
    HEVY_DEBUG_PATH,
    HevyIntegrationError,
    fetch_recent_workouts,
    normalize_hevy_workout,
    preview_hevy_import,
)


def validate_rows(rows: list[dict]) -> list[str]:
    """Return non-fatal validation warnings for normalized rows."""
    warnings = []
    for index, row in enumerate(rows, start=1):
        if not row.get("external_id"):
            warnings.append(f"row {index}: missing external_id")
        if row.get("source") != "hevy":
            warnings.append(f"row {index}: source is not hevy")
        if not row.get("date"):
            warnings.append(f"row {index}: missing date")
        if not row.get("exercise"):
            warnings.append(f"row {index}: missing exercise")
        if row.get("sets", 0) and not row.get("reps", 0):
            warnings.append(f"row {index}: set row has no reps")
    return warnings


def main() -> None:
    """Fetch recent Hevy workouts, save raw JSON, and print normalized rows."""
    try:
        workouts = fetch_recent_workouts(page_size=10, pages=1, save_debug=True)
    except HevyIntegrationError as exc:
        print(f"Hevy debug failed: {exc}")
        return

    print(f"Fetched {len(workouts)} workouts from Hevy.")
    print(f"Saved raw response to {HEVY_DEBUG_PATH}")

    all_rows = []
    for workout in workouts:
        rows = normalize_hevy_workout(workout)
        all_rows.extend(rows)
        exercises = sorted({row["exercise"] for row in rows if row.get("exercise")})
        print(
            f"- {workout.get('start_time') or workout.get('created_at')}: "
            f"{workout.get('title', 'Hevy Workout')} -> {len(rows)} rows, "
            f"{len(exercises)} exercises"
        )

    duplicate_ids = [external_id for external_id, count in Counter(row["external_id"] for row in all_rows).items() if count > 1]
    warnings = validate_rows(all_rows)
    if duplicate_ids:
        warnings.append(f"{len(duplicate_ids)} duplicate normalized external IDs in fetched payload")

    print(f"Normalized rows: {len(all_rows)}")
    if all_rows:
        print("First 5 normalized rows:")
        for row in all_rows[:5]:
            print(
                {
                    "date": row["date"],
                    "exercise": row["exercise"],
                    "sets": row["sets"],
                    "reps": row["reps"],
                    "weight": row["weight"],
                    "source": row["source"],
                    "external_id": row["external_id"],
                }
            )

    preview = preview_hevy_import(page_size=10, pages=1)
    print(
        "Preview summary: "
        f"{preview['estimated_rows']} estimated rows, "
        f"{preview['duplicates_detected']} duplicate rows detected."
    )

    if warnings:
        print("Validation warnings:")
        for warning in warnings:
            print(f"- {warning}")
    else:
        print("Validation warnings: none")


if __name__ == "__main__":
    main()
