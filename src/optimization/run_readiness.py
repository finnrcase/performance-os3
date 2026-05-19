"""Conservative extra-run readiness guidance.

This module is deterministic fitness guidance, not medical advice. It decides
whether an easy extra run is sensible from recovery, recent training, nutrition,
and a simple day-specific lifting split.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.training_schedule import LOWER_BODY_TERMS, is_run_row, load_training_schedule_profile, planned_training_for_date


def _empty(reason: str) -> dict:
    return {
        "status": "insufficient_data",
        "message": "Connect wearable data for run readiness.",
        "recommended_run": "Connect wearable data",
        "reasoning": [reason],
    }


def _to_date(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()


def _numeric(value: Any) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return float(parsed)


def _latest_from_df(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])


def _baseline(df: pd.DataFrame, column: str, exclude_latest: bool = True) -> float | None:
    if df.empty or column not in df.columns:
        return None
    values = pd.to_numeric(df[column], errors="coerce").dropna()
    if exclude_latest and len(values) > 1:
        values = values.iloc[:-1]
    if len(values) < 3:
        return None
    return float(values.tail(14).mean())


def _recovery_signal(recovery_data: Any) -> dict:
    if isinstance(recovery_data, dict):
        latest_score = _numeric(recovery_data.get("latest_score") or recovery_data.get("score"))
        sleep = None
        hrv = None
        resting_hr = None
        sleep_series = recovery_data.get("sleep") or []
        hrv_series = recovery_data.get("hrv") or []
        hr_series = recovery_data.get("resting_hr") or []
        if sleep_series:
            sleep = _numeric(sleep_series[-1].get("sleep_hours"))
        if hrv_series:
            hrv = _numeric(hrv_series[-1].get("hrv"))
        if hr_series:
            resting_hr = _numeric(hr_series[-1].get("resting_hr"))
        return {
            "has_data": bool(recovery_data.get("connected") or latest_score is not None or sleep is not None or hrv is not None or resting_hr is not None),
            "score": latest_score,
            "sleep": sleep,
            "hrv": hrv,
            "hrv_baseline": None,
            "resting_hr": resting_hr,
            "resting_hr_baseline": None,
            "fatigue": None,
            "soreness": None,
        }

    if not isinstance(recovery_data, pd.DataFrame) or recovery_data.empty:
        return {
            "has_data": False,
            "score": None,
            "sleep": None,
            "hrv": None,
            "hrv_baseline": None,
            "resting_hr": None,
            "resting_hr_baseline": None,
            "fatigue": None,
            "soreness": None,
        }

    df = recovery_data.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    if df.empty:
        return {
            "has_data": False,
            "score": None,
            "sleep": None,
            "hrv": None,
            "hrv_baseline": None,
            "resting_hr": None,
            "resting_hr_baseline": None,
            "fatigue": None,
            "soreness": None,
        }
    latest = df.iloc[-1]
    return {
        "has_data": True,
        "score": _numeric(latest.get("recovery_score")),
        "sleep": _numeric(latest.get("sleep_hours")),
        "hrv": _numeric(latest.get("hrv")),
        "hrv_baseline": _baseline(df, "hrv"),
        "resting_hr": _numeric(latest.get("resting_hr")),
        "resting_hr_baseline": _baseline(df, "resting_hr"),
        "fatigue": _numeric(latest.get("fatigue")),
        "soreness": _numeric(latest.get("soreness")),
    }


def _training_context(training_df: pd.DataFrame, strava_df: pd.DataFrame | None, today_date: str | date) -> dict:
    today = _to_date(today_date) or pd.Timestamp.today().normalize()
    if training_df is None or training_df.empty:
        training = pd.DataFrame()
    else:
        training = training_df.copy()
        training["date"] = pd.to_datetime(training.get("date"), errors="coerce").dt.normalize()
        training = training.dropna(subset=["date"])

    if strava_df is not None and not strava_df.empty:
        strava = strava_df.copy()
        strava["date"] = pd.to_datetime(strava.get("date"), errors="coerce").dt.normalize()
        strava = strava.dropna(subset=["date"])
        if "workout_type" not in strava.columns:
            strava["workout_type"] = "Run"
        training = pd.concat([training, strava], ignore_index=True)

    profile = load_training_schedule_profile()
    planned = planned_training_for_date(today, profile=profile)
    planned_day = planned["display_label"]
    yesterday = today - pd.Timedelta(days=1)
    week_start = today - pd.Timedelta(days=today.weekday())

    if training.empty:
        return {
            "planned_day": planned_day,
            "planned_is_run_day": bool(planned["is_run_day"]),
            "planned_is_leg_day": bool(planned["is_leg_day"]),
            "today_has_run": False,
            "today_has_leg": bool(planned["is_leg_day"]),
            "yesterday_had_leg": False,
            "weekly_cardio_sessions": 0,
            "weekly_cardio_minutes": 0.0,
            "hard_leg_context": bool(planned["is_leg_day"]),
        }

    for column in ["workout_type", "muscle_group", "exercise", "source", "notes"]:
        if column not in training.columns:
            training[column] = ""
    training["duration_minutes"] = pd.to_numeric(training.get("duration_minutes", 0), errors="coerce").fillna(0)
    text = (
        training["workout_type"].fillna("").astype(str)
        + " "
        + training["muscle_group"].fillna("").astype(str)
        + " "
        + training["exercise"].fillna("").astype(str)
        + " "
        + training["notes"].fillna("").astype(str)
    ).str.lower()
    cardio_mask = training.apply(lambda row: is_run_row(row, profile=profile), axis=1)
    leg_mask = text.str.contains("|".join(LOWER_BODY_TERMS), regex=True, na=False)

    today_rows = training[training["date"] == today]
    yesterday_rows = training[training["date"] == yesterday]
    week_rows = training[(training["date"] >= week_start) & (training["date"] <= today)]
    week_cardio = week_rows[cardio_mask.reindex(week_rows.index, fill_value=False)]

    return {
        "planned_day": planned_day,
        "planned_is_run_day": bool(planned["is_run_day"]),
        "planned_is_leg_day": bool(planned["is_leg_day"]),
        "today_has_run": bool(cardio_mask.reindex(today_rows.index, fill_value=False).any()),
        "today_has_leg": bool(leg_mask.reindex(today_rows.index, fill_value=False).any()) or bool(planned["is_leg_day"]),
        "yesterday_had_leg": bool(leg_mask.reindex(yesterday_rows.index, fill_value=False).any()),
        "weekly_cardio_sessions": int(len(week_cardio.groupby("date"))) if not week_cardio.empty else 0,
        "weekly_cardio_minutes": float(week_cardio["duration_minutes"].sum()) if not week_cardio.empty else 0.0,
        "hard_leg_context": bool(leg_mask.reindex(today_rows.index, fill_value=False).any() or leg_mask.reindex(yesterday_rows.index, fill_value=False).any() or planned["is_leg_day"]),
    }


def _nutrition_context(nutrition_summary: Any, today_date: str | date) -> dict:
    if nutrition_summary is None or (isinstance(nutrition_summary, pd.DataFrame) and nutrition_summary.empty):
        return {"calorie_delta": None, "carb_delta": None, "severely_under": False}
    if isinstance(nutrition_summary, dict):
        calorie_delta = _numeric(nutrition_summary.get("calories_delta"))
        carb_delta = _numeric(nutrition_summary.get("carbs_delta"))
        return {"calorie_delta": calorie_delta, "carb_delta": carb_delta, "severely_under": calorie_delta is not None and calorie_delta <= -500}

    today = (_to_date(today_date) or pd.Timestamp.today().normalize()).date().isoformat()
    df = nutrition_summary.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce").dt.date.astype(str)
    rows = df[df["date"] == today]
    if rows.empty:
        rows = df.tail(1)
    row = rows.iloc[-1]
    calorie_delta = _numeric(row.get("calories_delta"))
    carb_delta = _numeric(row.get("carbs_delta"))
    return {"calorie_delta": calorie_delta, "carb_delta": carb_delta, "severely_under": calorie_delta is not None and calorie_delta <= -500}


def generate_extra_run_readiness(
    recovery_data,
    training_df,
    strava_df,
    nutrition_summary,
    user_goals,
    today_date,
) -> dict:
    """Return conservative guidance for adding an easy extra run today."""
    recovery = _recovery_signal(recovery_data)
    training = _training_context(training_df, strava_df, today_date)
    nutrition = _nutrition_context(nutrition_summary, today_date)
    goal_type = str((user_goals or {}).get("goal_type", "")).lower()
    aggressiveness = str((user_goals or {}).get("aggressiveness", "")).lower()

    if not recovery["has_data"] and (training_df is None or training_df.empty) and nutrition["calorie_delta"] is None:
        return _empty("No wearable, recovery, training, or nutrition data is available yet.")

    red_flags: list[str] = []
    yellow_flags: list[str] = []
    positives: list[str] = []

    score = recovery["score"]
    sleep = recovery["sleep"]
    fatigue = recovery["fatigue"]
    soreness = recovery["soreness"]
    resting_hr = recovery["resting_hr"]
    resting_hr_baseline = recovery["resting_hr_baseline"]
    hrv = recovery["hrv"]
    hrv_baseline = recovery["hrv_baseline"]

    if score is not None:
        if score < 60:
            red_flags.append("Recovery score is low.")
        elif score < 80:
            yellow_flags.append("Recovery score is moderate.")
        else:
            positives.append("Recovery score is high.")

    if sleep is not None:
        if sleep < 6:
            red_flags.append("Sleep was poor.")
        elif sleep < 7:
            yellow_flags.append("Sleep was a bit low.")
        else:
            positives.append("Sleep looks adequate.")

    if fatigue is not None and fatigue >= 8:
        red_flags.append("Fatigue is elevated.")
    elif fatigue is not None and fatigue >= 6:
        yellow_flags.append("Fatigue is moderate.")

    if soreness is not None and soreness >= 8:
        red_flags.append("Soreness is elevated.")
    elif soreness is not None and soreness >= 6:
        yellow_flags.append("Soreness is moderate.")

    if resting_hr is not None and resting_hr_baseline is not None and resting_hr > resting_hr_baseline + 6:
        red_flags.append("Resting HR is elevated versus baseline.")
    elif resting_hr is not None and resting_hr_baseline is not None and resting_hr > resting_hr_baseline + 3:
        yellow_flags.append("Resting HR is slightly elevated.")

    if hrv is not None and hrv_baseline is not None and hrv < hrv_baseline * 0.85:
        red_flags.append("HRV is clearly below baseline.")
    elif hrv is not None and hrv_baseline is not None and hrv < hrv_baseline * 0.95:
        yellow_flags.append("HRV is slightly below baseline.")
    elif hrv is not None and hrv_baseline is not None:
        positives.append("HRV is near or above baseline.")

    if training["today_has_run"]:
        red_flags.append("A run or cardio workout is already logged today.")
    if training["planned_is_run_day"]:
        yellow_flags.append("Sunday is already the planned run day.")
    if training["today_has_leg"]:
        yellow_flags.append("Today is a leg-focused day.")
    if training["yesterday_had_leg"]:
        yellow_flags.append("Yesterday included leg training.")
    if training["weekly_cardio_sessions"] >= 4 or training["weekly_cardio_minutes"] >= 180:
        yellow_flags.append("Recent cardio volume is already high.")

    if nutrition["severely_under"]:
        red_flags.append("Calories are far under target.")
    elif nutrition["calorie_delta"] is not None and nutrition["calorie_delta"] <= -250:
        yellow_flags.append("Calories are under target.")
    if nutrition["carb_delta"] is not None and nutrition["carb_delta"] <= -75:
        yellow_flags.append("Carbs are running low.")

    if goal_type == "cut" and aggressiveness == "aggressive":
        red_flags.append("Aggressive cut increases fatigue risk.")

    excellent_recovery = (
        (score is not None and score >= 85)
        or (score is None and sleep is not None and sleep >= 7.5 and not red_flags)
    )
    if training["planned_is_leg_day"] and not excellent_recovery:
        red_flags.append("Leg day calls for a conservative run decision.")
    if training["planned_is_run_day"] and not excellent_recovery:
        red_flags.append("Avoid stacking extra running on Run Day without excellent recovery.")

    reasoning = [*red_flags, *yellow_flags, *positives]
    if red_flags:
        return {
            "status": "red",
            "message": "Skip extra running today. Recovery and training context are not favorable.",
            "recommended_run": "Skip extra run",
            "reasoning": reasoning[:5],
        }
    if yellow_flags:
        return {
            "status": "yellow",
            "message": "Optional, but keep it short and easy.",
            "recommended_run": "10-20 min easy Zone 2 or a walk",
            "reasoning": reasoning[:5],
        }
    return {
        "status": "green",
        "message": "Good to add an easy 20-30 min Zone 2 run.",
        "recommended_run": "20-30 min easy Zone 2",
        "reasoning": (reasoning or ["No major recovery, training, or nutrition flags found."])[:5],
    }
