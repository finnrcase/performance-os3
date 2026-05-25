"""Workout nutrition marker helpers.

Markers are intentionally lightweight dividers in the same-day food logging
sequence. Foods logged before a marker are pre-workout, foods logged after are
post-workout, and rows without stable ordering stay in unknown timing.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timezone
from uuid import uuid4

import numpy as np
import pandas as pd

from src.paths import processed_data_path


WORKOUT_MARKER_COLUMNS = [
    "marker_id",
    "date",
    "marker_sequence",
    "created_order",
    "workout_time",
    "workout_type",
    "notes",
    "created_at",
]
WORKOUT_MARKERS_PATH = processed_data_path("workout_markers.csv")

MACRO_COLUMNS = ["calories", "carbs", "protein", "fat"]
WINDOW_COLUMNS = [
    "marker_id",
    "date",
    "marker_sequence",
    "workout_time",
    "workout_type",
    "notes",
    "pre_workout_calories",
    "pre_workout_carbs",
    "pre_workout_protein",
    "pre_workout_fat",
    "pre_workout_close_fat",
    "post_workout_calories",
    "post_workout_carbs",
    "post_workout_protein",
    "post_workout_fat",
    "unknown_timing_calories",
    "unknown_timing_carbs",
    "unknown_timing_protein",
    "unknown_timing_fat",
    "total_same_day_calories",
    "total_same_day_carbs",
    "total_same_day_protein",
    "total_same_day_fat",
    "linked_training_session",
    "training_volume",
    "avg_rpe",
    "estimated_workout_quality",
]


def _empty_workout_markers() -> pd.DataFrame:
    return pd.DataFrame(columns=WORKOUT_MARKER_COLUMNS)


def _empty_workout_windows() -> pd.DataFrame:
    return pd.DataFrame(columns=WINDOW_COLUMNS)


def _stable_text(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return "" if text.lower() in {"", "nan", "none", "<na>", "nat"} else text


def _normalize_date(value) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date_type):
        return value.isoformat()
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return _stable_text(value)
    return parsed.date().isoformat()


def _normalize_time(value) -> str:
    if isinstance(value, time):
        return value.strftime("%H:%M")
    text = _stable_text(value)
    if not text:
        return ""
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text[:5]
    return parsed.strftime("%H:%M")


def _sequence_value(row: pd.Series | dict, *keys: str) -> float | None:
    for key in keys:
        value = row.get(key)
        parsed = pd.to_numeric(value, errors="coerce")
        if pd.isna(parsed):
            continue
        return float(parsed)
    return None


def _normalize_workout_markers(markers_df: pd.DataFrame | None) -> pd.DataFrame:
    df = markers_df.copy() if markers_df is not None else _empty_workout_markers()
    for column in WORKOUT_MARKER_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    df = df[WORKOUT_MARKER_COLUMNS].copy()
    df["marker_id"] = df["marker_id"].fillna("").astype(str)
    missing_ids = df["marker_id"].str.strip().isin(["", "nan", "None", "<NA>"])
    if missing_ids.any():
        df.loc[missing_ids, "marker_id"] = [str(uuid4()) for _ in range(int(missing_ids.sum()))]
    df["date"] = df["date"].apply(_normalize_date)
    for column in ("marker_sequence", "created_order"):
        df[column] = pd.to_numeric(df[column], errors="coerce")
    missing_marker_sequence = df["marker_sequence"].isna() & df["created_order"].notna()
    df.loc[missing_marker_sequence, "marker_sequence"] = df.loc[missing_marker_sequence, "created_order"]
    missing_created_order = df["created_order"].isna() & df["marker_sequence"].notna()
    df.loc[missing_created_order, "created_order"] = df.loc[missing_created_order, "marker_sequence"]
    df["workout_time"] = df["workout_time"].apply(_normalize_time)
    df["workout_type"] = df["workout_type"].fillna("Workout").astype(str).str.strip().replace("", "Workout")
    df["notes"] = df["notes"].fillna("").astype(str)
    df["created_at"] = df["created_at"].fillna("").astype(str)
    return df.sort_values(["date", "marker_sequence", "created_at", "workout_time"], kind="stable").reset_index(drop=True)


def load_workout_markers() -> pd.DataFrame:
    """Load workout markers from the local processed dataset."""
    if not WORKOUT_MARKERS_PATH.exists():
        return _empty_workout_markers()
    try:
        markers_df = pd.read_csv(WORKOUT_MARKERS_PATH)
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return _empty_workout_markers()
    return _normalize_workout_markers(markers_df)


def save_workout_markers(markers_df: pd.DataFrame | None) -> None:
    """Save workout markers without changing any food or training rows."""
    WORKOUT_MARKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _normalize_workout_markers(markers_df).to_csv(WORKOUT_MARKERS_PATH, index=False)


def create_workout_marker(
    date,
    workout_time,
    workout_type: str = "Workout",
    notes: str = "",
    marker_sequence: float | int | None = None,
) -> dict:
    """Persist one workout marker and return the created marker record."""
    markers_df = load_workout_markers()
    if marker_sequence is None and not markers_df.empty:
        existing = pd.to_numeric(markers_df.get("marker_sequence"), errors="coerce").dropna()
        marker_sequence = float(existing.max() + 1) if not existing.empty else np.nan
    marker = {
        "marker_id": str(uuid4()),
        "date": _normalize_date(date),
        "marker_sequence": np.nan if marker_sequence is None else marker_sequence,
        "created_order": np.nan if marker_sequence is None else marker_sequence,
        "workout_time": _normalize_time(workout_time),
        "workout_type": str(workout_type or "Workout").strip() or "Workout",
        "notes": str(notes or "").strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    markers_df = pd.concat([markers_df, pd.DataFrame([marker])], ignore_index=True)
    save_workout_markers(markers_df)
    return marker


def _sum_macros(df: pd.DataFrame | None, prefix: str = "") -> dict[str, float]:
    totals = {}
    if df is None or df.empty:
        for column in MACRO_COLUMNS:
            totals[f"{prefix}{column}"] = 0.0
        return totals
    for column in MACRO_COLUMNS:
        values = pd.to_numeric(df[column], errors="coerce").fillna(0) if column in df.columns else pd.Series(dtype=float)
        totals[f"{prefix}{column}"] = round(float(values.sum()), 1)
    return totals


def _training_summary_for_date(training_df: pd.DataFrame | None, marker_date: str) -> dict:
    if training_df is None or training_df.empty or "date" not in training_df.columns:
        return {
            "linked_training_session": "",
            "training_volume": 0.0,
            "avg_rpe": 0.0,
            "estimated_workout_quality": "Unknown",
        }

    daily = training_df[training_df["date"].astype(str) == str(marker_date)].copy()
    if daily.empty:
        return {
            "linked_training_session": "",
            "training_volume": 0.0,
            "avg_rpe": 0.0,
            "estimated_workout_quality": "Unknown",
        }

    for column in ("sets", "reps", "weight", "rpe"):
        if column not in daily.columns:
            daily[column] = 0
        daily[column] = pd.to_numeric(daily[column], errors="coerce").fillna(0)
    daily["volume"] = daily["sets"] * daily["reps"] * daily["weight"]
    volume = round(float(daily["volume"].sum()), 1)
    rpe_values = daily.loc[daily["rpe"] > 0, "rpe"]
    avg_rpe = round(float(rpe_values.mean()), 1) if not rpe_values.empty else 0.0
    workout_types = []
    for column in ("workout_type", "muscle_group", "exercise"):
        if column in daily.columns:
            workout_types = [value for value in daily[column].fillna("").astype(str).str.strip().unique().tolist() if value]
            if workout_types:
                break
    session_label = ", ".join(workout_types[:3])
    if volume >= 12000 or avg_rpe >= 8:
        quality = "High stress"
    elif volume > 0 or avg_rpe > 0:
        quality = "Moderate"
    else:
        quality = "Logged"
    return {
        "linked_training_session": session_label,
        "training_volume": volume,
        "avg_rpe": avg_rpe,
        "estimated_workout_quality": quality,
    }


def calculate_workout_nutrition_windows(
    nutrition_df: pd.DataFrame | None,
    training_df: pd.DataFrame | None,
    markers_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """Calculate pre/post workout nutrition windows from additive marker rows."""
    markers = _normalize_workout_markers(markers_df)
    if markers.empty:
        return _empty_workout_windows()

    nutrition = nutrition_df.copy() if nutrition_df is not None else pd.DataFrame()
    for column in ["date", *MACRO_COLUMNS, "logged_sequence", "created_order", "created_at", "updated_at"]:
        if column not in nutrition.columns:
            nutrition[column] = pd.NA
    nutrition["date"] = nutrition["date"].apply(_normalize_date)
    for column in ("logged_sequence", "created_order"):
        nutrition[column] = pd.to_numeric(nutrition[column], errors="coerce")
    missing_logged_sequence = nutrition["logged_sequence"].isna() & nutrition["created_order"].notna()
    nutrition.loc[missing_logged_sequence, "logged_sequence"] = nutrition.loc[missing_logged_sequence, "created_order"]
    missing_created_order = nutrition["created_order"].isna() & nutrition["logged_sequence"].notna()
    nutrition.loc[missing_created_order, "created_order"] = nutrition.loc[missing_created_order, "logged_sequence"]

    rows = []
    markers_by_day = {
        marker_date: day_markers.reset_index(drop=True)
        for marker_date, day_markers in markers.groupby(markers["date"].astype(str), sort=False)
    }
    for _, marker in markers.iterrows():
        marker_date = _normalize_date(marker.get("date"))
        marker_sequence = _sequence_value(marker, "marker_sequence", "created_order")
        daily_nutrition = nutrition[nutrition["date"].astype(str) == marker_date].copy()
        day_markers = markers_by_day.get(marker_date, pd.DataFrame())
        marker_sequences = [
            value
            for value in (_sequence_value(other, "marker_sequence", "created_order") for _, other in day_markers.iterrows())
            if value is not None
        ]
        previous_marker_sequence = max([value for value in marker_sequences if marker_sequence is not None and value < marker_sequence], default=None)
        next_marker_sequence = min([value for value in marker_sequences if marker_sequence is not None and value > marker_sequence], default=None)
        pre_rows = []
        post_rows = []
        unknown_rows = []
        pre_close_fat = 0.0
        if marker_sequence is None:
            unknown_rows = daily_nutrition.to_dict(orient="records")
        else:
            for _, food in daily_nutrition.iterrows():
                food_sequence = _sequence_value(food, "logged_sequence", "created_order")
                if food_sequence is None:
                    unknown_rows.append(food.to_dict())
                elif previous_marker_sequence is not None and food_sequence <= previous_marker_sequence:
                    continue
                elif next_marker_sequence is not None and food_sequence >= next_marker_sequence:
                    continue
                elif food_sequence < marker_sequence:
                    pre_rows.append(food.to_dict())
                elif food_sequence > marker_sequence:
                    post_rows.append(food.to_dict())
                else:
                    unknown_rows.append(food.to_dict())

        pre_df = pd.DataFrame(pre_rows)
        post_df = pd.DataFrame(post_rows)
        unknown_df = pd.DataFrame(unknown_rows)
        total = _sum_macros(daily_nutrition, "total_same_day_")
        training_summary = _training_summary_for_date(training_df, marker_date)
        rows.append(
            {
                "marker_id": marker.get("marker_id", ""),
                "date": marker_date,
                "marker_sequence": marker_sequence,
                "workout_time": _normalize_time(marker.get("workout_time")),
                "workout_type": marker.get("workout_type", "Workout"),
                "notes": marker.get("notes", ""),
                **_sum_macros(pre_df, "pre_workout_"),
                "pre_workout_close_fat": round(pre_close_fat, 1),
                **_sum_macros(post_df, "post_workout_"),
                **_sum_macros(unknown_df, "unknown_timing_"),
                **total,
                **training_summary,
            }
        )

    windows_df = pd.DataFrame(rows)
    for column in WINDOW_COLUMNS:
        if column not in windows_df.columns:
            windows_df[column] = np.nan
    return windows_df[WINDOW_COLUMNS].sort_values(["date", "marker_sequence", "workout_time"], kind="stable").reset_index(drop=True)


def _recovery_scores(recovery_df: pd.DataFrame | None) -> pd.DataFrame:
    if recovery_df is None or recovery_df.empty or "date" not in recovery_df.columns:
        return pd.DataFrame(columns=["date", "recovery_score"])
    df = recovery_df.copy()
    if "recovery_score" in df.columns:
        df["recovery_score"] = pd.to_numeric(df["recovery_score"], errors="coerce")
    else:
        def row_score(row) -> float:
            sleep = pd.to_numeric(row.get("sleep_hours"), errors="coerce")
            sleep_quality = pd.to_numeric(row.get("sleep_quality"), errors="coerce")
            fatigue = pd.to_numeric(row.get("fatigue"), errors="coerce")
            soreness = pd.to_numeric(row.get("soreness"), errors="coerce")
            stress = pd.to_numeric(row.get("stress"), errors="coerce")
            motivation = pd.to_numeric(row.get("motivation"), errors="coerce")
            parts = [
                min(float(sleep) / 8, 1) if not pd.isna(sleep) else 0,
                min(float(sleep_quality) / 10, 1) if not pd.isna(sleep_quality) else 0,
                max((10 - float(fatigue) + 1) / 10, 0) if not pd.isna(fatigue) else 0,
                max((10 - float(soreness) + 1) / 10, 0) if not pd.isna(soreness) else 0,
                max((10 - float(stress) + 1) / 10, 0) if not pd.isna(stress) else 0,
                min(float(motivation) / 10, 1) if not pd.isna(motivation) else 0,
            ]
            return round(float(np.mean(parts) * 100), 1)

        df["recovery_score"] = df.apply(row_score, axis=1)
    df["date"] = df["date"].apply(_normalize_date)
    return df[["date", "recovery_score"]].dropna(subset=["recovery_score"]).sort_values("date").reset_index(drop=True)


def generate_workout_fueling_recommendations(
    windows_df: pd.DataFrame | None,
    recovery_df: pd.DataFrame | None = None,
) -> dict:
    """Generate deterministic fueling and deload signals from marker windows."""
    if windows_df is None or windows_df.empty:
        return {
            "status": "empty",
            "deload_status": "Normal",
            "pre_workout_carb_suggestion": "Add a workout marker to split food into pre- and post-workout windows.",
            "post_workout_recovery_suggestion": "No workout nutrition marker data yet.",
            "recovery_signal": "No marker data yet.",
            "recent_improvement_signal": "No trend yet.",
            "diagnostics": {"marker_count": 0},
        }

    windows = windows_df.copy()
    for column in [
        "pre_workout_carbs",
        "pre_workout_fat",
        "pre_workout_close_fat",
        "post_workout_protein",
        "total_same_day_carbs",
        "training_volume",
        "avg_rpe",
    ]:
        if column not in windows.columns:
            windows[column] = 0
        windows[column] = pd.to_numeric(windows[column], errors="coerce").fillna(0)
    sort_columns = ["date", "marker_sequence"] if "marker_sequence" in windows.columns else ["date", "workout_time"]
    windows = windows.sort_values(sort_columns, kind="stable").reset_index(drop=True)
    latest = windows.iloc[-1]
    latest_high_stress = latest["training_volume"] >= 12000 or latest["avg_rpe"] >= 8

    if latest_high_stress and latest["pre_workout_carbs"] < 40:
        pre_suggestion = "Pre-workout carbs look low for a harder session. Try 40-60g carbs before similar workouts."
    elif latest["pre_workout_carbs"] < 20:
        pre_suggestion = "Pre-workout carbs are light. Add a simple carb source if the next workout feels flat."
    else:
        pre_suggestion = "Pre-workout carbs look adequate."

    close_fat = latest["pre_workout_close_fat"] if "pre_workout_close_fat" in latest.index and latest["pre_workout_close_fat"] > 0 else latest["pre_workout_fat"]
    if close_fat >= 25:
        pre_suggestion = f"{pre_suggestion} Pre-workout fat was {close_fat:.0f}g close to training, which may slow digestion."

    if latest["post_workout_protein"] < 30:
        post_suggestion = "Post-workout protein is under 30g. Add a protein feeding after training."
    else:
        post_suggestion = "Post-workout protein looks recovery-supportive."

    recent = windows.tail(5).copy()
    high_stress_count = int(((recent["training_volume"] >= 12000) | (recent["avg_rpe"] >= 8)).sum())
    low_carb_count = int((recent["pre_workout_carbs"] < 40).sum())
    recovery_scores = _recovery_scores(recovery_df)
    poor_recent_recovery = False
    recovery_declining = False
    if not recovery_scores.empty:
        recovery_recent = recovery_scores.tail(5)
        poor_recent_recovery = bool((recovery_recent["recovery_score"] < 65).sum() >= 2)
        if len(recovery_recent) >= 3:
            recovery_declining = bool(float(recovery_recent["recovery_score"].iloc[-1]) < float(recovery_recent["recovery_score"].iloc[0]) - 5)

    if high_stress_count >= 3 and recovery_declining:
        deload_status = "Deload Suggested"
        recovery_signal = "Training stress has been high while recovery is declining."
    elif (high_stress_count >= 2 and poor_recent_recovery) or (poor_recent_recovery and low_carb_count >= 2):
        deload_status = "Monitor"
        recovery_signal = "Fueling may be limiting recovery. Watch carbs and recovery over the next few sessions."
    else:
        deload_status = "Normal"
        recovery_signal = "No deload signal from current marker data."

    if high_stress_count >= 2 and poor_recent_recovery and low_carb_count >= 2:
        recovery_signal = "Repeated poor recovery with high training load and low carbs suggests fueling may be limiting recovery."

    if len(windows) >= 2:
        previous = windows.iloc[:-1].tail(4)
        previous_carbs = float(previous["pre_workout_carbs"].mean()) if not previous.empty else 0
        previous_volume = float(previous["training_volume"].mean()) if not previous.empty else 0
        recovery_improved = False
        if len(recovery_scores) >= 2:
            prior_recovery = recovery_scores.iloc[:-1].tail(4)
            prior_average = float(prior_recovery["recovery_score"].mean()) if not prior_recovery.empty else 0
            recovery_improved = bool(float(recovery_scores["recovery_score"].iloc[-1]) > prior_average + 3)
        carbs_improved = bool(latest["pre_workout_carbs"] > previous_carbs + 15)
        performance_held = bool(latest["training_volume"] >= previous_volume)
        if carbs_improved and (performance_held or recovery_improved):
            improvement_signal = "Recent pre-workout carbs improved while recovery or training output held steady or improved."
        elif recovery_improved:
            improvement_signal = "Recent recovery is improving. Keep marker data coming to connect it to fueling."
        else:
            improvement_signal = "No clear fueling improvement trend yet."
    else:
        improvement_signal = "One marker logged. Add more workouts to build a trend."

    return {
        "status": "ok",
        "deload_status": deload_status,
        "pre_workout_carb_suggestion": pre_suggestion,
        "post_workout_recovery_suggestion": post_suggestion,
        "recovery_signal": recovery_signal,
        "recent_improvement_signal": improvement_signal,
        "diagnostics": {
            "marker_count": int(len(windows)),
            "recent_high_stress_sessions": high_stress_count,
            "recent_low_carb_sessions": low_carb_count,
            "poor_recent_recovery": poor_recent_recovery,
            "recovery_declining": recovery_declining,
        },
    }
