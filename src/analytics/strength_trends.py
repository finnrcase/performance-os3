"""Strength trend analytics for Performance OS.

These functions are deterministic and operate only on the local training log.
They intentionally avoid coaching claims beyond what the saved sets support.
"""

from __future__ import annotations

import pandas as pd

from src.analytics.exercise_muscle_map import MUSCLE_GROUPS, get_exercise_muscle_group


def _strength_rows(training_df: pd.DataFrame) -> pd.DataFrame:
    """Return clean strength rows with usable exercise, reps, and weight."""
    if training_df.empty:
        return pd.DataFrame()

    df = training_df.copy()
    for column in ["sets", "reps", "weight", "rpe"]:
        if column not in df.columns:
            df[column] = 0
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    for column in ["date", "exercise", "workout_type"]:
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("").astype(str)

    df = df[
        (df["workout_type"].str.lower() == "strength")
        & (df["exercise"].str.strip() != "")
        & (df["reps"] > 0)
        & (df["weight"] > 0)
    ].copy()
    if df.empty:
        return df

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    df["estimated_1rm"] = df.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
    return df.sort_values("date")


def calculate_estimated_1rm(weight, reps) -> float:
    """Estimate 1RM with the Epley formula: weight * (1 + reps / 30)."""
    try:
        weight_value = float(weight or 0)
        reps_value = float(reps or 0)
    except (TypeError, ValueError):
        return 0.0
    if weight_value <= 0 or reps_value <= 0:
        return 0.0
    return round(weight_value * (1 + reps_value / 30), 1)


def calculate_exercise_estimated_1rm(set_row: dict | pd.Series) -> float:
    """Estimate 1RM for a set-like object."""
    return calculate_estimated_1rm(set_row.get("weight", 0), set_row.get("reps", 0))


def get_exercise_history(training_df: pd.DataFrame, exercise_name: str) -> pd.DataFrame:
    """Return set-level history for one exercise."""
    df = _strength_rows(training_df)
    if df.empty or not exercise_name:
        return pd.DataFrame(columns=["date", "weight", "reps", "rpe", "volume", "estimated_1rm"])
    df = df[df["exercise"].str.lower() == str(exercise_name).strip().lower()].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "weight", "reps", "rpe", "volume", "estimated_1rm"])
    latest = df["date"].max()
    df = df[df["date"] >= latest - pd.Timedelta(days=84)].copy()
    return df.reset_index(drop=True)


def calculate_volume_by_exercise(training_df: pd.DataFrame) -> pd.DataFrame:
    """Calculate total volume by exercise."""
    df = _strength_rows(training_df)
    if df.empty:
        return pd.DataFrame(columns=["exercise", "volume", "sets"])
    return (
        df.groupby("exercise", as_index=False)
        .agg(volume=("volume", "sum"), sets=("sets", "sum"))
        .sort_values("volume", ascending=False)
        .reset_index(drop=True)
    )


def _date_range_days(date_range: str) -> int | None:
    return {
        "4w": 28,
        "8w": 56,
        "12w": 84,
        "6m": 183,
        "all": None,
    }.get(str(date_range or "12w"), 84)


def _with_muscle_groups(training_df: pd.DataFrame) -> pd.DataFrame:
    df = _strength_rows(training_df)
    if df.empty:
        return df
    if "muscle_group" not in df.columns:
        df["muscle_group"] = ""
    resolved = df.apply(
        lambda row: get_exercise_muscle_group(
            row.get("exercise", ""),
            {
                "muscle_group": row.get("muscle_group", ""),
            },
        ),
        axis=1,
    )
    df["primary_muscle_group"] = resolved.apply(lambda item: item["primaryMuscleGroup"])
    df["secondary_muscle_groups"] = resolved.apply(lambda item: item["secondaryMuscleGroups"])
    df["muscle_group_source"] = resolved.apply(lambda item: item["muscleGroupSource"])
    return df


def _filter_date_range(df: pd.DataFrame, date_range: str) -> pd.DataFrame:
    days = _date_range_days(date_range)
    if df.empty or days is None:
        return df
    latest_date = df["date"].max()
    return df[df["date"] >= latest_date - pd.Timedelta(days=days)].copy()


def group_exercises_by_muscle_group(training_df: pd.DataFrame) -> dict:
    """Return exercise names grouped by resolved primary muscle group."""
    df = _with_muscle_groups(training_df)
    if df.empty:
        return {group: [] for group in MUSCLE_GROUPS}
    grouped = {group: [] for group in MUSCLE_GROUPS}
    for group, values in df.groupby("primary_muscle_group")["exercise"]:
        grouped.setdefault(str(group), [])
        grouped[str(group)] = sorted({str(value) for value in values if str(value).strip()})
    return grouped


