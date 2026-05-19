"""Workout quality scoring for today's Hevy/Strava performance."""

from __future__ import annotations

import math

import pandas as pd

from src.analytics.strength_trends import calculate_estimated_1rm
from src.training_schedule import is_run_row, is_strength_row, load_training_schedule_profile


def _empty(status: str = "missing") -> dict:
    return {
        "status": status,
        "score": None,
        "score_label": "Missing workout",
        "confidence": "low",
        "color": "gray",
        "explanation": "No Hevy or Strava activity logged today.",
        "comparison": None,
        "source": "none",
    }


def _note_value(note: str, key: str) -> str:
    marker = f"{key}="
    if marker not in str(note):
        return ""
    return str(note).split(marker, 1)[1].split("|", 1)[0].strip()


def _note_number(note: str, key: str) -> float:
    raw = _note_value(note, key)
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _score_color(score: float | None) -> str:
    if score is None:
        return "gray"
    if score <= 3:
        return "red"
    if score <= 6:
        return "orange"
    if score <= 8:
        return "green"
    return "bright_green"


def _clean_training(training_df: pd.DataFrame) -> pd.DataFrame:
    if training_df.empty:
        return pd.DataFrame()
    df = training_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"])
    for column in ["sets", "reps", "weight", "duration_minutes", "rpe"]:
        values = df[column] if column in df.columns else pd.Series(0, index=df.index)
        df[column] = pd.to_numeric(values, errors="coerce").fillna(0)
    for column in ["workout_id", "workout_type", "exercise", "notes", "source", "muscle_group"]:
        df[column] = df[column].fillna("").astype(str) if column in df.columns else pd.Series("", index=df.index)
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    df["estimated_1rm"] = df.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
    df["workout_title"] = df["notes"].apply(lambda note: _note_value(note, "workout_title"))
    df["distance_miles"] = df["notes"].apply(lambda note: _note_number(note, "distance_miles"))
    df["pace_min_per_mile"] = df["notes"].apply(lambda note: _note_number(note, "pace_min_per_mile"))
    return df.sort_values("date")


def _is_run(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)
    profile = load_training_schedule_profile()
    return df.apply(lambda row: is_run_row(row, profile=profile), axis=1)


def _is_strength(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)
    profile = load_training_schedule_profile()
    return df.apply(lambda row: is_strength_row(row, profile=profile), axis=1)


