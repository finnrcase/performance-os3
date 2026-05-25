"""Personal response learning from local health/performance history."""

from __future__ import annotations

import pandas as pd

from src.analytics.recovery_engine import calculate_recovery_score
from src.analytics.strength_trends import calculate_estimated_1rm
from src.body_metrics import canonical_daily_bodyweights


def _empty(status: str = "insufficient data", reason: str = "Keep logging nutrition, training, bodyweight, and recovery to unlock personal response insights.") -> dict:
    return {
        "status": status,
        "confidence": "low",
        "summary": reason,
        "window": "last 8 weeks",
        "data_points": 0,
        "insights": [],
    }


def _date_week(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "date" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"])
    if out.empty:
        return out
    out["week"] = out["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
    return out


def _note_number(note: str, key: str) -> float:
    marker = f"{key}="
    if marker not in str(note):
        return 0.0
    raw = str(note).split(marker, 1)[1].split("|", 1)[0].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _weekly_nutrition(nutrition_df: pd.DataFrame) -> pd.DataFrame:
    df = _date_week(nutrition_df)
    if df.empty:
        return pd.DataFrame(columns=["week", "calories", "protein", "carbs", "fat", "adherence"])
    column_map = {
        "calories": "total_calories" if "total_calories" in df.columns else "calories",
        "protein": "total_protein" if "total_protein" in df.columns else "protein",
        "carbs": "total_carbs" if "total_carbs" in df.columns else "carbs",
        "fat": "total_fat" if "total_fat" in df.columns else "fat",
        "adherence": "adherence_score" if "adherence_score" in df.columns else "",
    }
    for target, source in column_map.items():
        df[target] = pd.to_numeric(df.get(source, 0), errors="coerce") if source else pd.NA
    return (
        df.groupby("week", as_index=False)
        .agg(
            calories=("calories", "mean"),
            protein=("protein", "mean"),
            carbs=("carbs", "mean"),
            fat=("fat", "mean"),
            adherence=("adherence", "mean"),
        )
        .round(2)
    )


def _weekly_bodyweight(body_df: pd.DataFrame) -> pd.DataFrame:
    df = _date_week(canonical_daily_bodyweights(body_df))
    if df.empty or "bodyweight" not in df.columns:
        return pd.DataFrame(columns=["week", "bodyweight", "weekly_gain_lb"])
    df["bodyweight"] = pd.to_numeric(df["bodyweight"], errors="coerce")
    weekly = df.dropna(subset=["bodyweight"]).groupby("week", as_index=False).agg(bodyweight=("bodyweight", "mean")).sort_values("week")
    weekly["weekly_gain_lb"] = weekly["bodyweight"].diff()
    return weekly.round(2)


def _weekly_training(training_df: pd.DataFrame) -> pd.DataFrame:
    df = _date_week(training_df)
    if df.empty:
        return pd.DataFrame(columns=["week", "strength_index", "strength_volume", "runs", "miles", "pace"])
    for column in ["sets", "reps", "weight", "duration_minutes"]:
        values = df[column] if column in df.columns else pd.Series(0, index=df.index)
        df[column] = pd.to_numeric(values, errors="coerce").fillna(0)
    df["workout_type"] = df["workout_type"].fillna("").astype(str) if "workout_type" in df.columns else ""
    df["source"] = df["source"].fillna("").astype(str) if "source" in df.columns else ""
    df["notes"] = df["notes"].fillna("").astype(str) if "notes" in df.columns else ""
    df["exercise"] = df["exercise"].fillna("").astype(str) if "exercise" in df.columns else ""

    strength = df[(df["workout_type"].str.lower() == "strength") & (df["reps"] > 0) & (df["weight"] > 0)].copy()
    if not strength.empty:
        strength["volume"] = strength["sets"] * strength["reps"] * strength["weight"]
        strength["estimated_1rm"] = strength.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
        weekly_exercise = strength.groupby(["week", "exercise"], as_index=False).agg(estimated_1rm=("estimated_1rm", "max"), volume=("volume", "sum"))
        baselines = weekly_exercise.groupby("exercise")["estimated_1rm"].transform(lambda values: values.head(2).mean())
        weekly_exercise["strength_index"] = (weekly_exercise["estimated_1rm"] / baselines.replace(0, pd.NA)) * 100
        strength_weekly = weekly_exercise.groupby("week", as_index=False).agg(strength_index=("strength_index", "mean"), strength_volume=("volume", "sum"))
    else:
        strength_weekly = pd.DataFrame(columns=["week", "strength_index", "strength_volume"])

    runs = df[(df["workout_type"].str.lower() == "run") | (df["source"].str.lower() == "strava")].copy()
    if not runs.empty:
        runs["miles"] = runs["notes"].apply(lambda note: _note_number(note, "distance_miles"))
        runs["pace"] = runs["notes"].apply(lambda note: _note_number(note, "pace_min_per_mile")).replace(0, pd.NA)
        run_weekly = runs.groupby("week", as_index=False).agg(runs=("workout_id", "nunique"), miles=("miles", "sum"), pace=("pace", "mean"))
    else:
        run_weekly = pd.DataFrame(columns=["week", "runs", "miles", "pace"])

    weekly = pd.merge(strength_weekly, run_weekly, on="week", how="outer")
    for column in ["strength_index", "strength_volume", "runs", "miles", "pace"]:
        if column not in weekly.columns:
            weekly[column] = pd.NA
    return weekly.sort_values("week").round(2)


def _weekly_sleep(sleep_df: pd.DataFrame, recovery_df: pd.DataFrame) -> pd.DataFrame:
    df = _date_week(sleep_df)
    if not df.empty and "durationMinutes" in df.columns:
        df["sleep_hours"] = pd.to_numeric(df["durationMinutes"], errors="coerce") / 60
        df["hrv"] = pd.to_numeric(df.get("hrv"), errors="coerce")
        return df.groupby("week", as_index=False).agg(sleep_hours=("sleep_hours", "mean"), hrv=("hrv", "mean")).round(2)
    recovery = _date_week(recovery_df)
    if recovery.empty:
        return pd.DataFrame(columns=["week", "sleep_hours", "hrv"])
    recovery["sleep_hours"] = pd.to_numeric(recovery.get("sleep_hours"), errors="coerce")
    recovery["hrv"] = pd.to_numeric(recovery.get("hrv"), errors="coerce")
    return recovery.groupby("week", as_index=False).agg(sleep_hours=("sleep_hours", "mean"), hrv=("hrv", "mean")).round(2)


def _weekly_recovery(recovery_df: pd.DataFrame, training_df: pd.DataFrame, nutrition_df: pd.DataFrame, target_calories: float) -> pd.DataFrame:
    nutrition_for_recovery = nutrition_df.copy() if nutrition_df is not None else pd.DataFrame()
    if not nutrition_for_recovery.empty and "calories" not in nutrition_for_recovery.columns and "total_calories" in nutrition_for_recovery.columns:
        nutrition_for_recovery["calories"] = nutrition_for_recovery["total_calories"]
    analytics = calculate_recovery_score(recovery_df, training_df=training_df, nutrition_df=nutrition_for_recovery, target_calories=target_calories)
    df = _date_week(analytics)
    if df.empty:
        return pd.DataFrame(columns=["week", "recovery_score", "sleep_debt", "fatigue_load"])
    for column in ["recovery_score", "sleep_debt", "fatigue_load"]:
        df[column] = pd.to_numeric(df.get(column), errors="coerce")
    return df.groupby("week", as_index=False).agg(recovery_score=("recovery_score", "mean"), sleep_debt=("sleep_debt", "mean"), fatigue_load=("fatigue_load", "mean")).round(2)


def _corr(df: pd.DataFrame, x: str, y: str) -> float | None:
    if x not in df.columns or y not in df.columns:
        return None
    pairs = df[[x, y]].dropna()
    if len(pairs) < 5 or pairs[x].nunique() < 2 or pairs[y].nunique() < 2:
        return None
    value = pairs[x].corr(pairs[y])
    if pd.isna(value):
        return None
    return float(value)


def _confidence(weeks: int, corr_value: float | None) -> str:
    if corr_value is None:
        return "low"
    if weeks >= 10 and abs(corr_value) >= 0.5:
        return "high"
    if weeks >= 6 and abs(corr_value) >= 0.35:
        return "medium"
    return "low"


def _insight(title: str, explanation: str, confidence: str, window: str, impact: float) -> dict:
    return {
        "title": title,
        "explanation": explanation,
        "confidence": confidence,
        "window": window,
        "impact": round(float(impact), 3),
    }


def generate_personal_response_learning(
    body_metrics_df: pd.DataFrame,
    nutrition_df: pd.DataFrame,
    training_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    sleep_df: pd.DataFrame | None = None,
    current_targets: dict | None = None,
    window_weeks: int = 8,
) -> dict:
    """Generate conservative, correlation-style personal response insights."""
    target_calories = float((current_targets or {}).get("target_calories") or 0)
    if target_calories <= 0 and nutrition_df is not None and not nutrition_df.empty and "target_calories" in nutrition_df.columns:
        target_values = pd.to_numeric(nutrition_df["target_calories"], errors="coerce").dropna()
        target_calories = float(target_values.tail(14).mean()) if not target_values.empty else 0
    weekly = _weekly_nutrition(nutrition_df)
    for frame in [
        _weekly_bodyweight(body_metrics_df),
        _weekly_training(training_df),
        _weekly_sleep(sleep_df if sleep_df is not None else pd.DataFrame(), recovery_df),
        _weekly_recovery(recovery_df, training_df, nutrition_df, target_calories),
    ]:
        weekly = pd.merge(weekly, frame, on="week", how="outer") if not weekly.empty else frame
    if weekly.empty:
        return _empty()
    weekly = weekly.sort_values("week").tail(window_weeks).reset_index(drop=True)
    weeks = int(len(weekly))
    window = f"last {min(window_weeks, max(weeks, 1))} weeks"
    if weeks < 4:
        return {**_empty("learning", "Learning from your history. More weekly data is needed before pattern detection is useful."), "data_points": weeks, "window": window}

    insights = []
    carb_strength_corr = _corr(weekly, "carbs", "strength_index")
    if carb_strength_corr is not None and carb_strength_corr >= 0.35:
        threshold = weekly["carbs"].dropna().median()
        high = weekly[weekly["carbs"] >= threshold]["strength_index"].mean()
        low = weekly[weekly["carbs"] < threshold]["strength_index"].mean()
        if pd.notna(high) and pd.notna(low) and high > low:
            insights.append(
                _insight(
                    "Carbs and lifting response",
                    f"Your stronger lifting weeks tend to happen when carbs average above {threshold:.0f}g/day. This is a correlation, not a guarantee.",
                    _confidence(weeks, carb_strength_corr),
                    window,
                    carb_strength_corr,
                )
            )

    sleep_strength_corr = _corr(weekly, "sleep_hours", "strength_index")
    sleep_recovery_corr = _corr(weekly, "sleep_hours", "recovery_score")
    sleep_corr = sleep_strength_corr if sleep_strength_corr is not None else sleep_recovery_corr
    if sleep_corr is not None and sleep_corr >= 0.35:
        low_sleep = weekly[weekly["sleep_hours"] < 7]
        if len(low_sleep) >= 2:
            insights.append(
                _insight(
                    "Sleep sensitivity",
                    "Weeks with sleep under 7 hours tend to line up with weaker performance or recovery signals.",
                    _confidence(weeks, sleep_corr),
                    window,
                    sleep_corr,
                )
            )

    running_strength_corr = _corr(weekly, "miles", "strength_index")
    if running_strength_corr is not None and running_strength_corr <= -0.35:
        mileage = weekly["miles"].dropna().quantile(0.75)
        insights.append(
            _insight(
                "Running load interference watch",
                f"Runs above about {mileage:.0f} miles/week may coincide with softer lifting weeks. Treat this as a fatigue flag, not proof.",
                _confidence(weeks, running_strength_corr),
                window,
                abs(running_strength_corr),
            )
        )

    fat_recovery_corr = _corr(weekly, "fat", "recovery_score")
    if fat_recovery_corr is not None and fat_recovery_corr >= 0.35:
        fat_threshold = weekly["fat"].dropna().median()
        insights.append(
            _insight(
                "Fat intake and recovery",
                f"Recovery has tended to look better when fat averages near or above {fat_threshold:.0f}g/day.",
                _confidence(weeks, fat_recovery_corr),
                window,
                fat_recovery_corr,
            )
        )

    gain_strength_corr = _corr(weekly, "weekly_gain_lb", "strength_index")
    if gain_strength_corr is not None and gain_strength_corr <= 0.15 and weekly["weekly_gain_lb"].dropna().max() >= 0.6:
        insights.append(
            _insight(
                "Surplus efficiency",
                "Higher-gain weeks have not clearly produced better strength signals yet, so the conservative lean-bulk pace still looks appropriate.",
                _confidence(weeks, gain_strength_corr),
                window,
                abs(gain_strength_corr),
            )
        )

    insights = sorted(insights, key=lambda item: ({"high": 0, "medium": 1, "low": 2}.get(item["confidence"], 3), -item["impact"]))[:3]
    if not insights:
        return {
            "status": "learning",
            "confidence": "low",
            "summary": "Learning from your history. No strong personal pattern is clear enough to show yet.",
            "window": window,
            "data_points": weeks,
            "insights": [],
        }
    overall_confidence = "high" if any(item["confidence"] == "high" for item in insights) else "medium" if any(item["confidence"] == "medium" for item in insights) else "low"
    return {
        "status": "ready",
        "confidence": overall_confidence,
        "summary": "Personal response patterns are based on your logged history and should be treated as conservative correlations.",
        "window": window,
        "data_points": weeks,
        "insights": insights,
    }
