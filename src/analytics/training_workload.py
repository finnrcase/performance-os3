"""Training workload analytics from synced Hevy and Strava history."""

from __future__ import annotations

import pandas as pd

from src.analytics.exercise_muscle_map import get_exercise_muscle_group
from src.analytics.strength_trends import calculate_estimated_1rm, calculate_muscle_group_trend, calculate_strength_trend
from src.training_schedule import is_run_row, is_strength_row


WINDOWS = (7, 14, 28)


def _empty_workload() -> dict:
    return {
        "windows": {
            str(days): {
                "hevy": {
                    "workouts_per_week": 0,
                    "total_sets_per_week": 0,
                    "hard_sets_per_week": 0,
                    "hard_sets_by_muscle_group": {},
                    "total_volume_per_week": 0,
                    "average_session_duration_minutes": 0,
                },
                "strava": {
                    "runs_per_week": 0,
                    "weekly_mileage": 0,
                    "weekly_duration_minutes": 0,
                    "weekly_calories": 0,
                    "pace_trend": "insufficient data",
                    "average_pace_min_per_mile": 0,
                    "intensity": "unknown",
                },
            }
            for days in WINDOWS
        },
        "current": {
            "strength_workouts_per_week": 0,
            "runs_per_week": 0,
            "weekly_mileage": 0,
            "weekly_training_minutes": 0,
            "training_calorie_demand": 0,
            "cardio_calorie_demand": 0,
            "recovery_demand": "low",
            "carb_adjustment_grams": 0,
            "calorie_adjustment": 0,
            "strength_trend": "insufficient data",
            "muscle_group_trends": {},
        },
    }


def _note_number(note: str, key: str) -> float:
    marker = f"{key}="
    if marker not in str(note):
        return 0.0
    raw = str(note).split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _source_mask(df: pd.DataFrame, value: str) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)
    if value == "hevy":
        return df.apply(is_strength_row, axis=1)
    if value == "strava":
        return df.apply(is_run_row, axis=1)
    return pd.Series(False, index=df.index)


def _prepare_training(training_df: pd.DataFrame) -> pd.DataFrame:
    if training_df.empty:
        return pd.DataFrame()
    df = training_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"])
    for column in ["sets", "reps", "weight", "duration_minutes", "rpe"]:
        values = df[column] if column in df.columns else pd.Series(0, index=df.index)
        df[column] = pd.to_numeric(values, errors="coerce").fillna(0)
    df["volume"] = df["sets"].clip(lower=0) * df["reps"].clip(lower=0) * df["weight"].clip(lower=0)
    df["notes"] = df["notes"].fillna("").astype(str) if "notes" in df.columns else pd.Series("", index=df.index)
    return df.sort_values("date")


def _hevy_window(df: pd.DataFrame, days: int) -> dict:
    hevy = df[_source_mask(df, "hevy")].copy()
    if hevy.empty:
        return _empty_workload()["windows"][str(days)]["hevy"]
    latest = df["date"].max()
    window = hevy[hevy["date"] >= latest - pd.Timedelta(days=days - 1)].copy()
    if window.empty:
        return _empty_workload()["windows"][str(days)]["hevy"]
    scale = 7 / days
    workout_count = window[["date", "workout_id"]].drop_duplicates().shape[0] if "workout_id" in window.columns else window["date"].dt.date.nunique()
    total_sets = float(window["sets"].sum())
    hard = window[(window["rpe"] >= 7) | (window["rpe"] == 0)].copy()
    hard_sets_by_group: dict[str, float] = {}
    for _, row in hard.iterrows():
        group = str(row.get("muscle_group") or "").split(",", 1)[0].strip()
        if not group:
            group = get_exercise_muscle_group(str(row.get("exercise") or ""))["primaryMuscleGroup"]
        hard_sets_by_group[group] = hard_sets_by_group.get(group, 0) + float(row.get("sets") or 0)
    durations = window.groupby("workout_id")["duration_minutes"].sum() if "workout_id" in window.columns else window.groupby(window["date"].dt.date)["duration_minutes"].sum()
    durations = durations[durations > 0]
    return {
        "workouts_per_week": round(workout_count * scale, 2),
        "total_sets_per_week": round(total_sets * scale, 1),
        "hard_sets_per_week": round(float(hard["sets"].sum()) * scale, 1),
        "hard_sets_by_muscle_group": {group: round(value * scale, 1) for group, value in sorted(hard_sets_by_group.items())},
        "total_volume_per_week": round(float(window["volume"].sum()) * scale, 1),
        "average_session_duration_minutes": round(float(durations.mean()), 1) if not durations.empty else 0,
    }


