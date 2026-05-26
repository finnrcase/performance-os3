from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import logging
import re
import time
from typing import Any, Callable

from fastapi import APIRouter, Query
import pandas as pd

from backend_new.db import fetch_dashboard_core_bundle, fetch_latest_document
from backend_new.routes.goals import calculate_targets, fallback_goals
from backend_new.config import app_timezone_name
from backend_new.utils import app_today_iso, utc_now_iso
from src.body_metrics import canonical_daily_bodyweights
from src.analytics.recovery_engine import calculate_recovery_score
from src.training_schedule import DEFAULT_RECURRING_SCHEDULE_PROFILE, classify_strength_split, planned_training_for_date, summarize_training_day


router = APIRouter(tags=["dashboard"])
logger = logging.getLogger(__name__)

REQUIRED_BLOCKS = {"load_core_bundle"}


def _today_iso() -> str:
    return app_today_iso()


def _server_utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_dashboard_date(value: str | None) -> str:
    candidate = str(value or "").strip()[:10]
    if len(candidate) == 10:
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            pass
    return _today_iso()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _round(value: float) -> int | float:
    rounded = round(value, 1)
    return int(rounded) if rounded == int(rounded) else rounded


def _nutrition_value(item: dict[str, Any], field: str) -> float:
    aliases = {
        "protein": ("protein", "protein_g"),
        "carbs": ("carbs", "carbs_g"),
        "fat": ("fat", "fat_g"),
        "fiber": ("fiber", "fiber_g"),
    }
    for key in aliases.get(field, (field,)):
        if key in item:
            return _number(item.get(key), 0)
    return 0


def _totals(items: list[dict[str, Any]]) -> dict[str, int | float]:
    return {
        field: _round(sum(_nutrition_value(item, field) for item in items))
        for field in ("calories", "protein", "carbs", "fat", "fiber")
    }


