from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import csv
import io
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend_new.db import (
    count_rows,
    fetch_json_rows_for_value,
    fetch_json_rows_matching_any,
    fetch_latest_document,
    fetch_latest_json_rows,
    insert_json_row,
    load_recent_training_summary,
    move_workout_date_rows,
    upsert_json_row,
)
from backend_new.utils import json_safe, utc_now_iso
from src.training_schedule import classify_workout


router = APIRouter(tags=["training"])
logger = logging.getLogger(__name__)


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _bounded_int(value: int | str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _date_cutoff(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if isinstance(row, dict) and "_db_error" not in row]


def _volume(row: dict[str, Any]) -> float:
    return _number(row.get("sets"), 0) * _number(row.get("reps"), 0) * _number(row.get("weight"), 0)


def _total_reps(row: dict[str, Any]) -> int:
    return max(0, _int(row.get("sets"), 0)) * max(0, _int(row.get("reps"), 0))


def _infer_muscle_group(exercise: Any) -> str:
    name = str(exercise or "").lower()
    terms = [
        ("Chest", ("bench", "chest press", "fly", "pec", "push up", "push-up", "incline press")),
        ("Back", ("row", "pulldown", "pull down", "pullup", "pull-up", "chin", "lat ", "shrug")),
        ("Shoulders", ("overhead press", "shoulder press", "lateral raise", "front raise", "rear delt", "face pull", "arnold")),
        ("Biceps", ("curl", "preacher", "hammer curl")),
        ("Triceps", ("triceps", "skullcrusher", "skull crusher", "pushdown", "push down", "dip", "extension")),
        ("Quads", ("squat", "leg press", "leg extension", "lunge", "split squat", "hack squat")),
        ("Hamstrings", ("leg curl", "hamstring", "romanian", "rdl", "good morning")),
        ("Glutes", ("hip thrust", "glute", "kickback")),
        ("Calves", ("calf",)),
        ("Core", ("crunch", "plank", "sit up", "sit-up", "ab ", "cable crunch", "raise")),
        ("Cardio", ("run", "treadmill", "bike", "cycling", "elliptical", "stair", "rower", "swim")),
    ]
    for group, needles in terms:
        if any(needle in name for needle in needles):
            return group
    return ""


def _workout_title(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        notes = str(row.get("notes") or "")
        if "workout_title=" in notes:
            return notes.split("workout_title=", 1)[1].split("|", 1)[0].strip()
    for row in rows:
        title = str(row.get("workout_type") or row.get("title") or "").strip()
        if title:
            return title
    return "Workout"


def _classification_label(kind: str) -> str:
    return {
        "lift": "Lift",
        "run": "Run",
        "cardio": "Cardio",
        "lift_cardio": "Lift + cardio",
        "unknown": "Unknown",
    }.get(str(kind or "unknown"), "Unknown")


def _group_workouts(rows: list[dict[str, Any]], *, cutoff: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row_date = str(row.get("date") or "")
        if not row_date or row_date < cutoff:
            continue
        workout_id = str(row.get("workout_id") or row.get("hevy_workout_id") or f"{row_date}:unknown")
        grouped[(row_date, workout_id)].append(row)

    items: list[dict[str, Any]] = []
    for (workout_date, workout_id), workout_rows in grouped.items():
        exercises = list(dict.fromkeys(str(row.get("exercise") or "").strip() for row in workout_rows if str(row.get("exercise") or "").strip()))
        muscle_groups = sorted(
            {
                group
                for row in workout_rows
                for group in (str(row.get("muscle_group") or "").strip(), _infer_muscle_group(row.get("exercise")))
                if group
            }
        )
        sources = sorted({str(row.get("source") or "manual").strip() for row in workout_rows})
        classification = classify_workout(workout_rows)
        kind = str(classification.get("kind") or "unknown")
        details = sorted(workout_rows, key=lambda row: (str(row.get("exercise") or ""), _int(row.get("set_number"), 0)))
        for row in details:
            if not str(row.get("muscle_group") or "").strip():
                inferred = _infer_muscle_group(row.get("exercise"))
                if inferred:
                    row["muscle_group"] = inferred
        items.append(
            {
                "date": workout_date,
                "workout_id": workout_id,
                "workout_type": _workout_title(workout_rows),
                "classification": kind,
                "classification_label": _classification_label(kind),
                "classification_debug": {
                    "has_lift": bool(classification.get("has_lift")),
                    "has_cardio": bool(classification.get("has_cardio") or classification.get("has_run")),
                    "matched_lift_terms": classification.get("matched_lift_terms") or [],
                    "matched_cardio_terms": classification.get("matched_cardio_terms") or [],
                    "reason": classification.get("reason") or "",
                },
                "muscle_groups": muscle_groups,
                "exercise_names": exercises,
                "total_sets": int(sum(max(0, _int(row.get("sets"), 0)) for row in workout_rows)),
                "total_reps": int(sum(_total_reps(row) for row in workout_rows)),
                "total_volume": round(sum(_volume(row) for row in workout_rows), 1),
                "duration_minutes": round(max([_number(row.get("duration_minutes"), 0) for row in workout_rows] or [0]), 1),
                "source": ", ".join(sources) if sources else "manual",
                "details": details,
            }
        )
    return sorted(items, key=lambda item: (str(item.get("date") or ""), str(item.get("workout_id") or "")), reverse=True)


def _history_payload(limit: int = 25, days: int = 180) -> dict[str, Any]:
    started = time.perf_counter()
    bounded_limit = _bounded_int(limit, 25, 1, 200)
    bounded_days = _bounded_int(days, 180, 7, 3650)
    raw_limit = min(max(bounded_limit * 120, 1000), 5000)
    rows = _valid_rows(fetch_latest_json_rows("workout_logs", limit=raw_limit))
    cutoff = _date_cutoff(bounded_days)
    workouts = _group_workouts(rows, cutoff=cutoff)
    items = workouts[:bounded_limit]
    older_summaries = _valid_rows(fetch_latest_json_rows("weekly_training_summary", limit=500)) if bounded_days > 365 else []
    hevy_rows = [row for row in rows if str(row.get("source") or "").lower() == "hevy" or row.get("hevy_workout_id")]
    return {
        "items": items,
        "older_summaries": older_summaries,
        "limit": bounded_limit,
        "days": bounded_days,
        "raw_window_days": bounded_days,
        "has_more_recent": len(workouts) > len(items),
        "message": f"Showing latest {len(items)} local cached workouts from the last {bounded_days} days.",
        "debug": {
            "source": "local_cache",
            "raw_rows_read": len(rows),
            "read_limit": raw_limit,
            "grouped_workouts": len(workouts),
            "hevy_rows": len(hevy_rows),
            "hevy_workouts": len({str(row.get("workout_id") or row.get("hevy_workout_id") or "") for row in hevy_rows if row.get("workout_id") or row.get("hevy_workout_id")}),
            "full_raw_hevy_scan": False,
            "older_history_source": "weekly_training_summary" if older_summaries else "none",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }


def _trend_payload(weeks: int = 12, exercise_name: str | None = None, muscle_group: str | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    bounded_weeks = _bounded_int(weeks, 12, 1, 52)
    cutoff = _date_cutoff(bounded_weeks * 7)
    rows = [
        row for row in _valid_rows(fetch_latest_json_rows("workout_logs", limit=5000))
        if str(row.get("date") or "") >= cutoff
    ]
    if exercise_name:
        rows = [row for row in rows if str(row.get("exercise") or "").lower() == exercise_name.lower()]
    if muscle_group:
        rows = [row for row in rows if str(row.get("muscle_group") or "").lower() == muscle_group.lower()]

    by_exercise: dict[str, dict[str, Any]] = {}
    by_week: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"sets": 0, "reps": 0, "volume": 0.0, "top_weight": 0.0})
    for row in rows:
        exercise = str(row.get("exercise") or "Unknown")
        row_date = str(row.get("date") or "")
        week = row_date[:10]
        sets = max(0, _int(row.get("sets"), 0))
        reps = max(0, _int(row.get("reps"), 0))
        weight = _number(row.get("weight"), 0)
        volume = _volume(row)
        current = by_exercise.setdefault(exercise, {"exercise": exercise, "sets": 0, "reps": 0, "volume": 0.0, "top_weight": 0.0, "last_date": ""})
        current["sets"] += sets
        current["reps"] += reps
        current["volume"] += volume
        current["top_weight"] = max(current["top_weight"], weight)
        current["last_date"] = max(str(current["last_date"]), row_date)
        bucket = by_week[(exercise, week)]
        bucket["exercise"] = exercise
        bucket["week"] = week
        bucket["sets"] += sets
        bucket["reps"] += reps
        bucket["volume"] += volume
        bucket["top_weight"] = max(bucket["top_weight"], weight)

    exercises = sorted(by_exercise.values(), key=lambda item: (item["last_date"], item["volume"]), reverse=True)
    selected = exercise_name or (exercises[0]["exercise"] if exercises else "")
    selected_points = [value for (exercise, _), value in by_week.items() if exercise == selected]
    selected_points.sort(key=lambda item: item["week"])
    return {
        "status": "ok",
        "weeks": bounded_weeks,
        "selected_exercise": selected,
        "exercise_options": [item["exercise"] for item in exercises[:50]],
        "items": [
            {**item, "volume": round(item["volume"], 1), "top_weight": round(item["top_weight"], 1)}
            for item in exercises[:50]
        ],
        "trend": [
            {**item, "volume": round(item["volume"], 1), "top_weight": round(item["top_weight"], 1)}
            for item in selected_points
        ],
        "summary": {
            "rows_read": len(rows),
            "read_limit": 5000,
            "full_raw_hevy_scan": False,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }


def _jsonable_result(result: dict[str, Any]) -> dict[str, Any]:
    cleaned = {}
    for key, value in result.items():
        if key == "training_log":
            try:
                cleaned["training_log_rows"] = int(len(value))
            except Exception:
                cleaned["training_log_rows"] = None
            continue
        cleaned[key] = json_safe(value)
    return cleaned


def _hevy_configured() -> bool:
    return bool(os.getenv("HEVY_API_KEY", "").strip())


def _sync_state() -> dict[str, Any]:
    state = fetch_latest_document("integration_sync_state", {})
    return state if isinstance(state, dict) else {}


def _content_disposition(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


def _csv_response(rows: list[dict[str, Any]], filename: str) -> Response:
    output = io.StringIO()
    fields = sorted({key for row in rows for key in row.keys()}) or ["status", "message"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: json_safe(row.get(field, "")) for field in fields})
    return Response(output.getvalue(), media_type="text/csv", headers=_content_disposition(filename))


def _excel_response(sheets: dict[str, list[dict[str, Any]]], filename: str, fallback_rows: list[dict[str, Any]]) -> Response:
    try:
        import pandas as pd

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            for sheet_name, rows in sheets.items():
                pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name[:31], index=False)
        return Response(
            buffer.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=_content_disposition(filename),
        )
    except Exception:
        return _csv_response(fallback_rows, filename.replace(".xlsx", ".csv"))


def _summary_state() -> dict[str, Any]:
    state = fetch_latest_document("training_summary_state", {})
    return state if isinstance(state, dict) else {}


def _latest_date(rows: list[dict[str, Any]], *fields: str) -> str:
    values = []
    for row in rows:
        for field in fields:
            value = str(row.get(field) or "").strip()
            if value:
                values.append(value[:10])
    return max(values, default="")


def _same_workout(row: dict[str, Any], workout_id: str) -> bool:
    return any(str(row.get(field) or "").strip() == workout_id for field in ("workout_id", "hevy_workout_id", "external_id", "source_id"))


def _is_lift_workout_rows(rows: list[dict[str, Any]]) -> bool:
    return str(classify_workout(rows).get("kind") or "") == "lift"


def _has_lift_workout_rows(rows: list[dict[str, Any]]) -> bool:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row_date = str(row.get("date") or "")
        workout_id = str(row.get("workout_id") or row.get("hevy_workout_id") or row.get("external_id") or f"{row_date}:unknown")
        grouped[workout_id].append(row)
    return any(str(classify_workout(workout_rows).get("kind") or "") in {"lift", "lift_cardio"} for workout_rows in grouped.values())


@router.get("/api/training/history")
def training_history(limit: int = 25, days: int = 180) -> dict[str, Any]:
    return _history_payload(limit=limit, days=days)


@router.post("/api/training/workout-date")
def update_workout_date(payload: dict[str, Any]) -> dict[str, Any]:
    workout_id = str((payload or {}).get("workout_id") or "").strip()
    new_date = str((payload or {}).get("new_date") or "").strip()[:10]
    if not workout_id:
        raise HTTPException(status_code=400, detail="workout_id is required.")
    if not new_date:
        raise HTTPException(status_code=400, detail="new_date is required.")
    try:
        parsed_new_date = date.fromisoformat(new_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="new_date must be a valid YYYY-MM-DD date.") from None
    if parsed_new_date > date.today():
        raise HTTPException(status_code=400, detail="Workout date corrections cannot move a workout into the future.")

    selected_rows = _valid_rows(fetch_json_rows_matching_any("workout_logs", ("workout_id", "hevy_workout_id", "external_id", "source_id"), workout_id, limit=500))
    if not selected_rows:
        raise HTTPException(status_code=404, detail=f"No workout found with id {workout_id}.")
    if not _is_lift_workout_rows(selected_rows):
        raise HTTPException(status_code=400, detail="Only lifting workouts can be moved by the missed-day correction.")

    target_rows = [
        row for row in _valid_rows(fetch_json_rows_for_value("workout_logs", "date", new_date, limit=1000))
        if not _same_workout(row, workout_id)
    ]
    if target_rows and _has_lift_workout_rows(target_rows):
        raise HTTPException(status_code=409, detail=f"A lift is already logged on {new_date}.")

    normalized = move_workout_date_rows("workout_logs", workout_id, new_date, annotate_notes=True)
    if normalized.get("status") != "ok":
        status = str(normalized.get("status") or "error")
        raise HTTPException(
            status_code=503 if status == "not_configured" else 500,
            detail=normalized.get("message") or f"Could not move workout: {status}.",
        )
    if int(normalized.get("updated_rows") or 0) <= 0:
        raise HTTPException(status_code=404, detail=f"No workout found with id {workout_id}.")

    raw_workouts = move_workout_date_rows("raw_hevy_workouts", workout_id, new_date, match_fields=("hevy_workout_id", "workout_id", "id"))
    raw_sets = move_workout_date_rows("raw_hevy_sets", workout_id, new_date, match_fields=("hevy_workout_id", "workout_id"))
    cache_summary = load_recent_training_summary(force_refresh=True)
    old_date = str(normalized.get("old_date") or "")
    updated_rows = int(normalized.get("updated_rows") or 0)
    logger.info(
        "[move_workout_date] workout_id=%s old_date=%s new_date=%s updated_rows=%s",
        workout_id,
        old_date,
        normalized.get("new_date"),
        updated_rows,
    )
    return {
        "status": "ok",
        "workout_id": workout_id,
        "old_date": old_date,
        "new_date": normalized.get("new_date"),
        "updated_rows": updated_rows,
        "raw_updated_rows": int(raw_workouts.get("updated_rows") or 0) + int(raw_sets.get("updated_rows") or 0),
        "cache_summary": cache_summary,
        "debug": {
            "workout_logs": normalized,
            "raw_hevy_workouts": raw_workouts,
            "raw_hevy_sets": raw_sets,
        },
    }


@router.get("/api/training/strength-trends")
def strength_trends(weeks: int = 12, exercise_name: str | None = None, muscle_group: str | None = None) -> dict[str, Any]:
    return _trend_payload(weeks=weeks, exercise_name=exercise_name, muscle_group=muscle_group)


@router.get("/api/training/summary")
def training_summary(window: str = "weekly", period: str = "all") -> dict[str, Any]:
    history = _history_payload(limit=100, days=365)
    items = []
    for workout in history.get("items", []):
        workout_date = str(workout.get("date") or "")
        if not workout_date:
            continue
        items.append(
            {
                "period_start": workout_date,
                "period_label": workout_date,
                "workout_count": 1,
                "total_sets": workout.get("total_sets", 0),
                "total_reps": workout.get("total_reps", 0),
                "total_volume": workout.get("total_volume", 0),
                "duration_minutes": workout.get("duration_minutes", 0),
                "latest_workout_date": workout_date,
                "muscle_groups": workout.get("muscle_groups", []),
            }
        )
    return {
        "window": window,
        "period": period,
        "items": items,
        "muscle_groups": [],
        "raw_window_days": 365,
        "message": "Lightweight summary from local cached workout rows.",
    }


@router.get("/api/training/summary/status")
def training_summary_status() -> dict[str, Any]:
    training_count = count_rows("workout_logs")
    raw_workouts = count_rows("raw_hevy_workouts")
    raw_sets = count_rows("raw_hevy_sets")
    weekly = count_rows("weekly_training_summary")
    monthly = count_rows("monthly_training_summary")
    prs = count_rows("exercise_prs")
    muscle = count_rows("muscle_group_training_summary")
    sync_state = _sync_state()
    summary_state = _summary_state()
    latest_rows = _valid_rows(fetch_latest_json_rows("workout_logs", limit=1000))
    raw_latest_rows = _valid_rows(fetch_latest_json_rows("raw_hevy_workouts", limit=500))
    latest_workout_date = _latest_date(latest_rows, "date")
    latest_hevy_date = _latest_date(raw_latest_rows, "date", "start_time", "created_at") or latest_workout_date
    return {
        "raw_window_days": 180,
        "total_raw_rows": training_count.get("count_estimate", 0),
        "recent_raw_rows": training_count.get("count_estimate", 0),
        "older_raw_rows": 0,
        "raw_hevy_workouts": raw_workouts.get("count_estimate", 0),
        "raw_hevy_sets": raw_sets.get("count_estimate", 0),
        "normalized_workouts": training_count.get("count_estimate", 0),
        "normalized_sets": training_count.get("count_estimate", 0),
        "cache_health": "ready",
        "weekly_summaries": weekly.get("count_estimate", 0) or summary_state.get("weekly_summaries", 0),
        "monthly_summaries": monthly.get("count_estimate", 0) or summary_state.get("monthly_summaries", 0),
        "exercise_prs": prs.get("count_estimate", 0) or summary_state.get("exercise_prs", 0),
        "muscle_group_periods": muscle.get("count_estimate", 0) or summary_state.get("muscle_group_periods", 0),
        "latest_sync_date": sync_state.get("last_sync_at") or sync_state.get("last_synced_at") or "",
        "last_summary_rebuild_at": summary_state.get("rebuilt_at", ""),
        "last_summary_rebuild_status": summary_state.get("status", "not_run"),
        "last_summary_rebuild_message": summary_state.get("message", ""),
        "latest_hevy_workout_date": latest_hevy_date,
        "latest_hevy_workout_title": "",
        "last_hevy_result": sync_state.get("last_result", {}),
        "last_hevy_error": sync_state.get("last_error", ""),
        "last_hevy_failures": sync_state.get("failures", []),
        "row_counts": {
            "workout_logs": training_count,
            "raw_hevy_workouts": raw_workouts,
            "raw_hevy_sets": raw_sets,
            "weekly_training_summary": weekly,
            "monthly_training_summary": monthly,
            "exercise_prs": prs,
            "muscle_group_training_summary": muscle,
        },
        "architecture": {
            "hevy_role": "manual_sync_to_local_cache",
            "hevy_sync_mode": "manual",
            "startup_source": "local_cache",
            "live_raw_window_days": 180,
            "historical_source": "bounded_local_rows",
        },
    }


@router.get("/api/training/sync/hevy/status")
def hevy_sync_status() -> dict[str, Any]:
    history = _history_payload(limit=1, days=3650)
    latest = history["items"][0] if history.get("items") else {}
    state = _sync_state()
    raw_workouts = count_rows("raw_hevy_workouts")
    raw_sets = count_rows("raw_hevy_sets")
    return {
        "status": "ready" if _hevy_configured() else "not_configured",
        "configured": _hevy_configured(),
        "last_synced_at": state.get("last_sync_at", ""),
        "last_error": state.get("last_error", ""),
        "last_result": state.get("last_result", {}),
        "safe_mode": False,
        "hevy_rows": history.get("debug", {}).get("hevy_rows", 0),
        "hevy_workouts": history.get("debug", {}).get("hevy_workouts", 0),
        "latest_workout_date": latest.get("date", ""),
        "latest_workout_title": latest.get("workout_type", ""),
        "raw_hevy_workouts": raw_workouts.get("count_estimate", 0),
        "raw_hevy_sets": raw_sets.get("count_estimate", 0),
        "startup_sync": False,
    }


@router.post("/api/training/sync/hevy")
def sync_hevy() -> dict[str, Any]:
    if not _hevy_configured():
        return {"status": "not_configured", "message": "HEVY_API_KEY is not configured.", "checked_hevy": False}
    try:
        from src.integrations.hevy_client import HevyIntegrationError, import_hevy_workouts, sync_hevy_events

        try:
            result = sync_hevy_events()
        except HevyIntegrationError:
            result = import_hevy_workouts(page_size=10, pages=1)
        return {"status": "ok", "checked_hevy": True, "core_training_summary": load_recent_training_summary(force_refresh=True), **_jsonable_result(result)}
    except Exception as exc:
        return {"status": "error", "checked_hevy": True, "error_type": type(exc).__name__, "message": str(exc)}


@router.post("/api/training/repair/hevy-set-data")
def repair_hevy_set_data(fetch_missing: bool = True, zero_only: bool = True) -> dict[str, Any]:
    if not _hevy_configured() and fetch_missing:
        return {
            "status": "not_configured",
            "message": "HEVY_API_KEY is not configured, so only cached raw Hevy payloads can be repaired.",
            "target_workouts": 0,
            "repaired_workouts": 0,
        }
    try:
        from src.integrations.hevy_client import repair_hevy_set_data as repair_hevy_rows

        result = repair_hevy_rows(fetch_missing=fetch_missing, zero_only=zero_only)
        return {"core_training_summary": load_recent_training_summary(force_refresh=True), **_jsonable_result(result)}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "message": str(exc), "repaired_workouts": 0}


@router.post("/api/training/import/hevy/preview")
def preview_hevy_import(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _hevy_configured():
        return {"status": "not_configured", "message": "HEVY_API_KEY is not configured.", "workouts": [], "warnings": []}
    payload = payload or {}
    page_size = _bounded_int(payload.get("page_size"), 10, 1, 10)
    pages = _bounded_int(payload.get("pages"), 1, 1, 3)
    try:
        from src.integrations.hevy_client import preview_hevy_import as preview

        return _jsonable_result(preview(page_size=page_size, pages=pages))
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "message": str(exc), "workouts": [], "warnings": [str(exc)]}


@router.post("/api/training/import/hevy")
def import_hevy(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not _hevy_configured():
        return {"status": "not_configured", "message": "HEVY_API_KEY is not configured.", "imported_workouts": 0, "imported_rows": 0}
    payload = payload or {}
    page_size = _bounded_int(payload.get("page_size"), 10, 1, 10)
    pages = _bounded_int(payload.get("pages"), 1, 1, 3)
    try:
        from src.integrations.hevy_client import import_hevy_workouts

        result = import_hevy_workouts(page_size=page_size, pages=pages)
        return {"status": "ok", "core_training_summary": load_recent_training_summary(force_refresh=True), **_jsonable_result(result)}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "message": str(exc), "imported_workouts": 0, "imported_rows": 0}


@router.post("/api/training/import/strava")
def import_strava(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    per_page = _bounded_int(payload.get("per_page"), 30, 1, 100)
    try:
        from src.integrations.strava_client import (
            StravaIntegrationError,
            StravaReconnectRequired,
            import_recent_runs,
        )

        result = import_recent_runs(per_page=per_page)
        return {
            "status": "ok",
            "message": "Strava activities imported.",
            "core_training_summary": load_recent_training_summary(force_refresh=True),
            **_jsonable_result(result),
        }
    except StravaReconnectRequired as exc:
        logger.warning("Strava import requires reconnect: %s", exc)
        return {
            "status": "reconnect_required",
            "message": str(exc),
            "reconnect_required": True,
            "fetched_activities": 0,
            "imported_runs": 0,
            "updated_runs": 0,
            "skipped_duplicates": 0,
            "latest_activity_date": "",
        }
    except StravaIntegrationError as exc:
        logger.warning("Strava import failed: %s", exc)
        return {
            "status": "error",
            "message": str(exc),
            "error_type": type(exc).__name__,
            "fetched_activities": 0,
            "imported_runs": 0,
            "updated_runs": 0,
            "skipped_duplicates": 0,
            "latest_activity_date": "",
        }
    except Exception as exc:
        logger.exception("Unexpected Strava import failure.")
        return {
            "status": "error",
            "message": str(exc),
            "error_type": type(exc).__name__,
            "fetched_activities": 0,
            "imported_runs": 0,
            "updated_runs": 0,
            "skipped_duplicates": 0,
            "latest_activity_date": "",
        }


@router.get("/api/training/export/hevy-raw")
def export_hevy_raw(limit: int = 5000) -> Response:
    bounded = _bounded_int(limit, 5000, 1, 5000)
    workouts = _valid_rows(fetch_latest_json_rows("raw_hevy_workouts", limit=bounded))
    sets = _valid_rows(fetch_latest_json_rows("raw_hevy_sets", limit=bounded))
    normalized = [
        row for row in _valid_rows(fetch_latest_json_rows("workout_logs", limit=bounded))
        if str(row.get("source") or "").lower() == "hevy" or row.get("hevy_workout_id")
    ]
    metadata = [{**training_summary_status(), "generated_at": utc_now_iso(), "limit": bounded}]
    return _excel_response(
        {
            "raw_workouts": workouts,
            "raw_sets": sets,
            "normalized_hevy": normalized,
            "metadata": metadata,
        },
        f"hevy_raw_export_{date.today().isoformat()}.xlsx",
        sets or normalized or workouts or metadata,
    )


@router.get("/api/training/export/normalized")
def export_normalized(limit: int = 5000) -> Response:
    bounded = _bounded_int(limit, 5000, 1, 5000)
    rows = _valid_rows(fetch_latest_json_rows("workout_logs", limit=bounded))
    weekly = _valid_rows(fetch_latest_json_rows("weekly_training_summary", limit=bounded))
    monthly = _valid_rows(fetch_latest_json_rows("monthly_training_summary", limit=bounded))
    prs = _valid_rows(fetch_latest_json_rows("exercise_prs", limit=bounded))
    muscle = _valid_rows(fetch_latest_json_rows("muscle_group_training_summary", limit=bounded))
    metadata = [{**training_summary_status(), "generated_at": utc_now_iso(), "limit": bounded}]
    return _excel_response(
        {
            "normalized_sets": rows,
            "weekly_summary": weekly,
            "monthly_summary": monthly,
            "exercise_prs": prs,
            "muscle_group_summary": muscle,
            "metadata": metadata,
        },
        f"training_normalized_export_{date.today().isoformat()}.xlsx",
        rows or metadata,
    )


@router.post("/api/training/rebuild-summaries")
def rebuild_summaries() -> dict[str, Any]:
    history = _history_payload(limit=200, days=365)
    workouts = history.get("items", [])
    generated_at = utc_now_iso()
    weekly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "workout_count": 0,
            "total_sets": 0,
            "total_reps": 0,
            "total_volume": 0.0,
            "duration_minutes": 0.0,
            "muscle_groups": [],
        }
    )
    monthly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "workout_count": 0,
            "total_sets": 0,
            "total_reps": 0,
            "total_volume": 0.0,
            "duration_minutes": 0.0,
            "muscle_groups": [],
        }
    )
    muscle_periods: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "workout_count": 0,
            "total_sets": 0,
            "total_reps": 0,
            "total_volume": 0.0,
        }
    )
    prs: dict[str, dict[str, Any]] = {}

    def add_period(bucket: dict[str, Any], period_start: str, workout: dict[str, Any]) -> None:
        bucket["period_start"] = period_start
        bucket["period_label"] = period_start
        bucket["workout_count"] += 1
        bucket["total_sets"] += _int(workout.get("total_sets"), 0)
        bucket["total_reps"] += _int(workout.get("total_reps"), 0)
        bucket["total_volume"] += _number(workout.get("total_volume"), 0)
        bucket["duration_minutes"] += _number(workout.get("duration_minutes"), 0)
        bucket["latest_workout_date"] = max(str(bucket.get("latest_workout_date") or ""), str(workout.get("date") or "")[:10])
        bucket["muscle_groups"] = sorted(set(bucket["muscle_groups"]) | set(workout.get("muscle_groups") or []))

    for workout in workouts:
        workout_date = str(workout.get("date") or "")[:10]
        try:
            parsed_date = date.fromisoformat(workout_date)
            week = (parsed_date - timedelta(days=parsed_date.weekday())).isoformat()
            month = parsed_date.replace(day=1).isoformat()
        except ValueError:
            week = workout_date
            month = workout_date[:7]
        add_period(weekly[week], week, workout)
        add_period(monthly[month], month, workout)
        details = workout.get("details") if isinstance(workout.get("details"), list) else []
        seen_muscles: set[str] = set()
        for row in details:
            if not isinstance(row, dict):
                continue
            exercise = str(row.get("exercise") or "").strip()
            group = str(row.get("muscle_group") or "").strip() or _infer_muscle_group(exercise)
            sets = max(0, _int(row.get("sets"), 0))
            reps = max(0, _int(row.get("reps"), 0))
            weight = _number(row.get("weight"), 0)
            volume = _volume(row)
            if group:
                seen_muscles.add(group)
                for period_type, period_start in (("weekly", week), ("monthly", month)):
                    muscle_bucket = muscle_periods[(period_type, period_start, group)]
                    muscle_bucket["period_type"] = period_type
                    muscle_bucket["period_start"] = period_start
                    muscle_bucket["muscle_group"] = group
                    muscle_bucket["total_sets"] += sets
                    muscle_bucket["total_reps"] += sets * reps
                    muscle_bucket["total_volume"] += volume
                    muscle_bucket["latest_workout_date"] = max(str(muscle_bucket.get("latest_workout_date") or ""), workout_date)
            if exercise and weight > 0 and reps > 0:
                estimated_1rm = round(weight * (1 + reps / 30), 1)
                current = prs.get(exercise)
                if current is None or estimated_1rm > _number(current.get("estimated_1rm"), 0):
                    prs[exercise] = {
                        "pr_id": f"exercise-pr:{exercise.lower()}",
                        "exercise": exercise,
                        "date": workout_date,
                        "weight": weight,
                        "reps": reps,
                        "estimated_1rm": estimated_1rm,
                        "workout_id": workout.get("workout_id") or "",
                        "workout_type": workout.get("workout_type") or "",
                        "source": workout.get("source") or "local_cache",
                        "updated_at": generated_at,
                    }
        for group in seen_muscles:
            for period_type, period_start in (("weekly", week), ("monthly", month)):
                muscle_periods[(period_type, period_start, group)]["workout_count"] += 1

    summary_items = [dict(value) for value in weekly.values()]
    for item in summary_items:
        item["summary_id"] = f"weekly-training:{item.get('period_start')}"
        item["updated_at"] = generated_at
    monthly_items = [dict(value) for value in monthly.values()]
    for item in monthly_items:
        item["summary_id"] = f"monthly-training:{item.get('period_start')}"
        item["updated_at"] = generated_at
    muscle_items = [dict(value) for value in muscle_periods.values()]
    for item in muscle_items:
        item["summary_id"] = f"muscle-training:{item.get('period_type')}:{item.get('period_start')}:{item.get('muscle_group')}"
        item["updated_at"] = generated_at
        item["total_volume"] = round(_number(item.get("total_volume"), 0), 1)
    pr_items = sorted(prs.values(), key=lambda item: (str(item.get("date") or ""), _number(item.get("estimated_1rm"), 0)), reverse=True)
    result = {
        "status": "ok",
        "message": "Training summaries rebuilt from bounded local cached workout rows.",
        "raw_rows_summarized": len(workouts),
        "weekly_summaries": len(weekly),
        "monthly_summaries": len(monthly),
        "exercise_prs": len(pr_items),
        "muscle_group_periods": len(muscle_items),
        "items": summary_items,
        "monthly_items": monthly_items,
        "exercise_pr_items": pr_items,
        "muscle_group_items": muscle_items,
        "generated_at": generated_at,
    }
    for item in summary_items:
        if item.get("period_start"):
            upsert_json_row("weekly_training_summary", "summary_id", str(item["summary_id"]), item)
    for item in monthly_items:
        if item.get("period_start"):
            upsert_json_row("monthly_training_summary", "summary_id", str(item["summary_id"]), item)
    for item in pr_items:
        if item.get("pr_id"):
            upsert_json_row("exercise_prs", "pr_id", str(item["pr_id"]), item)
    for item in muscle_items:
        if item.get("summary_id"):
            upsert_json_row("muscle_group_training_summary", "summary_id", str(item["summary_id"]), item)
    insert_json_row(
        "training_summary_state",
        {
            "status": result["status"],
            "message": result["message"],
            "raw_rows_summarized": result["raw_rows_summarized"],
            "weekly_summaries": result["weekly_summaries"],
            "monthly_summaries": result["monthly_summaries"],
            "exercise_prs": result["exercise_prs"],
            "muscle_group_periods": result["muscle_group_periods"],
            "rebuilt_at": result["generated_at"],
        },
    )
    result["core_training_summary"] = load_recent_training_summary(force_refresh=True)
    return result


