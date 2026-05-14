"""FastAPI placeholder for the future Performance OS production backend.

The Streamlit app in app/main.py remains the current MVP user interface.
This FastAPI app will eventually serve a modern frontend while reusing the
shared business logic in src/.
"""

from pathlib import Path
import logging
import os
import threading
import time

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.routes import body_metrics, goals, integrations, nutrition, personal_records, recovery, training
from backend.routes.utils import dataframe_records
from src.analytics.food_history import (
    build_daily_nutrition_summary,
    calculate_calorie_adherence,
    get_food_history_for_optimization,
    save_daily_nutrition_summary,
)
from src.analytics.muscle_balance import analyze_muscle_balance
from src.analytics.personal_records import update_personal_records_from_logs
from src.analytics.personal_response_learning import generate_personal_response_learning
from src.analytics.recovery_engine import calculate_recovery_score as calculate_advanced_recovery_score
from src.analytics.strength_trends import calculate_strength_trend
from src.analytics.todays_action import generate_todays_action
from src.analytics.training_workload import analyze_training_workload
from src.analytics.weekly_report import generate_weekly_performance_report
from src.analytics.workout_quality import calculate_workout_quality
from src.body_metrics import load_body_metrics
from src.goals import build_automatic_goals, load_user_goals
from src.nutrition import calculate_daily_totals, load_nutrition_log
from src.nutrition_targets import analyze_weight_trend, calculate_macro_targets, load_nutrition_targets
from src.optimization.adaptive_nutrition_engine import build_adaptive_nutrition_recommendation
from src.optimization.lean_bulk_engine import generate_lean_bulk_calorie_recommendation
from src.optimization.performance_engine import generate_performance_recommendations
from src.optimization.run_readiness import generate_extra_run_readiness
from src.recovery import load_recovery_log, load_sleep_entries
from src.training import calculate_training_volume, load_training_log
from src.integrations.hevy_client import HevyIntegrationError, sync_hevy_events


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)
logger = logging.getLogger(__name__)
_hevy_poll_thread_started = False