def _simple_targets(goals: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    calculated = calculate_targets(goals)
    if not isinstance(targets, dict) or "_db_error" in targets:
        return calculated
    for field in (
        "target_calories",
        "maintenance_calories",
        "calorie_adjustment",
        "protein_grams",
        "carb_grams",
        "fat_grams",
        "expected_weekly_weight_change",
        "target_description",
        "timeline_status",
        "timeline_warning",
        "updated_at",
    ):
        if field in targets and targets[field] not in {None, ""}:
            calculated[field] = targets[field]
    return calculated


def _progress(actual: float, target: float | None) -> dict[str, Any]:
    if not target:
        return {"left": None, "over": None, "percent": 0}
    left = max(float(target) - float(actual), 0)
    over = max(float(actual) - float(target), 0)
    return {"left": _round(left), "over": _round(over), "percent": round(min(max(float(actual) / float(target) * 100, 0), 100), 1)}


def _food_tile(totals: dict[str, Any], targets: dict[str, Any], *, has_food: bool) -> dict[str, Any]:
    macro_targets = {
        "calories": targets.get("target_calories"),
        "protein": targets.get("protein_grams"),
        "carbs": targets.get("carb_grams"),
        "fat": targets.get("fat_grams"),
    }
    return {
        key: {
            "eaten": _number(totals.get(key), 0),
            "target": macro_targets[key],
            **_progress(_number(totals.get(key), 0), macro_targets[key]),
        }
        for key in ("calories", "protein", "carbs", "fat")
    } | {
        "has_targets": any(value for value in macro_targets.values()),
        "has_food_logged": has_food,
    }


def _weight_tile(rows: list[dict[str, Any]], today: str) -> tuple[float | None, list[dict[str, Any]], dict[str, Any]]:
    canonical = canonical_daily_bodyweights(rows)
    usable = []
    for row in canonical.to_dict(orient="records") if not canonical.empty else []:
        item = dict(row)
        try:
            item["date"] = row["date"].date().isoformat()
        except Exception:
            item["date"] = str(row.get("date") or "")
        usable.append(item)
    if not usable:
        tile = {
            "today_weight": None,
            "latest_weight": None,
            "seven_day_average": None,
            "trend_label": "insufficient data",
            "history": [],
            "message": "Enter today's weight",
            "canonical_rule": "lowest_weight_per_day",
        }
        return None, [], tile
    latest = _round(_number(usable[-1].get("bodyweight"), 0))
    recent = usable[-7:]
    average = _round(sum(_number(row.get("bodyweight"), 0) for row in recent) / len(recent)) if len(recent) >= 2 else None
    delta = _number(recent[-1].get("bodyweight"), 0) - _number(recent[0].get("bodyweight"), 0) if len(recent) >= 3 else 0
    trend = "gaining" if delta > 0.3 else "losing" if delta < -0.3 else "stable" if len(recent) >= 3 else "insufficient data"
    today_rows = [row for row in usable if str(row.get("date")) == today]
    tile = {
        "today_weight": _round(_number(today_rows[-1].get("bodyweight"), 0)) if today_rows else None,
        "latest_weight": latest,
        "seven_day_average": average,
        "trend_label": trend,
        "history": usable[-14:],
        "message": "Today's weight logged" if today_rows else "Enter today's weight",
        "canonical_rule": "lowest_weight_per_day",
    }
    return latest, usable[-30:], tile


def _volume(row: dict[str, Any]) -> float:
    return _number(row.get("sets"), 0) * _number(row.get("reps"), 0) * _number(row.get("weight"), 0)


def _latest_workout(rows: list[dict[str, Any]], target_date: str | None = None) -> dict[str, Any] | None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    normalized_target_date = _date_text(target_date)
    for row in rows:
        workout_date = _date_text(row.get("date"))
        if not workout_date:
            continue
        if normalized_target_date and workout_date != normalized_target_date:
            continue
        workout_id = str(row.get("workout_id") or row.get("hevy_workout_id") or f"{workout_date}:unknown")
        grouped[(workout_date, workout_id)].append(row)
    if not grouped:
        return None
    workout_date, workout_id = sorted(grouped.keys(), reverse=True)[0]
    workout_rows = grouped[(workout_date, workout_id)]
    exercises = list(dict.fromkeys(str(row.get("exercise") or "").strip() for row in workout_rows if str(row.get("exercise") or "").strip()))
    title = ""
    for row in workout_rows:
        notes = str(row.get("notes") or "")
        if "workout_title=" in notes:
            title = notes.split("workout_title=", 1)[1].split("|", 1)[0].strip()
            break
    title = title or str(workout_rows[0].get("workout_type") or "Workout")
    return {
        "date": workout_date,
        "workout_id": workout_id,
        "workout_type": title,
        "exercise_names": exercises,
        "total_sets": int(sum(max(0, int(_number(row.get("sets"), 0))) for row in workout_rows)),
        "total_volume": _round(sum(_volume(row) for row in workout_rows)),
        "duration_minutes": _round(max([_number(row.get("duration_minutes"), 0) for row in workout_rows] or [0])),
        "source": ", ".join(sorted({str(row.get("source") or "manual") for row in workout_rows})),
    }


def _training_rows_from_history(history_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in history_items:
        details = item.get("details") if isinstance(item.get("details"), list) else []
        if details:
            rows.extend(dict(row) for row in details if isinstance(row, dict))
            continue
        rows.append(
            {
                "date": item.get("date"),
                "workout_id": item.get("workout_id"),
                "workout_type": item.get("workout_type"),
                "sets": item.get("total_sets"),
                "reps": 1,
                "weight": item.get("total_volume"),
                "duration_minutes": item.get("duration_minutes"),
                "source": item.get("source"),
            }
        )
    return rows


def _safe_items(payload: dict[str, Any] | None, key: str = "items") -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        return []
    return [dict(item) for item in payload.get(key, []) if isinstance(item, dict) and "_db_error" not in item]


def _latest_field(rows: list[dict[str, Any]], *fields: str) -> str:
    values: list[str] = []
    for row in rows:
        for field in fields:
            value = str(row.get(field) or "").strip()
            if value:
                values.append(value)
                break
    return sorted(values)[-1] if values else ""


def _source_block(
    name: str,
    source: str,
    loader: Callable[[], dict[str, Any]],
    fallback: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = loader()
        if not isinstance(payload, dict):
            raise ValueError(f"{source} returned {type(payload).__name__}, expected object.")
        status = str(payload.get("status") or "ok")
        blocks.append(
            {
                "block": f"source_{name}",
                "name": f"source_{name}",
                "source": source,
                "status": "ok" if status != "error" else "warning",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "message": payload.get("error") if status == "error" else "",
            }
        )
        return payload
    except Exception as exc:
        logger.exception("[dashboard_core] source failed source=%s", source)
        blocks.append(
            {
                "block": f"source_{name}",
                "name": f"source_{name}",
                "source": source,
                "status": "warning",
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return fallback


def _dashboard_cache_payload(bundle: dict[str, Any], sources: dict[str, Any]) -> dict[str, Any]:
    bundle_cache = bundle.get("cache") if isinstance(bundle.get("cache"), dict) else {}
    versions = {
        "food": (sources.get("food") or {}).get("last_updated") or (sources.get("food") or {}).get("date") or "",
        "training": (sources.get("training") or {}).get("latest_workout_date") or "",
        "weight": (sources.get("weight") or {}).get("latest_weight_date") or "",
        "goals": (sources.get("goals") or {}).get("updated_at") or "",
        "recovery": (sources.get("recovery") or {}).get("latest_recovery_date") or (sources.get("recovery") or {}).get("latest_sleep_date") or "",
    }
    return {
        "hit": str(bundle_cache.get("status") or "") == "hit",
        "created_at": bundle_cache.get("created_at") or utc_now_iso(),
        "ttl_seconds": bundle_cache.get("ttl_seconds"),
        "invalidated_by": [],
        "source_versions": versions,
    }


def _latest_from_training_history(history_items: list[dict[str, Any]], target_date: str | None = None) -> dict[str, Any] | None:
    if not history_items:
        return None
    normalized_target_date = _date_text(target_date)
    if normalized_target_date:
        candidates = [dict(item) for item in history_items if _date_text(item.get("date")) == normalized_target_date]
        if not candidates:
            return None
        latest = candidates[0]
    else:
        latest = dict(history_items[0])
    return {
        "date": _date_text(latest.get("date")) or latest.get("date"),
        "workout_id": latest.get("workout_id"),
        "workout_type": latest.get("workout_type") or "Workout",
        "classification": latest.get("classification"),
        "classification_debug": latest.get("classification_debug"),
        "split_type": latest.get("split_type") or "",
        "split_confidence": latest.get("split_confidence", 0.0),
        "classification_reason": latest.get("classification_reason") or [],
        "exercise_names": latest.get("exercise_names") or [],
        "total_sets": latest.get("total_sets", 0),
        "total_volume": latest.get("total_volume", 0),
        "duration_minutes": latest.get("duration_minutes", 0),
        "source": latest.get("source") or "manual",
    }


def _workout_reps(item: dict[str, Any]) -> int:
    if item.get("total_reps") not in {None, ""}:
        return int(max(0, _number(item.get("total_reps"), 0)))
    details = item.get("details") if isinstance(item.get("details"), list) else []
    total = 0
    for row in details:
        if not isinstance(row, dict):
            continue
        total += int(max(0, _number(row.get("sets"), 0))) * int(max(0, _number(row.get("reps"), 0)))
    return total


def _workout_muscle_groups(item: dict[str, Any]) -> list[str]:
    groups: list[str] = []
    item_groups = item.get("muscle_groups") if isinstance(item.get("muscle_groups"), list) else []
    for group in item_groups:
        text = str(group or "").strip()
        if text and text not in groups:
            groups.append(text)
    details = item.get("details") if isinstance(item.get("details"), list) else []
    for row in details:
        if not isinstance(row, dict):
            continue
        text = str(row.get("muscle_group") or "").strip()
        if text and text not in groups:
            groups.append(text)
    return groups[:5]


def _is_lift_history_item(item: dict[str, Any]) -> bool:
    return str(item.get("classification") or "").lower() == "lift"


def _pct_change(current: float, average: float) -> float | None:
    if average <= 0:
        return None
    return round(((current - average) / average) * 100, 1)


def _clean_training_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _workout_title_from_item(item: dict[str, Any]) -> str:
    title = str(item.get("workout_type") or item.get("title") or "").strip()
    if title:
        return title
    details = item.get("details") if isinstance(item.get("details"), list) else []
    for row in details:
        notes = str(row.get("notes") or "")
        if "workout_title=" in notes:
            return notes.split("workout_title=", 1)[1].split("|", 1)[0].strip()
    return "Lift"


def _normalized_workout_split(item: dict[str, Any]) -> str:
    split = classify_strength_split(item)
    return str(split.get("split_type") or "").strip()


def _workout_split_payload(item: dict[str, Any]) -> dict[str, Any]:
    split = classify_strength_split(item)
    return {
        "split_type": str(split.get("split_type") or ""),
        "split_confidence": split.get("split_confidence", 0.0),
        "classification_reason": split.get("classification_reason") or [],
        "matched_by": split.get("matched_by") or "none",
    }


def _split_display_label(split_type: str) -> str:
    labels = {
        "pull_day": "Pull",
        "push_day": "Push",
        "chest_day": "Chest",
        "upper_day": "Upper",
        "lower_day": "Lower",
        "leg_day": "Leg",
        "leg_day_quad": "Quad leg",
        "leg_day_hamstring": "Hamstring leg",
    }
    return labels.get(str(split_type or ""), str(split_type or "").replace("_", " ").title())


def _comparison_match_label(split_type: str) -> str:
    legacy_labels = {
        "pull_day": "pull",
        "push_day": "push",
        "chest_day": "chest",
        "upper_day": "upper",
        "lower_day": "lower",
        "leg_day": "legs",
    }
    return legacy_labels.get(str(split_type or ""), str(split_type or ""))


def _normalized_workout_title(item: dict[str, Any]) -> str:
    text = _clean_training_text(_workout_title_from_item(item))
    stop_words = {"workout", "session", "day", "training", "lift", "strength"}
    words = [word for word in text.split() if word not in stop_words]
    return " ".join(words)


def _normalize_exercise_name(value: Any) -> str:
    text = _clean_training_text(value)
    return re.sub(r"\s+", " ", text).strip()


def _is_cardio_set(row: dict[str, Any]) -> bool:
    exercise = _clean_training_text(row.get("exercise"))
    group = _clean_training_text(row.get("muscle_group"))
    cardio_terms = ("run", "treadmill", "bike", "cycling", "elliptical", "stair", "rower", "swim", "cardio")
    return group == "cardio" or any(term in exercise for term in cardio_terms)


def _is_warmup_set(row: dict[str, Any]) -> bool:
    labels = " ".join(
        str(row.get(key) or "")
        for key in ("type", "set_type", "setType", "kind", "set_kind", "notes")
    ).lower()
    return bool(row.get("is_warmup")) or "warmup" in labels or "warm up" in labels


def _workout_set_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    details = item.get("details") if isinstance(item.get("details"), list) else []
    raw_sets: list[dict[str, Any]] = []
    for order, row in enumerate(details):
        if not isinstance(row, dict):
            continue
        exercise = str(row.get("exercise") or "").strip()
        reps = _number(row.get("reps"), 0)
        weight = _number(row.get("weight"), 0)
        set_count = int(max(0, _number(row.get("sets"), 1)))
        if not exercise or reps <= 0 or weight <= 0 or set_count <= 0:
            continue
        if _is_warmup_set(row) or _is_cardio_set(row):
            continue
        explicit_index = int(max(0, _number(row.get("set_number", row.get("set_index", row.get("index", 0))), 0)))
        for offset in range(set_count):
            raw_sets.append(
                {
                    "exercise": exercise,
                    "exercise_key": _normalize_exercise_name(exercise),
                    "muscle_group": str(row.get("muscle_group") or "").strip(),
                    "weight": weight,
                    "reps": reps,
                    "volume": weight * reps,
                    "explicit_index": explicit_index + offset if explicit_index else None,
                    "order": order + offset / max(1, set_count),
                    "workout_id": item.get("workout_id") or "",
                    "date": item.get("date") or "",
                }
            )
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_sets:
        grouped[row["exercise_key"]].append(row)
    positioned: list[dict[str, Any]] = []
    for exercise_sets in grouped.values():
        exercise_sets.sort(key=lambda row: (row.get("explicit_index") is None, row.get("explicit_index") or row.get("order") or 0, row.get("order") or 0))
        for index, row in enumerate(exercise_sets, start=1):
            row["set_index"] = int(row.get("explicit_index") or index)
            positioned.append(row)
    return sorted(positioned, key=lambda row: (str(row.get("exercise") or ""), int(row.get("set_index") or 0), float(row.get("order") or 0)))


def _workout_exercise_keys(item: dict[str, Any]) -> set[str]:
    from_sets = {row["exercise_key"] for row in _workout_set_rows(item) if row.get("exercise_key")}
    if from_sets:
        return from_sets
    exercises = item.get("exercise_names") if isinstance(item.get("exercise_names"), list) else []
    return {_normalize_exercise_name(exercise) for exercise in exercises if _normalize_exercise_name(exercise)}


def _similar_lift_workouts(latest: dict[str, Any], previous: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    split = _normalized_workout_split(latest)
    if split:
        matches = [item for item in previous if _normalized_workout_split(item) == split]
        if matches:
            return matches[:7], "normalized_split", _comparison_match_label(split)

    title = _normalized_workout_title(latest)
    if title:
        matches = [item for item in previous if _normalized_workout_title(item) == title]
        if matches:
            return matches[:7], "normalized_title", title

    latest_exercises = _workout_exercise_keys(latest)
    if not latest_exercises:
        return [], "none", ""
    threshold = max(1, min(2, round(len(latest_exercises) * 0.4)))
    matches = []
    for item in previous:
        overlap = latest_exercises & _workout_exercise_keys(item)
        if len(overlap) >= threshold:
            matches.append({**item, "_exercise_overlap": len(overlap)})
    return matches[:7], "exercise_overlap" if matches else "none", f"{len(latest_exercises)} exercise(s)"


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _format_pct_decimal(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.0f}%"


def _pct_decimal(current: float, average: float | None) -> float | None:
    if average is None or average <= 0:
        return None
    return (current - average) / average


def _historical_set_for_index(sets: list[dict[str, Any]], set_index: int) -> dict[str, Any] | None:
    exact = [row for row in sets if int(row.get("set_index") or 0) == set_index]
    if exact:
        return exact[-1]
    lower = [row for row in sets if int(row.get("set_index") or 0) <= set_index]
    if lower:
        return sorted(lower, key=lambda row: int(row.get("set_index") or 0))[-1]
    return None


def _exercise_quality_rating(avg_pct: float | None, top_pct: float | None, reps_delta: float | None) -> str:
    values = [value for value in (avg_pct, top_pct) if value is not None]
    if not values:
        return "Insufficient comparison data"
    score_pct = sum(values) / len(values)
    if score_pct >= 0.06 or (top_pct is not None and top_pct >= 0.08):
        return "Improved"
    if score_pct >= -0.04 or (reps_delta is not None and reps_delta >= 1):
        return "Stable"
    if score_pct >= -0.12:
        return "Lighter"
    return "Needs review"


def _exercise_breakdown_for_workout(today_sets: list[dict[str, Any]], similar_workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    historical_by_workout: list[dict[str, list[dict[str, Any]]]] = []
    for workout in similar_workouts:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in _workout_set_rows(workout):
            grouped[str(row.get("exercise_key") or "")].append(row)
        if grouped:
            historical_by_workout.append(grouped)

    today_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exercise_names: dict[str, str] = {}
    for row in today_sets:
        key = str(row.get("exercise_key") or "")
        if not key:
            continue
        today_grouped[key].append(row)
        exercise_names.setdefault(key, str(row.get("exercise") or "Exercise"))

    breakdown: list[dict[str, Any]] = []
    for exercise_key, sets in today_grouped.items():
        sets.sort(key=lambda row: int(row.get("set_index") or 0))
        set_pcts = []
        same_weight_rep_deltas = []
        for today_set in sets:
            historical_volumes = []
            for workout_sets in historical_by_workout:
                candidate = _historical_set_for_index(workout_sets.get(exercise_key, []), int(today_set.get("set_index") or 0))
                if candidate is not None:
                    historical_volumes.append(float(candidate.get("volume") or 0))
            historical_avg = _average([value for value in historical_volumes if value > 0])
            set_pct = _pct_decimal(float(today_set.get("volume") or 0), historical_avg)
            if set_pct is not None:
                set_pcts.append(set_pct)

            matching_reps = []
            today_weight = float(today_set.get("weight") or 0)
            tolerance = max(0.5, today_weight * 0.005)
            for workout_sets in historical_by_workout:
                for historical_set in workout_sets.get(exercise_key, []):
                    if abs(float(historical_set.get("weight") or 0) - today_weight) <= tolerance:
                        matching_reps.append(float(historical_set.get("reps") or 0))
            avg_reps = _average([value for value in matching_reps if value > 0])
            if avg_reps is not None:
                same_weight_rep_deltas.append(float(today_set.get("reps") or 0) - avg_reps)

        top_today = max((float(row.get("volume") or 0) for row in sets), default=0)
        historical_top_sets = []
        historical_average_sets = []
        for workout_sets in historical_by_workout:
            prior_sets = workout_sets.get(exercise_key, [])
            if prior_sets:
                historical_top_sets.append(max(float(row.get("volume") or 0) for row in prior_sets))
                historical_average_sets.append(sum(float(row.get("volume") or 0) for row in prior_sets) / len(prior_sets))
        top_pct = _pct_decimal(top_today, _average([value for value in historical_top_sets if value > 0]))
        avg_set_pct = _average(set_pcts)
        if avg_set_pct is None:
            avg_today = sum(float(row.get("volume") or 0) for row in sets) / len(sets)
            avg_set_pct = _pct_decimal(avg_today, _average([value for value in historical_average_sets if value > 0]))
        reps_delta = _average(same_weight_rep_deltas)
        score_pct_values = [value for value in (avg_set_pct, top_pct) if value is not None]
        score_pct = _average(score_pct_values)
        if score_pct is not None and reps_delta is not None:
            score_pct += max(-0.03, min(0.03, reps_delta * 0.01))
        breakdown.append(
            {
                "exercise": exercise_names[exercise_key],
                "sets_compared": len(set_pcts),
                "avg_set_volume_pct_change": round(avg_set_pct, 3) if avg_set_pct is not None else None,
                "top_set_pct_change": round(top_pct, 3) if top_pct is not None else None,
                "reps_at_same_weight_delta": round(reps_delta, 1) if reps_delta is not None else None,
                "rating": _exercise_quality_rating(avg_set_pct, top_pct, reps_delta),
                "_score_pct": score_pct,
            }
        )
    return sorted(
        breakdown,
        key=lambda item: (
            item.get("_score_pct") is None,
            -abs(float(item.get("_score_pct") or 0)),
            str(item.get("exercise") or ""),
        ),
    )


def _workout_score_rating(score: int | None) -> tuple[str, str]:
    if score is None:
        return "Insufficient comparison data", "gray"
    if score >= 90:
        return "Excellent", "bright_green"
    if score >= 75:
        return "Strong", "green"
    if score >= 60:
        return "Solid", "green"
    if score >= 40:
        return "Light", "orange"
    return "Needs review", "red"


def _workout_has_deload_note(item: dict[str, Any]) -> bool:
    text = _clean_training_text(_workout_title_from_item(item))
    details = item.get("details") if isinstance(item.get("details"), list) else []
    text += " " + " ".join(_clean_training_text(row.get("notes")) for row in details if isinstance(row, dict))
    return any(term in text for term in ("deload", "light", "recovery", "easy", "technique"))


def _poor_recovery(latest_recovery: dict[str, Any] | None) -> bool:
    if not isinstance(latest_recovery, dict):
        return False
    score = latest_recovery.get("recovery_score")
    classification = _clean_training_text(latest_recovery.get("classification"))
    return (score not in {None, ""} and _number(score, 100) < 50) or classification in {"poor", "red", "low"}


def _workout_quality_empty_payload(
    summary: str,
    *,
    active_date: str = "",
    lifts_checked: int = 0,
    matched_date_count: int = 0,
    rating: str = "No recent lift",
    score_label: str = "No recent lift",
) -> dict[str, Any]:
    return {
        "status": "empty",
        "date": active_date,
        "rating": rating,
        "score": None,
        "score_label": score_label,
        "color": "gray",
        "confidence": "low",
        "summary": summary,
        "explanation": summary,
        "comparison_basis": "last_7_similar_workouts",
        "similar_workouts_used": 0,
        "exercise_breakdown": [],
        "comparison": {
            "basis": "last_7_similar_workouts",
            "avg_set_volume_pct_change": None,
            "sample_size": 0,
        },
        "debug": {
            "source": "/api/training/history",
            "latest_lift_found": False,
            "matched_by": "none",
            "excluded_cardio": True,
            "active_date": active_date,
            "lift_items_checked": lifts_checked,
            "matched_date_count": matched_date_count,
        },
        "source": "/api/training/history",
    }


def _workout_quality_payload(training_items: list[dict[str, Any]], latest_recovery: dict[str, Any] | None = None, active_date: str | None = None) -> dict[str, Any]:
    lifts = [dict(item) for item in training_items if _is_lift_history_item(item)]
    if not lifts:
        target_date = _date_text(active_date)
        if target_date:
            return _workout_quality_empty_payload(
                "No workout logged for this date.",
                active_date=target_date,
                lifts_checked=0,
                matched_date_count=0,
                rating="No workout logged",
                score_label="No workout",
            )
        return _workout_quality_empty_payload("No recent lifting workout found.", lifts_checked=0)

    target_date = _date_text(active_date)
    if target_date:
        target_lifts = [item for item in lifts if _date_text(item.get("date")) == target_date]
        if not target_lifts:
            return _workout_quality_empty_payload(
                "No workout logged for this date.",
                active_date=target_date,
                lifts_checked=len(lifts),
                matched_date_count=0,
                rating="No workout logged",
                score_label="No workout",
            )
        lifts_for_selection = target_lifts
    else:
        lifts_for_selection = lifts

    latest = lifts_for_selection[0]
    latest_date = _date_text(latest.get("date"))
    latest_id = str(latest.get("workout_id") or "")
    title = _workout_title_from_item(latest)
    split_payload = _workout_split_payload(latest)
    split_type = split_payload.get("split_type") or ""
    split_confidence = split_payload.get("split_confidence", 0.0)
    classification_reason = split_payload.get("classification_reason") or []
    total_sets = int(max(0, _number(latest.get("total_sets"), 0)))
    total_reps = _workout_reps(latest)
    total_volume = _round(_number(latest.get("total_volume"), 0))
    duration = _round(_number(latest.get("duration_minutes"), 0))
    muscle_groups = _workout_muscle_groups(latest)
    previous = [
        item
        for item in lifts
        if str(item.get("workout_id") or "") != latest_id
        and _date_text(item.get("date"))
        and _date_text(item.get("date")) < latest_date
    ]
    previous = sorted(previous, key=lambda item: (_date_text(item.get("date")), str(item.get("workout_id") or "")), reverse=True)
    similar, matched_by, match_label = _similar_lift_workouts(latest, previous)
    sample_size = len(similar)
    today_sets = _workout_set_rows(latest)
    exercise_breakdown = _exercise_breakdown_for_workout(today_sets, similar)
    comparable = [item for item in exercise_breakdown if item.get("_score_pct") is not None]
    avg_progression = _average([float(item["_score_pct"]) for item in comparable])
    compared_sets = sum(int(item.get("sets_compared") or 0) for item in exercise_breakdown)
    score = None
    if avg_progression is not None and comparable:
        improved = sum(1 for item in comparable if float(item.get("_score_pct") or 0) >= 0.025)
        declined = sum(1 for item in comparable if float(item.get("_score_pct") or 0) <= -0.06)
        consistency_adjustment = ((improved - declined) / len(comparable)) * 4
        score = int(round(max(20, min(98, 67 + avg_progression * 240 + consistency_adjustment))))
        if score < 55 and (_workout_has_deload_note(latest) or _poor_recovery(latest_recovery)):
            score = 55
    rating, color = _workout_score_rating(score)
    confidence = "high" if sample_size >= 7 and compared_sets >= max(3, len(comparable) * 2) else "medium" if sample_size >= 3 and compared_sets else "low"
    split_label = _split_display_label(match_label) if matched_by == "normalized_split" and match_label else "similar"
    if avg_progression is None:
        summary = "Insufficient comparison data for set-level workout quality."
        comparison_text = "Need prior similar lifting workouts with comparable weighted sets."
    else:
        workout_noun = "workout" if sample_size == 1 else "workouts"
        workout_label = f"{split_label} {workout_noun}" if split_label != "similar" else f"similar {workout_noun}"
        summary = f"Average set volume {_format_pct_decimal(avg_progression)} vs last {sample_size} {workout_label}."
        comparison_text = f"{compared_sets} set comparison{'s' if compared_sets != 1 else ''} across {len(comparable)} exercise{'s' if len(comparable) != 1 else ''}."
    visible_breakdown = [{key: value for key, value in item.items() if key != "_score_pct"} for item in exercise_breakdown]
    return {
        "status": "ok",
        "date": latest_date,
        "workout_id": latest_id,
        "title": title,
        "workout_type": title,
        "classification": "lift",
        "classification_label": latest.get("classification_label") or "Lift",
        "split_type": split_type,
        "split_confidence": split_confidence,
        "classification_reason": classification_reason,
        "rating": rating,
        "score": score,
        "score_label": f"{score}/100" if score is not None else rating,
        "color": color,
        "confidence": confidence,
        "summary": summary,
        "explanation": summary,
        "total_sets": total_sets,
        "total_reps": total_reps,
        "total_volume": total_volume,
        "duration_minutes": duration,
        "muscle_groups": muscle_groups,
        "comparison_basis": "last_7_similar_workouts",
        "similar_workouts_used": sample_size,
        "exercise_breakdown": visible_breakdown,
        "comparison": {
            "basis": "last_7_similar_workouts",
            "avg_set_volume_pct_change": round(avg_progression, 3) if avg_progression is not None else None,
            "sample_size": sample_size,
            "summary": comparison_text,
        },
        "debug": {
            "source": "/api/training/history",
            "latest_lift_found": True,
            "history_items_checked": len(training_items),
            "lift_items_checked": len(lifts),
            "active_date": target_date,
            "matched_date_count": len(lifts_for_selection),
            "matched_by": matched_by,
            "match_label": match_label,
            "split_type": split_type,
            "split_confidence": split_confidence,
            "classification_reason": classification_reason,
            "split_matched_by": split_payload.get("matched_by") or "none",
            "excluded_cardio": True,
            "today_sets_scored": len(today_sets),
            "sets_compared": compared_sets,
        },
        "source": "/api/training/history",
    }


def _date_text(value: Any) -> str:
    text = str(value or "").strip()[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except ValueError:
        return ""


def _recent_rows(rows: list[dict[str, Any]], today: str, days: int) -> list[dict[str, Any]]:
    end = pd.to_datetime(today, errors="coerce")
    if pd.isna(end):
        end = pd.Timestamp.today().normalize()
    start = end - pd.Timedelta(days=max(0, days - 1))
    recent: list[dict[str, Any]] = []
    for row in rows:
        row_date = pd.to_datetime(_date_text(row.get("date")), errors="coerce")
        if not pd.isna(row_date) and start <= row_date <= end:
            recent.append(row)
    return recent


def _macro_score(actual: float, target: float, *, protein: bool = False) -> float | None:
    if target <= 0:
        return None
    if protein:
        deviation = max(0.0, target - actual) / target
        if actual > target * 1.4:
            deviation = max(deviation, (actual - target * 1.4) / target)
    else:
        deviation = abs(actual - target) / target
    return max(0.0, min(100.0, 100 - deviation * 100))


def _daily_adherence_score(row: dict[str, Any]) -> tuple[float | None, dict[str, float | None]]:
    fields = {
        "calories": ("total_calories", "target_calories", 0.35, False),
        "protein": ("total_protein", "target_protein", 0.30, True),
        "carbs": ("total_carbs", "target_carbs", 0.20, False),
        "fat": ("total_fat", "target_fat", 0.15, False),
    }
    weighted = 0.0
    weight_total = 0.0
    components: dict[str, float | None] = {}
    for name, (actual_key, target_key, weight, protein) in fields.items():
        score = _macro_score(_number(row.get(actual_key), 0), _number(row.get(target_key), 0), protein=protein)
        components[name] = round(score, 1) if score is not None else None
        if score is not None:
            weighted += score * weight
            weight_total += weight
    if weight_total <= 0:
        stored = row.get("adherence_score")
        if stored not in {None, ""}:
            return _number(stored, 0), components
        return None, components
    return round(weighted / weight_total, 1), components


def _finalized_nutrition_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    finalized = []
    for row in rows:
        if _date_text(row.get("date")) and row.get("nutrition_logged") is not False and row.get("logged_day") is not False:
            is_finalized = row.get("finalized") is True or str(row.get("status") or "").lower() == "finalized"
            has_targets = _number(row.get("target_calories"), 0) > 0
            if is_finalized and has_targets:
                finalized.append(row)
    return sorted(finalized, key=lambda item: _date_text(item.get("date")))


def _macro_adherence_payload(nutrition_rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    finalized = _finalized_nutrition_rows(nutrition_rows)
    recent = _recent_rows(finalized, today, 14)
    window_dates = {
        (pd.to_datetime(today) - pd.Timedelta(days=offset)).date().isoformat()
        for offset in range(14)
    }
    logged_dates = {_date_text(row.get("date")) for row in recent}
    missing_days = len(window_dates - logged_dates)
    daily = []
    component_values: dict[str, list[float]] = {"calories": [], "protein": [], "carbs": [], "fat": []}
    calorie_deltas = []
    for row in recent:
        score, components = _daily_adherence_score(row)
        if score is None:
            continue
        for key, value in components.items():
            if value is not None:
                component_values[key].append(value)
        target_calories = _number(row.get("target_calories"), 0)
        if target_calories > 0:
            calorie_deltas.append((_number(row.get("total_calories"), 0) - target_calories) / target_calories * 100)
        daily.append(
            {
                "date": _date_text(row.get("date")),
                "score": round(score, 1),
                **{key: value for key, value in components.items() if value is not None},
            }
        )
    if not daily:
        return {
            "weekly_score": None,
            "adherence_percent": None,
            "status": "insufficient data",
            "confidence": "low",
            "consistency": "insufficient data",
            "logged_days": 0,
            "missing_days": missing_days,
            "summary": "Insufficient finalized nutrition data.",
            "components": {},
            "daily": [],
            "correlations": [],
        }
    weekly_score = round(sum(item["score"] for item in daily) / len(daily), 1)
    avg_delta = sum(calorie_deltas) / len(calorie_deltas) if calorie_deltas else 0
    status = "on-target" if abs(avg_delta) <= 5 else "under" if avg_delta < -5 else "over"
    consistency = "consistent" if weekly_score >= 90 else "solid" if weekly_score >= 80 else "variable" if weekly_score >= 65 else "inconsistent"
    confidence = "high" if len(daily) >= 10 and missing_days <= 2 else "medium" if len(daily) >= 5 else "low"
    components = {
        key: round(sum(values) / len(values), 1) if values else None
        for key, values in component_values.items()
    }
    best_components = [key for key, value in components.items() if value is not None and value >= 85]
    summary = f"{weekly_score:.0f}% adherence. "
    if status == "on-target":
        summary += "Calories are near target"
    elif status == "under":
        summary += "Calories are trending under target"
    else:
        summary += "Calories are trending over target"
    if "protein" in best_components:
        summary += " and protein is consistent."
    else:
        summary += "."
    if missing_days:
        summary += f" {missing_days} missing day{'s' if missing_days != 1 else ''} lowers confidence."
    return {
        "weekly_score": weekly_score,
        "adherence_percent": weekly_score,
        "status": status,
        "confidence": confidence,
        "consistency": consistency,
        "logged_days": len(daily),
        "missing_days": missing_days,
        "summary": summary,
        "components": components,
        "daily": daily[-56:],
        "correlations": [],
    }


def _bodyweight_trend_payload(body_rows: list[dict[str, Any]], today: str) -> dict[str, Any]:
    usable = []
    for row in _recent_rows(body_rows, today, 35):
        weight = _number(row.get("bodyweight"), 0)
        if weight > 0:
            usable.append({"date": _date_text(row.get("date")), "bodyweight": weight, "body_fat_percent": row.get("body_fat_percent")})
    usable.sort(key=lambda item: item["date"])
    if len(usable) < 4:
        return {"status": "insufficient data", "weekly_change_lb": None, "lean_mass_weekly_change_lb": None, "days": len(usable)}
    first = usable[0]
    last = usable[-1]
    elapsed_days = max(1, (pd.to_datetime(last["date"]) - pd.to_datetime(first["date"])).days)
    weekly_change = (last["bodyweight"] - first["bodyweight"]) / elapsed_days * 7
    lean_first = None
    lean_last = None
    if first.get("body_fat_percent") not in {None, ""} and last.get("body_fat_percent") not in {None, ""}:
        lean_first = first["bodyweight"] * (1 - _number(first.get("body_fat_percent"), 0) / 100)
        lean_last = last["bodyweight"] * (1 - _number(last.get("body_fat_percent"), 0) / 100)
    lean_weekly = ((lean_last - lean_first) / elapsed_days * 7) if lean_first is not None and lean_last is not None else None
    return {
        "status": "ready",
        "weekly_change_lb": round(weekly_change, 2),
        "lean_mass_weekly_change_lb": round(lean_weekly, 2) if lean_weekly is not None else None,
        "days": elapsed_days,
        "latest_weight": _round(last["bodyweight"]),
    }


def _training_plateau_payload(training_rows: list[dict[str, Any]], body_rows: list[dict[str, Any]], goals: dict[str, Any], today: str) -> dict[str, Any]:
    rows = []
    for row in training_rows:
        if not _date_text(row.get("date")) or not str(row.get("exercise") or "").strip():
            continue
        reps = _number(row.get("reps"), 0)
        weight = _number(row.get("weight"), 0)
        sets = _number(row.get("sets"), 0)
        if reps <= 0 or weight <= 0 or sets <= 0:
            continue
        estimated = weight * (1 + reps / 30)
        rows.append({**row, "date": _date_text(row.get("date")), "estimated_1rm": estimated, "volume": sets * reps * weight})
    alerts = []
    if rows:
        frame = pd.DataFrame(rows)
        frame["date_dt"] = pd.to_datetime(frame["date"], errors="coerce")
        for exercise, history in frame.groupby("exercise"):
            history = history.sort_values("date_dt")
            daily = history.groupby("date", as_index=False).agg(date_dt=("date_dt", "max"), estimated_1rm=("estimated_1rm", "max"), volume=("volume", "sum"), reps=("reps", "max"))
            if len(daily) < 6:
                continue
            recent = daily.tail(3)
            previous = daily.iloc[-6:-3]
            weeks = max(1, round((recent["date_dt"].max() - previous["date_dt"].min()).days / 7))
            if weeks < 3:
                continue
            gap_days = int((recent["date_dt"].min() - previous["date_dt"].max()).days)
            if gap_days > 14:
                continue
            if abs(float(recent["reps"].mean() - previous["reps"].mean())) > 3:
                continue
            strength_change = _pct_change(float(recent["estimated_1rm"].mean()), float(previous["estimated_1rm"].mean()))
            volume_change = _pct_change(float(recent["volume"].mean()), float(previous["volume"].mean()))
            reps_delta = float(recent["reps"].mean() - previous["reps"].mean())
            if volume_change is not None and volume_change <= -30:
                continue
            if strength_change is not None and strength_change <= -3:
                signal = "performance decline"
                severity = "medium"
                message = f"{exercise} estimated 1RM is down {abs(strength_change):.1f}% over ~{weeks} weeks."
            elif strength_change is not None and abs(strength_change) < 1.5 and reps_delta <= 0 and weeks >= 3:
                signal = "possible plateau"
                severity = "medium"
                message = f"{exercise} top strength/reps are flat for ~{weeks} weeks."
            elif volume_change is not None and volume_change < -15 and weeks >= 3:
                signal = "volume decline"
                severity = "low"
                message = f"{exercise} volume is down {abs(volume_change):.1f}% over ~{weeks} weeks."
            else:
                continue
            alerts.append(
                {
                    "type": "exercise",
                    "name": str(exercise),
                    "muscle_group": str(history.get("muscle_group", pd.Series([""])).iloc[-1] or ""),
                    "signal": signal,
                    "severity": severity,
                    "duration_weeks": weeks,
                    "message": message,
                    "estimated_1rm_change_pct": round(strength_change, 1) if strength_change is not None else None,
                    "volume_change_pct": round(volume_change, 1) if volume_change is not None else None,
                    "reps_at_same_weight_delta": round(reps_delta, 1),
                }
            )
            if len(alerts) >= 2:
                break
    body_trend = _bodyweight_trend_payload(body_rows, today)
    goal_text = str(goals.get("goal_type") or "").lower()
    if "bulk" in goal_text and body_trend.get("weekly_change_lb") is not None and abs(_number(body_trend.get("weekly_change_lb"), 0)) < 0.1 and int(body_trend.get("days") or 0) >= 21:
        alerts.append(
            {
                "type": "bodyweight",
                "name": "Lean bulk bodyweight",
                "muscle_group": "",
                "signal": "possible plateau",
                "severity": "low",
                "duration_weeks": max(3, round(int(body_trend.get("days") or 21) / 7)),
                "message": "Bodyweight trend is flat during a lean bulk window.",
                "estimated_1rm_change_pct": None,
                "volume_change_pct": None,
                "reps_at_same_weight_delta": None,
            }
        )
    alerts = alerts[:2]
    if alerts:
        return {"status": "possible plateau", "summary": "Possible plateau detected.", "top_alerts": alerts, "details": alerts}
    if len(rows) >= 12 or int(body_trend.get("days") or 0) >= 21:
        return {"status": "clear", "summary": "No plateau detected.", "top_alerts": [], "details": []}
    return {"status": "insufficient data", "summary": "Insufficient data for conservative plateau detection.", "top_alerts": [], "details": []}


def _personal_baseline_payload(
    nutrition_rows: list[dict[str, Any]],
    training_items: list[dict[str, Any]],
    body_rows: list[dict[str, Any]],
    recovery_rows: list[dict[str, Any]],
    sleep_rows: list[dict[str, Any]],
    today: str,
) -> dict[str, Any]:
    finalized = _recent_rows(_finalized_nutrition_rows(nutrition_rows), today, 35)
    training_days = {_date_text(row.get("date")) for row in training_items if _date_text(row.get("date"))}
    body_days = {_date_text(row.get("date")) for row in _recent_rows(body_rows, today, 35) if _number(row.get("bodyweight"), 0) > 0}
    recovery_days = {_date_text(row.get("date")) for row in _recent_rows([*recovery_rows, *sleep_rows], today, 35) if _date_text(row.get("date"))}
    nutrition_days = len({_date_text(row.get("date")) for row in finalized})
    data_points = nutrition_days + len(training_days) + len(body_days) + len(recovery_days)
    if nutrition_days >= 28 and len(training_days) >= 12 and len(body_days) >= 14:
        confidence = "high"
        title = "Baseline confidence strong"
        summary = f"{nutrition_days} nutrition days, {len(training_days)} training days, and {len(body_days)} weigh-ins are available."
        status = "ready"
    elif nutrition_days >= 14 and len(training_days) >= 6 and len(body_days) >= 7:
        confidence = "medium"
        title = "Baseline confidence improving"
        summary = f"{nutrition_days} finalized nutrition days plus recent training/bodyweight data are available."
        status = "building"
    else:
        confidence = "low"
        title = "Building baseline"
        missing_nutrition = max(0, 14 - nutrition_days)
        summary = f"Needs {missing_nutrition} more finalized nutrition day{'s' if missing_nutrition != 1 else ''} plus consistent training/bodyweight history."
        status = "insufficient data" if data_points < 8 else "building"
    insight = {"title": title, "summary": summary, "confidence": confidence, "metric": "data_completeness"}
    return {
        "status": status,
        "confidence": confidence,
        "summary": summary,
        "dashboard_insight": insight,
        "insights": [insight],
        "data_points": data_points,
        "counts": {
            "nutrition_days": nutrition_days,
            "training_days": len(training_days),
            "bodyweight_days": len(body_days),
            "recovery_days": len(recovery_days),
        },
    }


def _nutrition_recommendation_payload(
    *,
    latest_history: dict[str, Any],
    targets: dict[str, Any],
    macro_adherence: dict[str, Any],
    plateau_watch: dict[str, Any],
    body_trend: dict[str, Any],
    goals: dict[str, Any],
) -> dict[str, Any]:
    adaptive = latest_history.get("adaptive_recommendation") if isinstance(latest_history, dict) else None
    if isinstance(adaptive, dict) and adaptive:
        adjustment = int(round(_number(adaptive.get("calorieAdjustment"), 0)))
        trace = adaptive.get("recommendation_trace") if isinstance(adaptive.get("recommendation_trace"), dict) else {}
        decision = str(trace.get("decision") or ("increase" if adjustment > 0 else "decrease" if adjustment < 0 else "hold"))
        reasons = adaptive.get("reasoning") if isinstance(adaptive.get("reasoning"), list) else trace.get("main_reasons")
        primary = str((reasons or ["Latest recommendation snapshot loaded."])[0])
        confidence = str(adaptive.get("confidenceLevel") or (adaptive.get("confidence") or {}).get("overall") or "low")
        title = "Hold targets" if adjustment == 0 else f"{'Increase' if adjustment > 0 else 'Decrease'} {adjustment:+d} kcal"
        return {
            "status": "ok",
            "decision": decision,
            "title": title,
            "calorie_adjustment": adjustment,
            "confidence": confidence,
            "data_quality_score": adaptive.get("dataQualityScore"),
            "primary_reason": primary,
            "source": "/api/recommendations/latest",
            "engine_snapshot_available": True,
        }

    confidence = str(macro_adherence.get("confidence") or "low")
    body_change = body_trend.get("weekly_change_lb")
    plateau_status = str(plateau_watch.get("status") or "")
    macro_status = str(macro_adherence.get("status") or "")
    goal_text = str(goals.get("goal_type") or "").lower()
    adjustment = 0
    decision = "hold"
    if confidence == "low":
        reason = "Insufficient finalized nutrition history for a calorie change."
    elif "bulk" in goal_text and body_change is not None and _number(body_change, 0) < 0.1 and macro_status in {"on-target", "under"}:
        adjustment = 100
        decision = "increase"
        reason = "Bodyweight is flat during lean bulk while intake is not over target."
    elif macro_status == "over" and body_change is not None and _number(body_change, 0) > 0.6:
        adjustment = -100
        decision = "decrease"
        reason = "Calories are over target and bodyweight is rising faster than expected."
    elif plateau_status == "possible plateau" and macro_status != "over":
        adjustment = 0
        reason = "Possible plateau detected, but nutrition confidence favors holding before changing targets."
    else:
        reason = "Current logged nutrition and trend data do not justify changing targets."
    title = "Hold targets" if adjustment == 0 else f"{'Increase' if adjustment > 0 else 'Decrease'} {adjustment:+d} kcal"
    return {
        "status": "ok" if confidence != "low" else "insufficient data",
        "decision": decision,
        "title": title,
        "calorie_adjustment": adjustment,
        "confidence": confidence,
        "data_quality_score": {"high": 85, "medium": 65, "low": 35}.get(confidence, 35),
        "primary_reason": reason,
        "source": "lightweight_dashboard_snapshot",
        "engine_snapshot_available": False,
        "target_calories": targets.get("target_calories"),
    }


def _adaptive_from_optimization_signals(signals: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    nutrition = signals["nutrition_recommendation"]
    adjustment = int(nutrition.get("calorie_adjustment") or 0)
    current = {
        "calories": _round(_number(targets.get("target_calories"), 0)),
        "protein": _round(_number(targets.get("protein_grams"), 0)),
        "carbs": _round(_number(targets.get("carb_grams"), 0)),
        "fat": _round(_number(targets.get("fat_grams"), 0)),
    }
    recommended = {**current, "calories": current["calories"] + adjustment}
    return {
        "recommendedCalories": recommended["calories"],
        "recommendedProtein": recommended["protein"],
        "recommendedCarbs": recommended["carbs"],
        "recommendedFat": recommended["fat"],
        "caloriesTarget": recommended["calories"],
        "proteinTarget": recommended["protein"],
        "carbsTarget": recommended["carbs"],
        "fatTarget": recommended["fat"],
        "calorieAdjustment": adjustment,
        "macroAdjustment": {"calories": adjustment, "protein": 0, "carbs": 0, "fat": 0},
        "macroChanges": {"calories": adjustment, "protein": 0, "carbs": 0, "fat": 0},
        "dayType": "standard",
        "dayTypeAdjustment": {"type": "standard", "reason": "Using lightweight dashboard signals.", "calorie_delta": 0, "carb_delta": 0, "fat_delta": 0, "confidence": nutrition.get("confidence", "low"), "applied_delta": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}, "adjusted_targets": current},
        "confidence": signals["confidence"],
        "confidenceLevel": nutrition.get("confidence", "low"),
        "dataQualityScore": nutrition.get("data_quality_score", signals["confidence"].get("score", 0)),
        "reasoning": [nutrition.get("primary_reason") or "Insufficient data."],
        "warnings": [] if nutrition.get("status") == "ok" else ["More finalized nutrition, bodyweight, and training history will improve confidence."],
        "detectedTrends": [signals["plateau_watch"].get("summary", "")],
        "missingDataWarnings": signals["confidence"].get("missing_data", []),
        "nextReviewDate": "",
        "currentTarget": current,
        "recommendedTargets": {"target_calories": recommended["calories"], "protein_grams": recommended["protein"], "carb_grams": recommended["carbs"], "fat_grams": recommended["fat"]},
        "baselineRecommendedTargets": targets,
        "dayTypeAdjustedTargets": targets,
        "signals": {
            "bodyComposition": {"status": "dashboard_snapshot", "lean_gain_quality": "unknown"},
            "performance": {"label": signals["plateau_watch"].get("status", "insufficient data"), "confidence": nutrition.get("confidence", "low"), "summary": signals["plateau_watch"].get("summary", ""), "recommendation": nutrition.get("decision", "hold"), "drivers": [], "muscle_group_drivers": []},
            "recovery": {"status": "dashboard_snapshot", "label": "Recent recovery", "confidence": "low", "summary": "Recovery is included in baseline confidence.", "recommendation": "maintain", "drivers": []},
            "trainingLoad": {"status": "dashboard_snapshot", "summary": signals["plateau_watch"].get("summary", "")},
            "runningLoad": {"status": "dashboard_snapshot", "summary": "Recent runs are excluded from lift quality selection.", "interference_risk": "unknown"},
            "nutrition": {"adherence": signals["macro_adherence"].get("status"), "days": signals["macro_adherence"].get("logged_days"), "missing_days_14": signals["macro_adherence"].get("missing_days")},
            "dataQuality": signals["confidence"],
            "historicalLearning": {"detectedTrends": [signals["personal_baseline"].get("summary", "")]},
        },
        "recommendation_trace": {"decision": nutrition.get("decision", "hold"), "calorie_change": adjustment, "main_reasons": [nutrition.get("primary_reason", "")], "what_would_change_decision": signals["confidence"].get("missing_data", [])},
        "strategy": "Lightweight dashboard optimization snapshot",
    }


def _optimization_signals_payload(
    *,
    nutrition_history_items: list[dict[str, Any]],
    training_items: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
    body_rows: list[dict[str, Any]],
    recovery_rows: list[dict[str, Any]],
    sleep_rows: list[dict[str, Any]],
    goals: dict[str, Any],
    targets: dict[str, Any],
    today: str,
) -> dict[str, Any]:
    macro_adherence = _macro_adherence_payload(nutrition_history_items, today)
    plateau_watch = _training_plateau_payload(training_rows, body_rows, goals, today)
    personal_baseline = _personal_baseline_payload(nutrition_history_items, training_items, body_rows, recovery_rows, sleep_rows, today)
    body_trend = _bodyweight_trend_payload(body_rows, today)
    latest_recommendation = fetch_latest_document("nutrition_recommendation_history", {})
    nutrition_recommendation = _nutrition_recommendation_payload(
        latest_history=latest_recommendation,
        targets=targets,
        macro_adherence=macro_adherence,
        plateau_watch=plateau_watch,
        body_trend=body_trend,
        goals=goals,
    )
    confidence_values = [nutrition_recommendation.get("confidence"), macro_adherence.get("confidence"), personal_baseline.get("confidence")]
    rank = {"high": 3, "medium": 2, "low": 1}
    confidence_score = round(sum(rank.get(str(value), 1) for value in confidence_values) / max(1, len(confidence_values)) / 3 * 100)
    missing = []
    if macro_adherence.get("missing_days"):
        missing.append(f"{macro_adherence['missing_days']} nutrition day(s) missing in the last 14 days.")
    counts = personal_baseline.get("counts", {})
    if int(counts.get("nutrition_days") or 0) < 14:
        missing.append("More finalized nutrition summaries needed.")
    if int(counts.get("training_days") or 0) < 6:
        missing.append("More recent lifting history needed.")
    overall = "high" if confidence_score >= 75 else "medium" if confidence_score >= 50 else "low"
    return {
        "nutrition_recommendation": nutrition_recommendation,
        "macro_adherence": macro_adherence,
        "plateau_watch": plateau_watch,
        "personal_baseline": personal_baseline,
        "confidence": {"overall": overall, "score": confidence_score, "missing_data": missing},
        "debug": {
            "source": "dashboard_core_lightweight",
            "engine_ran": False,
            "openai_called": False,
            "training_history_limit": 50,
            "full_hevy_scan": False,
        },
    }


def _lift_performance_payload(
    *,
    today: str,
    latest_workout: dict[str, Any] | None,
    training_items: list[dict[str, Any]],
    training_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    planned = planned_training_for_date(today, profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)
    day_summary = {
        "planned": planned,
        "planned_workout": planned["display_label"],
        "completed_workouts": [],
        "completed_summary": "",
        "has_lift": False,
        "has_run": False,
        "sources": [],
        "schedule_match": "missed",
        "match_label": "Workout not logged yet",
        "planned_split_type": planned.get("split_type") or "",
        "completed_split_types": [],
        "split_match": False,
        "classification_reason": [],
        "cardio_indicator": "Planned run/cardio" if planned["is_run_day"] else None,
        "extra_run_added": False,
        "recovery_status_relative_to_plan": "Plan pending",
    }
    today_items = [item for item in training_items if str(item.get("date") or "") == today]
    completed_workouts = list(
        dict.fromkeys(
            str(item.get("workout_type") or item.get("classification_label") or "Workout").strip()
            for item in today_items
            if str(item.get("workout_type") or item.get("classification_label") or "").strip()
        )
    )
    if completed_workouts:
        planned_label = str((day_summary.get("planned") or {}).get("label") or "").lower()
        completed_text = " ".join(completed_workouts).lower()
        has_lift = any(str(item.get("classification") or "") in {"lift", "lift_cardio"} for item in today_items)
        has_run = any(str(item.get("classification") or "") in {"run", "cardio", "lift_cardio"} for item in today_items)
        split_payloads = [_workout_split_payload(item) for item in today_items if str(item.get("classification") or "") in {"lift", "lift_cardio"}]
        completed_split_types = list(dict.fromkeys(str(item.get("split_type") or "") for item in split_payloads if item.get("split_type")))
        planned_split_type = str((day_summary.get("planned") or {}).get("split_type") or "")
        split_match = bool(planned_split_type and planned_split_type in completed_split_types)
        label_match = bool(planned_label and planned_label in completed_text)
        if planned.get("is_run_day"):
            schedule_match = "matched" if has_run else "different"
        elif planned.get("is_strength_day"):
            strength_match = split_match or (not planned_split_type and label_match)
            schedule_match = "matched_plus_extra_run" if strength_match and has_run else "matched" if strength_match else "different"
        else:
            schedule_match = "logged"
        match_label = {
            "matched": "Matched schedule",
            "matched_plus_extra_run": "Matched + recovery run added",
            "different": "Different from planned",
            "logged": "Logged",
        }.get(schedule_match, "Logged")
        day_summary = {
            **day_summary,
            "completed_workouts": completed_workouts,
            "completed_summary": " + ".join(completed_workouts),
            "has_lift": has_lift,
            "has_run": has_run,
            "sources": sorted({str(item.get("source") or "manual").capitalize() for item in today_items if item.get("source")}),
            "schedule_match": schedule_match,
            "match_label": match_label,
            "completed_split_types": completed_split_types,
            "split_match": split_match,
            "classification_reason": list(
                dict.fromkeys(
                    reason
                    for item in split_payloads
                    for reason in (item.get("classification_reason") or [])
                    if reason
                )
            )[:6],
            "cardio_indicator": "Run/cardio logged" if has_run else None,
            "extra_run_added": bool(has_run and has_lift),
            "recovery_status_relative_to_plan": "Extra run added" if schedule_match == "matched_plus_extra_run" else "On plan" if schedule_match == "matched" else match_label,
        }
    elif training_rows:
        training_df = pd.DataFrame(training_rows)
        day_summary = summarize_training_day(training_df, today, profile=DEFAULT_RECURRING_SCHEDULE_PROFILE)
    completed_summary = str(day_summary.get("completed_summary") or "")
    summary = completed_summary or (latest_workout.get("workout_type") if latest_workout else "Workout not logged yet")
    today_workout = latest_workout if latest_workout and latest_workout.get("date") == today else None
    return {
        "status": f"Latest: {latest_workout.get('workout_type')}" if latest_workout else "Workout not logged yet",
        "summary": summary,
        "comparison": None,
        "today_volume": today_workout.get("total_volume") if today_workout else None,
        "percent_vs_average": None,
        "planned_workout": day_summary.get("planned_workout", "Training"),
        "completed_workouts": day_summary.get("completed_workouts", []),
        "completed_summary": completed_summary,
        "schedule_match": day_summary.get("schedule_match", "missed"),
        "match_label": day_summary.get("match_label", "Workout not logged yet"),
        "planned_split_type": day_summary.get("planned_split_type") or (day_summary.get("planned") or {}).get("split_type") or "",
        "completed_split_types": day_summary.get("completed_split_types", []),
        "split_match": bool(day_summary.get("split_match")),
        "classification_reason": day_summary.get("classification_reason", []),
        "sources": day_summary.get("sources", []),
        "has_run": bool(day_summary.get("has_run")),
        "has_lift": bool(day_summary.get("has_lift")),
        "cardio_indicator": day_summary.get("cardio_indicator"),
        "extra_run_added": bool(day_summary.get("extra_run_added")),
        "recovery_status_relative_to_plan": day_summary.get("recovery_status_relative_to_plan"),
    }


def _recovery_payload(recovery_rows: list[dict[str, Any]], sleep_rows: list[dict[str, Any]], target_calories: float | int | None = None) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    recovery_df = pd.DataFrame(recovery_rows)
    sleep_df = pd.DataFrame(sleep_rows)
    measured_fields = ("sleep_hours", "sleep_quality", "fatigue", "soreness", "stress", "motivation", "hrv", "resting_hr")
    has_measured_recovery = any(
        any(row.get(field) not in {None, ""} for field in measured_fields)
        for row in recovery_rows
    )
    try:
        analytics = calculate_recovery_score(recovery_df, target_calories=_number(target_calories, 0) or 0) if recovery_rows and has_measured_recovery else pd.DataFrame()
    except Exception:
        analytics = pd.DataFrame()

    trend: list[dict[str, Any]] = []
    latest_recovery = None
    if not analytics.empty:
        analytics = analytics.sort_values("date")
        for row in analytics.tail(14).to_dict(orient="records"):
            item = {
                "date": str(row.get("date"))[:10],
                "recovery_score": _round(_number(row.get("recovery_score"), 0)),
                "classification": str(row.get("classification") or "unknown"),
            }
            trend.append(item)
        latest = analytics.iloc[-1].to_dict()
        latest_recovery = {
            "recovery_score": _round(_number(latest.get("recovery_score"), 0)),
            "classification": str(latest.get("classification") or "unknown"),
            "explanation": str(latest.get("explanation") or latest.get("reason") or ""),
        }
    elif recovery_rows and has_measured_recovery:
        latest_row = sorted(recovery_rows, key=lambda row: str(row.get("date") or ""))[-1]
        score = max(
            0,
            min(
                100,
                100
                - _number(latest_row.get("fatigue"), 0) * 7
                - _number(latest_row.get("soreness"), 0) * 4
                - _number(latest_row.get("stress"), 0) * 4
                + _number(latest_row.get("motivation"), 0) * 3,
            ),
        )
        latest_recovery = {"recovery_score": _round(score), "classification": "manual", "explanation": "Manual recovery check-in."}
        trend = [{"date": str(row.get("date") or ""), "recovery_score": _round(score), "classification": "manual"} for row in recovery_rows[-14:]]

    sleep_trend = []
    for row in sorted(sleep_rows, key=lambda item: str(item.get("date") or ""))[-14:]:
        hours = _number(row.get("sleep_hours"), 0)
        if not hours:
            hours = _number(row.get("durationMinutes"), 0) / 60
        if hours:
            sleep_trend.append({"date": str(row.get("date") or ""), "sleep_hours": _round(hours)})
    if not sleep_trend:
        for row in sorted(recovery_rows, key=lambda item: str(item.get("date") or ""))[-14:]:
            hours = _number(row.get("sleep_hours"), 0)
            if hours:
                sleep_trend.append({"date": str(row.get("date") or ""), "sleep_hours": _round(hours)})

    hrv = [
        {"date": str(row.get("date") or ""), "hrv": _round(_number(row.get("hrv"), 0))}
        for row in sorted(recovery_rows, key=lambda item: str(item.get("date") or ""))[-14:]
        if row.get("hrv") not in {None, ""}
    ]
    resting_hr = [
        {"date": str(row.get("date") or ""), "resting_hr": _round(_number(row.get("resting_hr"), row.get("restingHeartRate") or 0))}
        for row in sorted([*recovery_rows, *sleep_rows], key=lambda item: str(item.get("date") or ""))[-14:]
        if row.get("resting_hr") not in {None, ""} or row.get("restingHeartRate") not in {None, ""}
    ]
    connected = bool(recovery_rows or sleep_rows)
    latest_score = latest_recovery.get("recovery_score") if latest_recovery else None
    classification = latest_recovery.get("classification") if latest_recovery else "unknown"
    message = "Recovery data loaded from saved check-ins." if connected else "No recovery or sleep entries yet."
    data_mode = "measured recovery" if latest_score is not None else "insufficient data" if not connected else "inferred recovery"
    payload = {
        "connected": connected,
        "source": "manual" if recovery_rows else "sleep" if sleep_rows else "none",
        "data_mode": data_mode,
        "latest_score": latest_score,
        "trend": trend,
        "sleep": sleep_trend,
        "hrv": hrv,
        "resting_hr": resting_hr,
        "status": "ready" if connected else "missing",
        "classification": classification,
        "message": message,
        "extra_run_readiness": {
            "status": "insufficient_data" if not connected else "green" if _number(latest_score, 0) >= 70 else "yellow" if _number(latest_score, 0) >= 50 else "red",
            "message": "Recovery looks usable for normal training." if connected and _number(latest_score, 0) >= 70 else "Use recovery page check-ins to guide extra running." if connected else "Log recovery data for run readiness.",
            "recommended_run": "Optional easy run" if connected and _number(latest_score, 0) >= 70 else "Keep it easy" if connected else "Need recovery data",
            "reasoning": [message],
        },
    }
    return payload, latest_recovery, trend


def _target_macros(targets: dict[str, Any]) -> dict[str, int | float]:
    return {
        "calories": _round(_number(targets.get("target_calories"), 0)),
        "protein": _round(_number(targets.get("protein_grams"), 0)),
        "carbs": _round(_number(targets.get("carb_grams"), 0)),
        "fat": _round(_number(targets.get("fat_grams"), 0)),
    }


def _lean_bulk_placeholder(targets: dict[str, Any]) -> dict[str, Any]:
    return {
        "recommendation": "maintain",
        "calorie_change": 0,
        "new_target_calories": _round(_number(targets.get("target_calories"), 0)),
        "confidence": "low",
        "weekly_weight_change_pct": None,
        "fat_gain_risk_score": 0,
        "reasoning": ["Lean bulk analysis is deferred in dashboard core."],
        "next_check_in_days": 7,
        "details": {
            "seven_day_avg_weight": None,
            "fourteen_day_avg_weight": None,
            "calorie_average": None,
            "protein_average": None,
            "protein_target": targets.get("protein_grams"),
            "training_trend": "Need data",
            "recovery_trend": "Need data",
            "recovery_average": None,
            "target_weekly_gain_pct": targets.get("expected_weekly_weight_change"),
            "calorie_target_delta_average": None,
            "protein_consistency": None,
            "days_over_calorie_target": None,
            "days_under_calorie_target": None,
            "key_lift_trends": {},
            "performance_signal": {
                "label": "deferred",
                "confidence": "low",
                "summary": "Performance analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
                "muscle_group_drivers": [],
            },
            "recovery_signal": {
                "status": "deferred",
                "label": "Need data",
                "confidence": "low",
                "summary": "Recovery analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
            },
        },
    }


def _adaptive_placeholder(targets: dict[str, Any]) -> dict[str, Any]:
    macros = _target_macros(targets)
    return {
        "recommendedCalories": macros["calories"],
        "recommendedProtein": macros["protein"],
        "recommendedCarbs": macros["carbs"],
        "recommendedFat": macros["fat"],
        "caloriesTarget": macros["calories"],
        "proteinTarget": macros["protein"],
        "carbsTarget": macros["carbs"],
        "fatTarget": macros["fat"],
        "calorieAdjustment": 0,
        "macroAdjustment": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
        "macroChanges": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
        "dayType": "standard",
        "dayTypeAdjustment": {
            "type": "standard",
            "reason": "Adaptive analytics are disabled in dashboard core.",
            "calorie_delta": 0,
            "carb_delta": 0,
            "fat_delta": 0,
            "confidence": "low",
            "applied_delta": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0},
            "adjusted_targets": macros,
        },
        "carbTimingRecommendation": "",
        "confidence": "low",
        "dataQualityScore": 0,
        "reasoning": ["Adaptive analytics are disabled in dashboard core."],
        "warnings": [],
        "detectedTrends": [],
        "missingDataWarnings": [],
        "nextReviewDate": "",
        "strategy": "deferred",
        "currentTarget": macros,
        "recommendedTargets": targets,
        "baselineRecommendedTargets": targets,
        "dayTypeAdjustedTargets": targets,
        "signals": {
            "weight": {
                "status": "insufficient_data",
                "weekly_change_pct": None,
                "weekly_change_lb": None,
                "calorie_adjustment": 0,
                "confidence": "low",
                "reason": "Need bodyweight trend.",
            },
            "bodyComposition": {
                "status": "insufficient_data",
                "lean_gain_quality": "unknown",
                "latest_bodyweight": None,
                "latest_body_fat_percent": None,
                "latest_lean_mass": None,
                "latest_fat_mass": None,
                "weight_7_day_average": None,
                "weight_14_day_average": None,
                "weight_28_day_average": None,
                "weight_gain_rate_lb_per_week": None,
                "weight_gain_rate_pct_per_week": None,
                "lean_mass_trend_7": None,
                "lean_mass_trend_14": None,
                "lean_mass_trend_28": None,
                "fat_mass_trend_7": None,
                "fat_mass_trend_14": None,
                "fat_mass_trend_28": None,
                "body_fat_percent_trend_14": None,
                "body_fat_percent_trend_28": None,
                "data_points": 0,
                "body_fat_data_points": 0,
            },
            "performance": {
                "label": "deferred",
                "confidence": "low",
                "summary": "Performance analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
                "muscle_group_drivers": [],
            },
            "recovery": {
                "status": "deferred",
                "label": "Need data",
                "confidence": "low",
                "summary": "Recovery analytics are deferred in dashboard core.",
                "recommendation": "maintain",
                "drivers": [],
            },
            "trainingLoad": {"status": "deferred", "summary": "Training load analytics are deferred.", "hard_sets_per_week": 0, "weekly_training_minutes": 0},
            "runningLoad": {"status": "deferred", "summary": "Running load analytics are deferred.", "runs_per_week": 0, "weekly_mileage": 0, "interference_risk": "unknown"},
            "nutrition": {"days": 0, "calories": None, "protein": None, "carbs": None, "fat": None},
            "dataQuality": {"score": 0, "confidence": "low", "missingDataWarnings": []},
            "historicalLearning": {"detectedTrends": []},
        },
    }


def _fallback_payload(today: str, blocks: list[dict[str, Any]], *, started: float) -> dict[str, Any]:
    failed = [block for block in blocks if block.get("status") == "error"]
    return {
        "ok": False,
        "core_ready": False,
        "date": today,
        "food": {},
        "weight": {},
        "goals": {},
        "targets": {},
        "nutrition_today": {},
        "latest_workout": None,
        "counts": {},
        "debug": {
            "dashboard_status": "failed",
            "blocks": blocks,
            "errors": failed,
            "required_blocks": sorted(REQUIRED_BLOCKS),
            "required_blocks_failed": [block.get("block") for block in failed if block.get("block") in REQUIRED_BLOCKS],
            "generated_at": utc_now_iso(),
            "total_duration_ms": round((time.perf_counter() - started) * 1000, 1),
        },
    }


@router.get("/api/dashboard/core")
def dashboard_core(date: str | None = Query(default=None)) -> dict[str, Any]:
    started = time.perf_counter()
    app_local_date = _today_iso()
    server_utc_date = _server_utc_date()
    today = _normalize_dashboard_date(date)
    bundle = fetch_dashboard_core_bundle(today, body_limit=400, food_limit=200, recovery_limit=180, sleep_limit=180, include_training_summary=True)
    bundle_status = str(bundle.get("status") or "")
    bundle_ready = bundle_status in {"ok", "not_configured"}
    blocks = [
        {
            "block": "load_core_bundle",
            "name": "load_core_bundle",
            "status": "ok" if bundle_ready else "error",
            "duration_ms": bundle.get("duration_ms", 0),
            "message": bundle.get("message", "") or ("DATABASE_URL is not configured; using empty local shell data." if bundle_status == "not_configured" else ""),
            "error_type": bundle.get("error_type"),
        }
    ]
    if isinstance(bundle.get("blocks"), list):
        blocks.extend(bundle.get("blocks") or [])
    if not bundle_ready:
        return _fallback_payload(today, blocks, started=started)

    bundle_food_rows = bundle.get("food_rows") if isinstance(bundle.get("food_rows"), list) else []
    bundle_body_rows = bundle.get("body_rows") if isinstance(bundle.get("body_rows"), list) else []
    bundle_recovery_rows = bundle.get("recovery_rows") if isinstance(bundle.get("recovery_rows"), list) else []
    bundle_sleep_rows = bundle.get("sleep_rows") if isinstance(bundle.get("sleep_rows"), list) else []
    bundle_training_summary = bundle.get("training_summary") if isinstance(bundle.get("training_summary"), dict) else {}
    bundle_training_items = bundle_training_summary.get("items") if isinstance(bundle_training_summary.get("items"), list) else []

    from backend_new.routes.body_metrics import get_body_metrics
    from backend_new.routes.goals import get_goals
    from backend_new.routes.nutrition import get_nutrition_history, get_nutrition_today
    from backend_new.routes.recovery import get_recovery_logs, get_sleep_entries
    from backend_new.routes.training import training_history

    food_payload = _source_block(
        "food",
        "/api/nutrition/today",
        lambda: get_nutrition_today(today),
        {"date": today, "items": bundle_food_rows, "totals": _totals(bundle_food_rows), "targets": bundle.get("targets") or {}, "status": "fallback"},
        blocks,
    )
    nutrition_history_payload = _source_block(
        "nutrition_history",
        "/api/nutrition/history",
        lambda: get_nutrition_history(limit=30),
        {"items": [], "adherence": {}},
        blocks,
    )
    goals_payload = _source_block(
        "goals",
        "/api/goals",
        get_goals,
        {"goals": {**fallback_goals(), **(bundle.get("goals") if isinstance(bundle.get("goals"), dict) else {})}, "targets": bundle.get("targets") if isinstance(bundle.get("targets"), dict) else {}, "status": "fallback"},
        blocks,
    )
    body_payload = _source_block(
        "weight",
        "/api/body-metrics",
        lambda: get_body_metrics(limit=5000),
        {"items": bundle_body_rows, "canonical_items": bundle_body_rows, "raw_items": bundle_body_rows, "status": "fallback"},
        blocks,
    )
    training_payload = _source_block(
        "training",
        "/api/training/history",
        lambda: training_history(limit=50, days=180),
        {"items": bundle_training_items, "debug": {}, "status": "fallback"},
        blocks,
    )
    recovery_payload = _source_block(
        "recovery",
        "/api/recovery/logs",
        lambda: get_recovery_logs(limit=500),
        {"items": bundle_recovery_rows, "status": "fallback"},
        blocks,
    )
    sleep_payload = _source_block(
        "sleep",
        "/api/recovery/sleep",
        lambda: get_sleep_entries(limit=500),
        {"items": bundle_sleep_rows, "status": "fallback"},
        blocks,
    )

    food_rows = _safe_items(food_payload)
    nutrition_history_items = _safe_items(nutrition_history_payload)
    body_rows = _safe_items(body_payload, "canonical_items") or _safe_items(body_payload) or bundle_body_rows
    raw_body_rows = _safe_items(body_payload, "raw_items") or bundle_body_rows
    recovery_rows = _safe_items(recovery_payload)
    sleep_rows = _safe_items(sleep_payload)
    training_items = _safe_items(training_payload)
    training_rows = _training_rows_from_history(training_items)
    goals = {**fallback_goals(), **(goals_payload.get("goals") if isinstance(goals_payload.get("goals"), dict) else {})}
    targets = goals_payload.get("targets") if isinstance(goals_payload.get("targets"), dict) else _simple_targets(goals, bundle.get("targets") if isinstance(bundle.get("targets"), dict) else {})
    nutrition_today = food_payload.get("totals") if isinstance(food_payload.get("totals"), dict) else _totals(food_rows)
    latest_bodyweight, bodyweight_trend, weight = _weight_tile(body_rows, today)
    latest_workout = _latest_from_training_history(training_items)
    training_debug = training_payload.get("debug") if isinstance(training_payload.get("debug"), dict) else {}
    training_summary = {
        "status": training_payload.get("status") or "ok",
        "items": training_items,
        "latest_workout": latest_workout,
        "latest_workout_date": latest_workout.get("date") if latest_workout else "",
        "latest_workout_type": latest_workout.get("workout_type") if latest_workout else "",
        "recent_rows": training_debug.get("raw_rows_read", len(training_rows)),
        "total_rows": training_debug.get("raw_rows_read", len(training_rows)),
        "duration_ms": training_debug.get("duration_ms", 0),
        "source": "/api/training/history",
        "days": training_payload.get("days", 180),
        "limit_workouts": training_payload.get("limit", 25),
        "max_core_training_rows": training_debug.get("read_limit", 0),
        "message": training_payload.get("message", ""),
    }
    if latest_workout is None and isinstance(bundle_training_summary.get("latest_workout"), dict):
        latest_workout = bundle_training_summary.get("latest_workout")
    if latest_workout is None:
        latest_workout = _latest_workout(training_rows)
    training_status = str(training_summary.get("status") or "ok")
    training_available = training_status in {"ok", "not_configured", "not_loaded"}
    target_calories = _number(targets.get("target_calories"), 0)
    recovery, latest_recovery, recovery_trend = _recovery_payload(recovery_rows, sleep_rows, target_calories)
    counts = {
        **(bundle.get("counts") if isinstance(bundle.get("counts"), dict) else {}),
        "nutrition": len(food_rows),
        "body_metrics": len(body_rows),
        "body_metric_raw": len(raw_body_rows),
        "training": len(training_items),
        "training_rows": len(training_rows),
        "recovery": len(recovery_rows),
        "sleep": len(sleep_rows),
    }
    sources = {
        "food": {
            "source": "/api/nutrition/today",
            "date": food_payload.get("date") or today,
            "today_items": len(food_rows),
            "today_calories": _round(_number(nutrition_today.get("calories"), 0)),
            "last_updated": _latest_field(food_rows, "updated_at", "created_at"),
            "nutrition_history_latest_date": _latest_field(nutrition_history_items, "date"),
        },
        "training": {
            "source": "/api/training/history",
            "latest_workout_date": latest_workout.get("date") if latest_workout else "",
            "latest_workout_title": latest_workout.get("workout_type") if latest_workout else "",
            "workout_count": len(training_items),
        },
        "weight": {
            "source": "canonical_daily_bodyweights",
            "raw_rows": len(raw_body_rows),
            "canonical_rows": len(body_rows),
            "latest_weight_date": bodyweight_trend[-1].get("date") if bodyweight_trend else "",
        },
        "goals": {
            "source": "/api/goals",
            "target_calories": _round(target_calories),
            "updated_at": targets.get("updated_at") or "",
        },
        "recovery": {
            "source": "/api/recovery/logs + /api/recovery/sleep",
            "recovery_rows": len(recovery_rows),
            "sleep_rows": len(sleep_rows),
            "latest_recovery_date": _latest_field(recovery_rows, "date"),
            "latest_sleep_date": _latest_field(sleep_rows, "date"),
        },
    }
    cache = _dashboard_cache_payload(bundle, sources)
    date_debug = {
        "server_utc_date": server_utc_date,
        "app_local_date": app_local_date,
        "dashboard_date_used": today,
        "timezone": app_timezone_name(),
        "food_rows_for_date": len(food_rows),
        "nutrition_history_latest_date": sources["food"]["nutrition_history_latest_date"],
        "latest_training_date": sources["training"]["latest_workout_date"],
    }
    lean_bulk_decision = _lean_bulk_placeholder(targets)
    lift_performance = _lift_performance_payload(today=today, latest_workout=latest_workout, training_items=training_items, training_rows=training_rows)
    workout_quality = _workout_quality_payload(training_items, latest_recovery=latest_recovery, active_date=today)
    optimization_signals = _optimization_signals_payload(
        nutrition_history_items=nutrition_history_items,
        training_items=training_items,
        training_rows=training_rows,
        body_rows=body_rows,
        recovery_rows=recovery_rows,
        sleep_rows=sleep_rows,
        goals=goals,
        targets=targets,
        today=today,
    )
    adaptive_recommendation = _adaptive_from_optimization_signals(optimization_signals, targets)
    macro_targets = _target_macros(targets)
    optimization = {
        "day_type_macros": {
            "day_type": "standard",
            "confidence": optimization_signals["confidence"]["overall"],
            "reason": optimization_signals["nutrition_recommendation"]["primary_reason"],
            "baseline_targets": macro_targets,
            "adjusted_targets": {
                **macro_targets,
                "calories": _round(_number(macro_targets.get("calories"), 0) + _number(optimization_signals["nutrition_recommendation"].get("calorie_adjustment"), 0)),
            },
            "delta": {"calories": optimization_signals["nutrition_recommendation"].get("calorie_adjustment", 0), "protein": 0, "carbs": 0, "fat": 0},
            "signals": [
                optimization_signals["macro_adherence"].get("summary", ""),
                optimization_signals["plateau_watch"].get("summary", ""),
                optimization_signals["personal_baseline"].get("summary", ""),
            ],
        },
        "plateau_detection": optimization_signals["plateau_watch"],
        "macro_adherence": optimization_signals["macro_adherence"],
        "personal_baseline": optimization_signals["personal_baseline"],
    }
    total_duration_ms = round((time.perf_counter() - started) * 1000, 1)
    blocks.extend(
        [
            {"block": "today_food_summary", "name": "today_food_summary", "status": "ok", "rows": len(food_rows), "duration_ms": 0},
            {"block": "weight_summary", "name": "weight_summary", "status": "ok", "rows": len(body_rows), "duration_ms": 0},
            {"block": "recovery_summary", "name": "recovery_summary", "status": "ok", "rows": len(recovery_rows), "sleep_rows": len(sleep_rows), "duration_ms": 0},
            {
                "block": "load_training",
                "name": "load_training",
                "status": "ok" if training_available else "degraded",
                "rows": training_summary.get("recent_rows", len(training_rows)),
                "total_rows": training_summary.get("total_rows", counts.get("training", 0)),
                "duration_ms": training_summary.get("duration_ms", 0),
                "source": training_summary.get("source", "training_cache_metadata"),
                "message": training_summary.get("message", ""),
                "full_raw_hevy_scan": False,
            },
            {
                "block": "latest_workout",
                "name": "latest_workout",
                "status": "ok",
                "rows": len(training_rows),
                "duration_ms": 0,
            },
        ]
    )
    training_unavailable = not training_available and not latest_workout
    training_summary_text = "Training summary temporarily unavailable" if training_unavailable else latest_workout.get("workout_type") if latest_workout else "Workout not logged yet"
    return {
        "ok": True,
        "core_ready": True,
        "date": today,
        "cache": cache,
        "food": _food_tile(nutrition_today, targets, has_food=bool(food_rows)),
        "weight": weight,
        "goals": goals,
        "targets": targets,
        "base_targets": targets,
        "nutrition_today": nutrition_today,
        "latest_bodyweight": latest_bodyweight,
        "bodyweight_trend": bodyweight_trend,
        "latest_workout": latest_workout,
        "lift_performance": lift_performance,
        "workout_quality": workout_quality,
        "todays_action": {"status": "maintain", "color": "gray", "headline": "Keep logging", "reason": "Lightweight dashboard core loaded."},
        "recovery": recovery,
        "prs": {"bench_press": None, "mile_time": None},
        "latest_recovery": latest_recovery,
        "recovery_trend": recovery_trend,
        "strength_trend_summary": {"exercise": "", "label": "deferred", "summary": "Strength trends are deferred."},
        "muscle_balance_warning": None,
        "ai_insight_preview": None,
        "training_volume": [],
        "personal_records": {"bench_press": None, "mile_time": None, "history": {"bench_press": [], "mile_time": []}},
        "lean_bulk_decision": lean_bulk_decision,
        "adaptive_recommendation": adaptive_recommendation,
        "optimization_signals": optimization_signals,
        "personal_learning": {"status": "deferred", "confidence": "low", "summary": "Personal learning is deferred.", "window": "", "data_points": 0, "insights": []},
        "weekly_report": {"status": "deferred", "period_label": "Deferred", "summary": "Weekly report is deferred.", "rows": [], "best_trend": "", "watch": "", "recommendation": ""},
        "optimization": optimization,
        "recommendation": {
            "recommendation_summary": optimization_signals["nutrition_recommendation"]["primary_reason"],
            "reasoning_explanation": f"{optimization_signals['nutrition_recommendation']['title']} from lightweight dashboard signals.",
        },
        "counts": counts,
        "errors": [],
        "debug": {
            "dashboard_status": "ok",
            "blocks": blocks,
            "sources": sources,
            "cache": cache,
            **date_debug,
            "warnings": bundle.get("warnings", []) if isinstance(bundle.get("warnings"), list) else [],
            "errors": [],
            "required_blocks": sorted(REQUIRED_BLOCKS),
            "required_blocks_failed": [],
            "generated_at": utc_now_iso(),
            "total_duration_ms": total_duration_ms,
            "training_read_limit": training_summary.get("max_core_training_rows", 0),
            "training_core_limit": training_summary.get("limit_workouts", 0),
            "training_core_days": training_summary.get("days", 90),
            "training_recent_rows": training_summary.get("recent_rows", len(training_rows)),
            "training_total_rows": counts.get("training", training_summary.get("total_rows", 0)),
            "training_summary_source": training_summary.get("source", "training_cache_metadata"),
            "full_training_history_scanned": False,
            "external_api_checks": False,
            "syncs": False,
        },
    }
