"""High-value optimization features for the dashboard and history views.

The functions here are deterministic and conservative. They turn existing logs
into compact UI-ready signals without mutating user data.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from src.analytics.strength_trends import calculate_estimated_1rm
from src.analytics.workout_quality import calculate_workout_quality
from src.body_metrics import canonical_daily_bodyweights
from src.recovery import calculate_recovery_score
from src.training_schedule import is_run_row, load_training_schedule_profile


LOWER_BODY_TERMS = "leg|quad|hamstring|glute|calf|lower"


def _today(today: str | None = None) -> str:
    return str(today or pd.Timestamp.today().date().isoformat())


def _num(value, default: float = 0.0) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    return default if pd.isna(parsed) else float(parsed)


def _round(value, digits: int = 1):
    parsed = _num(value)
    if abs(parsed - round(parsed)) < 0.05:
        return int(round(parsed))
    return round(parsed, digits)


def _date_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty or "date" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = out.dropna(subset=["date"])
    return out.sort_values("date").reset_index(drop=True)


def _run_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)
    profile = load_training_schedule_profile()
    return df.apply(lambda row: is_run_row(row, profile=profile), axis=1)


def _note_number(note: str, key: str) -> float:
    marker = f"{key}="
    if marker not in str(note):
        return 0.0
    raw = str(note).split(marker, 1)[1].split("|", 1)[0].strip()
    return _num(raw)


def _latest_recovery(recovery_df: pd.DataFrame | None) -> dict:
    df = _date_frame(recovery_df)
    if df.empty:
        return {"score": None, "status": "unknown", "reason": "No recovery check-in available."}
    row = df.iloc[-1]
    score = calculate_recovery_score(row)
    fatigue = _num(row.get("fatigue"), 5)
    soreness = _num(row.get("soreness"), 5)
    stress = _num(row.get("stress"), 5)
    if score < 45 or fatigue >= 8 or stress >= 8:
        status = "high fatigue"
    elif score >= 75 and fatigue <= 4:
        status = "ready"
    else:
        status = "normal"
    return {
        "score": round(float(score), 1),
        "status": status,
        "reason": f"Latest recovery score is {score:.0f}/100.",
        "fatigue": fatigue,
        "soreness": soreness,
    }


def _target_snapshot(targets: dict | None) -> dict:
    targets = targets or {}
    return {
        "calories": int(round(_num(targets.get("target_calories")))),
        "protein": int(round(_num(targets.get("protein_grams")))),
        "carbs": int(round(_num(targets.get("carb_grams")))),
        "fat": int(round(_num(targets.get("fat_grams")))),
    }


def _same_weekday_plan(training_df: pd.DataFrame, today_key: str) -> tuple[str, list[str]]:
    df = _date_frame(training_df)
    if df.empty:
        return "", []
    today_dt = pd.to_datetime(today_key)
    lookback = df[(df["date"] < today_dt) & (df["date"] >= today_dt - pd.Timedelta(days=56))].copy()
    if lookback.empty:
        return "", []
    same_weekday = lookback[lookback["date"].dt.weekday == today_dt.weekday()].copy()
    if same_weekday.empty or same_weekday["date"].dt.date.nunique() < 2:
        return "", []
    run_rows = same_weekday[_run_mask(same_weekday)]
    strength_rows = same_weekday[~_run_mask(same_weekday)]
    if not run_rows.empty and strength_rows.empty:
        return "Run/cardio-focused day", ["Recent same-weekday history is usually running/cardio."]
    muscle_values = strength_rows.get("muscle_group", pd.Series("", index=strength_rows.index)).fillna("").astype(str).str.lower()
    exercise_values = strength_rows.get("exercise", pd.Series("", index=strength_rows.index)).fillna("").astype(str).str.lower()
    if muscle_values.str.contains(LOWER_BODY_TERMS, regex=True, na=False).any() or exercise_values.str.contains(LOWER_BODY_TERMS, regex=True, na=False).any():
        return "Leg day", ["Recent same-weekday history suggests lower-body training."]
    if len(strength_rows):
        return "Moderate lifting day", ["Recent same-weekday history suggests lifting."]
    return "", []


def training_day_macros(
    training_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    targets: dict,
    today: str | None = None,
) -> dict:
    """Detect day type and return temporary target adjustments for today."""
    today_key = _today(today)
    baseline = _target_snapshot(targets)
    if not any(baseline.values()):
        return {
            "day_type": "Targets not configured",
            "confidence": "low",
            "reason": "Set baseline macro targets before day-type adjustments can be calculated.",
            "baseline_targets": baseline,
            "adjusted_targets": baseline,
            "delta": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
            "signals": [],
        }

    recovery = _latest_recovery(recovery_df)
    training = _date_frame(training_df)
    today_rows = training[training["date"].dt.date.astype(str) == today_key].copy() if not training.empty else pd.DataFrame()
    signals: list[str] = []

    day_type = "Recovery/rest day"
    confidence = "medium"
    if recovery["status"] == "high fatigue":
        day_type = "High fatigue day"
        signals.append(recovery["reason"])

    if not today_rows.empty:
        run_rows = today_rows[_run_mask(today_rows)]
        strength_rows = today_rows[~_run_mask(today_rows)].copy()
        for column in ["sets", "reps", "weight", "duration_minutes"]:
            strength_rows[column] = pd.to_numeric(strength_rows.get(column, 0), errors="coerce").fillna(0)
        strength_sets = float(strength_rows.get("sets", pd.Series(dtype=float)).sum())
        strength_volume = float((strength_rows.get("sets", 0) * strength_rows.get("reps", 0) * strength_rows.get("weight", 0)).sum()) if not strength_rows.empty else 0.0
        recent = training[(training["date"] < pd.to_datetime(today_key)) & (training["date"] >= pd.to_datetime(today_key) - pd.Timedelta(days=42))].copy()
        recent_strength = recent[~_run_mask(recent)].copy() if not recent.empty else pd.DataFrame()
        if not recent_strength.empty:
            for column in ["sets", "reps", "weight"]:
                recent_strength[column] = pd.to_numeric(recent_strength.get(column, 0), errors="coerce").fillna(0)
            recent_strength["volume"] = recent_strength["sets"] * recent_strength["reps"] * recent_strength["weight"]
            avg_volume = float(recent_strength.groupby(recent_strength["date"].dt.date)["volume"].sum().tail(8).mean())
        else:
            avg_volume = 0.0

        muscle_values = strength_rows.get("muscle_group", pd.Series("", index=strength_rows.index)).fillna("").astype(str).str.lower()
        exercise_values = strength_rows.get("exercise", pd.Series("", index=strength_rows.index)).fillna("").astype(str).str.lower()
        is_leg_day = muscle_values.str.contains(LOWER_BODY_TERMS, regex=True, na=False).any() or exercise_values.str.contains(LOWER_BODY_TERMS, regex=True, na=False).any()

        if recovery["status"] != "high fatigue":
            if is_leg_day:
                day_type = "Leg day"
                signals.append("Lower-body Hevy work detected.")
            elif not run_rows.empty and strength_sets < 6:
                day_type = "Run/cardio-focused day"
                signals.append("Strava run/cardio activity detected.")
            elif strength_sets >= 18 or (avg_volume > 0 and strength_volume >= avg_volume * 1.15):
                day_type = "Heavy lifting day"
                signals.append("Lifting workload is above recent baseline.")
            elif strength_sets >= 6:
                day_type = "Moderate lifting day"
                signals.append("Lifting work is logged for today.")
        confidence = "high"
    elif recovery["status"] != "high fatigue":
        planned_type, planned_signals = _same_weekday_plan(training, today_key)
        if planned_type:
            day_type = planned_type
            signals.extend(planned_signals)
            confidence = "low"
        else:
            signals.append("No Hevy or Strava workload logged for today.")
            confidence = "medium"

    adjustments = {
        "Leg day": {"carbs": 55, "calories": 220, "reason": "+55g carbs added to support lower-body recovery and performance."},
        "Heavy lifting day": {"carbs": 40, "calories": 160, "reason": "+40g carbs added for heavy lifting workload."},
        "Run/cardio-focused day": {"carbs": 40, "calories": 160, "reason": "+40g carbs added for run/cardio fuel."},
        "Moderate lifting day": {"carbs": 20, "calories": 80, "reason": "+20g carbs added for moderate lifting."},
        "Recovery/rest day": {"carbs": -25, "calories": -100, "reason": "-25g carbs on a lower workload day."},
        "High fatigue day": {"carbs": -20, "calories": -80, "reason": "Calories stay conservative while fatigue is elevated."},
    }
    adjustment = adjustments.get(day_type, {"carbs": 0, "calories": 0, "reason": "Baseline targets are unchanged."})
    adjusted = baseline.copy()
    adjusted["protein"] = baseline["protein"]
    adjusted["fat"] = max(baseline["fat"], int(round(_num(targets.get("fat_floor_grams"), baseline["fat"]))))
    adjusted["carbs"] = max(0, baseline["carbs"] + adjustment["carbs"])
    adjusted["calories"] = max(1200, baseline["calories"] + adjustment["calories"])
    if adjusted["fat"] != baseline["fat"]:
        signals.append("Fat was kept at the configured healthy floor.")

    return {
        "day_type": day_type,
        "confidence": confidence,
        "reason": f"{day_type}: {adjustment['reason']}",
        "baseline_targets": baseline,
        "adjusted_targets": adjusted,
        "delta": {
            "calories": adjusted["calories"] - baseline["calories"],
            "protein": adjusted["protein"] - baseline["protein"],
            "carbs": adjusted["carbs"] - baseline["carbs"],
            "fat": adjusted["fat"] - baseline["fat"],
        },
        "signals": signals[:4],
    }


def _strength_rows(training_df: pd.DataFrame | None) -> pd.DataFrame:
    df = _date_frame(training_df)
    if df.empty:
        return pd.DataFrame()
    df = df[~_run_mask(df)].copy()
    for column in ["sets", "reps", "weight", "rpe"]:
        df[column] = pd.to_numeric(df.get(column, 0), errors="coerce").fillna(0)
    for column in ["exercise", "muscle_group"]:
        if column not in df.columns:
            df[column] = ""
        df[column] = df[column].fillna("").astype(str)
    df = df[(df["exercise"].str.strip() != "") & (df["reps"] > 0) & (df["weight"] > 0)].copy()
    if df.empty:
        return df
    df["volume"] = df["sets"] * df["reps"] * df["weight"]
    df["estimated_1rm"] = df.apply(lambda row: calculate_estimated_1rm(row["weight"], row["reps"]), axis=1)
    return df.sort_values("date")


def plateau_detection(training_df: pd.DataFrame, today: str | None = None) -> dict:
    """Conservatively detect likely exercise and muscle-group plateaus."""
    today_dt = pd.to_datetime(_today(today))
    strength = _strength_rows(training_df)
    if strength.empty:
        return {
            "status": "learning",
            "summary": "Log more lifting history to detect plateaus.",
            "top_alerts": [],
            "details": [],
        }

    strength = strength.copy()
    strength["day"] = strength["date"].dt.date
    daily = (
        strength.groupby(["exercise", "day"], as_index=False)
        .agg(
            date=("date", "max"),
            best_estimated_1rm=("estimated_1rm", "max"),
            total_volume=("volume", "sum"),
            max_reps=("reps", "max"),
            muscle_group=("muscle_group", lambda values: next((str(value) for value in values if str(value).strip()), "")),
        )
        .sort_values("date")
    )
    alerts = []
    details = []
    for exercise, history in daily.groupby("exercise"):
        history = history.sort_values("date")
        sessions = len(history)
        if sessions < 6 or (today_dt - history["date"].max()).days > 60:
            continue
        recent = history.tail(3)
        previous = history.iloc[-6:-3]
        if len(previous) < 3 or len(recent) < 3:
            continue
        weeks = max(1, round((recent["date"].max() - previous["date"].min()).days / 7))
        strength_change = _pct_change(recent["best_estimated_1rm"].mean(), previous["best_estimated_1rm"].mean())
        volume_change = _pct_change(recent["total_volume"].mean(), previous["total_volume"].mean())
        reps_delta = float(recent["max_reps"].mean() - previous["max_reps"].mean())
        if strength_change <= -3:
            signal = "regression"
            severity = "high"
            message = f"{exercise} is trending down over {weeks} weeks."
        elif abs(strength_change) < 1.5 and weeks >= 4:
            signal = "plateau"
            severity = "medium"
            message = f"{exercise} plateau detected ({weeks} weeks)."
        elif volume_change >= 20 and strength_change < 1:
            signal = "diminishing returns"
            severity = "medium"
            message = f"{exercise} volume is up without a matching strength response."
        else:
            continue
        detail = {
            "type": "exercise",
            "name": str(exercise),
            "muscle_group": str(recent["muscle_group"].dropna().iloc[-1] or ""),
            "signal": signal,
            "severity": severity,
            "duration_weeks": weeks,
            "message": message,
            "estimated_1rm_change_pct": round(strength_change, 1),
            "volume_change_pct": round(volume_change, 1),
            "reps_at_same_weight_delta": round(reps_delta, 1),
        }
        details.append(detail)
        alerts.append(detail)

    muscle = (
        strength.groupby(["muscle_group", "day"], as_index=False)
        .agg(date=("date", "max"), strength_index=("estimated_1rm", "mean"), total_volume=("volume", "sum"))
        .sort_values("date")
    )
    for muscle_group, history in muscle.groupby("muscle_group"):
        name = str(muscle_group or "").strip()
        if not name or len(history) < 6:
            continue
        recent = history.tail(3)
        previous = history.iloc[-6:-3]
        if len(previous) < 3:
            continue
        strength_change = _pct_change(recent["strength_index"].mean(), previous["strength_index"].mean())
        volume_change = _pct_change(recent["total_volume"].mean(), previous["total_volume"].mean())
        if strength_change > -4:
            continue
        detail = {
            "type": "muscle_group",
            "name": name,
            "muscle_group": name,
            "signal": "regression",
            "severity": "medium",
            "duration_weeks": max(1, round((recent["date"].max() - previous["date"].min()).days / 7)),
            "message": f"{name} strength is trending down.",
            "estimated_1rm_change_pct": round(strength_change, 1),
            "volume_change_pct": round(volume_change, 1),
            "reps_at_same_weight_delta": None,
        }
        details.append(detail)
        alerts.append(detail)

    running_alert = _running_interference_alert(training_df, strength, today_dt)
    if running_alert:
        details.append(running_alert)
        alerts.append(running_alert)

    quality_alert = _workout_quality_alert(training_df)
    if quality_alert:
        details.append(quality_alert)
        alerts.append(quality_alert)

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    alerts = sorted(alerts, key=lambda item: (severity_rank.get(item["severity"], 3), -abs(_num(item.get("estimated_1rm_change_pct")))))[:2]
    return {
        "status": "ready" if details else "clear",
        "summary": "No conservative plateau flags are active." if not details else f"{len(details)} training trend flag(s) found.",
        "top_alerts": alerts,
        "details": details[:12],
    }


def _pct_change(current: float, previous: float) -> float:
    if previous <= 0:
        return 0.0
    return ((float(current) - float(previous)) / float(previous)) * 100


def _running_interference_alert(training_df: pd.DataFrame, strength_df: pd.DataFrame, today_dt: pd.Timestamp) -> dict | None:
    training = _date_frame(training_df)
    if training.empty or strength_df.empty:
        return None
    runs = training[_run_mask(training)].copy()
    if runs.empty:
        return None
    runs["miles"] = runs.get("notes", pd.Series("", index=runs.index)).apply(lambda note: _note_number(str(note), "distance_miles"))
    recent_miles = float(runs[runs["date"] >= today_dt - pd.Timedelta(days=13)]["miles"].sum())
    previous_miles = float(runs[(runs["date"] < today_dt - pd.Timedelta(days=13)) & (runs["date"] >= today_dt - pd.Timedelta(days=27))]["miles"].sum())
    if recent_miles < 8 or recent_miles <= previous_miles + 3:
        return None
    legs = strength_df[
        strength_df["muscle_group"].str.lower().str.contains(LOWER_BODY_TERMS, regex=True, na=False)
        | strength_df["exercise"].str.lower().str.contains(LOWER_BODY_TERMS, regex=True, na=False)
    ].copy()
    if legs["date"].dt.date.nunique() < 4:
        return None
    daily = legs.groupby(legs["date"].dt.date).agg(date=("date", "max"), strength_index=("estimated_1rm", "mean")).sort_values("date")
    recent = daily.tail(2)
    previous = daily.iloc[-5:-2]
    if len(previous) < 2:
        return None
    change = _pct_change(recent["strength_index"].mean(), previous["strength_index"].mean())
    if change > -2:
        return None
    return {
        "type": "interference",
        "name": "Leg fatigue",
        "muscle_group": "Legs",
        "signal": "fatigue",
        "severity": "medium",
        "duration_weeks": 2,
        "message": "Leg fatigue elevated from running volume.",
        "estimated_1rm_change_pct": round(change, 1),
        "volume_change_pct": None,
        "reps_at_same_weight_delta": None,
    }


def _workout_quality_alert(training_df: pd.DataFrame) -> dict | None:
    df = _date_frame(training_df)
    if df.empty:
        return None
    dates = [value.isoformat() for value in sorted(df["date"].dt.date.unique())[-8:]]
    scores = []
    for item in dates:
        score = calculate_workout_quality(training_df, item).get("score")
        if score is not None:
            scores.append({"date": item, "score": float(score)})
    if len(scores) < 6:
        return None
    recent = sum(row["score"] for row in scores[-3:]) / 3
    previous = sum(row["score"] for row in scores[-6:-3]) / 3
    if recent >= 5.5 or previous < 6.5:
        return None
    return {
        "type": "quality",
        "name": "Workout quality",
        "muscle_group": "",
        "signal": "fatigue",
        "severity": "medium",
        "duration_weeks": 2,
        "message": "Workout quality is slipping versus recent baseline.",
        "estimated_1rm_change_pct": round(((recent - previous) / previous) * 100, 1) if previous else None,
        "volume_change_pct": None,
        "reps_at_same_weight_delta": None,
    }


def macro_adherence_analysis(
    summary_df: pd.DataFrame,
    training_df: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
) -> dict:
    if summary_df is None or summary_df.empty:
        return {
            "weekly_score": None,
            "status": "learning",
            "summary": "Log meals against targets to calculate macro adherence.",
            "components": {},
            "daily": [],
            "correlations": [],
        }
    df = summary_df.copy()
    df["date"] = pd.to_datetime(df.get("date"), errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    components = {
        "calories": ("total_calories", "target_calories"),
        "protein": ("total_protein", "target_protein"),
        "carbs": ("total_carbs", "target_carbs"),
        "fat": ("total_fat", "target_fat"),
    }
    weights = {"calories": 0.35, "protein": 0.3, "carbs": 0.2, "fat": 0.15}
    daily = []
    for _, row in df.iterrows():
        score_parts = {}
        weighted_score = 0.0
        weight_total = 0.0
        for name, (actual_key, target_key) in components.items():
            target = _num(row.get(target_key), 0)
            if target <= 0:
                continue
            actual = _num(row.get(actual_key), 0)
            if name == "protein":
                deviation = max(0, target - actual) / target
                if actual > target * 1.4:
                    deviation = max(deviation, (actual - target * 1.4) / target)
            else:
                deviation = abs(actual - target) / target
            score = max(0.0, min(100.0, 100 - deviation * 100))
            score_parts[name] = round(score, 1)
            weighted_score += score * weights[name]
            weight_total += weights[name]
        if weight_total:
            daily.append(
                {
                    "date": row["date"].date().isoformat(),
                    "score": round(weighted_score / weight_total, 1),
                    **score_parts,
                }
            )
    if not daily:
        return {
            "weekly_score": None,
            "status": "no targets",
            "summary": "Saved macro targets are needed before adherence can be scored.",
            "components": {},
            "daily": [],
            "correlations": [],
        }
    recent = daily[-7:]
    weekly_score = round(sum(item["score"] for item in recent) / len(recent), 1)
    component_summary = {}
    for key in components:
        values = [item[key] for item in recent if key in item]
        component_summary[key] = round(sum(values) / len(values), 1) if values else None
    status = "excellent" if weekly_score >= 90 else "solid" if weekly_score >= 80 else "inconsistent" if weekly_score >= 65 else "needs attention"
    correlations = _adherence_correlations(daily, df, training_df, body_metrics_df)
    return {
        "weekly_score": weekly_score,
        "status": status,
        "summary": f"Weekly macro adherence is {weekly_score:.0f}/100 ({status}).",
        "components": component_summary,
        "daily": daily[-56:],
        "correlations": correlations,
    }


def _adherence_correlations(daily: list[dict], summary_df: pd.DataFrame, training_df: pd.DataFrame, body_metrics_df: pd.DataFrame) -> list[dict]:
    adherence = pd.DataFrame(daily)
    if adherence.empty:
        return []
    adherence["date"] = pd.to_datetime(adherence["date"], errors="coerce")
    adherence["week"] = adherence["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
    nutrition_weekly = adherence.groupby("week", as_index=False).agg(adherence=("score", "mean"), carbs=("carbs", "mean"), calories=("calories", "mean"))

    strength = _strength_rows(training_df)
    if not strength.empty:
        strength["week"] = strength["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        strength_weekly = strength.groupby("week", as_index=False).agg(strength_index=("estimated_1rm", "mean"), volume=("volume", "sum"))
    else:
        strength_weekly = pd.DataFrame(columns=["week", "strength_index", "volume"])

    body = _date_frame(canonical_daily_bodyweights(body_metrics_df))
    if not body.empty:
        body["bodyweight"] = pd.to_numeric(body.get("bodyweight"), errors="coerce")
        body["week"] = body["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        body_weekly = body.groupby("week", as_index=False).agg(weight=("bodyweight", "mean"))
        body_weekly["weight_gain"] = body_weekly["weight"].diff()
    else:
        body_weekly = pd.DataFrame(columns=["week", "weight_gain"])

    weekly = nutrition_weekly.merge(strength_weekly, on="week", how="left").merge(body_weekly[["week", "weight_gain"]], on="week", how="left")
    if len(weekly) < 4:
        return [{"label": "Learning", "summary": "Need at least 4 overlapping weeks for adherence correlations.", "confidence": "low"}]

    correlations = []
    for left, right, label, positive_text, negative_text in [
        ("adherence", "strength_index", "Adherence vs performance", "Performance improves when macro adherence is higher.", "Performance has not clearly improved with higher adherence yet."),
        ("carbs", "volume", "Carbs vs training volume", "Higher carb adherence lines up with stronger training volume.", "Carb adherence has not clearly tracked training volume yet."),
        ("calories", "weight_gain", "Calories vs weight gain", "Weight gain is more consistent when calorie adherence is higher.", "Weight gain consistency is not clearly tied to calorie adherence yet."),
    ]:
        corr = _corr(weekly, left, right)
        if corr is None:
            continue
        if corr >= 0.35:
            summary = positive_text
        elif corr <= -0.35:
            summary = negative_text
        else:
            summary = "No strong relationship is clear enough yet."
        correlations.append({"label": label, "summary": summary, "correlation": round(corr, 2), "confidence": "medium" if len(weekly) >= 6 else "low"})
    return correlations or [{"label": "Learning", "summary": "No strong adherence correlation is clear enough yet.", "confidence": "low"}]


def _corr(df: pd.DataFrame, left: str, right: str) -> float | None:
    if left not in df.columns or right not in df.columns:
        return None
    pair = df[[left, right]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(pair) < 4 or pair[left].std() == 0 or pair[right].std() == 0:
        return None
    value = pair[left].corr(pair[right])
    return None if pd.isna(value) else float(value)


def _numeric_column(df: pd.DataFrame, column: str) -> pd.Series:
    if df is None or df.empty or column not in df.columns:
        return pd.Series(pd.NA, index=df.index if df is not None else None, dtype="Float64")
    return pd.to_numeric(df[column], errors="coerce")


def personal_baseline_learning(
    summary_df: pd.DataFrame,
    training_df: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    sleep_df: pd.DataFrame,
    personal_learning: dict | None = None,
) -> dict:
    insights = []
    for insight in (personal_learning or {}).get("insights", []):
        insights.append(
            {
                "title": str(insight.get("title", "Personal pattern")),
                "summary": str(insight.get("explanation", "")),
                "confidence": str(insight.get("confidence", "low")),
                "metric": "correlation",
            }
        )

    weekly = _weekly_baseline_frame(summary_df, training_df, body_metrics_df, recovery_df, sleep_df)
    if len(weekly) >= 4:
        strength_values = _numeric_column(weekly, "strength_index")
        strength_history = strength_values.dropna()
        strong = pd.DataFrame()
        if len(strength_history) >= 2:
            strong_cutoff = strength_history.quantile(0.7)
            strong = weekly[strength_values >= strong_cutoff].copy()
        if len(strong) >= 2:
            carbs = _numeric_column(strong, "carbs").dropna()
            calories = _numeric_column(strong, "calories").dropna()
            sleep = _numeric_column(strong, "sleep_hours").dropna()
            miles = _numeric_column(strong, "miles").dropna()
            recovery = _numeric_column(strong, "recovery_score").dropna()
            gain = _numeric_column(strong, "weight_gain").dropna()
            confidence = "medium" if len(weekly) >= 8 else "low"
            if not carbs.empty:
                insights.append({"title": "Carb baseline", "summary": f"Your strongest training weeks average about {_round(carbs.mean(), 0)}g carbs/day.", "confidence": confidence, "metric": "carbs"})
            if not calories.empty:
                insights.append({"title": "Calorie surplus range", "summary": f"Strong weeks average about {_round(calories.mean(), 0)} kcal/day.", "confidence": confidence, "metric": "calories"})
            if not sleep.empty:
                insights.append({"title": "Sleep threshold", "summary": f"Strong weeks average {_round(sleep.mean(), 1)} hours of sleep.", "confidence": confidence, "metric": "sleep"})
            if not miles.empty and miles.max() > 0:
                insights.append({"title": "Running threshold", "summary": f"Strong weeks average {_round(miles.mean(), 1)} running miles/week.", "confidence": confidence, "metric": "mileage"})
            if not gain.empty:
                insights.append({"title": "Gain-rate baseline", "summary": f"Strong weeks average {_round(gain.mean(), 2)} lb/week bodyweight change.", "confidence": confidence, "metric": "weight_gain"})
            if not recovery.empty:
                insights.append({"title": "Recovery baseline", "summary": f"Strong weeks average {_round(recovery.mean(), 0)}/100 recovery.", "confidence": confidence, "metric": "recovery"})

        sleep_values = _numeric_column(weekly, "sleep_hours")
        low_sleep = weekly[sleep_values < 7]
        normal_sleep = weekly[sleep_values >= 7]
        if len(low_sleep) >= 2 and len(normal_sleep) >= 1:
            low_strength = _num(_numeric_column(low_sleep, "strength_index").mean())
            normal_strength = _num(_numeric_column(normal_sleep, "strength_index").mean())
            if normal_strength > 0 and low_strength < normal_strength * 0.95:
                insights.append({"title": "Sleep sensitivity", "summary": "Sleep below 7h has lined up with softer performance/recovery weeks.", "confidence": "low", "metric": "sleep"})

    if not insights:
        return {
            "status": "learning",
            "confidence": "low",
            "summary": "Learning from your history. More overlapping nutrition, training, sleep, recovery, and bodyweight data is needed.",
            "dashboard_insight": None,
            "insights": [],
        }
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    insights = sorted(insights, key=lambda item: confidence_rank.get(item.get("confidence", "low"), 1), reverse=True)
    return {
        "status": "ready",
        "confidence": insights[0].get("confidence", "low"),
        "summary": "Personal baseline insights are conservative patterns from your logged history.",
        "dashboard_insight": insights[0],
        "insights": insights[:10],
    }


def _weekly_baseline_frame(
    summary_df: pd.DataFrame,
    training_df: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    sleep_df: pd.DataFrame,
) -> pd.DataFrame:
    weekly = pd.DataFrame()
    nutrition = summary_df.copy() if summary_df is not None else pd.DataFrame()
    if not nutrition.empty:
        nutrition["date"] = pd.to_datetime(nutrition.get("date"), errors="coerce")
        nutrition = nutrition.dropna(subset=["date"])
        nutrition["week"] = nutrition["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        for column in ["total_calories", "total_carbs"]:
            nutrition[column] = pd.to_numeric(nutrition.get(column), errors="coerce")
        weekly = nutrition.groupby("week", as_index=False).agg(calories=("total_calories", "mean"), carbs=("total_carbs", "mean"))

    strength = _strength_rows(training_df)
    if not strength.empty:
        strength["week"] = strength["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        strength_weekly = strength.groupby("week", as_index=False).agg(strength_index=("estimated_1rm", "mean"))
        weekly = strength_weekly if weekly.empty else weekly.merge(strength_weekly, on="week", how="outer")

    training = _date_frame(training_df)
    if not training.empty:
        runs = training[_run_mask(training)].copy()
        if not runs.empty:
            runs["miles"] = runs.get("notes", pd.Series("", index=runs.index)).apply(lambda note: _note_number(str(note), "distance_miles"))
            runs["week"] = runs["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
            run_weekly = runs.groupby("week", as_index=False).agg(miles=("miles", "sum"))
            weekly = run_weekly if weekly.empty else weekly.merge(run_weekly, on="week", how="outer")

    sleep = _date_frame(sleep_df)
    if not sleep.empty:
        sleep["durationMinutes"] = pd.to_numeric(sleep.get("durationMinutes"), errors="coerce")
        sleep["week"] = sleep["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        sleep_weekly = sleep.groupby("week", as_index=False).agg(sleep_hours=("durationMinutes", lambda values: values.mean() / 60))
        weekly = sleep_weekly if weekly.empty else weekly.merge(sleep_weekly, on="week", how="outer")

    recovery = _date_frame(recovery_df)
    if not recovery.empty:
        recovery["recovery_score"] = recovery.apply(calculate_recovery_score, axis=1)
        recovery["week"] = recovery["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        recovery_weekly = recovery.groupby("week", as_index=False).agg(recovery_score=("recovery_score", "mean"))
        weekly = recovery_weekly if weekly.empty else weekly.merge(recovery_weekly, on="week", how="outer")

    body = _date_frame(canonical_daily_bodyweights(body_metrics_df))
    if not body.empty:
        body["bodyweight"] = pd.to_numeric(body.get("bodyweight"), errors="coerce")
        body["week"] = body["date"].dt.to_period("W").apply(lambda period: period.start_time.date().isoformat())
        body_weekly = body.groupby("week", as_index=False).agg(weight=("bodyweight", "mean"))
        body_weekly["weight_gain"] = body_weekly["weight"].diff()
        weekly = body_weekly[["week", "weight_gain"]] if weekly.empty else weekly.merge(body_weekly[["week", "weight_gain"]], on="week", how="outer")
    return weekly.sort_values("week").tail(12).reset_index(drop=True) if not weekly.empty else weekly


def build_optimization_features(
    *,
    nutrition_summary_df: pd.DataFrame,
    training_df: pd.DataFrame,
    recovery_df: pd.DataFrame,
    sleep_df: pd.DataFrame,
    body_metrics_df: pd.DataFrame,
    targets: dict,
    personal_learning: dict | None = None,
    today: str | None = None,
) -> dict:
    """Return all high-value optimization features in one stable shape."""
    return {
        "day_type_macros": training_day_macros(training_df, recovery_df, targets, today=today),
        "plateau_detection": plateau_detection(training_df, today=today),
        "macro_adherence": macro_adherence_analysis(nutrition_summary_df, training_df, body_metrics_df),
        "personal_baseline": personal_baseline_learning(
            nutrition_summary_df,
            training_df,
            body_metrics_df,
            recovery_df,
            sleep_df,
            personal_learning=personal_learning,
        ),
    }
