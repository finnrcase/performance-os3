"""Wearable dashboard signals.

These helpers keep wearable calories as context only. Saved adaptive
targets remain the baseline, and calorie changes require bodyweight trend
confirmation before being suggested.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any

GOOGLE_HEALTH_SIGNAL_FIELDS = [
    "sleep_hours",
    "total_sleep_minutes",
    "rem_sleep_minutes",
    "deep_sleep_minutes",
    "light_sleep_minutes",
    "awake_minutes",
    "sleep_efficiency",
    "sleep_score",
    "resting_hr",
    "resting_hr_baseline",
    "resting_hr_deviation",
    "hrv",
    "average_hr",
    "max_hr",
    "workout_average_hr",
    "workout_max_hr",
    "steps",
    "active_minutes",
    "active_zone_minutes",
    "distance_meters",
    "distance_miles",
    "total_calories_burned",
    "calories_burned",
    "active_calories_burned",
    "basal_calories_burned",
    "workout_minutes",
    "cardio_load",
    "breathing_rate",
    "spo2",
    "skin_temperature",
    "body_temperature",
]


def _num(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_num(value: Any) -> float | None:
    parsed = _num(value)
    return parsed if parsed is not None and parsed > 0 else None


def _first_positive(row: dict[str, Any], *fields: str) -> float | None:
    for field in fields:
        parsed = _positive_num(row.get(field))
        if parsed is not None:
            return parsed
    return None


def _round(value: float | None, digits: int = 1) -> float | int | None:
    if value is None or not math.isfinite(float(value)):
        return None
    rounded = round(float(value), digits)
    return int(rounded) if rounded == int(rounded) else rounded


def _date_text(value: Any) -> str:
    text = str(value or "").strip()[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def _date_obj(value: Any):
    text = _date_text(value)
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def _same_day_row(rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    candidates = [dict(row) for row in rows if _date_text(row.get("date")) == today]
    if not candidates:
        return {}
    return sorted(candidates, key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""))[-1]


def _value_present(value: Any, *, zero_is_missing: bool = False) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if str(value).strip().lower() in {"nan", "none", "<na>", "nat"}:
        return False
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return False
    parsed = _num(value)
    if zero_is_missing and parsed is not None and parsed <= 0:
        return False
    return True


def _booleanish(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes", "placeholder"}


def google_health_populated_metric_count(row: dict[str, Any] | None) -> int:
    sample = row if isinstance(row, dict) else {}
    stored = _num(sample.get("populated_metric_count"))
    if stored is not None and stored > 0:
        return int(stored)
    return sum(1 for field in GOOGLE_HEALTH_SIGNAL_FIELDS if _value_present(sample.get(field), zero_is_missing=True))


def google_health_row_has_metrics(row: dict[str, Any] | None) -> bool:
    sample = row if isinstance(row, dict) else {}
    return not _booleanish(sample.get("placeholder")) and google_health_populated_metric_count(sample) > 0


def _compact_debug_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    keep = {"date", "source", "provider", "populated_metric_count", "placeholder", "raw_payload", *GOOGLE_HEALTH_SIGNAL_FIELDS}
    return {key: row.get(key) for key in keep if key in row}


def _merge_row_value(target: dict[str, Any], key: str, value: Any) -> None:
    if key.startswith("_") or key in {"metric_id", "summary_id", "sleep_id", "heart_id", "activity_id", "signal_id"}:
        return
    mapped_key = {
        "total_sleep_time": "sleep_hours",
        "hr_zones": "heart_rate_zones",
    }.get(key, key)
    if not _value_present(value):
        target.setdefault(mapped_key, value if mapped_key in {"date", "source"} else target.get(mapped_key))
        return
    if not _value_present(target.get(mapped_key)):
        target[mapped_key] = value


def merge_google_health_rows(
    *,
    wearable_rows: list[dict[str, Any]],
    daily_summary_rows: list[dict[str, Any]] | None = None,
    sleep_rows: list[dict[str, Any]] | None = None,
    heart_rows: list[dict[str, Any]] | None = None,
    activity_rows: list[dict[str, Any]] | None = None,
    recovery_signal_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge normalized and split Google Health tables into one row per date."""
    by_date: dict[str, dict[str, Any]] = {}

    def absorb(table: str, rows: list[dict[str, Any]] | None) -> None:
        for raw in rows or []:
            if not isinstance(raw, dict):
                continue
            day = _date_text(raw.get("date"))
            if not day:
                continue
            target = by_date.setdefault(day, {"date": day, "source": "google_health", "_source_tables": [], "_raw_table_rows": {}})
            source_tables = raw.get("_source_tables") if isinstance(raw.get("_source_tables"), list) else [table]
            for source_table in source_tables:
                if source_table not in target["_source_tables"]:
                    target["_source_tables"].append(source_table)
            if isinstance(raw.get("_raw_table_rows"), dict):
                target["_raw_table_rows"].update(raw["_raw_table_rows"])
            else:
                target["_raw_table_rows"][table] = _compact_debug_row(raw)
            for key, value in raw.items():
                _merge_row_value(target, key, value)

    absorb("wearable_metrics", wearable_rows)
    absorb("google_health_daily_summary", daily_summary_rows)
    absorb("google_health_sleep", sleep_rows)
    absorb("google_health_heart", heart_rows)
    absorb("google_health_activity", activity_rows)
    absorb("google_health_recovery_signals", recovery_signal_rows)
    for row in by_date.values():
        count = google_health_populated_metric_count(row)
        row["populated_metric_count"] = count
        row["placeholder"] = count <= 0
    return sorted(by_date.values(), key=lambda row: _date_text(row.get("date")))


