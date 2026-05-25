"""Weekly muscle coverage analytics for Data & History."""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.analytics.exercise_muscle_map import get_exercise_muscle_group


MUSCLE_COVERAGE_GROUPS = [
    "Chest",
    "Back",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Quads",
    "Hamstrings",
    "Glutes",
    "Calves",
    "Core",
]

DEFAULT_WEEKLY_TARGET_SETS = {
    "Chest": 8.0,
    "Back": 10.0,
    "Shoulders": 6.0,
    "Biceps": 4.0,
    "Triceps": 4.0,
    "Quads": 6.0,
    "Hamstrings": 6.0,
    "Glutes": 4.0,
    "Calves": 4.0,
    "Core": 4.0,
}

STATUS_STYLES = {
    "missed": {"color": "Purple", "hex": "#7c3aed", "label": "Missed"},
    "low": {"color": "Red", "hex": "#ef4444", "label": "Not hit enough"},
    "lacking": {"color": "Yellow", "hex": "#facc15", "label": "Slightly lacking"},
    "good": {"color": "Green", "hex": "#22c55e", "label": "Good"},
}


def _canonical_coverage_group(value: object, exercise: object = "") -> str:
    clean = str(value or "").split(",", 1)[0].strip()
    if clean.lower() in {"abs/core", "abs", "abdominals", "core"}:
        return "Core"
    for group in MUSCLE_COVERAGE_GROUPS:
        if clean.lower() == group.lower():
            return group
    inferred = get_exercise_muscle_group(str(exercise or ""), {"muscle_group": clean})
    primary = str(inferred.get("primaryMuscleGroup") or "").strip()
    if primary.lower() in {"abs/core", "abs", "abdominals", "core"}:
        return "Core"
    return primary if primary in MUSCLE_COVERAGE_GROUPS else ""


def _coverage_group_weights(row: pd.Series) -> dict[str, float]:
    explicit = _canonical_coverage_group(row.get("muscle_group"), row.get("exercise"))
    inferred = get_exercise_muscle_group(str(row.get("exercise") or ""), {"muscle_group": explicit} if explicit else None)
    primary = explicit or str(inferred.get("primaryMuscleGroup") or "")
    if primary.lower() in {"abs/core", "abs", "abdominals"}:
        primary = "Core"
    weights: dict[str, float] = {}
    if primary in MUSCLE_COVERAGE_GROUPS:
        weights[primary] = 1.0

    local_mapping = get_exercise_muscle_group(str(row.get("exercise") or ""))
    secondary_values = list(inferred.get("secondaryMuscleGroups") or []) + list(local_mapping.get("secondaryMuscleGroups") or [])
    for value in secondary_values:
        group = "Core" if str(value).lower() in {"abs/core", "abs", "abdominals", "core"} else str(value)
        if group in MUSCLE_COVERAGE_GROUPS and group != primary:
            weights[group] = max(weights.get(group, 0.0), 0.5)
    return weights


def _prepare_strength_rows(training_df: pd.DataFrame | None) -> pd.DataFrame:
    if training_df is None or training_df.empty:
        return pd.DataFrame(columns=["date", "muscle_group", "hard_sets", "sets", "volume"])
    df = training_df.copy()
    for column in ["date", "workout_type", "muscle_group", "exercise", "sets", "reps", "weight", "rpe"]:
        if column not in df.columns:
            df[column] = 0 if column in {"sets", "reps", "weight", "rpe"} else ""
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "muscle_group", "hard_sets", "sets", "volume"])
    for column in ["sets", "reps", "weight", "rpe"]:
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    workout_type = df["workout_type"].fillna("").astype(str).str.lower()
    cardio_mask = workout_type.str.contains("run|cardio|rest", regex=True, na=False)
    strength_mask = ~cardio_mask & (df["sets"] > 0)
    df = df[strength_mask].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "muscle_group", "hard_sets", "sets", "volume"])
    expanded_rows = []
    for _, row in df.iterrows():
        group_weights = _coverage_group_weights(row)
        if not group_weights:
            continue
        rpe = float(row.get("rpe") or 0)
        sets = float(row.get("sets") or 0)
        working_set_multiplier = 1.0 if rpe >= 7 else 0.5 if rpe <= 0 and float(row.get("weight") or 0) > 0 and float(row.get("reps") or 0) > 0 else 0.0
        base_hard_sets = sets * working_set_multiplier
        volume = float(row.get("sets") or 0) * float(row.get("reps") or 0) * float(row.get("weight") or 0)
        for group, weight in group_weights.items():
            expanded_rows.append(
                {
                    "date": row["date"],
                    "muscle_group": group,
                    "hard_sets": base_hard_sets * weight,
                    "sets": sets * weight,
                    "volume": volume * weight,
                }
            )
    if not expanded_rows:
        return pd.DataFrame(columns=["date", "muscle_group", "hard_sets", "sets", "volume"])
    return pd.DataFrame(expanded_rows)


