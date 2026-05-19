import logging
import time
import json
from io import BytesIO, StringIO

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import pandas as pd

from backend.routes.utils import dataframe_records
from src.ai.training_insights import generate_training_insights
from src.analytics.muscle_balance import analyze_muscle_balance
from src.analytics.personal_records import update_personal_records_from_logs
from src.analytics.recovery_engine import calculate_recovery_score as calculate_advanced_recovery_score
from src.analytics.strength_trends import calculate_muscle_group_trend, calculate_strength_trend, calculate_volume_by_exercise
from src.analytics.training_workload import analyze_training_workload
from src.integrations.hevy_client import (
    HevyIntegrationError,
    handle_hevy_webhook,
    import_hevy_workouts,
    is_hevy_api_configured,
    load_hevy_sync_state,
    preview_hevy_import,
    save_hevy_sync_state,
    sync_hevy_events,
    verify_webhook_token,
)
from src.integrations.strava_client import StravaIntegrationError, import_recent_runs
from src.nutrition import calculate_daily_totals, load_nutrition_log
from src.nutrition_targets import calculate_macro_targets
from src.goals import build_automatic_goals, load_user_goals
from src.recovery import load_recovery_log
from src.training import (
    TRAINING_COLUMNS,
    TRAINING_LOG_PATH,
    add_training_entry,
    consolidate_old_training_history,
    load_exercise_pr_history,
    load_live_training_log,
    load_monthly_training_summary,
    load_muscle_group_volume_history,
    load_training_log,
    load_training_summary_state,
    load_weekly_training_summary,
    move_workout_date,
    recent_training_window,
    training_raw_window_days,
)
from src.storage import count_dataframe_rows
from src.training_schedule import load_training_schedule_profile, planned_training_for_date, save_training_schedule_profile


router = APIRouter(tags=["training"])
logger = logging.getLogger(__name__)


def _safe_training_items() -> list[dict]:
    try:
        return dataframe_records(load_live_training_log(max_rows=5000))
    except Exception as exc:
        logger.warning("Training log unavailable while reporting Hevy sync failure: %s", exc)
        return []