def _previous_values(rows: list[dict[str, Any]], today: str, field: str, *, days: int = 14) -> list[float]:
    today_obj = _date_obj(today)
    if today_obj is None:
        return []
    start = today_obj - timedelta(days=days)
    values: list[float] = []
    for row in rows:
        row_date = _date_obj(row.get("date"))
        value = _positive_num(row.get(field))
        if row_date is None or value is None:
            continue
        if start <= row_date < today_obj:
            values.append(value)
    return values


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _status_from_score(score: float | None) -> str:
    if score is None:
        return "insufficient_data"
    if score >= 82:
        return "good"
    if score >= 68:
        return "fair"
    return "poor"


def _sleep_signal(row: dict[str, Any]) -> dict[str, Any]:
    duration = _positive_num(row.get("sleep_hours"))
    total_minutes = _positive_num(row.get("total_sleep_minutes"))
    if duration is None and total_minutes is not None:
        duration = total_minutes / 60
    rem = _positive_num(row.get("rem_sleep_minutes"))
    deep = _positive_num(row.get("deep_sleep_minutes"))
    efficiency = _positive_num(row.get("sleep_efficiency"))
    source_score = _positive_num(row.get("sleep_score"))
    weighted = 0.0
    total_weight = 0.0
    if duration is not None:
        weighted += min(max(duration / 8, 0), 1) * 40
        total_weight += 40
    if efficiency is not None:
        weighted += min(max(efficiency / 92, 0), 1) * 25
        total_weight += 25
    if rem is not None or deep is not None:
        restorative_minutes = float(rem or 0) + float(deep or 0)
        weighted += min(max(restorative_minutes / 150, 0), 1) * 20
        total_weight += 20
    if source_score is not None:
        weighted += min(max(source_score / 100, 0), 1) * 15
        total_weight += 15
    score = (weighted / total_weight * 100) if total_weight else None
    status = _status_from_score(score)
    poor = bool(
        status == "poor"
        or (duration is not None and duration < 6.5)
        or (efficiency is not None and efficiency < 80)
    )
    return {
        "score": _round(score, 0),
        "status": status,
        "duration_hours": _round(duration, 2),
        "rem_minutes": _round(rem, 0),
        "deep_minutes": _round(deep, 0),
        "light_minutes": _round(_num(row.get("light_sleep_minutes")), 0),
        "awake_minutes": _round(_num(row.get("awake_minutes")), 0),
        "efficiency": _round(efficiency, 0),
        "poor_sleep": poor,
        "message": "Sleep data unavailable from wearable provider." if status == "insufficient_data" else "Sleep is supporting recovery." if status == "good" else "Sleep quality is a recovery limiter." if status == "poor" else "Sleep is adequate, but worth watching.",
    }