def _run_calories(distance_miles: float, bodyweight: float, strava_calories: float) -> float:
    if strava_calories > 0:
        return strava_calories
    return distance_miles * max(bodyweight, 1) * 0.72


def _strava_window(df: pd.DataFrame, days: int, bodyweight: float) -> dict:
    runs = df[_source_mask(df, "strava")].copy()
    if runs.empty:
        return _empty_workload()["windows"][str(days)]["strava"]
    latest = df["date"].max()
    window = runs[runs["date"] >= latest - pd.Timedelta(days=days - 1)].copy()
    if window.empty:
        return _empty_workload()["windows"][str(days)]["strava"]
    window["distance_miles"] = window["notes"].apply(lambda note: _note_number(note, "distance_miles"))
    window["pace_min_per_mile"] = window["notes"].apply(lambda note: _note_number(note, "pace_min_per_mile"))
    window["strava_calories"] = window["notes"].apply(lambda note: _note_number(note, "calories"))
    window["estimated_calories"] = window.apply(lambda row: _run_calories(row["distance_miles"], bodyweight, row["strava_calories"]), axis=1)
    scale = 7 / days
    runs_count = window[["date", "workout_id"]].drop_duplicates().shape[0] if "workout_id" in window.columns else len(window)
    paces = window[window["pace_min_per_mile"] > 0]["pace_min_per_mile"]
    pace_trend = "insufficient data"
    if len(paces) >= 4:
        midpoint = len(paces) // 2
        pace_trend = "improving" if paces.iloc[midpoint:].mean() < paces.iloc[:midpoint].mean() else "slower" if paces.iloc[midpoint:].mean() > paces.iloc[:midpoint].mean() else "stable"
    duration = float(window["duration_minutes"].sum())
    mileage = float(window["distance_miles"].sum())
    intensity = "high" if (not paces.empty and paces.mean() < 8) or duration * scale > 180 else "moderate" if mileage * scale >= 8 else "low"
    return {
        "runs_per_week": round(runs_count * scale, 2),
        "weekly_mileage": round(mileage * scale, 1),
        "weekly_duration_minutes": round(duration * scale, 1),
        "weekly_calories": round(float(window["estimated_calories"].sum()) * scale, 0),
        "pace_trend": pace_trend,
        "average_pace_min_per_mile": round(float(paces.mean()), 2) if not paces.empty else 0,
        "intensity": intensity,
    }


def _performance_empty(reason: str = "Need more comparable Hevy lifting history.") -> dict:
    return {
        "label": "insufficient data",
        "confidence": "low",
        "summary": reason,
        "recommendation": "Keep nutrition targets stable until more comparable sessions are available.",
        "drivers": [],
        "muscle_group_drivers": [],
        "windows": {
            "recent_2w": {"exercise_count": 0, "workout_count": 0},
            "previous_2w": {"exercise_count": 0, "workout_count": 0},
            "recent_4w": {"exercise_count": 0, "workout_count": 0},
            "previous_4w": {"exercise_count": 0, "workout_count": 0},
        },
    }


