"""Personal record tracking for Performance OS."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.analytics.strength_trends import calculate_estimated_1rm
from src.paths import processed_data_path
from src.storage import load_document, save_document


PERSONAL_RECORDS_PATH = processed_data_path("personal_records.json")

BENCH_ALIASES = {
    "bench press",
    "barbell bench press",
    "flat bench press",
    "bench",
}


def default_personal_records() -> dict:
    return {
        "bench_press": None,
        "mile_time": None,
        "history": {
            "bench_press": [],
            "mile_time": [],
        },
    }


def load_personal_records() -> dict:
    """Load PRs from local JSON."""
    records = default_personal_records()
    saved = load_document("personal_records", PERSONAL_RECORDS_PATH, records)
    records.update({key: saved.get(key, records[key]) for key in ["bench_press", "mile_time"]})
    saved_history = saved.get("history", {})
    records["history"]["bench_press"] = list(saved_history.get("bench_press", []))
    records["history"]["mile_time"] = list(saved_history.get("mile_time", []))
    for key in ["bench_press", "mile_time"]:
        if records.get(key):
            records[key].setdefault("manual_override", False)
            records[key].setdefault("updated_at", "")
            records[key].setdefault("notes", "")
    return records


def save_personal_records(records: dict) -> None:
    """Save PRs to local JSON."""
    normalized = default_personal_records()
    normalized.update({key: records.get(key) for key in ["bench_press", "mile_time"]})
    normalized["history"]["bench_press"] = list(records.get("history", {}).get("bench_press", []))
    normalized["history"]["mile_time"] = list(records.get("history", {}).get("mile_time", []))
    save_document("personal_records", PERSONAL_RECORDS_PATH, normalized)


def _note_value(note: str, key: str) -> str:
    marker = f"{key}="
    if marker not in str(note):
        return ""
    return str(note).split(marker, 1)[1].split("|", 1)[0].strip()


def _display_seconds(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _is_bench_press(exercise: str) -> bool:
    name = str(exercise or "").strip().lower()
    if name in BENCH_ALIASES:
        return True
    return "bench press" in name and "incline" not in name and "decline" not in name


def _better_bench(candidate: dict | None, current: dict | None) -> bool:
    if not candidate:
        return False
    if not current:
        return True
    candidate_value = float(candidate.get("value") or 0)
    current_value = float(current.get("value") or 0)
    if candidate_value != current_value:
        return candidate_value > current_value
    return float(candidate.get("estimated_1rm") or 0) > float(current.get("estimated_1rm") or 0)


def _better_mile(candidate: dict | None, current: dict | None) -> bool:
    if not candidate:
        return False
    if not current:
        return True
    return float(candidate.get("value_seconds") or 0) < float(current.get("value_seconds") or 999999)


def calculate_bench_press_pr(training_df: pd.DataFrame) -> dict | None:
    """Calculate bench PR from Hevy/imported/manual training rows."""
    if training_df.empty:
        return None
    df = training_df.copy()
    for column in ["weight", "reps"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    for column in ["exercise", "date", "source", "notes"]:
        df[column] = df.get(column, "").fillna("").astype(str)
    df = df[df["exercise"].apply(_is_bench_press) & (df["weight"] > 0)]
    if df.empty:
        return None
    df["estimated_1rm"] = df.apply(
        lambda row: float(row["weight"]) if float(row["reps"] or 0) <= 1 else calculate_estimated_1rm(row["weight"], row["reps"]),
        axis=1,
    )
    best = df.sort_values(["weight", "estimated_1rm", "reps"], ascending=False).iloc[0]
    return {
        "value": float(best["weight"]),
        "unit": "lb",
        "reps": int(best["reps"] or 1),
        "date": str(best["date"]),
        "source": str(best["source"] or "manual"),
        "estimated_1rm": float(best["estimated_1rm"] or best["weight"]),
        "notes": str(best["notes"] or ""),
        "manual_override": False,
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def calculate_mile_pr(training_df: pd.DataFrame, strava_df=None) -> dict | None:
    """Calculate mile PR from Strava/manual run rows.

    The current Strava import stores average pace, not exact splits. Those PRs
    are labelled estimated unless a manual mile PR is entered.
    """
    if training_df.empty:
        return None
    df = training_df.copy()
    for column in ["date", "workout_type", "exercise", "notes", "source"]:
        df[column] = df.get(column, "").fillna("").astype(str)
    df["duration_minutes"] = pd.to_numeric(df.get("duration_minutes", 0), errors="coerce").fillna(0)
    runs = df[df["workout_type"].str.lower().isin(["run", "cardio"])].copy()
    candidates = []
    for _, row in runs.iterrows():
        note = str(row["notes"])
        distance = float(_note_value(note, "distance_miles") or 0)
        pace = float(_note_value(note, "pace_min_per_mile") or 0)
        if pace <= 0 and distance >= 1 and row["duration_minutes"] > 0:
            pace = float(row["duration_minutes"]) / distance
        if pace <= 0 and "mile" in str(row["exercise"]).lower() and row["duration_minutes"] > 0:
            pace = float(row["duration_minutes"])
            distance = 1
        if pace <= 0:
            continue
        estimated = not (0.98 <= distance <= 1.02 and str(row["source"]).lower() == "manual")
        candidates.append(
            {
                "value_seconds": int(round(pace * 60)),
                "display": _display_seconds(pace * 60),
                "date": str(row["date"]),
                "source": str(row["source"] or "manual"),
                "estimated": estimated,
                "notes": note,
                "manual_override": False,
                "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
        )
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: item["value_seconds"])[0]


def update_personal_records_from_logs(training_df: pd.DataFrame, strava_df=None, force: bool = False) -> dict:
    """Recalculate PRs from logs.

    Manual overrides are preserved unless ``force`` is true. This lets the UI
    keep user-entered PRs authoritative until the user explicitly recalculates.
    """
    records = load_personal_records()
    bench_candidate = calculate_bench_press_pr(training_df)
    mile_candidate = calculate_mile_pr(training_df, strava_df=strava_df)

    current_bench = records.get("bench_press")
    if not (current_bench and current_bench.get("manual_override") and not force):
        if (
            bench_candidate
            and current_bench
            and current_bench.get("source") != "manual"
            and float(bench_candidate.get("value") or 0) == float(current_bench.get("value") or 0)
            and bench_candidate != current_bench
        ):
            records["bench_press"] = bench_candidate
        elif _better_bench(bench_candidate, current_bench):
            records["bench_press"] = bench_candidate
            records["history"]["bench_press"].append(bench_candidate)
    if not (records.get("mile_time") and records["mile_time"].get("manual_override") and not force) and _better_mile(mile_candidate, records.get("mile_time")):
        records["mile_time"] = mile_candidate
        records["history"]["mile_time"].append(mile_candidate)

    save_personal_records(records)
    return records


def add_manual_pr(record_type: str, value, date, source: str = "manual", notes: str = "", reps=1) -> dict:
    """Add or override a manual bench or mile PR."""
    records = load_personal_records()
    record_date = str(date or datetime.today().date().isoformat())
    updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    if record_type == "bench_press":
        candidate = {
            "value": float(value or 0),
            "unit": "lb",
            "reps": int(reps or 1),
            "date": record_date,
            "source": source,
            "estimated_1rm": float(value or 0) if int(reps or 1) <= 1 else calculate_estimated_1rm(float(value or 0), int(reps or 1)),
            "notes": str(notes or ""),
            "manual_override": source == "manual",
            "updated_at": updated_at,
        }
        records["bench_press"] = candidate
        records["history"]["bench_press"].append(candidate)
    elif record_type == "mile_time":
        candidate = {
            "value_seconds": int(value or 0),
            "display": _display_seconds(float(value or 0)),
            "date": record_date,
            "source": source,
            "estimated": False,
            "notes": str(notes or ""),
            "manual_override": source == "manual",
            "updated_at": updated_at,
        }
        records["mile_time"] = candidate
        records["history"]["mile_time"].append(candidate)
    else:
        raise ValueError("record_type must be bench_press or mile_time")
    save_personal_records(records)
    return records