def calculate_exercise_trend(exercise_history: pd.DataFrame) -> dict:
    """Calculate normalized exercise trend history for muscle-group aggregation."""
    if exercise_history.empty:
        return {"history": [], "baseline": 0.0}
    daily = (
        exercise_history.groupby(["date", "exercise", "primary_muscle_group"], as_index=False)
        .agg(
            estimated_1rm=("estimated_1rm", "max"),
            total_volume=("volume", "sum"),
            hard_sets=("sets", "sum"),
            total_reps=("reps", "sum"),
            average_working_weight=("weight", "mean"),
        )
        .sort_values("date")
    )
    baseline = float(daily.head(min(3, len(daily)))["estimated_1rm"].mean() or 0)
    if baseline <= 0:
        daily["strength_index"] = 100.0
    else:
        daily["strength_index"] = (daily["estimated_1rm"] / baseline) * 100
    return {"history": daily, "baseline": baseline}


def calculate_muscle_group_trend(
    training_df: pd.DataFrame,
    date_range: str = "12w",
    muscle_group: str = "",
) -> dict:
    """Calculate normalized strength and volume trends by primary muscle group."""
    df = _with_muscle_groups(training_df)
    if df.empty:
        return {
            "date_range": date_range,
            "muscle_group_options": MUSCLE_GROUPS,
            "selected_muscle_group": muscle_group,
            "summary": [],
            "history": [],
            "unmapped_exercises": [],
        }

    baselines = {}
    for exercise, exercise_df in df.groupby("exercise"):
        trend = calculate_exercise_trend(exercise_df)
        baselines[str(exercise)] = float(trend["baseline"] or 0)

    ranged = _filter_date_range(df, date_range)
    if muscle_group:
        ranged = ranged[ranged["primary_muscle_group"].str.lower() == str(muscle_group).lower()].copy()
    if ranged.empty:
        return {
            "date_range": date_range,
            "muscle_group_options": MUSCLE_GROUPS,
            "selected_muscle_group": muscle_group,
            "summary": [],
            "history": [],
            "unmapped_exercises": sorted(df[df["muscle_group_source"] == "unknown"]["exercise"].dropna().astype(str).unique().tolist()),
        }

    daily_exercise = (
        ranged.groupby(["date", "exercise", "primary_muscle_group"], as_index=False)
        .agg(
            estimated_1rm=("estimated_1rm", "max"),
            total_volume=("volume", "sum"),
            hard_sets=("sets", "sum"),
            total_reps=("reps", "sum"),
            average_working_weight=("weight", "mean"),
        )
        .sort_values("date")
    )
    daily_exercise["baseline"] = daily_exercise["exercise"].map(baselines).fillna(0)
    daily_exercise["strength_index"] = daily_exercise.apply(
        lambda row: 100.0 if float(row["baseline"] or 0) <= 0 else (float(row["estimated_1rm"]) / float(row["baseline"])) * 100,
        axis=1,
    )
    daily_exercise["weight_for_index"] = daily_exercise["hard_sets"].clip(lower=1)
    daily_exercise["weighted_index"] = daily_exercise["strength_index"] * daily_exercise["weight_for_index"]
    daily_exercise["week"] = daily_exercise["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())

    weekly = (
        daily_exercise.groupby(["week", "primary_muscle_group"], as_index=False)
        .agg(
            weighted_index=("weighted_index", "sum"),
            index_weight=("weight_for_index", "sum"),
            weekly_volume=("total_volume", "sum"),
            hard_sets=("hard_sets", "sum"),
            total_reps=("total_reps", "sum"),
            average_working_weight=("average_working_weight", "mean"),
            best_estimated_1rm=("estimated_1rm", "max"),
            workout_frequency=("date", "nunique"),
        )
        .rename(columns={"primary_muscle_group": "muscle_group"})
        .sort_values(["week", "muscle_group"])
    )
    weekly["strength_index"] = (weekly["weighted_index"] / weekly["index_weight"]).round(1)
    weekly["weekly_volume"] = weekly["weekly_volume"].round(1)
    weekly["average_working_weight"] = weekly["average_working_weight"].round(1)
    weekly["best_estimated_1rm"] = weekly["best_estimated_1rm"].round(1)

    summary = []
    for group, group_df in weekly.groupby("muscle_group", sort=False):
        first_index = float(group_df.head(min(3, len(group_df)))["strength_index"].mean() or 0)
        current_index = float(group_df.iloc[-1]["strength_index"] or 0)
        strength_change = 0.0 if first_index <= 0 else ((current_index - first_index) / first_index) * 100
        first_volume = float(group_df.head(min(3, len(group_df)))["weekly_volume"].mean() or 0)
        recent_volume = float(group_df.tail(min(3, len(group_df)))["weekly_volume"].mean() or 0)
        volume_change = 0.0 if first_volume <= 0 else ((recent_volume - first_volume) / first_volume) * 100
        group_exercises = daily_exercise[daily_exercise["primary_muscle_group"] == group].copy()
        recent_best = group_exercises.sort_values(["date", "strength_index", "estimated_1rm"], ascending=[False, False, False]).head(1)
        recent_best_exercise = str(recent_best.iloc[0]["exercise"]) if not recent_best.empty else ""
        summary.append(
            {
                "muscle_group": str(group),
                "strength_change_pct": round(strength_change, 1),
                "volume_change_pct": round(volume_change, 1),
                "strength_index": round(current_index, 1),
                "weekly_volume": round(recent_volume, 1),
                "hard_sets": int(group_df["hard_sets"].sum()),
                "total_reps": int(group_df["total_reps"].sum()),
                "workout_frequency": int(group_df["workout_frequency"].sum()),
                "average_working_weight": round(float(group_df.tail(min(3, len(group_df)))["average_working_weight"].mean() or 0), 1),
                "best_estimated_1rm": round(float(group_df["best_estimated_1rm"].max() or 0), 1),
                "recent_best_exercise": recent_best_exercise,
            }
        )

    weekly = weekly.drop(columns=["weighted_index", "index_weight"])
    return {
        "date_range": date_range,
        "muscle_group_options": MUSCLE_GROUPS,
        "selected_muscle_group": muscle_group,
        "summary": sorted(summary, key=lambda item: item["strength_index"], reverse=True),
        "history": weekly.to_dict(orient="records"),
        "unmapped_exercises": sorted(df[df["muscle_group_source"] == "unknown"]["exercise"].dropna().astype(str).unique().tolist()),
    }


def calculate_strength_trend(training_df: pd.DataFrame, exercise_name: str) -> dict:
    """Calculate strength trend metrics for one exercise."""
    history = get_exercise_history(training_df, exercise_name)
    if len(history) < 2:
        return {
            "exercise": exercise_name,
            "label": "insufficient data",
            "history": [],
            "best_set": None,
            "recent_pr": None,
            "summary": "Log this exercise at least twice to calculate a trend.",
        }

    daily = (
        history.groupby("date", as_index=False)
        .agg(
            best_set_weight=("weight", "max"),
            estimated_1rm=("estimated_1rm", "max"),
            total_volume=("volume", "sum"),
            average_working_weight=("weight", "mean"),
            average_rpe=("rpe", "mean"),
            total_reps=("reps", "sum"),
        )
        .sort_values("date")
    )

    first = daily.head(min(3, len(daily)))["estimated_1rm"].mean()
    recent = daily.tail(min(3, len(daily)))["estimated_1rm"].mean()
    change_pct = 0.0 if first == 0 else ((recent - first) / first) * 100

    if len(daily) < 3:
        label = "insufficient data"
    elif change_pct > 2:
        label = "improving"
    elif change_pct < -2:
        label = "declining"
    else:
        label = "stable"

    best_row = history.sort_values(["estimated_1rm", "weight", "reps"], ascending=False).iloc[0]
    latest_best = daily.iloc[-1]["estimated_1rm"]
    previous_best = daily.iloc[:-1]["estimated_1rm"].max() if len(daily) > 1 else 0
    recent_pr = bool(latest_best >= previous_best and latest_best > 0)

    daily["date"] = daily["date"].dt.date.astype(str)
    return {
        "exercise": exercise_name,
        "label": label,
        "change_pct": round(change_pct, 1),
        "history": daily.to_dict(orient="records"),
        "best_set": {
            "date": best_row["date"].date().isoformat(),
            "weight": float(best_row["weight"]),
            "reps": int(best_row["reps"]),
            "estimated_1rm": float(best_row["estimated_1rm"]),
            "rpe": float(best_row["rpe"]),
        },
        "recent_pr": recent_pr,
        "summary": f"{exercise_name} trend is {label} based on estimated 1RM across logged sessions.",
    }


def detect_strength_decline(training_df: pd.DataFrame, exercise_name: str) -> dict:
    """Detect whether recent estimated 1RM is meaningfully below earlier sessions."""
    trend = calculate_strength_trend(training_df, exercise_name)
    return {
        "exercise": exercise_name,
        "declining": trend.get("label") == "declining",
        "change_pct": trend.get("change_pct", 0),
        "message": trend.get("summary", "Insufficient data."),
    }