def _percent_change(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    return ((current - previous) / previous) * 100


def _window_summary(window: pd.DataFrame) -> dict:
    if window.empty:
        return {"exercise_count": 0, "workout_count": 0, "set_count": 0, "volume": 0}
    workout_count = window[["date", "workout_id"]].drop_duplicates().shape[0] if "workout_id" in window.columns else window["date"].dt.date.nunique()
    return {
        "exercise_count": int(window["exercise"].nunique()),
        "workout_count": int(workout_count),
        "set_count": int(window["sets"].sum()),
        "volume": round(float(window["volume"].sum()), 1),
    }


def _exercise_window_metrics(window: pd.DataFrame) -> dict[str, dict]:
    metrics = {}
    if window.empty:
        return metrics
    for exercise, exercise_df in window.groupby("exercise"):
        same_weight = (
            exercise_df.groupby("weight", as_index=False)
            .agg(max_reps=("reps", "max"), set_count=("sets", "sum"))
            .sort_values(["set_count", "weight"], ascending=False)
        )
        metrics[str(exercise)] = {
            "sessions": int(exercise_df["date"].dt.date.nunique()),
            "estimated_1rm": float(exercise_df["estimated_1rm"].max()),
            "top_set_weight": float(exercise_df.sort_values("estimated_1rm", ascending=False).iloc[0]["weight"]),
            "top_set_reps": float(exercise_df.sort_values("estimated_1rm", ascending=False).iloc[0]["reps"]),
            "volume": float(exercise_df["volume"].sum()),
            "reps": float((exercise_df["sets"] * exercise_df["reps"]).sum()),
            "same_weight_reps": {float(row["weight"]): float(row["max_reps"]) for _, row in same_weight.iterrows()},
            "muscle_group": get_exercise_muscle_group(str(exercise))["primaryMuscleGroup"],
        }
    return metrics


def _compare_exercise_windows(recent: pd.DataFrame, previous: pd.DataFrame) -> list[dict]:
    recent_metrics = _exercise_window_metrics(recent)
    previous_metrics = _exercise_window_metrics(previous)
    drivers = []
    for exercise in sorted(set(recent_metrics) & set(previous_metrics)):
        current = recent_metrics[exercise]
        prior = previous_metrics[exercise]
        if current["sessions"] < 1 or prior["sessions"] < 1:
            continue
        one_rm_change = _percent_change(current["estimated_1rm"], prior["estimated_1rm"])
        volume_change = _percent_change(current["volume"], prior["volume"])
        top_set_change = _percent_change(current["top_set_weight"], prior["top_set_weight"])
        shared_weights = set(current["same_weight_reps"]) & set(prior["same_weight_reps"])
        reps_delta = None
        if shared_weights:
            best_weight = max(shared_weights)
            reps_delta = current["same_weight_reps"][best_weight] - prior["same_weight_reps"][best_weight]

        decline_markers = 0
        improve_markers = 0
        if one_rm_change is not None:
            decline_markers += int(one_rm_change <= -3)
            improve_markers += int(one_rm_change >= 3)
        if volume_change is not None:
            decline_markers += int(volume_change <= -8)
            improve_markers += int(volume_change >= 8)
        if top_set_change is not None:
            decline_markers += int(top_set_change <= -3)
            improve_markers += int(top_set_change >= 3)
        if reps_delta is not None:
            decline_markers += int(reps_delta <= -2)
            improve_markers += int(reps_delta >= 2)

        signal = "stable"
        if decline_markers >= 2 and decline_markers > improve_markers:
            signal = "declining"
        elif improve_markers >= 2 and improve_markers > decline_markers:
            signal = "improving"

        drivers.append(
            {
                "name": exercise,
                "muscle_group": current["muscle_group"],
                "signal": signal,
                "estimated_1rm_change_pct": round(one_rm_change, 1) if one_rm_change is not None else None,
                "volume_change_pct": round(volume_change, 1) if volume_change is not None else None,
                "top_set_weight_change_pct": round(top_set_change, 1) if top_set_change is not None else None,
                "reps_at_same_weight_delta": round(reps_delta, 1) if reps_delta is not None else None,
                "recent_sessions": current["sessions"],
                "previous_sessions": prior["sessions"],
            }
        )
    return drivers


def _muscle_group_driver_summary(drivers: list[dict]) -> list[dict]:
    groups = {}
    for driver in drivers:
        group = str(driver.get("muscle_group") or "Other")
        groups.setdefault(group, {"muscle_group": group, "declining": 0, "improving": 0, "stable": 0, "estimated_1rm_changes": []})
        groups[group][str(driver.get("signal") or "stable")] += 1
        if driver.get("estimated_1rm_change_pct") is not None:
            groups[group]["estimated_1rm_changes"].append(float(driver["estimated_1rm_change_pct"]))
    summaries = []
    for group, values in groups.items():
        average_change = (
            round(sum(values["estimated_1rm_changes"]) / len(values["estimated_1rm_changes"]), 1)
            if values["estimated_1rm_changes"]
            else None
        )
        signal = "stable"
        if values["declining"] >= max(1, values["improving"] + 1):
            signal = "declining"
        elif values["improving"] >= max(1, values["declining"] + 1):
            signal = "improving"
        summaries.append(
            {
                "muscle_group": group,
                "signal": signal,
                "estimated_1rm_change_pct": average_change,
                "exercise_count": values["declining"] + values["improving"] + values["stable"],
            }
        )
    return sorted(summaries, key=lambda item: (item["signal"] != "declining", item["signal"] != "improving", item["muscle_group"]))


def analyze_hevy_performance_signal(training_df: pd.DataFrame) -> dict:
    """Detect recent Hevy performance direction without reacting to one bad set."""
    df = _prepare_training(training_df)
    if df.empty:
        return _performance_empty()
    hevy = df[_source_mask(df, "hevy")].copy()
    if hevy.empty:
        return _performance_empty("No Hevy lifting sessions found yet.")
    workout_type = hevy["workout_type"] if "workout_type" in hevy.columns else pd.Series("strength", index=hevy.index)
    exercise = hevy["exercise"] if "exercise" in hevy.columns else pd.Series("", index=hevy.index)
    hevy = hevy[
        (workout_type.astype(str).str.lower() == "strength")
        & (exercise.fillna("").astype(str).str.strip() != "")
        & (hevy["reps"] > 0)
        & (hevy["weight"] > 0)
    ].copy()
    if hevy.empty:
        return _performance_empty("Hevy sessions need weighted strength sets before performance trends can be compared.")
    hevy["estimated_1rm"] = hevy.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
    latest = hevy["date"].max()
    recent_2w = hevy[hevy["date"] >= latest - pd.Timedelta(days=13)].copy()
    previous_2w = hevy[(hevy["date"] < latest - pd.Timedelta(days=13)) & (hevy["date"] >= latest - pd.Timedelta(days=27))].copy()
    recent_4w = hevy[hevy["date"] >= latest - pd.Timedelta(days=27)].copy()
    previous_4w = hevy[(hevy["date"] < latest - pd.Timedelta(days=27)) & (hevy["date"] >= latest - pd.Timedelta(days=55))].copy()

    drivers_2w = _compare_exercise_windows(recent_2w, previous_2w)
    drivers_4w = _compare_exercise_windows(recent_4w, previous_4w)
    primary_drivers = drivers_2w if len(drivers_2w) >= 2 else drivers_4w
    if len(primary_drivers) < 2:
        return {
            **_performance_empty("Need at least two comparable exercises across recent and previous Hevy windows."),
            "windows": {
                "recent_2w": _window_summary(recent_2w),
                "previous_2w": _window_summary(previous_2w),
                "recent_4w": _window_summary(recent_4w),
                "previous_4w": _window_summary(previous_4w),
            },
        }

    declining = [driver for driver in primary_drivers if driver["signal"] == "declining"]
    improving = [driver for driver in primary_drivers if driver["signal"] == "improving"]
    stable = [driver for driver in primary_drivers if driver["signal"] == "stable"]
    label = "stable"
    if len(declining) >= 2 and len(declining) > len(improving):
        label = "declining"
    elif len(improving) >= 2 and len(improving) > len(declining):
        label = "improving"

    recent_volume = float(recent_2w["volume"].sum())
    previous_volume = float(previous_2w["volume"].sum())
    volume_change = _percent_change(recent_volume, previous_volume) if previous_volume > 0 else None
    if label in {"declining", "stable"} and volume_change is not None and volume_change >= 20 and len(declining) >= 1:
        label = "fatigue/performance stagnation"

    comparable_count = len(primary_drivers)
    confidence = "high" if comparable_count >= 5 and (len(recent_2w) > 0 and len(previous_2w) > 0) else "medium"

    if label == "declining":
        summary = f"{len(declining)} comparable exercises are down versus recent Hevy history."
        recommendation = "If weight gain is also slow, add a small carb-focused calorie bump; otherwise review fatigue, sleep, and programming."
    elif label == "fatigue/performance stagnation":
        summary = "Performance is flat/down while recent lifting volume is elevated."
        recommendation = "Prioritize recovery and carbs around training before assuming a larger surplus is needed."
    elif label == "improving":
        summary = f"{len(improving)} comparable exercises are improving versus recent Hevy history."
        recommendation = "Keep macros steady unless bodyweight gain is above the lean-bulk target."
    else:
        summary = f"Most comparable exercises are stable ({len(stable)} stable, {len(improving)} improving, {len(declining)} declining)."
        recommendation = "Keep nutrition targets steady and keep monitoring Hevy trends."

    ranked = sorted(
        primary_drivers,
        key=lambda item: (
            item["signal"] != "declining",
            item["signal"] != "improving",
            -abs(item.get("estimated_1rm_change_pct") or 0),
        ),
    )
    return {
        "label": label,
        "confidence": confidence,
        "summary": summary,
        "recommendation": recommendation,
        "drivers": ranked[:6],
        "muscle_group_drivers": _muscle_group_driver_summary(primary_drivers)[:6],
        "windows": {
            "recent_2w": _window_summary(recent_2w),
            "previous_2w": _window_summary(previous_2w),
            "recent_4w": _window_summary(recent_4w),
            "previous_4w": _window_summary(previous_4w),
        },
    }


def analyze_training_workload(training_df: pd.DataFrame, bodyweight: float = 180.0) -> dict:
    """Summarize recent Hevy lifting and Strava running workload for nutrition targets."""
    df = _prepare_training(training_df)
    if df.empty:
        return _empty_workload()
    windows = {
        str(days): {
            "hevy": _hevy_window(df, days),
            "strava": _strava_window(df, days, bodyweight),
        }
        for days in WINDOWS
    }
    current = windows["28"]
    hevy = current["hevy"]
    strava = current["strava"]
    training_calorie_demand = hevy["workouts_per_week"] * 55 + min(hevy["total_sets_per_week"], 90) * 2.5
    cardio_calorie_demand = min(strava["weekly_calories"], 900)
    weekly_minutes = hevy["workouts_per_week"] * hevy["average_session_duration_minutes"] + strava["weekly_duration_minutes"]
    recovery_score = hevy["hard_sets_per_week"] + (strava["weekly_mileage"] * 1.4)
    recovery_demand = "high" if recovery_score >= 70 or weekly_minutes >= 360 else "moderate" if recovery_score >= 35 or weekly_minutes >= 180 else "low"
    carb_adjustment = 40 if recovery_demand == "high" else 25 if recovery_demand == "moderate" else 0
    exercises = df[_source_mask(df, "hevy")]["exercise"].fillna("").astype(str)
    top_exercise = exercises.value_counts().index[0] if not exercises.empty else ""
    strength_trend = calculate_strength_trend(df, top_exercise).get("label", "insufficient data") if top_exercise else "insufficient data"
    muscle_trends = calculate_muscle_group_trend(df, "12w").get("summary", [])
    performance_signal = analyze_hevy_performance_signal(df)
    return {
        "windows": windows,
        "current": {
            "strength_workouts_per_week": hevy["workouts_per_week"],
            "runs_per_week": strava["runs_per_week"],
            "weekly_mileage": strava["weekly_mileage"],
            "weekly_training_minutes": round(weekly_minutes, 1),
            "training_calorie_demand": round(training_calorie_demand, 0),
            "cardio_calorie_demand": round(cardio_calorie_demand, 0),
            "recovery_demand": recovery_demand,
            "carb_adjustment_grams": carb_adjustment,
            "calorie_adjustment": round((training_calorie_demand + cardio_calorie_demand) / 7, 0),
            "strength_trend": strength_trend,
            "performance_signal": performance_signal,
            "muscle_group_trends": {item["muscle_group"]: item.get("strength_change_pct", 0) for item in muscle_trends[:8]},
        },
    }