def _status_for_ratio(hard_sets: float, ratio: float) -> dict:
    if hard_sets <= 0:
        return STATUS_STYLES["missed"]
    if ratio < 0.5:
        return STATUS_STYLES["low"]
    if ratio < 0.85:
        return STATUS_STYLES["lacking"]
    return STATUS_STYLES["good"]


def calculate_weekly_muscle_coverage(training_df: pd.DataFrame | None, reference_date: str | date | None = None) -> pd.DataFrame:
    """Return last-7-day muscle coverage compared with simple targets/baseline."""
    rows = _prepare_strength_rows(training_df)
    reference = pd.to_datetime(reference_date or date.today(), errors="coerce")
    if pd.isna(reference):
        reference = pd.Timestamp.today().normalize()
    reference = reference.normalize()
    current_start = reference - pd.Timedelta(days=6)
    baseline_start = current_start - pd.Timedelta(days=28)
    baseline_end = current_start - pd.Timedelta(days=1)

    if rows.empty:
        current = pd.DataFrame(columns=["muscle_group", "hard_sets", "sets", "volume"])
        baseline = pd.Series(dtype=float)
    else:
        current_rows = rows[(rows["date"] >= current_start) & (rows["date"] <= reference)].copy()
        current = (
            current_rows.groupby("muscle_group", as_index=False)
            .agg(hard_sets=("hard_sets", "sum"), sets=("sets", "sum"), volume=("volume", "sum"))
        )
        baseline_rows = rows[(rows["date"] >= baseline_start) & (rows["date"] <= baseline_end)].copy()
        baseline = baseline_rows.groupby("muscle_group")["hard_sets"].sum() / 4.0 if not baseline_rows.empty else pd.Series(dtype=float)

    current_by_group = current.set_index("muscle_group") if not current.empty else pd.DataFrame()
    coverage_rows = []
    for group in MUSCLE_COVERAGE_GROUPS:
        if group in current_by_group.index:
            group_row = current_by_group.loc[group]
            hard_sets = float(group_row.get("hard_sets", 0) or 0)
            total_sets = float(group_row.get("sets", 0) or 0)
            volume = float(group_row.get("volume", 0) or 0)
        else:
            hard_sets = 0.0
            total_sets = 0.0
            volume = 0.0
        baseline_sets = float(baseline.get(group, 0) or 0)
        target_sets = max(DEFAULT_WEEKLY_TARGET_SETS[group], baseline_sets)
        ratio = hard_sets / target_sets if target_sets > 0 else 0.0
        status = _status_for_ratio(hard_sets, ratio)
        coverage_rows.append(
            {
                "muscle_group": group,
                "hard_sets": round(hard_sets, 1),
                "sets": round(total_sets, 1),
                "volume": round(volume, 1),
                "baseline_weekly_hard_sets": round(baseline_sets, 1),
                "target_sets": round(target_sets, 1),
                "coverage_pct": round(ratio * 100, 0),
                "gap_pct": round(max(0.0, 1.0 - ratio) * 100, 0),
                "status": status["label"],
                "color": status["color"],
                "color_hex": status["hex"],
            }
        )
    return pd.DataFrame(coverage_rows)