@router.get("/api/training/pr-history")
def pr_history(exercise: str = "", limit: int = 200) -> dict[str, Any]:
    bounded = _bounded_int(limit, 200, 1, 1000)
    cached_prs = _valid_rows(fetch_latest_json_rows("exercise_prs", limit=bounded))
    if cached_prs:
        filtered = [item for item in cached_prs if not exercise or str(item.get("exercise") or "").lower() == exercise.lower()]
        exercise_options = sorted({str(row.get("exercise") or "").strip() for row in cached_prs if str(row.get("exercise") or "").strip()})
        return {
            "exercise": exercise,
            "exercise_options": exercise_options,
            "items": filtered[:bounded],
            "raw_window_days": 365,
            "debug": {"rows_read": len(cached_prs), "full_raw_hevy_scan": False, "source": "exercise_prs_cache"},
        }
    rows = _valid_rows(fetch_latest_json_rows("workout_logs", limit=5000))
    best_by_exercise_date: dict[tuple[str, str], dict[str, Any]] = {}
    exercises: set[str] = set()
    for row in rows:
        name = str(row.get("exercise") or "").strip()
        if not name:
            continue
        if exercise and name.lower() != exercise.lower():
            continue
        exercises.add(name)
        reps = max(1, _int(row.get("reps"), 1))
        weight = _number(row.get("weight"), 0)
        estimated_1rm = weight * (1 + reps / 30)
        row_date = str(row.get("date") or "")[:10]
        key = (name, row_date)
        current = best_by_exercise_date.get(key)
        if current is None or estimated_1rm > current.get("estimated_1rm", 0):
            best_by_exercise_date[key] = {
                "exercise": name,
                "date": row_date,
                "weight": weight,
                "reps": reps,
                "estimated_1rm": round(estimated_1rm, 1),
                "workout_id": row.get("workout_id") or row.get("hevy_workout_id") or "",
                "source": row.get("source") or "local_cache",
            }
    items = sorted(best_by_exercise_date.values(), key=lambda item: (item["exercise"], item["date"]), reverse=True)[:bounded]
    all_exercise_rows = _valid_rows(fetch_latest_json_rows("workout_logs", limit=5000))
    exercise_options = sorted({str(row.get("exercise") or "").strip() for row in all_exercise_rows if str(row.get("exercise") or "").strip()})
    return {
        "exercise": exercise,
        "exercise_options": exercise_options,
        "items": items,
        "raw_window_days": 180,
        "debug": {"rows_read": len(rows), "full_raw_hevy_scan": False},
    }


@router.post("/api/training/consolidate-history")
def consolidate_history() -> dict[str, Any]:
    result = rebuild_summaries()
    return {
        "status": result["status"],
        "raw_rows_summarized": len(result.get("items", [])),
        "weekly_summaries": result.get("weekly_summaries", 0),
        "monthly_summaries": result.get("monthly_summaries", 0),
        "message": result.get("message", ""),
    }
