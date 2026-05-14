"""Muscle group balance analytics for local training logs."""

from __future__ import annotations

import pandas as pd


LOW_VOLUME_MAX = 3
MODERATE_VOLUME_MAX = 8
NORMAL_VOLUME_MAX = 20
HIGH_VOLUME_MIN = 21

PUSH_GROUPS = {"chest", "shoulders", "triceps"}
PULL_GROUPS = {"back", "biceps", "rear delts"}
LEG_GROUPS = {"quads", "hamstrings", "glutes", "calves", "legs"}
UPPER_GROUPS = PUSH_GROUPS | PULL_GROUPS
LOWER_GROUPS = LEG_GROUPS

EXERCISE_MUSCLE_KEYWORDS = {
    "chest": ["bench", "press", "fly", "pec"],
    "back": ["row", "pulldown", "pullup", "pull-up", "lat", "t bar", "shrug"],
    "shoulders": ["lateral raise", "shoulder", "overhead press"],
    "rear delts": ["rear delt", "reverse fly"],
    "biceps": ["curl", "hammer"],
    "triceps": ["triceps", "pushdown", "skullcrusher", "rope"],
    "quads": ["squat", "leg extension", "pendulum"],
    "hamstrings": ["deadlift", "leg curl", "hamstring", "rdl"],
    "glutes": ["hip thrust", "glute"],
    "calves": ["calf"],
    "core": ["crunch", "plank", "abs"],
}


def infer_muscle_group(exercise: str, explicit_group: str = "") -> str:
    """Infer a broad muscle group from explicit input or exercise name."""
    explicit = str(explicit_group or "").strip().lower()
    if explicit:
        return explicit
    name = str(exercise or "").strip().lower()
    for group, keywords in EXERCISE_MUSCLE_KEYWORDS.items():
        if any(keyword in name for keyword in keywords):
            return group
    return "other"


def _training_sets(training_df: pd.DataFrame) -> pd.DataFrame:
    if training_df.empty:
        return pd.DataFrame()
    df = training_df.copy()
    for column in ["sets", "date", "exercise", "muscle_group", "workout_type"]:
        if column not in df.columns:
            df[column] = 0 if column == "sets" else ""
    df["sets"] = pd.to_numeric(df["sets"], errors="coerce").fillna(0)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    df = df[(df["workout_type"].fillna("").astype(str).str.lower() == "strength") & (df["sets"] > 0)].copy()
    if df.empty:
        return df
    df["inferred_muscle_group"] = df.apply(
        lambda row: infer_muscle_group(row.get("exercise", ""), row.get("muscle_group", "")),
        axis=1,
    )
    return df


