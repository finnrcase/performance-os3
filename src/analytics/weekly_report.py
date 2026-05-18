"""Compact weekly performance report for the dashboard."""

from __future__ import annotations

import pandas as pd

from src.analytics.strength_trends import calculate_estimated_1rm
from src.training_schedule import is_run_row, is_strength_row


def _empty_report() -> dict:
    return {
        "status": "learning",
        "period_label": "Last 7 days",
        "summary": "Keep logging bodyweight, food, workouts, runs, and recovery to build a useful weekly report.",
        "rows": [
            {"label": "Weight", "value": "Need data", "detail": "Daily weigh-ins unlock weekly change."},
            {"label": "Nutrition", "value": "Need data", "detail": "Food logs unlock calorie and macro averages."},
            {"label": "Training", "value": "Need data", "detail": "Hevy and Strava sessions unlock performance trends."},
        ],
        "best_trend": "Need more comparable lifting history.",
        "watch": "No clear weak signal yet.",
        "recommendation": "Keep logging this week so the next report can be more specific.",
    }


def _clean_dates(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out.get("date"), errors="coerce")
    return out.dropna(subset=["date"]).sort_values("date")


def _num(series: pd.Series | float | int | None) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _range(df: pd.DataFrame, end: pd.Timestamp, days: int = 7) -> pd.DataFrame:
    if df.empty:
        return df
    start = end - pd.Timedelta(days=days - 1)
    return df[(df["date"].dt.normalize() >= start.normalize()) & (df["date"].dt.normalize() <= end.normalize())].copy()


def _fmt_signed(value: float | None, unit: str = "") -> str:
    if value is None or pd.isna(value):
        return "Need data"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.1f}{unit}"


def _note_number(note: str, key: str) -> float:
    marker = f"{key}="
    if marker not in str(note):
        return 0.0
    raw = str(note).split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _source_mask(df: pd.DataFrame, source_name: str) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)
    if source_name == "hevy":
        return df.apply(is_strength_row, axis=1)
    if source_name == "strava":
        return df.apply(is_run_row, axis=1)
    return pd.Series(False, index=df.index)


def _weight_summary(body_metrics_df: pd.DataFrame, end: pd.Timestamp) -> tuple[dict, float | None]:
    df = _clean_dates(body_metrics_df)
    if df.empty or "bodyweight" not in df.columns:
        return {"label": "Weight", "value": "Need data", "detail": "No weigh-ins this week."}, None
    df["bodyweight"] = _num(df["bodyweight"])
    current = _range(df, end, 7).dropna(subset=["bodyweight"])
    previous = _range(df, end - pd.Timedelta(days=7), 7).dropna(subset=["bodyweight"])
    if current.empty:
        return {"label": "Weight", "value": "Need data", "detail": "No weigh-ins in the last 7 days."}, None
    if not previous.empty:
        change = float(current["bodyweight"].mean() - previous["bodyweight"].mean())
        detail = f"{current['bodyweight'].mean():.1f} lb 7-day average"
    elif len(current) >= 2:
        change = float(current.iloc[-1]["bodyweight"] - current.iloc[0]["bodyweight"])
        detail = "Change across available weigh-ins"
    else:
        change = None
        detail = f"Latest: {current.iloc[-1]['bodyweight']:.1f} lb"
    return {"label": "Weight", "value": _fmt_signed(change, " lb"), "detail": detail}, change


def _nutrition_summary(nutrition_df: pd.DataFrame, end: pd.Timestamp) -> tuple[list[dict], float | None, float | None, float | None, float | None]:
    df = _clean_dates(nutrition_df)
    if df.empty:
        return [{"label": "Nutrition", "value": "Need data", "detail": "No food logs this week."}], None, None, None, None
    week = _range(df, end, 7)
    if week.empty:
        return [{"label": "Nutrition", "value": "Need data", "detail": "No food logs in the last 7 days."}], None, None, None, None
    column_map = {
        "calories": "total_calories" if "total_calories" in week.columns else "calories",
        "protein": "total_protein" if "total_protein" in week.columns else "protein",
        "carbs": "total_carbs" if "total_carbs" in week.columns else "carbs",
        "fat": "total_fat" if "total_fat" in week.columns else "fat",
    }
    for target, source in column_map.items():
        week[target] = _num(week.get(source, 0)).fillna(0)
    calories = float(week["calories"].mean())
    protein = float(week["protein"].mean())
    carbs = float(week["carbs"].mean())
    fat = float(week["fat"].mean())
    rows = [
        {"label": "Calories", "value": f"{calories:.0f}/day", "detail": "7-day average"},
        {"label": "Macros", "value": f"P {protein:.0f}g / C {carbs:.0f}g / F {fat:.0f}g", "detail": "Daily averages"},
    ]
    return rows, calories, protein, carbs, fat