app = FastAPI(
    title="Performance OS API",
    version="0.1.0",
    description="Placeholder API for the future production Performance OS frontend.",
)


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOW_ORIGINS", "") or os.getenv("FRONTEND_ORIGIN", "")
    origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
    ]
    if configured:
        origins.extend(origin.strip() for origin in configured.split(",") if origin.strip())
    return origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Health check used by local development and deployment probes."""
    return {"status": "ok", "service": "performance-os-api"}


def _hevy_poll_loop() -> None:
    interval_seconds = int(os.getenv("HEVY_POLL_INTERVAL_SECONDS", "300") or 300)
    interval_seconds = max(300, min(interval_seconds, 600))
    while True:
        time.sleep(interval_seconds)
        try:
            logger.info("Starting scheduled Hevy event poll.")
            sync_hevy_events()
        except HevyIntegrationError as exc:
            logger.warning("Scheduled Hevy sync failed: %s", exc)
        except Exception:
            logger.exception("Unexpected scheduled Hevy sync failure.")


@app.on_event("startup")
def start_hevy_polling() -> None:
    """Start a lightweight 5-10 minute Hevy event polling fallback."""
    global _hevy_poll_thread_started
    if _hevy_poll_thread_started:
        return
    _hevy_poll_thread_started = True
    thread = threading.Thread(target=_hevy_poll_loop, name="hevy-event-poller", daemon=True)
    thread.start()


@app.get("/api/dashboard")
def dashboard() -> dict:
    """Return local-first dashboard data for the Next.js frontend."""
    nutrition_df = load_nutrition_log()
    body_metrics_df = load_body_metrics()
    recovery_df = load_recovery_log()
    sleep_df = load_sleep_entries()
    training_df = load_training_log()
    goals = build_automatic_goals(load_user_goals(), body_metrics_df=body_metrics_df, training_df=training_df)
    active_targets = load_nutrition_targets()
    training_workload = analyze_training_workload(training_df, bodyweight=goals["current_bodyweight"])
    targets = calculate_macro_targets(
        goals,
        nutrition_df=nutrition_df,
        training_df=training_df,
        recovery_df=recovery_df,
        body_metrics_df=body_metrics_df,
        workload_data=training_workload,
    )
    daily_nutrition_summary = build_daily_nutrition_summary(nutrition_df, targets)
    save_daily_nutrition_summary(daily_nutrition_summary)
    nutrition_for_optimization = get_food_history_for_optimization(daily_nutrition_summary)

    today = pd.Timestamp.today().date().isoformat()
    nutrition_totals = calculate_daily_totals(nutrition_df, today)
    weight_feedback = analyze_weight_trend(body_metrics_df, goals)

    latest_bodyweight = None
    bodyweight_trend = []
    if not body_metrics_df.empty:
        bodyweight_clean = body_metrics_df.copy()
        bodyweight_clean["date"] = pd.to_datetime(bodyweight_clean["date"], errors="coerce")
        bodyweight_clean["bodyweight"] = pd.to_numeric(bodyweight_clean["bodyweight"], errors="coerce")
        bodyweight_clean = bodyweight_clean.dropna(subset=["date", "bodyweight"]).sort_values("date")
        if not bodyweight_clean.empty:
            latest_bodyweight = float(bodyweight_clean.iloc[-1]["bodyweight"])
            bodyweight_clean["date"] = bodyweight_clean["date"].dt.date.astype(str)
            bodyweight_trend = dataframe_records(bodyweight_clean.tail(30))

    latest_recovery = None
    recovery_trend = []
    if not recovery_df.empty:
        recovery_analytics = calculate_advanced_recovery_score(
            recovery_df=recovery_df,
            training_df=training_df,
            nutrition_df=nutrition_df,
            target_calories=targets["target_calories"],
        )
        if not recovery_analytics.empty:
            recovery_analytics["date"] = pd.to_datetime(recovery_analytics["date"], errors="coerce").dt.date.astype(str)
            latest_recovery = dataframe_records(recovery_analytics.tail(1))[0]
            recovery_trend = dataframe_records(recovery_analytics.tail(30))

    latest_workout = None
    strength_trend_summary = {"label": "insufficient data", "exercise": "", "summary": "Log workouts to calculate strength trends."}
    muscle_balance_warning = None
    if not training_df.empty:
        latest_workout = dataframe_records(training_df.sort_values("date").tail(1))[0]
        exercises = training_df["exercise"].fillna("").astype(str).str.strip()
        exercises = exercises[exercises != ""]
        if not exercises.empty:
            selected_exercise = exercises.value_counts().index[0]
            trend = calculate_strength_trend(training_df, selected_exercise)
            strength_trend_summary = {
                "exercise": selected_exercise,
                "label": trend.get("label", "insufficient data"),
                "summary": trend.get("summary", ""),
            }
        balance = analyze_muscle_balance(
            training_df,
            latest_recovery_score=latest_recovery.get("recovery_score") if latest_recovery else None,
        )
        muscle_balance_warning = balance["flags"][0] if balance.get("flags") else None

    volume_df = calculate_training_volume(training_df)
    performance_plan = generate_performance_recommendations(
        recovery_df=recovery_df,
        training_df=training_df,
        nutrition_df=nutrition_df,
        body_metrics_df=body_metrics_df,
        target_calories=targets["target_calories"],
        target_protein=targets["protein_grams"],
        goal=goals["goal_type"],
    )
    personal_records_data = update_personal_records_from_logs(training_df)
    lean_bulk_decision = generate_lean_bulk_calorie_recommendation(
        body_metrics_df=body_metrics_df,
        nutrition_df=nutrition_for_optimization,
        training_df=training_df,
        recovery_df=recovery_df,
        user_goals=goals,
    )
    adaptive_recommendation = build_adaptive_nutrition_recommendation(
        user_goals=goals,
        body_metrics_df=body_metrics_df,
        nutrition_df=daily_nutrition_summary,
        training_df=training_df,
        recovery_df=recovery_df,
        current_targets=active_targets or targets,
    )
    personal_learning = generate_personal_response_learning(
        body_metrics_df=body_metrics_df,
        nutrition_df=daily_nutrition_summary,
        training_df=training_df,
        recovery_df=recovery_df,
        sleep_df=sleep_df,
        current_targets=active_targets or targets,
    )
    food_tile = _food_dashboard_tile(nutrition_totals, targets)
    weight_tile = _weight_dashboard_tile(body_metrics_df, bodyweight_trend, today)
    recovery_tile = _recovery_dashboard_tile(recovery_df, latest_recovery, today)
    recovery_tile["extra_run_readiness"] = generate_extra_run_readiness(
        recovery_data=recovery_tile if recovery_tile.get("connected") else recovery_df,
        training_df=training_df,
        strava_df=training_df[training_df["source"].astype(str).str.lower() == "strava"] if not training_df.empty and "source" in training_df.columns else None,
        nutrition_summary=daily_nutrition_summary,
        user_goals=goals,
        today_date=today,
    )
    lift_tile = _lift_performance_tile(training_df, today)
    workout_quality = calculate_workout_quality(training_df, today)
    nutrition_adherence = calculate_calorie_adherence(daily_nutrition_summary)
    todays_action = generate_todays_action(
        workout_quality=workout_quality,
        recovery_tile=recovery_tile,
        sleep_df=sleep_df,
        weight_feedback=weight_feedback,
        nutrition_adherence=nutrition_adherence,
        training_workload=training_workload,
        adaptive_recommendation=adaptive_recommendation,
    )
    weekly_report = generate_weekly_performance_report(
        body_metrics_df=body_metrics_df,
        nutrition_df=daily_nutrition_summary,
        training_df=training_df,
        recovery_df=recovery_df,
        sleep_df=sleep_df,
        today=today,
    )
    prs_tile = {
        "bench_press": personal_records_data.get("bench_press"),
        "mile_time": personal_records_data.get("mile_time"),
    }

    return {
        "date": today,
        "food": food_tile,
        "weight": weight_tile,
        "lift_performance": lift_tile,
        "workout_quality": workout_quality,
        "todays_action": todays_action,
        "weekly_report": weekly_report,
        "recovery": recovery_tile,
        "prs": prs_tile,
        "goals": goals,
        "targets": targets,
        "training_workload": training_workload,
        "nutrition_today": nutrition_totals,
        "latest_bodyweight": latest_bodyweight,
        "bodyweight_trend": bodyweight_trend,
        "weight_feedback": weight_feedback,
        "latest_recovery": latest_recovery,
        "recovery_trend": recovery_trend,
        "latest_workout": latest_workout,
        "strength_trend_summary": strength_trend_summary,
        "muscle_balance_warning": muscle_balance_warning,
        "ai_insight_preview": "Run AI training analysis from the Training page." if len(training_df) else None,
        "training_volume": dataframe_records(volume_df),
        "personal_records": personal_records_data,
        "lean_bulk_decision": lean_bulk_decision,
        "adaptive_recommendation": adaptive_recommendation,
        "personal_learning": personal_learning,
        "recommendation": performance_plan,
        "counts": {
            "nutrition": len(nutrition_df),
            "body_metrics": len(body_metrics_df),
            "recovery": len(recovery_df),
            "training": len(training_df),
        },
    }


def _left(actual: float, target: float | None) -> dict:
    if not target:
        return {"left": None, "over": None, "percent": 0}
    return {
        "left": max(float(target) - float(actual), 0),
        "over": max(float(actual) - float(target), 0),
        "percent": min(max(float(actual) / float(target) * 100, 0), 100),
    }


def _food_dashboard_tile(nutrition_totals: dict, targets: dict) -> dict:
    calories = float(nutrition_totals.get("calories", 0) or 0)
    protein = float(nutrition_totals.get("protein", 0) or 0)
    carbs = float(nutrition_totals.get("carbs", 0) or 0)
    fat = float(nutrition_totals.get("fat", 0) or 0)
    target_calories = targets.get("target_calories")
    target_protein = targets.get("protein_grams")
    target_carbs = targets.get("carb_grams")
    target_fat = targets.get("fat_grams")
    return {
        "calories": {"eaten": calories, "target": target_calories, **_left(calories, target_calories)},
        "protein": {"eaten": protein, "target": target_protein, **_left(protein, target_protein)},
        "carbs": {"eaten": carbs, "target": target_carbs, **_left(carbs, target_carbs)},
        "fat": {"eaten": fat, "target": target_fat, **_left(fat, target_fat)},
        "has_targets": bool(target_calories and target_protein and target_carbs and target_fat),
        "has_food_logged": calories > 0 or protein > 0 or carbs > 0 or fat > 0,
    }


def _weight_dashboard_tile(body_metrics_df: pd.DataFrame, bodyweight_trend: list[dict], today: str) -> dict:
    if body_metrics_df.empty:
        return {
            "today_weight": None,
            "latest_weight": None,
            "seven_day_average": None,
            "trend_label": "insufficient data",
            "history": [],
            "message": "Enter today's weight",
        }
    df = body_metrics_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["bodyweight"] = pd.to_numeric(df["bodyweight"], errors="coerce")
    df = df.dropna(subset=["date", "bodyweight"]).sort_values("date")
    if df.empty:
        return {
            "today_weight": None,
            "latest_weight": None,
            "seven_day_average": None,
            "trend_label": "insufficient data",
            "history": [],
            "message": "Enter today's weight",
        }
    today_rows = df[df["date"].dt.date.astype(str) == today]
    recent = df.tail(7)
    seven_day_avg = round(float(recent["bodyweight"].mean()), 1) if len(recent) >= 2 else None
    trend_label = "insufficient data"
    if len(recent) >= 3:
        delta = float(recent["bodyweight"].iloc[-1] - recent["bodyweight"].iloc[0])
        if delta > 0.3:
            trend_label = "gaining"
        elif delta < -0.3:
            trend_label = "losing"
        else:
            trend_label = "stable"
    return {
        "today_weight": float(today_rows.iloc[-1]["bodyweight"]) if not today_rows.empty else None,
        "latest_weight": float(df.iloc[-1]["bodyweight"]),
        "seven_day_average": seven_day_avg,
        "trend_label": trend_label,
        "history": bodyweight_trend[-14:],
        "message": "Today's weight logged" if not today_rows.empty else "Enter today's weight",
    }


def _daily_training_rows(training_df: pd.DataFrame) -> pd.DataFrame:
    if training_df.empty:
        return pd.DataFrame()
    df = training_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    for column in ["sets", "reps", "weight", "duration_minutes"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    grouped = (
        df.groupby(df["date"].dt.date)
        .agg(
            date=("date", "max"),
            workout_type=("workout_type", lambda values: ", ".join(sorted(set(str(value) for value in values if str(value))))),
            muscle_group=("muscle_group", lambda values: ", ".join(sorted(set(str(value) for value in values if str(value))))),
            total_volume=("volume", "sum"),
            total_sets=("sets", "sum"),
            duration_minutes=("duration_minutes", "max"),
        )
        .reset_index(drop=True)
        .sort_values("date")
    )
    grouped["weekday"] = grouped["date"].dt.day_name()
    return grouped


def _lift_performance_tile(training_df: pd.DataFrame, today: str) -> dict:
    daily = _daily_training_rows(training_df)
    if daily.empty:
        return {
            "status": "No lift logged today",
            "summary": "Log a workout or import from Hevy.",
            "comparison": None,
            "today_volume": None,
            "percent_vs_average": None,
        }
    today_dt = pd.to_datetime(today)
    today_rows = daily[daily["date"].dt.date.astype(str) == today]
    if today_rows.empty:
        return {
            "status": "No lift logged today",
            "summary": "Training tile updates after today's workout is logged.",
            "comparison": None,
            "today_volume": None,
            "percent_vs_average": None,
        }
    today_row = today_rows.iloc[-1]
    previous = daily[daily["date"] < today_dt]
    same_weekday = previous[previous["weekday"] == today_row["weekday"]]
    similar = same_weekday
    if len(similar) < 2 and today_row["workout_type"]:
        similar = previous[previous["workout_type"] == today_row["workout_type"]]
    if len(similar) < 2 and today_row["muscle_group"]:
        similar = previous[previous["muscle_group"] == today_row["muscle_group"]]
    if similar.empty:
        return {
            "status": "Need more similar workouts",
            "summary": f"Today: {today_row['workout_type'] or 'Workout'} · {int(today_row['total_sets'])} sets",
            "comparison": None,
            "today_volume": round(float(today_row["total_volume"]), 0),
            "percent_vs_average": None,
        }
    baseline = float(similar.tail(4)["total_volume"].mean())
    today_volume = float(today_row["total_volume"])
    percent = ((today_volume - baseline) / baseline * 100) if baseline > 0 else 0
    direction = "Stronger" if percent > 3 else "Lighter" if percent < -3 else "Similar"
    return {
        "status": f"{direction} than average {today_row['weekday']} session",
        "summary": f"Volume {percent:+.0f}% vs last {min(4, len(similar))} similar sessions",
        "comparison": f"{today_row['workout_type']} · {today_row['muscle_group']}",
        "today_volume": round(today_volume, 0),
        "percent_vs_average": round(percent, 1),
    }


def _series(df: pd.DataFrame, column: str, output_key: str = "value") -> list[dict]:
    if column not in df.columns:
        return []
    values = pd.to_numeric(df[column], errors="coerce")
    series_df = df.loc[values.notna(), ["date"]].copy()
    series_df[output_key] = values[values.notna()].astype(float)
    series_df["date"] = series_df["date"].dt.date.astype(str)
    return dataframe_records(series_df.tail(30))


def _recovery_classification(score: float | None) -> str:
    if score is None:
        return "Sync pending"
    if score >= 80:
        return "Optimal"
    if score >= 60:
        return "Moderate"
    if score >= 40:
        return "Fatigued"
    return "High Risk"


def _recovery_dashboard_tile(recovery_df: pd.DataFrame, latest_recovery: dict | None, today: str) -> dict:
    """Return a wearable-first recovery dashboard shape.

    Manual recovery check-ins remain available elsewhere, but the dashboard tile
    is reserved for future Fitbit/Google Health style wearable ingestion.
    """
    empty_tile = {
        "connected": False,
        "source": "fitbit",
        "latest_score": None,
        "trend": [],
        "sleep": [],
        "hrv": [],
        "resting_hr": [],
        "status": "not_connected",
        "classification": "Not connected",
        "message": "Connect Fitbit/Google Health to enable recovery tracking.",
    }
    if recovery_df.empty:
        return empty_tile

    df = recovery_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return empty_tile

    source_col = "source" if "source" in df.columns else "data_source" if "data_source" in df.columns else None
    if not source_col:
        return empty_tile

    wearable_sources = {"fitbit", "google_health", "google_fit", "wearable", "withings"}
    source_values = df[source_col].fillna("").astype(str).str.lower().str.strip()
    wearable_df = df[source_values.isin(wearable_sources)].copy()
    if wearable_df.empty:
        return empty_tile

    score_column = next((column for column in ["recovery_score", "readiness_score", "score"] if column in wearable_df.columns), None)
    latest_score = None
    trend = []
    if score_column:
        score_values = pd.to_numeric(wearable_df[score_column], errors="coerce")
        if score_values.notna().any():
            latest_score = float(score_values.dropna().iloc[-1])
            trend = _series(wearable_df, score_column, "recovery_score")
    elif latest_recovery:
        latest_score = latest_recovery.get("recovery_score")

    latest_source = str(wearable_df[source_col].dropna().astype(str).iloc[-1] or "fitbit").lower()
    return {
        "connected": True,
        "source": latest_source,
        "latest_score": latest_score,
        "trend": trend,
        "sleep": _series(wearable_df, "sleep_hours", "sleep_hours"),
        "hrv": _series(wearable_df, "hrv", "hrv"),
        "resting_hr": _series(wearable_df, "resting_hr", "resting_hr"),
        "status": "connected" if latest_score is not None or len(wearable_df) else "sync_pending",
        "classification": _recovery_classification(float(latest_score) if latest_score is not None else None),
        "message": "Wearable recovery data synced.",
    }


app.include_router(nutrition.router)
app.include_router(training.router)
app.include_router(personal_records.router)
app.include_router(recovery.router)
app.include_router(body_metrics.router)
app.include_router(integrations.router)
app.include_router(goals.router)
