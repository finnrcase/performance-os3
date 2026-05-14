"""Read-only data export endpoints."""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response

from src.analytics.food_history import DAILY_NUTRITION_SUMMARY_PATH, SUMMARY_COLUMNS, build_daily_nutrition_summary, save_daily_nutrition_summary
from src.analytics.personal_records import PERSONAL_RECORDS_PATH
from src.analytics.personal_response_learning import generate_personal_response_learning
from src.analytics.strength_trends import calculate_estimated_1rm
from src.analytics.training_workload import analyze_training_workload
from src.analytics.workout_quality import calculate_workout_quality
from src.body_metrics import BODY_METRICS_COLUMNS, BODY_METRICS_PATH, load_body_metrics
from src.config import SETTINGS_PATH
from src.goals import USER_GOALS_PATH, build_automatic_goals, load_user_goals
from src.integrations.hevy_client import HEVY_SYNC_STATE_PATH
from src.nutrition import (
    FOOD_SHORTCUTS_PATH,
    FOOD_SHORTCUT_COLUMNS,
    FREQUENT_FOODS_PATH,
    FREQUENT_FOOD_COLUMNS,
    MEAL_TEMPLATES_PATH,
    MEAL_TEMPLATE_COLUMNS,
    NUTRITION_COLUMNS,
    NUTRITION_LOG_PATH,
    load_nutrition_log,
)
from src.nutrition_targets import NUTRITION_TARGETS_PATH, calculate_macro_targets, load_nutrition_targets
from src.optimization.adaptive_nutrition_engine import NUTRITION_RECOMMENDATION_HISTORY_PATH
from src.optimization.high_value_features import build_optimization_features
from src.optimization.performance_engine import generate_performance_recommendations
from src.recovery import RECOVERY_COLUMNS, RECOVERY_LOG_PATH, SLEEP_ENTRIES_PATH, SLEEP_ENTRY_COLUMNS, calculate_recovery_score, load_recovery_log, load_sleep_entries
from src.storage import load_dataframe, load_document, save_dataframe, save_document
from src.training import TRAINING_COLUMNS, TRAINING_LOG_PATH, load_training_log


router = APIRouter(prefix="/api/export", tags=["export"])

ACCESS_COOKIE = "performance_os_access"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30

CSV_COLUMNS = [
    "date",
    "body_weight",
    "body_fat_percent",
    "lean_mass",
    "fat_mass",
    "calories_consumed",
    "calorie_target",
    "protein_consumed",
    "protein_target",
    "carbs_consumed",
    "carbs_target",
    "fat_consumed",
    "fat_target",
    "fiber",
    "sodium",
    "meal_count",
    "food_items_summary",
    "workout_completed",
    "workout_count",
    "workout_names",
    "total_sets",
    "total_reps",
    "total_volume",
    "estimated_1rm_highlights",
    "muscle_groups_trained",
    "workout_quality_score",
    "run_completed",
    "run_count",
    "total_miles",
    "total_run_duration",
    "average_pace",
    "strava_activity_names",
    "calories_burned_running",
    "recovery_score",
    "readiness_score",
    "sleep_duration_minutes",
    "sleep_duration_hours",
    "sleep_efficiency",
    "bedtime",
    "wake_time",
    "hrv",
    "resting_heart_rate",
    "recovery_status",
    "active_calorie_target",
    "active_macro_targets",
    "recommended_calorie_adjustment",
    "recommendation_summary",
    "personal_learning_insights",
]