def _training_summary(training_df: pd.DataFrame, end: pd.Timestamp) -> tuple[list[dict], str, str, dict]:
    df = _clean_dates(training_df)
    if df.empty:
        return [{"label": "Training", "value": "0 workouts / 0 runs", "detail": "No Hevy or Strava sessions this week."}], "Need more training history.", "No workout signal this week.", {"workouts": 0, "runs": 0}

    for column in ["sets", "reps", "weight", "duration_minutes"]:
        df[column] = _num(df[column] if column in df.columns else pd.Series(0, index=df.index)).fillna(0)
    for column in ["workout_id", "exercise", "notes", "workout_type", "source"]:
        df[column] = df[column].fillna("").astype(str) if column in df.columns else pd.Series("", index=df.index)
    week = _range(df, end, 7)
    previous = _range(df, end - pd.Timedelta(days=7), 7)
    hevy = week[_source_mask(week, "hevy")]
    runs = week[_source_mask(week, "strava")]
    workout_count = int(hevy[["date", "workout_id"]].drop_duplicates().shape[0]) if not hevy.empty else 0
    run_count = int(runs[["date", "workout_id"]].drop_duplicates().shape[0]) if not runs.empty else 0
    mileage = 0.0
    if not runs.empty:
        mileage = float(runs["notes"].apply(lambda note: _note_number(note, "distance_miles")).sum())

    best_trend = "Need more comparable lifting history."
    watch = "No clear weak performance signal this week."
    strength_week = hevy[(hevy["reps"] > 0) & (hevy["weight"] > 0)].copy()
    strength_prev = previous[_source_mask(previous, "hevy") & (previous["reps"] > 0) & (previous["weight"] > 0)].copy() if not previous.empty else pd.DataFrame()
    if not strength_week.empty and not strength_prev.empty:
        strength_week["estimated_1rm"] = strength_week.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
        strength_prev["estimated_1rm"] = strength_prev.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
        changes = []
        for exercise, current_rows in strength_week.groupby("exercise"):
            prior_rows = strength_prev[strength_prev["exercise"].str.lower() == str(exercise).lower()]
            if prior_rows.empty:
                continue
            current_best = float(current_rows["estimated_1rm"].max())
            prior_best = float(prior_rows["estimated_1rm"].max())
            if prior_best <= 0:
                continue
            changes.append({"exercise": str(exercise), "change": ((current_best - prior_best) / prior_best) * 100})
        if changes:
            best = max(changes, key=lambda item: item["change"])
            weakest = min(changes, key=lambda item: item["change"])
            best_trend = f"{best['exercise']} {best['change']:+.1f}% estimated 1RM"
            if weakest["change"] <= -2:
                watch = f"{weakest['exercise']} {weakest['change']:.1f}% estimated 1RM"

    rows = [
        {"label": "Training", "value": f"{workout_count} workouts / {run_count} runs", "detail": f"{mileage:.1f} running miles"},
        {"label": "Best trend", "value": best_trend, "detail": "Compared with the previous 7 days"},
    ]
    return rows, best_trend, watch, {"workouts": workout_count, "runs": run_count, "miles": mileage}


