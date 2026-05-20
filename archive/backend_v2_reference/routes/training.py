from __future__ import annotations

from collections import defaultdict
import time

from fastapi import APIRouter

from backend_v2.db import load_recent_rows
from backend_v2.utils import to_float, to_int


router = APIRouter(tags=["training"])


def _volume(row: dict) -> float:
    return to_float(row.get("sets"), 0) * to_float(row.get("reps"), 0) * to_float(row.get("weight"), 0)


def _workout_title(rows: list[dict]) -> str:
    for row in rows:
        notes = str(row.get("notes") or "")
        if "workout_title=" in notes:
            return notes.split("workout_title=", 1)[1].split("|", 1)[0].strip()
    workout_type = sorted({str(row.get("workout_type") or "").strip() for row in rows if str(row.get("workout_type") or "").strip()})
    return ", ".join(workout_type)


def grouped_workout_history(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for index, row in enumerate(rows):
        date = str(row.get("date") or "")
        workout_id = str(row.get("workout_id") or row.get("hevy_workout_id") or f"{date}:unknown")
        grouped[(date, workout_id)].append({**row, "_row_index": index})

    cards: list[dict] = []
    for (workout_date, workout_id), workout_rows in grouped.items():
        exercises = [str(row.get("exercise") or "").strip() for row in workout_rows if str(row.get("exercise") or "").strip()]
        muscle_groups = sorted({str(row.get("muscle_group") or "").strip() for row in workout_rows if str(row.get("muscle_group") or "").strip()})
        sources = sorted({str(row.get("source") or "").strip() for row in workout_rows if str(row.get("source") or "").strip()})
        cards.append(
            {
                "date": workout_date,
                "workout_id": workout_id,
                "workout_type": _workout_title(workout_rows),
                "muscle_groups": muscle_groups,
                "exercise_names": list(dict.fromkeys(exercises)),
                "total_sets": int(sum(max(0, to_int(row.get("sets"), 0)) for row in workout_rows)),
                "total_volume": round(sum(_volume(row) for row in workout_rows), 1),
                "duration_minutes": round(max([to_float(row.get("duration_minutes"), 0) for row in workout_rows] or [0]), 1),
                "source": ", ".join(sources) if sources else "manual",
                "details": sorted(workout_rows, key=lambda row: (str(row.get("exercise") or ""), to_int(row.get("set_number"), 0), row.get("_row_index", 0))),
            }
        )
    return sorted(cards, key=lambda item: (str(item.get("date") or ""), str(item.get("workout_id") or "")), reverse=True)


def training_history_payload(limit: int = 25, days: int = 180) -> dict:
    started = time.perf_counter()
    bounded_limit = max(1, min(int(limit or 25), 200))
    bounded_days = max(7, min(int(days or 180), 3650))
    rows = load_recent_rows("training_log", days=bounded_days, limit=max(bounded_limit * 80, 2000), timeout_ms=1500)
    grouped = grouped_workout_history(rows)
    items = grouped[:bounded_limit]
    hevy_rows = [
        row for row in rows
        if str(row.get("source") or "").lower() == "hevy" or str(row.get("hevy_workout_id") or "").strip() or "hevy_workout_id=" in str(row.get("notes") or "").lower()
    ]
    return {
        "items": items,
        "limit": bounded_limit,
        "days": bounded_days,
        "raw_window_days": bounded_days,
        "has_more_recent": len(grouped) > len(items),
        "message": f"Showing recent raw workouts from the last {bounded_days} days.",
        "debug": {
            "hevy_rows": len(hevy_rows),
            "hevy_workouts": len({str(row.get("workout_id") or row.get("hevy_workout_id") or "") for row in hevy_rows if str(row.get("workout_id") or row.get("hevy_workout_id") or "").strip()}),
            "raw_rows": len(rows),
            "grouped_workouts": len(grouped),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "message": "No Hevy rows found" if not hevy_rows else "",
        },
    }


@router.get("/api/training/history")
def get_training_history(limit: int = 25, days: int = 180) -> dict:
    return training_history_payload(limit=limit, days=days)