BACKUP_DATASETS = {
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

BACKUP_DOCUMENTS = {
    "user_settings": SETTINGS_PATH,
    "user_goals": USER_GOALS_PATH,
    "nutrition_targets": NUTRITION_TARGETS_PATH,
    "nutrition_recommendation_history": NUTRITION_RECOMMENDATION_HISTORY_PATH,
    "personal_records": PERSONAL_RECORDS_PATH,
    "hevy_sync_state": HEVY_SYNC_STATE_PATH,
}

BACKUP_DEDUPE_KEYS = {
    "nutrition_log": ["created_at", "date", "meal_type", "food_name", "calories", "protein", "carbs", "fat"],
    "frequent_foods": ["food_name"],
    "food_shortcuts": ["shortcut_id"],
    "meal_templates": ["template_name", "food_name", "calories", "protein", "carbs", "fat"],
    "body_metrics": ["date", "bodyweight", "estimated_body_fat", "notes"],
    "training_log": ["workout_id", "external_id", "exercise", "set_number", "date"],
    "recovery_log": ["date"],
    "sleep_entries": ["id", "date"],
    "daily_nutrition_summary": ["date"],
}


def _sign_session(timestamp: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8").replace("+", "-").replace("/", "_").replace("=", "")


def _require_authenticated_request(request: Request) -> None:
    if not os.getenv("APP_PASSWORD"):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="APP_PASSWORD is not configured")
    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="SESSION_SECRET is not configured")

    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    timestamp, separator, signature = token.partition(".")
    if not separator:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    try:
        timestamp_ms = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc

    now_ms = int(time.time() * 1000)
    if now_ms - timestamp_ms > SESSION_MAX_AGE_SECONDS * 1000:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    expected_signature = _sign_session(timestamp, session_secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


def _parse_date_param(value: str | None, name: str) -> date | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name} must be YYYY-MM-DD")
    return parsed.date()


def _date_key(value) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    return parsed.date().isoformat()


def _dated_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["_export_date"] = out["date"].apply(_date_key)
    return out[out["_export_date"] != ""].copy()


def _all_data_dates(frames: list[pd.DataFrame]) -> list[date]:
    dates: set[date] = set()
    for frame in frames:
        if frame.empty or "date" not in frame.columns:
            continue
        parsed = pd.to_datetime(frame["date"], errors="coerce").dropna()
        dates.update(value.date() for value in parsed)
    return sorted(dates)


def _export_dates(frames: list[pd.DataFrame], start_date: date | None, end_date: date | None) -> list[date]:
    data_dates = _all_data_dates(frames)
    if start_date and end_date:
        day_count = (end_date - start_date).days
        return [start_date + timedelta(days=offset) for offset in range(day_count + 1)]

    filtered = []
    for item in data_dates:
        if start_date and item < start_date:
            continue
        if end_date and item > end_date:
            continue
        filtered.append(item)
    return filtered