def _hevy_training_summary(training_df: pd.DataFrame | None = None) -> dict:
    try:
        df = load_live_training_log(max_rows=20000) if training_df is None else training_df
        df = recent_training_window(df, training_raw_window_days())
    except Exception as exc:
        logger.warning("Training log unavailable while summarizing Hevy rows: %s", exc)
        return {"hevy_rows": 0, "hevy_workouts": 0, "latest_workout_date": "", "latest_workout_title": ""}
    if df is None or df.empty:
        return {"hevy_rows": 0, "hevy_workouts": 0, "latest_workout_date": "", "latest_workout_title": ""}
    source = (df["source"] if "source" in df.columns else pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    notes = (df["notes"] if "notes" in df.columns else pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    hevy_id = (df["hevy_workout_id"] if "hevy_workout_id" in df.columns else pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    hevy_df = df.loc[(source == "hevy") | notes.str.contains("hevy_workout_id=", regex=False) | (hevy_id != "")].copy()
    if hevy_df.empty:
        return {"hevy_rows": 0, "hevy_workouts": 0, "latest_workout_date": "", "latest_workout_title": ""}
    hevy_df["date_dt"] = pd.to_datetime(hevy_df.get("date"), errors="coerce")
    latest_rows = hevy_df.dropna(subset=["date_dt"]).sort_values("date_dt")
    latest = latest_rows.iloc[-1] if not latest_rows.empty else hevy_df.iloc[-1]
    workout_ids = (hevy_df["workout_id"] if "workout_id" in hevy_df.columns else pd.Series("", index=hevy_df.index)).fillna("").astype(str).str.strip()
    workout_count = int(workout_ids[workout_ids != ""].nunique()) if not workout_ids.empty else 0
    title = ""
    notes_text = str(latest.get("notes", "") or "")
    if "workout_title=" in notes_text:
        title = notes_text.split("workout_title=", 1)[1].split("|", 1)[0].strip()
    return {
        "hevy_rows": int(len(hevy_df)),
        "hevy_workouts": workout_count,
        "latest_workout_date": str(latest.get("date", "") or ""),
        "latest_workout_title": title,
    }


@router.get("/status")
def status() -> dict:
    """Return placeholder route status."""
    return {"status": "placeholder", "module": "training"}


class TrainingEntry(BaseModel):
    workout_id: str = ""
    date: str
    workout_type: str
    muscle_group: str = ""
    exercise: str = ""
    set_number: int = 1
    sets: int = 0
    reps: int = 0
    weight: float = 0
    rpe: float = 0
    duration_minutes: float = 0
    notes: str = ""
    source: str = "manual"
    external_id: str = ""


class StravaImportRequest(BaseModel):
    per_page: int = 30


class HevyImportRequest(BaseModel):
    page_size: int = 10
    pages: int = 1


class TrainingInsightsRequest(BaseModel):
    exercise_name: str | None = None


class TrainingScheduleProfilePayload(BaseModel):
    name: str | None = None
    days: dict[str, dict]


def _training_log_with_volume(training_df: pd.DataFrame | None = None) -> pd.DataFrame:
    training_df = load_live_training_log(max_rows=20000) if training_df is None else training_df
    if training_df.empty:
        return training_df
    df = training_df.copy()
    for column in ["sets", "reps", "weight", "duration_minutes"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    return df


def grouped_workout_history(training_df: pd.DataFrame) -> list[dict]:
    """Group set-level rows into expandable workout/date cards."""
    if training_df.empty:
        return []

    df = _training_log_with_volume(training_df)
    group_columns = ["date", "workout_id"]
    cards = []
    for (date, workout_id), group in df.groupby(group_columns, dropna=False, sort=False):
        exercise_names = [name for name in group["exercise"].dropna().astype(str).unique().tolist() if name]
        muscle_groups = sorted({value for value in group["muscle_group"].dropna().astype(str) if value})
        sources = sorted({value for value in group["source"].dropna().astype(str) if value})
        details = dataframe_records(group.sort_values(["exercise", "set_number"]))
        cards.append(
            {
                "date": str(date),
                "workout_id": str(workout_id),
                "workout_type": ", ".join(sorted({str(value) for value in group["workout_type"].dropna().unique()})),
                "muscle_groups": muscle_groups,
                "exercise_names": exercise_names,
                "total_sets": int(group["sets"].sum()),
                "total_volume": round(float(group["volume"].sum()), 1),
                "duration_minutes": round(float(group["duration_minutes"].max()), 1),
                "source": ", ".join(sources) if sources else "manual",
                "details": details,
            }
        )
    return sorted(cards, key=lambda item: item["date"], reverse=True)


def _recent_training_summary(training_df: pd.DataFrame) -> dict:
    if training_df.empty:
        return {"workout_count": 0, "recent_volume": 0, "top_exercises": []}
    df = _training_log_with_volume(training_df)
    df["date_dt"] = pd.to_datetime(df["date"], errors="coerce")
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=28)
    recent = df[df["date_dt"] >= cutoff].copy()
    if recent.empty:
        recent = df.tail(50).copy()
    top_exercises = (
        recent.groupby("exercise", as_index=False)["volume"]
        .sum()
        .sort_values("volume", ascending=False)
        .head(8)
        .to_dict(orient="records")
    )
    return {
        "workout_count": int(recent[["date", "workout_id"]].drop_duplicates().shape[0]),
        "recent_volume": round(float(recent["volume"].sum()), 1),
        "top_exercises": top_exercises,
    }


def _latest_recovery_score(training_df: pd.DataFrame) -> float | None:
    recovery_df = load_recovery_log()
    if recovery_df.empty:
        return None
    goals = build_automatic_goals(load_user_goals(), training_df=training_df)
    targets = calculate_macro_targets(goals, training_df=training_df, workload_data=analyze_training_workload(training_df, bodyweight=goals["current_bodyweight"]))
    analytics = calculate_advanced_recovery_score(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=load_nutrition_log(),
        target_calories=targets["target_calories"],
    )
    if analytics.empty:
        return None
    return float(analytics.iloc[-1]["recovery_score"])


def _training_summary_status() -> dict:
    raw_window_days = training_raw_window_days()
    total_rows = count_dataframe_rows("training_log", TRAINING_LOG_PATH)
    recent_df = load_live_training_log(days=raw_window_days, max_rows=100000)
    recent_rows = int(len(recent_df))
    weekly = load_weekly_training_summary()
    monthly = load_monthly_training_summary()
    prs = load_exercise_pr_history()
    muscle = load_muscle_group_volume_history()
    state = load_training_summary_state()
    return {
        "raw_window_days": raw_window_days,
        "total_raw_rows": int(total_rows),
        "recent_raw_rows": recent_rows,
        "older_raw_rows": max(int(total_rows) - recent_rows, 0),
        "weekly_summaries": int(len(weekly)),
        "monthly_summaries": int(len(monthly)),
        "exercise_prs": int(len(prs)),
        "muscle_group_periods": int(len(muscle)),
        "last_summary_rebuild_date": state.get("last_rebuilt_at", ""),
        "latest_weekly_period": str(weekly["period_start"].max()) if not weekly.empty and "period_start" in weekly.columns else "",
        "latest_monthly_period": str(monthly["period_start"].max()) if not monthly.empty and "period_start" in monthly.columns else "",
        "coaching_contract": {
            "plateau_detection": f"recent raw set-level rows, capped at {raw_window_days} days",
            "calorie_changes": "recent bodyweight, finalized nutrition summaries, recent raw training load, recovery/sleep, and run/cardio load",
            "long_term_context": "weekly/monthly summaries plus PR history",
            "raw_features_preserved": [
                "exercise",
                "date",
                "set_number",
                "reps",
                "weight",
                "rpe",
                "estimated_1rm",
                "volume",
                "muscle_group",
                "hard_set_flag",
                "workout_id",
                "source",
            ],
        },
    }


def _note_markers(note: str) -> dict:
    markers: dict[str, str] = {}
    for part in str(note or "").split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = "".join(character if character.isalnum() or character == "_" else "_" for character in key.strip().lower())
        if key:
            markers[key] = value.strip()
    return markers


def _expand_note_markers(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "notes" not in df.columns:
        return df
    expanded = df.copy()
    marker_rows = expanded["notes"].fillna("").astype(str).apply(_note_markers)
    marker_keys = sorted({key for item in marker_rows for key in item.keys()})
    for key in marker_keys:
        column = f"note_{key}" if key in expanded.columns else key
        expanded[column] = marker_rows.apply(lambda item: item.get(key, ""))
    return expanded


def _excel_ready(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    for column in out.columns:
        out[column] = out[column].apply(lambda value: json.dumps(value, default=str) if isinstance(value, (dict, list)) else value)
    return out


@router.get("/api/training/logs")
def get_training_logs() -> dict:
    """Return recent raw set-level training logs only."""
    window_days = training_raw_window_days()
    return {
        "items": dataframe_records(load_live_training_log(days=window_days, max_rows=20000)),
        "raw_window_days": window_days,
        "message": f"Raw set-level rows are limited to the most recent {window_days} days.",
    }


@router.get("/api/training/history")
def get_training_history(limit: int = 50, days: int = 180) -> dict:
    """Return expandable workouts grouped by date and workout_id."""
    started = time.perf_counter()
    bounded_limit = max(1, min(int(limit or 50), 200))
    raw_window_days = training_raw_window_days()
    bounded_days = max(7, min(int(days or raw_window_days), raw_window_days))
    training_df = load_live_training_log(days=bounded_days, max_rows=max(bounded_limit * 80, 2000))
    grouped = grouped_workout_history(recent_training_window(training_df, days=bounded_days))
    items = grouped[:bounded_limit]
    logger.info(
        "training/history rows=%s grouped=%s returned=%s days=%s took=%.1fms",
        len(training_df),
        len(grouped),
        len(items),
        bounded_days,
        (time.perf_counter() - started) * 1000,
    )
    hevy_summary = _hevy_training_summary(training_df)
    return {
        "items": items,
        "limit": bounded_limit,
        "days": bounded_days,
        "raw_window_days": raw_window_days,
        "has_more_recent": len(grouped) > len(items),
        "message": f"Showing recent raw workouts from the last {bounded_days} days.",
        "debug": {
            **hevy_summary,
            "message": "No Hevy rows found" if hevy_summary["hevy_rows"] == 0 else "",
        },
    }


@router.get("/api/training/summary")
def get_training_summary(window: str = "weekly", period: str = "all", limit: int = 260) -> dict:
    """Return consolidated long-term training summaries without raw set rows."""
    selected_window = "monthly" if str(window).lower() == "monthly" else "weekly"
    bounded_limit = max(1, min(int(limit or 260), 1000))
    summary_df = load_monthly_training_summary() if selected_window == "monthly" else load_weekly_training_summary()
    if not summary_df.empty:
        summary_df = summary_df.sort_values("period_start")
        if period != "all":
            summary_df = summary_df.tail(bounded_limit)
    muscle_df = load_muscle_group_volume_history()
    if not muscle_df.empty:
        muscle_df = muscle_df[muscle_df["period_type"].fillna("").astype(str).str.lower() == selected_window].sort_values("period_start")
        if period != "all":
            muscle_df = muscle_df.tail(bounded_limit * 8)
    return {
        "window": selected_window,
        "period": period,
        "items": dataframe_records(summary_df.tail(bounded_limit) if period != "all" else summary_df),
        "muscle_groups": dataframe_records(muscle_df),
        "raw_window_days": training_raw_window_days(),
        "message": "Run /api/training/consolidate-history if no historical summary rows exist." if summary_df.empty else "",
    }


@router.get("/api/training/pr-history")
def get_training_pr_history(exercise: str = "", limit: int = 200) -> dict:
    """Return consolidated PR history by exercise."""
    bounded_limit = max(1, min(int(limit or 200), 1000))
    pr_df = load_exercise_pr_history()
    all_prs = pr_df.copy()
    if not pr_df.empty:
        if exercise:
            pr_df = pr_df[pr_df["exercise"].fillna("").astype(str).str.lower() == exercise.lower()]
        pr_df = pr_df.sort_values(["exercise", "date"]).tail(bounded_limit)
    exercises = sorted(all_prs["exercise"].fillna("").astype(str).replace("", pd.NA).dropna().unique().tolist()) if not all_prs.empty else []
    return {
        "exercise": exercise,
        "exercise_options": exercises,
        "items": dataframe_records(pr_df),
        "raw_window_days": training_raw_window_days(),
    }


@router.post("/api/training/consolidate-history")
def consolidate_training_history(cutoff_days: int | None = None) -> dict:
    """Build summary datasets for rows older than the live raw window."""
    started = time.perf_counter()
    result = consolidate_old_training_history(cutoff_days=cutoff_days)
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    result["status_summary"] = _training_summary_status()
    return result


@router.get("/api/training/summary/status")
def get_training_summary_status() -> dict:
    """Return raw-window and historical summary management status."""
    return _training_summary_status()


@router.get("/api/training/export/hevy-raw")
def export_hevy_raw_training_data():
    """Export all raw training rows and consolidated Hevy summaries."""
    started = time.perf_counter()
    today = pd.Timestamp.today().date().isoformat()
    raw_df = _expand_note_markers(load_training_log())
    workouts_df = pd.DataFrame(grouped_workout_history(raw_df)) if not raw_df.empty else pd.DataFrame()
    if not workouts_df.empty and "details" in workouts_df.columns:
        workouts_df = workouts_df.drop(columns=["details"])
    weekly = load_weekly_training_summary()
    prs = load_exercise_pr_history()
    metadata = pd.DataFrame([
        {
            **_training_summary_status(),
            "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
            "export_duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    ])
    filename = f"hevy_raw_export_{today}.xlsx"
    try:
        import openpyxl  # noqa: F401

        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            _excel_ready(raw_df).to_excel(writer, sheet_name="raw_sets", index=False)
            _excel_ready(workouts_df).to_excel(writer, sheet_name="workouts_summary", index=False)
            _excel_ready(prs).to_excel(writer, sheet_name="exercise_prs", index=False)
            _excel_ready(weekly).to_excel(writer, sheet_name="weekly_summary", index=False)
            _excel_ready(metadata).to_excel(writer, sheet_name="metadata", index=False)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.warning("Excel raw Hevy export failed; falling back to CSV: %s", exc)
        text_buffer = StringIO()
        _excel_ready(raw_df).to_csv(text_buffer, index=False)
        csv_buffer = BytesIO(text_buffer.getvalue().encode("utf-8"))
        return StreamingResponse(
            csv_buffer,
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="hevy_raw_export_{today}.csv"'},
        )


@router.get("/api/training/schedule")
def get_training_schedule() -> dict:
    """Return the configurable recurring split profile."""
    profile = load_training_schedule_profile()
    return {"profile": profile, "today": planned_training_for_date(pd.Timestamp.today().normalize(), profile=profile)}


@router.put("/api/training/schedule")
def update_training_schedule(payload: TrainingScheduleProfilePayload) -> dict:
    """Replace the recurring split profile used by dashboard/adaptive logic."""
    profile = save_training_schedule_profile(payload.model_dump(exclude_none=True))
    return {"profile": profile, "today": planned_training_for_date(pd.Timestamp.today().normalize(), profile=profile)}


@router.get("/api/training/exercises")
def get_training_exercises() -> dict:
    """Return exercise names for trend dropdowns."""
    training_df = load_live_training_log(max_rows=20000)
    if training_df.empty:
        return {"items": []}
    exercises = (
        training_df["exercise"]
        .fillna("")
        .astype(str)
        .str.strip()
        .loc[lambda series: series != ""]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    return {"items": exercises}


@router.get("/api/training/strength-trends")
def get_strength_trends(exercise_name: str = "", date_range: str = "12w", muscle_group: str = "", days: int | None = None) -> dict:
    """Return exercise-level and muscle-group strength trend analytics."""
    window_days = int(days) if days is not None else 84
    if date_range.endswith("w") and date_range[:-1].isdigit():
        window_days = int(date_range[:-1]) * 7
    elif date_range.endswith("d") and date_range[:-1].isdigit():
        window_days = int(date_range[:-1])
    window_days = max(28, min(window_days, training_raw_window_days()))
    training_df = load_live_training_log(days=window_days, max_rows=12000)
    if not exercise_name and not training_df.empty:
        exercise_counts = training_df["exercise"].fillna("").astype(str).str.strip()
        exercise_counts = exercise_counts[exercise_counts != ""]
        if not exercise_counts.empty:
            exercise_name = exercise_counts.value_counts().index[0]
    return {
        "exercise_options": sorted(training_df["exercise"].fillna("").astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()) if not training_df.empty else [],
        "selected_exercise": exercise_name,
        "trend": calculate_strength_trend(training_df, exercise_name),
        "volume_by_exercise": dataframe_records(calculate_volume_by_exercise(training_df)),
        "muscle_group_trends": calculate_muscle_group_trend(training_df, date_range=date_range, muscle_group=muscle_group),
    }


@router.get("/api/training/muscle-balance")
def get_muscle_balance() -> dict:
    """Return muscle group balance analytics."""
    training_df = load_live_training_log(max_rows=20000)
    return analyze_muscle_balance(training_df, latest_recovery_score=_latest_recovery_score(training_df))


@router.post("/api/training/logs")
def add_training_log(entry: TrainingEntry) -> dict:
    """Add a local training entry."""
    training_df = add_training_entry(**entry.model_dump())
    return {"items": dataframe_records(recent_training_window(training_df, training_raw_window_days()))}


class WorkoutDateUpdate(BaseModel):
    workout_id: str
    new_date: str


@router.post("/api/training/workout-date")
def update_workout_date(payload: WorkoutDateUpdate) -> dict:
    """Move a logged workout to a different date (e.g. an accidental same-day
    duplicate that belonged to the previous day). The workout is moved in
    place — never duplicated — and source IDs are preserved."""
    try:
        result = move_workout_date(payload.workout_id, payload.new_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", **result}


@router.post("/api/training/ai/insights")
def ai_training_insights(payload: TrainingInsightsRequest) -> dict:
    """Generate grounded AI training insights from local analytics summaries."""
    training_df = load_live_training_log(max_rows=20000)
    exercise_name = payload.exercise_name or ""
    if not exercise_name and not training_df.empty:
        exercises = get_training_exercises()["items"]
        exercise_name = exercises[0] if exercises else ""

    strength = calculate_strength_trend(training_df, exercise_name)
    recovery_score = _latest_recovery_score(training_df)
    goals = build_automatic_goals(load_user_goals(), training_df=training_df)
    targets = calculate_macro_targets(goals, training_df=training_df, workload_data=analyze_training_workload(training_df, bodyweight=goals["current_bodyweight"]))
    today = pd.Timestamp.today().date().isoformat()
    nutrition_status = {
        "today": calculate_daily_totals(load_nutrition_log(), today),
        "target_calories": targets["target_calories"],
        "target_protein": targets["protein_grams"],
    }
    return generate_training_insights(
        recent_training_summary=_recent_training_summary(training_df),
        strength_trends=strength,
        muscle_balance=analyze_muscle_balance(training_df, latest_recovery_score=recovery_score),
        recovery_score=recovery_score,
        nutrition_status=nutrition_status,
    )


@router.post("/api/training/import/strava")
def import_strava(payload: StravaImportRequest) -> dict:
    """Import recent Strava runs/activities into the local training log."""
    try:
        result = import_recent_runs(per_page=payload.per_page)
    except StravaIntegrationError as exc:
        return {
            "status": "error",
            "message": str(exc),
            "imported_runs": 0,
            "skipped_duplicates": 0,
            "items": _safe_training_items(),
        }

    return {
        "status": "ok",
        "imported_runs": result["imported_runs"],
        "updated_runs": result.get("updated_runs", 0),
        "fetched_activities": result.get("fetched_activities", 0),
        "latest_activity_date": result.get("latest_activity_date", ""),
        "skipped_duplicates": result["skipped_duplicates"],
        "personal_records": update_personal_records_from_logs(recent_training_window(result["training_log"], training_raw_window_days())),
        "items": dataframe_records(recent_training_window(result["training_log"], training_raw_window_days())),
        "last_synced_at": result.get("last_synced_at", ""),
    }


@router.post("/api/training/sync/hevy")
def sync_hevy_now() -> dict:
    """Manually sync Hevy events and import recent workouts as a fallback."""
    if not is_hevy_api_configured():
        message = "Missing Hevy API key. Enter a key or set HEVY_API_KEY."
        state = save_hevy_sync_state({"last_error": message, "last_result": {"status": "error", "source": "manual_sync"}})
        return {
            "status": "error",
            "message": message,
            "events": 0,
            "saved_workouts": 0,
            "imported_workouts": 0,
            "imported_rows": 0,
            "deleted_rows": 0,
            "failures": [message],
            "items": _safe_training_items(),
            "last_synced_at": state.get("last_sync_at", ""),
            **_hevy_training_summary(),
        }

    failures: list[str] = []
    events = 0
    event_saved_workouts = 0
    deleted_rows = 0
    imported_workouts = 0
    imported_rows = 0
    replaced_rows = 0
    training_df = pd.DataFrame(columns=TRAINING_COLUMNS)

    try:
        event_result = sync_hevy_events()
        events = int(event_result.get("events", 0) or 0)
        event_saved_workouts = int(event_result.get("saved_workouts", 0) or 0)
        deleted_rows = int(event_result.get("deleted_rows", 0) or 0)
        failures.extend(str(item) for item in event_result.get("failures", []) if str(item).strip())
        if isinstance(event_result.get("training_log"), pd.DataFrame):
            training_df = event_result["training_log"]
    except HevyIntegrationError as exc:
        logger.warning("Manual Hevy event sync failed; falling back to recent import: %s", exc)
        failures.append(f"event sync: {exc}")
    except Exception as exc:
        logger.exception("Unexpected manual Hevy event sync failure; falling back to recent import.")
        failures.append(f"event sync: {exc}")

    try:
        import_result = import_hevy_workouts(page_size=10, pages=1)
        imported_workouts = int(import_result.get("imported_workouts", 0) or 0)
        imported_rows = int(import_result.get("imported_rows", 0) or 0)
        replaced_rows = int(import_result.get("skipped_duplicates", 0) or 0)
        failures.extend(str(item) for item in import_result.get("failures", []) if str(item).strip())
        if isinstance(import_result.get("training_log"), pd.DataFrame):
            training_df = import_result["training_log"]
    except HevyIntegrationError as exc:
        logger.warning("Manual Hevy recent import failed: %s", exc)
        failures.append(f"recent import: {exc}")
    except Exception as exc:
        logger.exception("Unexpected manual Hevy recent import failure.")
        failures.append(f"recent import: {exc}")

    saved_workouts = event_saved_workouts + imported_workouts
    status_value = "ok" if saved_workouts > 0 or deleted_rows > 0 or not failures else "error"
    message = "" if status_value == "ok" else failures[0] if failures else "Hevy sync failed."
    summary = _hevy_training_summary(training_df)
    last_result = {
        "status": status_value,
        "source": "manual_sync",
        "events": events,
        "saved_workouts": saved_workouts,
        "event_saved_workouts": event_saved_workouts,
        "imported_workouts": imported_workouts,
        "imported_rows": imported_rows,
        "replaced_rows": replaced_rows,
        "deleted_rows": deleted_rows,
        "failures": failures,
        **summary,
    }
    state = save_hevy_sync_state({"last_error": message, "last_result": last_result})
    last_synced_at = state.get("last_sync_at", "")
    return {
        "status": status_value,
        "message": message,
        "events": events,
        "saved_workouts": saved_workouts,
        "event_saved_workouts": event_saved_workouts,
        "imported_workouts": imported_workouts,
        "imported_rows": imported_rows,
        "replaced_rows": replaced_rows,
        "deleted_rows": deleted_rows,
        "failures": failures,
        "items": dataframe_records(recent_training_window(training_df, training_raw_window_days())),
        "last_synced_at": last_synced_at,
        **summary,
    }


@router.get("/api/training/sync/hevy/status")
def hevy_sync_status() -> dict:
    """Return last Hevy sync metadata for UI freshness labels."""
    state = load_hevy_sync_state()
    summary = _hevy_training_summary()
    configured = is_hevy_api_configured()
    last_error = state.get("last_error", "")
    return {
        "status": "error" if last_error else "connected" if configured else "not_configured",
        "configured": configured,
        "last_synced_at": state.get("last_sync_at", ""),
        "last_error": last_error,
        "last_result": state.get("last_result", {}),
        "safe_mode": bool(state.get("safe_mode")),
        **summary,
    }


@router.post("/api/hevy/webhook")
async def hevy_webhook(request: Request) -> dict:
    """Receive Hevy workout webhooks and upsert/delete the affected workout."""
    headers = {key.lower(): value for key, value in request.headers.items()}
    if not verify_webhook_token(headers):
        raise HTTPException(status_code=401, detail="Invalid Hevy webhook secret.")
    payload = await request.json()
    try:
        result = handle_hevy_webhook(payload)
    except HevyIntegrationError as exc:
        logger.warning("Hevy webhook failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Unexpected Hevy webhook failure.")
        raise HTTPException(status_code=503, detail="Hevy webhook sync failed safely. Retry later.") from exc
    return {
        "status": result.get("status", "ok"),
        "action": result.get("action", "processed"),
        "workout_id": result.get("workout_id"),
        "saved_rows": result.get("saved_rows", 0),
        "replaced_rows": result.get("replaced_rows", 0),
        "deleted_rows": result.get("deleted_rows", 0),
    }


@router.post("/api/training/import/hevy/preview")
def preview_hevy(payload: HevyImportRequest) -> dict:
    """Preview recent Hevy workouts before writing rows to the local log."""
    try:
        return preview_hevy_import(page_size=payload.page_size, pages=payload.pages)
    except HevyIntegrationError as exc:
        return {
            "status": "error",
            "message": str(exc),
            "workouts": [],
            "estimated_rows": 0,
            "duplicates_detected": 0,
            "warnings": [],
        }


@router.post("/api/training/import/hevy")
def import_hevy(payload: HevyImportRequest) -> dict:
    """Manually import or update recent Hevy workouts into the local training log."""
    try:
        result = import_hevy_workouts(page_size=payload.page_size, pages=payload.pages)
    except HevyIntegrationError as exc:
        summary = _hevy_training_summary()
        return {
            "status": "error",
            "message": str(exc),
            "imported_workouts": 0,
            "imported_rows": 0,
            "skipped_duplicates": 0,
            "failures": [str(exc)],
            "items": _safe_training_items(),
            **summary,
        }

    summary = _hevy_training_summary(result["training_log"])
    recent_items = recent_training_window(result["training_log"], training_raw_window_days())
    return {
        "status": "ok",
        "imported_workouts": result["imported_workouts"],
        "imported_rows": result["imported_rows"],
        "skipped_duplicates": result["skipped_duplicates"],
        "skipped_workouts": result["skipped_workouts"],
        "failures": result["failures"],
        "debug_file": result["debug_file"],
        "personal_records": update_personal_records_from_logs(recent_items),
        "items": dataframe_records(recent_items),
        "last_synced_at": result.get("last_synced_at", ""),
        **summary,
    }