def weekly_sets_per_muscle_group(training_df: pd.DataFrame) -> pd.DataFrame:
    """Return sets per muscle group per week."""
    df = _training_sets(training_df)
    if df.empty:
        return pd.DataFrame(columns=["week", "muscle_group", "sets"])
    df["week"] = df["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
    return (
        df.groupby(["week", "inferred_muscle_group"], as_index=False)["sets"]
        .sum()
        .rename(columns={"inferred_muscle_group": "muscle_group"})
        .sort_values(["week", "muscle_group"])
        .reset_index(drop=True)
    )


def rolling_4_week_sets_per_muscle_group(training_df: pd.DataFrame) -> pd.DataFrame:
    """Return average weekly sets by muscle group over the last four weeks."""
    weekly = weekly_sets_per_muscle_group(training_df)
    if weekly.empty:
        return pd.DataFrame(columns=["muscle_group", "average_weekly_sets", "status"])
    latest_week = pd.to_datetime(weekly["week"]).max()
    cutoff = latest_week - pd.Timedelta(weeks=3)
    recent = weekly[pd.to_datetime(weekly["week"]) >= cutoff].copy()
    summary = (
        recent.groupby("muscle_group", as_index=False)["sets"]
        .mean()
        .rename(columns={"sets": "average_weekly_sets"})
        .sort_values("average_weekly_sets", ascending=False)
        .reset_index(drop=True)
    )
    summary["average_weekly_sets"] = summary["average_weekly_sets"].round(1)
    summary["status"] = summary["average_weekly_sets"].apply(classify_volume)
    return summary


def classify_volume(sets: float) -> str:
    """Classify weekly set volume with editable module-level thresholds."""
    if sets <= LOW_VOLUME_MAX:
        return "likely undertrained"
    if sets <= MODERATE_VOLUME_MAX:
        return "low/moderate"
    if sets <= NORMAL_VOLUME_MAX:
        return "normal hypertrophy range"
    return "high volume"


def push_pull_legs_balance(training_df: pd.DataFrame) -> dict:
    """Summarize recent push, pull, and legs set balance."""
    summary = rolling_4_week_sets_per_muscle_group(training_df)
    totals = {"push": 0.0, "pull": 0.0, "legs": 0.0}
    for _, row in summary.iterrows():
        group = str(row["muscle_group"]).lower()
        sets = float(row["average_weekly_sets"])
        if group in PUSH_GROUPS:
            totals["push"] += sets
        if group in PULL_GROUPS:
            totals["pull"] += sets
        if group in LEG_GROUPS:
            totals["legs"] += sets
    return {key: round(value, 1) for key, value in totals.items()}


def upper_lower_balance(training_df: pd.DataFrame) -> dict:
    """Summarize recent upper/lower set balance."""
    summary = rolling_4_week_sets_per_muscle_group(training_df)
    totals = {"upper": 0.0, "lower": 0.0}
    for _, row in summary.iterrows():
        group = str(row["muscle_group"]).lower()
        sets = float(row["average_weekly_sets"])
        if group in UPPER_GROUPS:
            totals["upper"] += sets
        if group in LOWER_GROUPS:
            totals["lower"] += sets
    return {key: round(value, 1) for key, value in totals.items()}


def analyze_muscle_balance(training_df: pd.DataFrame, latest_recovery_score: float | None = None) -> dict:
    """Return muscle balance tables and conservative flags."""
    weekly = weekly_sets_per_muscle_group(training_df)
    rolling = rolling_4_week_sets_per_muscle_group(training_df)
    flags = []

    for _, row in rolling.iterrows():
        group = str(row["muscle_group"])
        sets = float(row["average_weekly_sets"])
        if sets <= LOW_VOLUME_MAX:
            flags.append(f"{group} volume low ({sets:g} sets/week).")
        elif sets >= HIGH_VOLUME_MIN:
            flags.append(f"{group} volume high ({sets:g} sets/week).")
            if latest_recovery_score is not None and latest_recovery_score < 60:
                flags.append(f"{group} high volume plus low recovery may increase fatigue risk.")

    ppls = push_pull_legs_balance(training_df)
    if ppls["legs"] <= LOW_VOLUME_MAX and (ppls["push"] > MODERATE_VOLUME_MAX or ppls["pull"] > MODERATE_VOLUME_MAX):
        flags.append("legs neglected relative to upper-body training.")
    if ppls["pull"] + 2 < ppls["push"]:
        flags.append("back/pull volume low relative to push volume.")
    if ppls["push"] + 2 < ppls["pull"]:
        flags.append("push volume low relative to pull volume.")

    return {
        "weekly_sets": weekly.to_dict(orient="records"),
        "rolling_4_week": rolling.to_dict(orient="records"),
        "push_pull_legs": ppls,
        "upper_lower": upper_lower_balance(training_df),
        "flags": flags,
        "thresholds": {
            "undertrained_max": LOW_VOLUME_MAX,
            "low_moderate_max": MODERATE_VOLUME_MAX,
            "normal_max": NORMAL_VOLUME_MAX,
            "high_min": HIGH_VOLUME_MIN,
        },
    }