def _recovery_summary(recovery_df: pd.DataFrame, sleep_df: pd.DataFrame, end: pd.Timestamp) -> tuple[dict, str]:
    sleep = _clean_dates(sleep_df)
    if not sleep.empty and "durationMinutes" in sleep.columns:
        week = _range(sleep, end, 7)
        if not week.empty:
            hours = _num(week["durationMinutes"]).dropna() / 60
            efficiency = _num(week.get("efficiencyPercent")).dropna()
            if not hours.empty:
                detail = f"{hours.mean():.1f}h sleep avg"
                if not efficiency.empty:
                    detail = f"{detail} / {efficiency.mean():.0f}% efficiency"
                watch = "Sleep under 7h average" if hours.mean() < 7 else "Sleep is supporting recovery"
                return {"label": "Sleep/recovery", "value": f"{hours.mean():.1f}h avg", "detail": detail}, watch

    recovery = _clean_dates(recovery_df)
    if recovery.empty:
        return {"label": "Sleep/recovery", "value": "Need data", "detail": "No sleep or recovery entries this week."}, "Recovery data is missing"
    week = _range(recovery, end, 7)
    if week.empty:
        return {"label": "Sleep/recovery", "value": "Need data", "detail": "No recovery entries in the last 7 days."}, "Recovery data is missing"
    sleep_hours = _num(week.get("sleep_hours")).dropna()
    fatigue = _num(week.get("fatigue")).dropna()
    if not sleep_hours.empty:
        detail = f"{sleep_hours.mean():.1f}h sleep avg"
        if not fatigue.empty:
            detail = f"{detail} / fatigue {fatigue.mean():.1f}/10"
        watch = "Sleep under 7h average" if sleep_hours.mean() < 7 else "Recovery inputs look steady"
        return {"label": "Sleep/recovery", "value": f"{sleep_hours.mean():.1f}h avg", "detail": detail}, watch
    return {"label": "Sleep/recovery", "value": "Need data", "detail": "Recovery check-ins need sleep duration."}, "Recovery data is incomplete"


def _recommendation(weight_change: float | None, calories: float | None, carbs: float | None, watch: str, counts: dict) -> str:
    if "Sleep under 7h" in watch:
        return "Prioritize sleep consistency and keep carbs available around harder sessions."
    if weight_change is not None and weight_change > 0.8:
        return "Keep training steady, but avoid pushing calories higher until weight gain slows."
    if weight_change is not None and weight_change < 0.1 and calories is not None:
        return "Consider a small carb-focused calorie bump if training performance also feels flat."
    if counts.get("runs", 0) >= 2 and carbs is not None:
        return "Maintain calories and keep carbs high around lifting and run days."
    if counts.get("workouts", 0) >= 3:
        return "Maintain calories and keep protein/carbs consistent for next week's sessions."
    return "Keep targets stable and build another week of clean logs."


def generate_weekly_performance_report(
    body_metrics_df: pd.DataFrame,
    nutrition_df: pd.DataFrame,
    training_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    sleep_df: pd.DataFrame | None = None,
    today: str | None = None,
) -> dict:
    """Build a concise last-7-days report for the dashboard."""
    end = pd.to_datetime(today).normalize() if today else pd.Timestamp.today().normalize()
    rows: list[dict] = []

    weight_row, weight_change = _weight_summary(body_metrics_df, end)
    nutrition_rows, calories, protein, carbs, fat = _nutrition_summary(nutrition_df, end)
    training_rows, best_trend, performance_watch, counts = _training_summary(training_df, end)
    recovery_row, recovery_watch = _recovery_summary(recovery_df, sleep_df if sleep_df is not None else pd.DataFrame(), end)

    rows.append(weight_row)
    rows.extend(nutrition_rows)
    rows.extend(training_rows)
    rows.append(recovery_row)

    watch = recovery_watch if recovery_watch not in {"Sleep is supporting recovery", "Recovery inputs look steady"} else performance_watch
    recommendation = _recommendation(weight_change, calories, carbs, watch, counts)
    available_signals = sum(
        [
            weight_change is not None,
            calories is not None,
            counts.get("workouts", 0) > 0 or counts.get("runs", 0) > 0,
            recovery_row["value"] != "Need data",
        ]
    )
    status = "ready" if available_signals >= 3 else "learning"
    calorie_text = f"{calories:.0f}/day" if calories is not None else "nutrition data pending"
    macro_text = f"Protein {protein:.0f}g, carbs {carbs:.0f}g, fat {fat:.0f}g" if protein is not None and carbs is not None and fat is not None else "macros pending"
    weight_text = _fmt_signed(weight_change, " lb") if weight_change is not None else "pending"
    return {
        "status": status,
        "period_label": "Last 7 days",
        "summary": f"Weight {weight_text}; calories {calorie_text}; {macro_text}.",
        "rows": rows,
        "best_trend": best_trend,
        "watch": watch,
        "recommendation": recommendation,
    } if rows else _empty_report()