def _pct(current: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return ((current - baseline) / baseline) * 100


def _quality_from_pct(pct: float | None, inverted: bool = False) -> float:
    if pct is None:
        return 5.0
    value = -pct if inverted else pct
    return max(0.0, min(10.0, 6.0 + (value / 4.0)))


def _run_quality(df: pd.DataFrame, today_rows: pd.DataFrame, today_date: pd.Timestamp) -> dict:
    today = today_rows[_is_run(today_rows)].copy()
    if today.empty:
        return _empty()
    today_run = today.sort_values("duration_minutes").iloc[-1]
    previous = df[_is_run(df) & (df["date"] < today_date)].copy()
    distance = float(today_run["distance_miles"])
    pace = float(today_run["pace_min_per_mile"])
    if previous.empty:
        score = 6.0
        return {
            **_empty("low_history"),
            "score": score,
            "score_label": f"{score:.1f}/10",
            "color": _score_color(score),
            "explanation": "Run logged, but not enough comparable history yet.",
            "source": str(today_run.get("source") or "run"),
        }
    if distance > 0:
        similar = previous[(previous["distance_miles"] >= distance * 0.8) & (previous["distance_miles"] <= distance * 1.2)]
    else:
        similar = previous[previous["exercise"].str.lower() == str(today_run["exercise"]).lower()]
    if len(similar) < 2:
        similar = previous.tail(5)
    baseline_pace = float(similar[similar["pace_min_per_mile"] > 0]["pace_min_per_mile"].tail(5).mean() or 0)
    baseline_distance = float(similar[similar["distance_miles"] > 0]["distance_miles"].tail(5).mean() or 0)
    pace_change = _pct(pace, baseline_pace) if pace > 0 else None
    distance_change = _pct(distance, baseline_distance) if distance > 0 else None
    pace_score = _quality_from_pct(pace_change, inverted=True)
    distance_score = _quality_from_pct(distance_change)
    score = round((pace_score * 0.7) + (distance_score * 0.3), 1)
    if pace_change is None:
        explanation = "Run logged, but pace history is incomplete."
    elif pace_change <= -2:
        explanation = f"Run pace improved {abs(pace_change):.1f}% versus recent similar runs."
    elif pace_change >= 2:
        explanation = f"Run pace was {pace_change:.1f}% slower versus recent similar runs."
    else:
        explanation = "Run pace was similar to recent comparable runs."
    return {
        "status": "scored",
        "score": score,
        "score_label": f"{score:.1f}/10",
        "confidence": "medium" if len(similar) >= 3 else "low",
        "color": _score_color(score),
        "explanation": explanation,
        "comparison": f"Compared with {min(5, len(similar))} similar runs.",
        "source": str(today_run.get("source") or "run"),
    }


def _choose_today_strength(today_strength: pd.DataFrame) -> pd.DataFrame:
    if "workout_id" not in today_strength.columns or today_strength["workout_id"].str.strip().eq("").all():
        return today_strength
    latest_id = today_strength.sort_values("date").iloc[-1]["workout_id"]
    return today_strength[today_strength["workout_id"] == latest_id].copy()


def _strength_quality(df: pd.DataFrame, today_rows: pd.DataFrame, today_date: pd.Timestamp) -> dict:
    strength = today_rows[_is_strength(today_rows)].copy()
    strength = strength[(strength["reps"] > 0) & (strength["weight"] > 0)]
    if strength.empty:
        return _empty()
    today = _choose_today_strength(strength)
    previous = df[_is_strength(df) & (df["date"] < today_date) & (df["reps"] > 0) & (df["weight"] > 0)].copy()
    if previous.empty:
        score = 6.0
        return {
            **_empty("low_history"),
            "score": score,
            "score_label": f"{score:.1f}/10",
            "color": _score_color(score),
            "explanation": "Workout logged, but not enough comparable history yet.",
            "source": "hevy",
        }

    title = str(today["workout_title"].replace("", pd.NA).dropna().iloc[0]) if not today["workout_title"].replace("", pd.NA).dropna().empty else ""
    if title:
        similar = previous[previous["workout_title"].str.lower() == title.lower()]
    else:
        similar = previous[previous["date"].dt.day_name() == today_date.day_name()]
    today_exercises = set(today["exercise"].str.lower())
    if len(similar["date"].dt.date.unique()) < 2:
        similar = previous[previous["exercise"].str.lower().isin(today_exercises)]
    if similar.empty:
        score = 6.0
        return {
            **_empty("low_history"),
            "score": score,
            "score_label": f"{score:.1f}/10",
            "color": _score_color(score),
            "explanation": "Workout logged, but not enough comparable history yet.",
            "source": "hevy",
        }

    today_volume = float(today["volume"].sum())
    baseline_volume = float(similar.groupby(similar["date"].dt.date)["volume"].sum().tail(4).mean())
    volume_score = _quality_from_pct(_pct(today_volume, baseline_volume))

    exercise_scores = []
    improved = []
    weaker = []
    for exercise, exercise_today in today.groupby("exercise"):
        history = similar[similar["exercise"].str.lower() == str(exercise).lower()]
        if history.empty:
            continue
        today_best = float(exercise_today["estimated_1rm"].max())
        history_best = float(history.groupby(history["date"].dt.date)["estimated_1rm"].max().tail(4).mean())
        change = _pct(today_best, history_best)
        if change is None:
            continue
        exercise_scores.append(_quality_from_pct(change))
        if change >= 2:
            improved.append(str(exercise))
        elif change <= -2:
            weaker.append(str(exercise))

    exercise_score = sum(exercise_scores) / len(exercise_scores) if exercise_scores else 5.5
    completion_ratio = min(1.15, len(today_exercises) / max(1, similar["exercise"].nunique()))
    completion_score = max(0, min(10, 5 + ((completion_ratio - 0.8) * 10)))
    score = round((exercise_score * 0.55) + (volume_score * 0.3) + (completion_score * 0.15), 1)
    session_count = len(similar["date"].dt.date.unique())
    if improved:
        explanation = f"{', '.join(improved[:2])} improved versus recent similar sessions."
    elif weaker:
        explanation = f"{', '.join(weaker[:2])} looked weaker versus recent similar sessions."
    else:
        explanation = "Volume and top sets were similar to recent comparable sessions."
    if math.isfinite(score) is False:
        score = 6.0
    return {
        "status": "scored",
        "score": score,
        "score_label": f"{score:.1f}/10",
        "confidence": "medium" if session_count >= 3 else "low",
        "color": _score_color(score),
        "explanation": explanation,
        "comparison": f"Compared with {min(4, session_count)} similar lifting sessions.",
        "source": "hevy",
    }


def calculate_workout_quality(training_df: pd.DataFrame, today: str | None = None) -> dict:
    """Score today's workout/run quality from local Hevy and Strava rows."""
    df = _clean_training(training_df)
    if df.empty:
        return _empty()
    today_dt = pd.to_datetime(today).normalize() if today else pd.Timestamp.today().normalize()
    today_rows = df[df["date"].dt.normalize() == today_dt].copy()
    if today_rows.empty:
        return _empty()
    if not today_rows[_is_strength(today_rows)].empty:
        return _strength_quality(df, today_rows, today_dt)
    if not today_rows[_is_run(today_rows)].empty:
        return _run_quality(df, today_rows, today_dt)
    return _empty()