def _rhr_signal(row: dict[str, Any], rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    resting_hr = _positive_num(row.get("resting_hr"))
    baseline = _positive_num(row.get("resting_hr_baseline")) or _avg(_previous_values(rows, today, "resting_hr", days=14)[-7:])
    deviation = _num(row.get("resting_hr_deviation"))
    if deviation is None and resting_hr is not None and baseline is not None:
        deviation = resting_hr - baseline
    status = "insufficient_data"
    if resting_hr is not None and baseline is not None:
        status = "high" if deviation is not None and deviation >= 5 else "normal" if deviation is not None and deviation <= 2 else "watch"
    return {
        "resting_hr": _round(resting_hr, 0),
        "baseline": _round(baseline, 0),
        "deviation": _round(deviation, 1),
        "status": status,
        "abnormal": bool(deviation is not None and deviation >= 5),
    }


def _hrv_signal(row: dict[str, Any], rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    hrv = _positive_num(row.get("hrv"))
    baseline = _avg(_previous_values(rows, today, "hrv", days=14)[-7:])
    suppressed = bool(hrv is not None and baseline is not None and hrv < baseline * 0.9)
    watch = bool(hrv is not None and baseline is not None and hrv < baseline * 0.95)
    return {
        "hrv": _round(hrv, 0),
        "baseline": _round(baseline, 0),
        "status": "suppressed" if suppressed else "watch" if watch else "normal" if hrv is not None else "insufficient_data",
        "abnormal": suppressed,
    }


def _subjective_recovery_signal(recovery_rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    row = _same_day_row(recovery_rows, today)
    score = _num(row.get("recovery_score"))
    fatigue = _num(row.get("fatigue"))
    quality = _num(row.get("sleep_quality"))
    poor = bool((score is not None and score < 60) or (fatigue is not None and fatigue >= 7) or (quality is not None and quality <= 5))
    return {
        "score": _round(score, 0),
        "fatigue": _round(fatigue, 0),
        "sleep_quality": _round(quality, 0),
        "abnormal": poor,
        "status": "poor" if poor else "normal" if row else "missing",
    }


def _activity_signal(row: dict[str, Any], training_rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    today_obj = _date_obj(today)
    steps = _positive_num(row.get("steps"))
    active = _positive_num(row.get("active_minutes"))
    zone = _positive_num(row.get("active_zone_minutes"))
    distance = _positive_num(row.get("distance_miles"))
    distance_meters = _positive_num(row.get("distance_meters"))
    if distance is None and distance_meters is not None:
        distance = distance_meters / 1609.344
    recent_training_minutes = 0.0
    recent_hard_sets = 0.0
    if today_obj is not None:
        start = today_obj - timedelta(days=6)
        for item in training_rows:
            row_date = _date_obj(item.get("date"))
            if row_date is None or not (start <= row_date <= today_obj):
                continue
            recent_training_minutes += _num(item.get("duration_minutes")) or 0
            sets = _num(item.get("sets")) or 0
            rpe = _num(item.get("rpe"))
            recent_hard_sets += sets if rpe is not None and rpe >= 7 else sets * 0.5 if sets else 0
    wearable_activity_present = any(value is not None for value in (steps, active, zone, distance))
    load_score = (steps or 0) / 1000 + (active or 0) + (zone or 0) * 1.5 + (distance or 0) * 2 + recent_training_minutes / 20 if wearable_activity_present else None
    high = bool(wearable_activity_present and ((active or 0) >= 90 or (zone or 0) >= 45 or recent_training_minutes >= 240 or recent_hard_sets >= 35))
    return {
        "steps": _round(steps, 0),
        "active_minutes": _round(active, 0),
        "active_zone_minutes": _round(zone, 0),
        "distance_miles": _round(distance, 2),
        "recent_training_minutes": _round(recent_training_minutes, 0),
        "recent_hard_sets": _round(recent_hard_sets, 1),
        "load_score": _round(load_score, 1),
        "status": "high" if high else "normal" if wearable_activity_present else "insufficient_data",
        "high_load": high,
    }


def _missing_metric_warnings(row: dict[str, Any]) -> list[str]:
    checks = [
        ("sleep", [row.get("sleep_hours"), row.get("total_sleep_minutes")]),
        ("resting heart rate", [row.get("resting_hr")]),
        ("calories burned", [row.get("total_calories_burned"), row.get("calories_burned")]),
        ("activity", [row.get("steps"), row.get("active_minutes"), row.get("active_zone_minutes")]),
    ]
    warnings: list[str] = []
    for label, values in checks:
        if all(_positive_num(value) is None for value in values):
            warnings.append(f"Wearable {label} metric is missing for this date.")
    return warnings


def _fields_used(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row.get(field) for field in GOOGLE_HEALTH_SIGNAL_FIELDS if _value_present(row.get(field), zero_is_missing=True)}


def _missing_fields(row: dict[str, Any]) -> list[str]:
    return [field for field in GOOGLE_HEALTH_SIGNAL_FIELDS if not _value_present(row.get(field), zero_is_missing=True)]


def _bodyweight_confirmation(body_rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    today_obj = _date_obj(today)
    if today_obj is None:
        return {"confirmed": False, "sample_size": 0, "weekly_change_lb": None}
    start = today_obj - timedelta(days=14)
    points = []
    for row in body_rows:
        row_date = _date_obj(row.get("date"))
        weight = _num(row.get("bodyweight"))
        if row_date is None or weight is None or not (start <= row_date <= today_obj):
            continue
        points.append((row_date, weight))
    points = sorted(points)
    if len(points) < 7:
        return {"confirmed": False, "sample_size": len(points), "weekly_change_lb": None}
    elapsed = max(1, (points[-1][0] - points[0][0]).days)
    weekly_change = (points[-1][1] - points[0][1]) / elapsed * 7
    return {"confirmed": True, "sample_size": len(points), "weekly_change_lb": _round(weekly_change, 2)}


def build_google_health_dashboard_signals(
    *,
    wearable_rows: list[dict[str, Any]],
    recovery_rows: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
    nutrition_today: dict[str, Any],
    targets: dict[str, Any],
    body_rows: list[dict[str, Any]],
    today: str,
) -> dict[str, Any]:
    """Return dashboard-ready wearable recovery and calorie context."""
    day = _date_text(today)
    all_rows = merge_google_health_rows(wearable_rows=[dict(row) for row in wearable_rows if isinstance(row, dict)])
    rows = [row for row in all_rows if google_health_row_has_metrics(row)]
    placeholder_rows = [row for row in all_rows if not google_health_row_has_metrics(row)]
    row = _same_day_row(rows, day)
    if not row:
        latest_date = sorted([_date_text(item.get("date")) for item in rows if _date_text(item.get("date"))])
        reason = "no_data_for_date" if latest_date else "connected_no_wearable_metrics" if placeholder_rows else "no_wearable_data_connected"
        return {
            "status": "insufficient_data",
            "source": "wearable_metrics",
            "date": day,
            "reason": reason,
            "latest_metric_date": latest_date[-1] if latest_date else "",
            "message": (
                "No wearable metrics for this date. Sync a wearable provider or choose a date with wearable data."
                if latest_date
                else "Connected, but no wearable metrics are available yet."
                if placeholder_rows
                else "No wearable data connected. Connect or sync a wearable provider to enable recovery signals."
            ),
            "debug": {
                "metric_rows_available": len(rows),
                "raw_metric_rows_available": len(all_rows),
                "placeholder_rows_ignored": len(placeholder_rows),
                "latest_metric_date": latest_date[-1] if latest_date else "",
                "latest_raw_row": {"wearable_metrics": _compact_debug_row(placeholder_rows[-1])} if placeholder_rows else {},
                "fields_used": {},
                "missing_fields": GOOGLE_HEALTH_SIGNAL_FIELDS,
            },
        }

    sleep = _sleep_signal(row)
    rhr = _rhr_signal(row, rows, day)
    hrv = _hrv_signal(row, rows, day)
    subjective = _subjective_recovery_signal(recovery_rows, day)
    activity = _activity_signal(row, training_rows, day)
    missing_metric_warnings = _missing_metric_warnings(row)
    breathing_rate = _positive_num(row.get("breathing_rate"))
    spo2 = _positive_num(row.get("spo2"))
    skin_temperature = _num(row.get("skin_temperature"))
    body_temperature = _positive_num(row.get("body_temperature"))
    abnormal_signals: list[str] = []
    if rhr["abnormal"]:
        abnormal_signals.append("Resting HR elevated above baseline")
    if hrv["abnormal"]:
        abnormal_signals.append("HRV suppressed below baseline")
    if sleep["poor_sleep"]:
        abnormal_signals.append("Poor sleep quality")
    if breathing_rate is not None and breathing_rate >= 22:
        abnormal_signals.append("Breathing rate elevated")
    if spo2 is not None and spo2 < 94:
        abnormal_signals.append("SpO2 lower than normal")
    if skin_temperature is not None and abs(skin_temperature) <= 5 and abs(skin_temperature) >= 1:
        abnormal_signals.append("Skin temperature elevated vs baseline")
    if body_temperature is not None and body_temperature >= 37.8:
        abnormal_signals.append("Body temperature elevated")
    if subjective["abnormal"]:
        abnormal_signals.append("Poor recovery reported")
    vitals_or_heart_available = any(
        value is not None
        for value in (
            rhr.get("resting_hr"),
            hrv.get("hrv"),
            breathing_rate,
            spo2,
            skin_temperature,
            body_temperature,
            subjective.get("score"),
            subjective.get("fatigue"),
            subjective.get("sleep_quality"),
        )
    )
    sickness_status = (
        "warning"
        if len(abnormal_signals) >= 2
        else "watch"
        if abnormal_signals
        else "clear"
        if vitals_or_heart_available
        else "insufficient_data"
    )
    sickness_warning = {
        "status": sickness_status,
        "label": "Possible sickness / elevated recovery risk" if sickness_status == "warning" else "Recovery watch" if sickness_status == "watch" else "No sickness pattern detected" if sickness_status == "clear" else "Sickness pattern unavailable",
        "message": "Consider reducing intensity today. Prioritize sleep, hydration, and easy movement." if sickness_status == "warning" else "One recovery marker is off; keep intensity honest." if sickness_status == "watch" else "No multi-signal sickness pattern from available wearable data." if sickness_status == "clear" else "No wearable vitals are available to evaluate sickness/recovery stress.",
        "abnormal_signals": abnormal_signals,
        "signal_count": len(abnormal_signals),
        "disclaimer": "This is not a diagnosis.",
    }
    readiness_score = 100.0
    readiness_score -= 20 if sleep["status"] == "poor" else 8 if sleep["status"] == "fair" else 0
    readiness_score -= 15 if rhr["abnormal"] else 6 if rhr["status"] == "watch" else 0
    readiness_score -= 15 if hrv["abnormal"] else 5 if hrv["status"] == "watch" else 0
    readiness_score -= min(24, len(abnormal_signals) * 8)
    readiness_score -= 10 if activity["high_load"] else 0
    readiness_score -= 12 if subjective["abnormal"] else 0
    readiness_score = max(0, min(100, readiness_score))
    readiness_status = "green" if readiness_score >= 80 else "yellow" if readiness_score >= 60 else "red"
    heart_recovery_signal_available = bool(rhr.get("resting_hr") is not None or hrv.get("hrv") is not None)
    recovery_confidence = "medium" if heart_recovery_signal_available else "low" if sleep["status"] != "insufficient_data" or activity["status"] != "insufficient_data" else "insufficient_data"
    recovery_readiness = {
        "score": _round(readiness_score, 0),
        "status": readiness_status,
        "confidence": recovery_confidence,
        "missing_heart_signals": not heart_recovery_signal_available,
        "label": "Ready" if readiness_status == "green" else "Reduce intensity" if readiness_status == "yellow" else "Recovery priority",
        "message": "Recovery signals support normal training." if readiness_status == "green" else "Consider reducing intensity today." if readiness_status == "yellow" else "Prioritize recovery before hard training.",
    }

    baseline_target = _num(targets.get("target_calories"))
    calories_burned = _first_positive(row, "total_calories_burned", "calories_burned")
    intake = _num(nutrition_today.get("calories"))
    calorie_delta = intake - calories_burned if intake is not None and calories_burned is not None else None
    if calorie_delta is None:
        calorie_status = "insufficient_data"
    elif abs(calorie_delta) <= 150:
        calorie_status = "likely_near_maintenance"
    elif calorie_delta < -300:
        calorie_status = "below_estimated_burn"
    elif calorie_delta > 300:
        calorie_status = "above_estimated_burn"
    else:
        calorie_status = "near_estimated_burn"
    activity_modifier = 0.0
    if baseline_target is not None and calories_burned is not None:
        activity_modifier = max(-150.0, min(150.0, (calories_burned - baseline_target) * 0.15))
    recovery_modifier = -100.0 if sickness_status == "warning" else -50.0 if readiness_status == "red" else 50.0 if activity["high_load"] and readiness_status == "green" else 0.0
    context_target = (baseline_target or 0) + activity_modifier + recovery_modifier if baseline_target is not None else None
    body_confirmation = _bodyweight_confirmation(body_rows, day)
    suggested_adjustment = 0
    if body_confirmation["confirmed"] and calorie_delta is not None:
        weekly_change = _num(body_confirmation.get("weekly_change_lb")) or 0
        if weekly_change < -0.35 and calorie_delta < -150:
            suggested_adjustment = 100
        elif weekly_change > 0.6 and calorie_delta > 150:
            suggested_adjustment = -100
    calories = {
        "calories_burned": _round(calories_burned, 0),
        "logged_intake": _round(intake, 0),
        "intake_vs_burned": _round(calorie_delta, 0),
        "status": calorie_status,
        "message": "Wearable burn unavailable." if calorie_status == "insufficient_data" else "Likely near maintenance from intake vs wearable burn." if calorie_status == "likely_near_maintenance" else "Wearable burn is context only; saved target remains bodyweight-trend based.",
    }
    suggested_calorie_adjustment = {
        "adjustment": suggested_adjustment,
        "status": "suggest_adjustment" if suggested_adjustment else "hold",
        "confidence": "medium" if body_confirmation["confirmed"] else "low",
        "baseline_target": _round(baseline_target, 0),
        "activity_modifier": _round(activity_modifier, 0),
        "recovery_modifier": _round(recovery_modifier, 0),
        "context_target": _round(context_target, 0),
        "bodyweight_confirmation": body_confirmation,
        "message": "Several weigh-ins confirm a small target change may be reasonable." if suggested_adjustment else "Hold saved target until several days of bodyweight trend confirm a change.",
    }
    return {
        "status": "ok",
        "source": str(row.get("source") or "google_health"),
        "date": day,
        "sleep_quality": sleep,
        "recovery_readiness": recovery_readiness,
        "sickness_warning": sickness_warning,
        "resting_hr_vs_baseline": rhr,
        "hrv": hrv,
        "health": {
            "breathing_rate": _round(breathing_rate, 1),
            "spo2": _round(spo2, 1),
            "skin_temperature": _round(skin_temperature, 1),
            "body_temperature": _round(body_temperature, 1),
        },
        "calories_burned_vs_intake": calories,
        "suggested_calorie_adjustment": suggested_calorie_adjustment,
        "activity_load": activity,
        "debug": {
            "metric_rows_available": len(rows),
            "raw_metric_rows_available": len(all_rows),
            "placeholder_rows_ignored": len(placeholder_rows),
            "selected_date": day,
            "source_table": ", ".join(row.get("_source_tables") or ["wearable_metrics"]),
            "source_tables": row.get("_source_tables") or ["wearable_metrics"],
            "latest_raw_row": row.get("_raw_table_rows") or {"wearable_metrics": _compact_debug_row(row)},
            "normalized_wearable_row": _compact_debug_row(row),
            "fields_used": _fields_used(row),
            "missing_fields": _missing_fields(row),
            "missing_metric_warnings": missing_metric_warnings,
            "partial_data": bool(missing_metric_warnings),
        },
    }
