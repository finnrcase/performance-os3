import logging

from fastapi import APIRouter, HTTPException, Request
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
from src.training import add_training_entry, load_recent_training_log, load_training_log, move_workout_date
from src.training_schedule import load_training_schedule_profile, planned_training_for_date, save_training_schedule_profile


router = APIRouter(tags=["training"])
logger = logging.getLogger(__name__)


def _safe_training_items() -> list[dict]:
    try:
        return dataframe_records(load_training_log())
    except Exception as exc:
        logger.warning("Training log unavailable while reporting Hevy sync failure: %s", exc)
        return []


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


def _training_log_with_volume() -> pd.DataFrame:
    training_df = load_training_log()
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

    df = _training_log_with_volume()
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
    df = _training_log_with_volume()
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


@router.get("/api/training/logs")
def get_training_logs() -> dict:
    """Return saved training logs."""
    return {"items": dataframe_records(load_training_log())}


@router.get("/api/training/history")
def get_training_history() -> dict:
    """Return expandable workouts grouped by date and workout_id."""
    return {"items": grouped_workout_history(load_training_log())}


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
    training_df = load_training_log()
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
def get_strength_trends(exercise_name: str = "", date_range: str = "12w", muscle_group: str = "") -> dict:
    """Return exercise-level and muscle-group strength trend analytics."""
    training_df = load_recent_training_log(days=84)
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
    training_df = load_training_log()
    return analyze_muscle_balance(training_df, latest_recovery_score=_latest_recovery_score(training_df))


@router.post("/api/training/logs")
def add_training_log(entry: TrainingEntry) -> dict:
    """Add a local training entry."""
    training_df = add_training_entry(**entry.model_dump())
    return {"items": dataframe_records(training_df)}


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
    training_df = load_training_log()
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
            "items": dataframe_records(load_training_log()),
        }

    return {
        "status": "ok",
        "imported_runs": result["imported_runs"],
        "updated_runs": result.get("updated_runs", 0),
        "fetched_activities": result.get("fetched_activities", 0),
        "latest_activity_date": result.get("latest_activity_date", ""),
        "skipped_duplicates": result["skipped_duplicates"],
        "personal_records": update_personal_records_from_logs(result["training_log"]),
        "items": dataframe_records(result["training_log"]),
        "last_synced_at": result.get("last_synced_at", ""),
    }


@router.post("/api/training/sync/hevy")
def sync_hevy_now() -> dict:
    """Immediately poll Hevy workout events and apply changed/deleted workouts."""
    try:
        result = sync_hevy_events()
    except HevyIntegrationError as exc:
        logger.warning("Manual Hevy sync failed: %s", exc)
        return {
            "status": "error",
            "message": str(exc),
            "events": 0,
            "saved_workouts": 0,
            "deleted_rows": 0,
            "failures": [str(exc)],
            "items": _safe_training_items(),
            "last_synced_at": load_hevy_sync_state().get("last_sync_at", ""),
        }
    except Exception as exc:
        logger.exception("Unexpected manual Hevy sync failure.")
        state = save_hevy_sync_state({"last_error": str(exc), "last_result": {"status": "error", "source": "manual_sync"}})
        return {
            "status": "error",
            "message": str(exc),
            "events": 0,
            "saved_workouts": 0,
            "deleted_rows": 0,
            "failures": [str(exc)],
            "items": _safe_training_items(),
            "last_synced_at": state.get("last_sync_at", ""),
        }
    return {
        "status": "ok",
        "events": result["events"],
        "saved_workouts": result["saved_workouts"],
        "deleted_rows": result["deleted_rows"],
        "failures": result["failures"],
        "items": dataframe_records(result["training_log"]),
        "last_synced_at": result.get("last_synced_at", ""),
    }


@router.get("/api/training/sync/hevy/status")
def hevy_sync_status() -> dict:
    """Return last Hevy sync metadata for UI freshness labels."""
    state = load_hevy_sync_state()
    return {
        "last_synced_at": state.get("last_sync_at", ""),
        "last_error": state.get("last_error", ""),
        "last_result": state.get("last_result", {}),
        "safe_mode": bool(state.get("safe_mode")),
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
        return {
            "status": "error",
            "message": str(exc),
            "imported_workouts": 0,
            "imported_rows": 0,
            "skipped_duplicates": 0,
            "failures": [],
            "items": dataframe_records(load_training_log()),
        }

    return {
        "status": "ok",
        "imported_workouts": result["imported_workouts"],
        "imported_rows": result["imported_rows"],
        "skipped_duplicates": result["skipped_duplicates"],
        "skipped_workouts": result["skipped_workouts"],
        "failures": result["failures"],
        "debug_file": result["debug_file"],
        "personal_records": update_personal_records_from_logs(result["training_log"]),
        "items": dataframe_records(result["training_log"]),
        "last_synced_at": result.get("last_synced_at", ""),
    }