def _is_missing(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _number(value, decimals: int = 1) -> str:
    if _is_missing(value):
        return ""
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return ""
    number = float(parsed)
    if abs(number - round(number)) < 0.005:
        return str(int(round(number)))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def _text(value) -> str:
    if _is_missing(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _json_ready(value):
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if _is_missing(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _dataframe_records(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    clean = df.where(pd.notna(df), None)
    return [_json_ready(record) for record in clean.to_dict(orient="records")]


def _dedupe_dataframe(dataset: str, df: pd.DataFrame) -> pd.DataFrame:
    subset = [column for column in BACKUP_DEDUPE_KEYS.get(dataset, []) if column in df.columns]
    if subset:
        return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)
    try:
        return df.drop_duplicates(keep="last").reset_index(drop=True)
    except TypeError:
        return df.astype(str).drop_duplicates(keep="last").reset_index(drop=True)


def _unique_join(values, limit: int | None = None) -> str:
    seen: set[str] = set()
    items = []
    for value in values:
        text = _text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
        if limit and len(items) >= limit:
            break
    return "; ".join(items)


def _note_value(note: str, key: str) -> str:
    marker = f"{key}="
    if marker not in str(note):
        return ""
    return str(note).split(marker, 1)[1].split("|", 1)[0].strip()


def _note_number(note: str, key: str) -> float:
    raw = _note_value(note, key)
    parsed = pd.to_numeric(raw, errors="coerce")
    return 0.0 if pd.isna(parsed) else float(parsed)


def _is_run_rows(df: pd.DataFrame) -> pd.Series:
    source = df.get("source", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    workout_type = df.get("workout_type", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    notes = df.get("notes", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    return source.eq("strava") | workout_type.str.contains("run", na=False) | notes.str.contains("strava_activity_id=", na=False)


def _build_active_targets(
    nutrition_df: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    training_df: pd.DataFrame,
) -> tuple[dict, dict]:
    goals = build_automatic_goals(load_user_goals(), body_metrics_df=body_metrics_df, training_df=training_df)
    active_targets = load_nutrition_targets()
    if active_targets:
        return active_targets, goals

    workload = analyze_training_workload(training_df, bodyweight=goals.get("current_bodyweight"))
    targets = calculate_macro_targets(
        goals,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        body_metrics_df=body_metrics_df,
        workload_data=workload,
    )
    return targets, goals


def _target_value(target_map: dict[str, dict], targets: dict, date_key: str, daily_key: str, target_key: str) -> str:
    daily_row = target_map.get(date_key, {})
    return _number(daily_row.get(daily_key), 0) or _number(targets.get(target_key), 0)


def _nutrition_by_date(nutrition_df: pd.DataFrame) -> dict[str, dict]:
    df = _dated_frame(nutrition_df)
    if df.empty:
        return {}

    result: dict[str, dict] = {}
    numeric_columns = ["calories", "protein", "carbs", "fat", "fiber", "sodium"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)

    for date_key, group in df.groupby("_export_date"):
        meal_types = [value for value in group.get("meal_type", pd.Series([], dtype=str)) if _text(value)]
        food_summaries = []
        for _, row in group.iterrows():
            name = _text(row.get("food_name")) or "Food"
            macro_parts = [
                f"{_number(row.get('calories'), 0)} kcal",
                f"P {_number(row.get('protein'), 0)}g",
                f"C {_number(row.get('carbs'), 0)}g",
                f"F {_number(row.get('fat'), 0)}g",
            ]
            food_summaries.append(f"{name} ({', '.join(part for part in macro_parts if part.strip())})")

        result[date_key] = {
            "calories_consumed": _number(group["calories"].sum(), 0),
            "protein_consumed": _number(group["protein"].sum(), 1),
            "carbs_consumed": _number(group["carbs"].sum(), 1),
            "fat_consumed": _number(group["fat"].sum(), 1),
            "fiber": _number(group["fiber"].sum(), 1),
            "sodium": _number(group["sodium"].sum(), 0),
            "meal_count": str(len(set(_text(value).lower() for value in meal_types if _text(value))) or len(group)),
            "food_items_summary": "; ".join(food_summaries),
        }
    return result


def _body_by_date(body_metrics_df: pd.DataFrame) -> dict[str, dict]:
    df = _dated_frame(body_metrics_df)
    if df.empty:
        return {}
    df = df.sort_values("_export_date")
    result: dict[str, dict] = {}
    for date_key, group in df.groupby("_export_date"):
        row = group.iloc[-1]
        body_weight = pd.to_numeric(row.get("bodyweight"), errors="coerce")
        body_fat = pd.to_numeric(row.get("estimated_body_fat"), errors="coerce")
        fat_mass = body_weight * (body_fat / 100) if pd.notna(body_weight) and pd.notna(body_fat) else None
        lean_mass = body_weight - fat_mass if fat_mass is not None else None
        result[date_key] = {
            "body_weight": _number(body_weight, 1),
            "body_fat_percent": _number(body_fat, 1),
            "lean_mass": _number(lean_mass, 1),
            "fat_mass": _number(fat_mass, 1),
        }
    return result


def _training_by_date(training_df: pd.DataFrame) -> tuple[dict[str, dict], dict[str, dict]]:
    df = _dated_frame(training_df)
    if df.empty:
        return {}, {}

    for column in ["sets", "reps", "weight", "duration_minutes"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    df["estimated_1rm"] = df.apply(lambda row: calculate_estimated_1rm(row.get("weight", 0), row.get("reps", 0)), axis=1)
    df["workout_title"] = df.get("notes", pd.Series("", index=df.index)).apply(lambda note: _note_value(str(note), "workout_title"))
    df["distance_miles"] = df.get("notes", pd.Series("", index=df.index)).apply(lambda note: _note_number(str(note), "distance_miles"))
    df["pace_min_per_mile"] = df.get("notes", pd.Series("", index=df.index)).apply(lambda note: _note_number(str(note), "pace_min_per_mile"))
    df["run_calories"] = df.get("notes", pd.Series("", index=df.index)).apply(lambda note: _note_number(str(note), "calories"))

    run_mask = _is_run_rows(df)
    workout_summary: dict[str, dict] = {}
    run_summary: dict[str, dict] = {}

    for date_key, group in df.loc[~run_mask].groupby("_export_date"):
        workout_ids = [_text(value) for value in group.get("workout_id", pd.Series([], dtype=str))]
        named_workouts = [
            _text(value)
            for value in list(group.get("workout_title", pd.Series([], dtype=str))) + list(group.get("workout_type", pd.Series([], dtype=str)))
        ]
        exercise_names = _unique_join(group.get("exercise", pd.Series([], dtype=str)), limit=8)
        names = _unique_join(named_workouts, limit=4) or exercise_names
        one_rep_max_rows = group[group["estimated_1rm"] > 0].copy()
        one_rep_max_rows = one_rep_max_rows.sort_values("estimated_1rm", ascending=False).drop_duplicates("exercise").head(3)
        highlights = "; ".join(
            f"{_text(row.get('exercise'))} {_number(row.get('estimated_1rm'), 1)} lb"
            for _, row in one_rep_max_rows.iterrows()
            if _text(row.get("exercise"))
        )
        quality = calculate_workout_quality(training_df, date_key)
        workout_summary[date_key] = {
            "workout_completed": "yes" if len(group) else "no",
            "workout_count": str(len(set(value for value in workout_ids if value)) or (1 if len(group) else 0)),
            "workout_names": names,
            "total_sets": _number(group["sets"].sum(), 0),
            "total_reps": _number(group["reps"].sum(), 0),
            "total_volume": _number(group["volume"].sum(), 0),
            "estimated_1rm_highlights": highlights,
            "muscle_groups_trained": _unique_join(group.get("muscle_group", pd.Series([], dtype=str))),
            "workout_quality_score": _number(quality.get("score"), 1),
        }

    for date_key, group in df.loc[run_mask].groupby("_export_date"):
        run_ids = [_text(value) for value in group.get("workout_id", pd.Series([], dtype=str))]
        total_miles = float(group["distance_miles"].sum())
        total_duration = float(group["duration_minutes"].sum())
        average_pace = _pace_text(total_duration / total_miles) if total_miles > 0 else ""
        run_summary[date_key] = {
            "run_completed": "yes" if len(group) else "no",
            "run_count": str(len(set(value for value in run_ids if value)) or (1 if len(group) else 0)),
            "total_miles": _number(total_miles, 2),
            "total_run_duration": _number(total_duration, 1),
            "average_pace": average_pace,
            "strava_activity_names": _unique_join(group.get("exercise", pd.Series([], dtype=str))),
            "calories_burned_running": _number(group["run_calories"].sum(), 0) if group["run_calories"].sum() > 0 else "",
        }

    return workout_summary, run_summary


def _pace_text(minutes_per_mile: float) -> str:
    if not minutes_per_mile or pd.isna(minutes_per_mile):
        return ""
    minutes = int(minutes_per_mile)
    seconds = int(round((minutes_per_mile - minutes) * 60))
    if seconds == 60:
        minutes += 1
        seconds = 0
    return f"{minutes}:{seconds:02d}/mi"


def _recovery_status(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 80:
        return "Optimal"
    if score >= 60:
        return "Moderate"
    if score >= 40:
        return "Fatigued"
    return "High Risk"


def _recovery_by_date(recovery_df: pd.DataFrame, sleep_df: pd.DataFrame) -> dict[str, dict]:
    recovery = _dated_frame(recovery_df)
    sleep = _dated_frame(sleep_df)
    result: dict[str, dict] = {}

    if not recovery.empty:
        for date_key, group in recovery.groupby("_export_date"):
            row = group.iloc[-1]
            score = calculate_recovery_score(row)
            result.setdefault(date_key, {}).update(
                {
                    "recovery_score": _number(score, 1),
                    "readiness_score": _number(row.get("readiness_score") if "readiness_score" in row else score, 1),
                    "hrv": _number(row.get("hrv"), 1),
                    "resting_heart_rate": _number(row.get("resting_hr"), 0),
                    "recovery_status": _recovery_status(score),
                }
            )

    if not sleep.empty:
        for column in ["durationMinutes", "efficiencyPercent", "restingHeartRate", "hrv"]:
            sleep[column] = pd.to_numeric(sleep.get(column, 0), errors="coerce")
        for date_key, group in sleep.groupby("_export_date"):
            duration = group["durationMinutes"].sum()
            efficiency = group["efficiencyPercent"].mean()
            hrv = group["hrv"].mean()
            resting_hr = group["restingHeartRate"].mean()
            result.setdefault(date_key, {}).update(
                {
                    "sleep_duration_minutes": _number(duration, 0),
                    "sleep_duration_hours": _number(duration / 60 if pd.notna(duration) else None, 2),
                    "sleep_efficiency": _number(efficiency, 1),
                    "bedtime": _unique_join(group.get("sleepStart", pd.Series([], dtype=str)), limit=1),
                    "wake_time": _unique_join(group.get("sleepEnd", pd.Series([], dtype=str)), limit=1),
                    "hrv": _number(hrv, 1) or result.get(date_key, {}).get("hrv", ""),
                    "resting_heart_rate": _number(resting_hr, 0) or result.get(date_key, {}).get("resting_heart_rate", ""),
                }
            )

    return result


def _system_summaries(
    targets: dict,
    goals: dict,
    nutrition_df: pd.DataFrame,
    nutrition_summary: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    sleep_df: pd.DataFrame,
    training_df: pd.DataFrame,
) -> dict:
    recommendation = generate_performance_recommendations(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        body_metrics_df=body_metrics_df,
        target_calories=targets.get("target_calories", 2850),
        target_protein=targets.get("protein_grams", 160),
        goal=goals.get("goal_type", "lean bulk"),
    )
    learning = generate_personal_response_learning(
        body_metrics_df=body_metrics_df,
        nutrition_df=nutrition_summary if not nutrition_summary.empty else nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        sleep_df=sleep_df,
        current_targets=targets,
    )
    insight_summaries = [
        f"{_text(item.get('title'))}: {_text(item.get('explanation'))}"
        for item in learning.get("insights", [])
        if _text(item.get("explanation"))
    ]
    return {
        "active_calorie_target": _number(targets.get("target_calories"), 0),
        "active_macro_targets": (
            f"P {_number(targets.get('protein_grams'), 0)}g / "
            f"C {_number(targets.get('carb_grams'), 0)}g / "
            f"F {_number(targets.get('fat_grams'), 0)}g"
        ),
        "recommended_calorie_adjustment": _number(targets.get("calorie_adjustment"), 0),
        "recommendation_summary": _text(recommendation.get("recommendation_summary")),
        "personal_learning_insights": "; ".join(insight_summaries) or _text(learning.get("summary")),
    }


@router.get("/daily-csv")
def export_daily_csv(
    _: None = Depends(_require_authenticated_request),
    start_date_value: str | None = Query(default=None, alias="startDate"),
    end_date_value: str | None = Query(default=None, alias="endDate"),
) -> Response:
    """Export available Performance OS data as one CSV row per day."""
    start_date = _parse_date_param(start_date_value, "startDate")
    end_date = _parse_date_param(end_date_value, "endDate")
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="endDate must be on or after startDate")

    nutrition_df = load_nutrition_log()
    body_metrics_df = load_body_metrics()
    recovery_df = load_recovery_log()
    sleep_df = load_sleep_entries()
    training_df = load_training_log()

    targets, goals = _build_active_targets(nutrition_df, body_metrics_df, recovery_df, training_df)
    nutrition_summary_df = build_daily_nutrition_summary(nutrition_df, targets)
    target_map = {
        _date_key(row.get("date")): row.to_dict()
        for _, row in nutrition_summary_df.iterrows()
        if _date_key(row.get("date"))
    }

    export_dates = _export_dates(
        [nutrition_df, body_metrics_df, recovery_df, sleep_df, training_df],
        start_date=start_date,
        end_date=end_date,
    )
    nutrition = _nutrition_by_date(nutrition_df)
    body = _body_by_date(body_metrics_df)
    workouts, runs = _training_by_date(training_df)
    recovery = _recovery_by_date(recovery_df, sleep_df)
    system_values = _system_summaries(
        targets=targets,
        goals=goals,
        nutrition_df=nutrition_df,
        nutrition_summary=nutrition_summary_df,
        body_metrics_df=body_metrics_df,
        recovery_df=recovery_df,
        sleep_df=sleep_df,
        training_df=training_df,
    )

    rows = []
    for export_date in export_dates:
        date_key = export_date.isoformat()
        row = dict.fromkeys(CSV_COLUMNS, "")
        row["date"] = date_key
        row.update(body.get(date_key, {}))
        row.update(nutrition.get(date_key, {}))
        row.update(
            {
                "calorie_target": _target_value(target_map, targets, date_key, "target_calories", "target_calories"),
                "protein_target": _target_value(target_map, targets, date_key, "target_protein", "protein_grams"),
                "carbs_target": _target_value(target_map, targets, date_key, "target_carbs", "carb_grams"),
                "fat_target": _target_value(target_map, targets, date_key, "target_fat", "fat_grams"),
            }
        )
        row.update(workouts.get(date_key, {"workout_completed": "no", "workout_count": "0"}))
        row.update(runs.get(date_key, {"run_completed": "no", "run_count": "0"}))
        row.update(recovery.get(date_key, {}))
        row.update(system_values)
        rows.append(row)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    filename = f"performance-os-backup-{date.today().isoformat()}.csv"
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/full-backup")
def export_full_backup(_: None = Depends(_require_authenticated_request)) -> Response:
    """Download a complete JSON backup of persisted Performance OS data."""
    nutrition_df = load_nutrition_log()
    body_metrics_df = load_body_metrics()
    recovery_df = load_recovery_log()
    sleep_df = load_sleep_entries()
    training_df = load_training_log()
    targets, goals = _build_active_targets(nutrition_df, body_metrics_df, recovery_df, training_df)
    nutrition_summary_df = build_daily_nutrition_summary(nutrition_df, targets)

    derived = {
        "system": _system_summaries(
            targets=targets,
            goals=goals,
            nutrition_df=nutrition_df,
            nutrition_summary=nutrition_summary_df,
            body_metrics_df=body_metrics_df,
            recovery_df=recovery_df,
            sleep_df=sleep_df,
            training_df=training_df,
        ),
        "optimization": build_optimization_features(
            nutrition_summary_df=nutrition_summary_df,
            training_df=training_df,
            recovery_df=recovery_df,
            sleep_df=sleep_df,
            body_metrics_df=body_metrics_df,
            targets=targets,
        ),
    }

    bundle = {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "dataframes": {
            dataset: _dataframe_records(load_dataframe(dataset, path, columns))
            for dataset, (path, columns) in BACKUP_DATASETS.items()
        },
        "documents": {
            name: _json_ready(load_document(name, path, {}))
            for name, path in BACKUP_DOCUMENTS.items()
        },
        "derived": _json_ready(derived),
    }
    filename = f"performance-os-full-backup-{date.today().isoformat()}.json"
    return Response(
        content=json.dumps(bundle, indent=2, default=_json_ready),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/full-backup/import")
async def import_full_backup(
    _: None = Depends(_require_authenticated_request),
    file: UploadFile = File(...),
) -> dict:
    """Safely merge a JSON backup into current storage with duplicate protection."""
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup import must be a JSON file.")
    content = await file.read()
    if len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup file is too large.")
    try:
        bundle = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup file is not valid JSON.") from exc
    if not isinstance(bundle, dict) or "dataframes" not in bundle:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup file is missing Performance OS dataframes.")

    imported: dict[str, dict] = {}
    incoming_dataframes = bundle.get("dataframes", {})
    if not isinstance(incoming_dataframes, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup dataframes must be an object.")

    for dataset, (path, columns) in BACKUP_DATASETS.items():
        if dataset not in incoming_dataframes:
            continue
        rows = incoming_dataframes.get(dataset) or []
        if not isinstance(rows, list):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{dataset} must be a list of rows.")
        incoming_df = pd.DataFrame(rows)
        for column in columns:
            if column not in incoming_df.columns:
                incoming_df[column] = pd.NA
        incoming_df = incoming_df[columns]
        current_df = load_dataframe(dataset, path, columns)
        merged_df = pd.concat([current_df, incoming_df], ignore_index=True)
        merged_df = _dedupe_dataframe(dataset, merged_df)
        save_dataframe(dataset, path, merged_df, columns)
        imported[dataset] = {"incoming_rows": len(incoming_df), "saved_rows": len(merged_df)}

    incoming_documents = bundle.get("documents", {})
    if incoming_documents and not isinstance(incoming_documents, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Backup documents must be an object.")
    document_count = 0
    for name, path in BACKUP_DOCUMENTS.items():
        document = incoming_documents.get(name) if isinstance(incoming_documents, dict) else None
        if not isinstance(document, dict) or not document:
            continue
        save_document(name, path, document)
        document_count += 1

    if "nutrition_log" in imported or "nutrition_targets" in incoming_documents:
        save_daily_nutrition_summary(build_daily_nutrition_summary(load_nutrition_log(), load_nutrition_targets()))

    return {
        "status": "ok",
        "message": "Backup imported safely.",
        "datasets": imported,
        "documents_imported": document_count,
    }
