"""Recurring training split and workout classification helpers."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import re
from typing import Any

import pandas as pd

from src.paths import processed_data_path
from src.storage import load_document, save_document


TRAINING_SCHEDULE_PROFILE_PATH = processed_data_path("training_schedule_profile.json")

DEFAULT_RECURRING_SCHEDULE_PROFILE = {
    "name": "Default Pull/Legs/Push split",
    "version": 1,
    "days": {
        "Monday": {
            "label": "Pull",
            "split_type": "pull_day",
            "category": "strength",
            "expected_fatigue": "moderate",
            "recovery_demand": "moderate",
            "calorie_delta": 75,
            "carb_delta": 25,
        },
        "Tuesday": {
            "label": "Legs",
            "split_type": "leg_day_quad",
            "category": "strength",
            "expected_fatigue": "high",
            "recovery_demand": "high",
            "calorie_delta": 150,
            "carb_delta": 55,
        },
        "Wednesday": {
            "label": "Push",
            "split_type": "push_day",
            "category": "strength",
            "expected_fatigue": "moderate",
            "recovery_demand": "moderate",
            "calorie_delta": 75,
            "carb_delta": 25,
        },
        "Thursday": {
            "label": "Pull",
            "split_type": "pull_day",
            "category": "strength",
            "expected_fatigue": "moderate",
            "recovery_demand": "moderate",
            "calorie_delta": 75,
            "carb_delta": 25,
        },
        "Friday": {
            "label": "Legs",
            "split_type": "leg_day_hamstring",
            "category": "strength",
            "expected_fatigue": "high",
            "recovery_demand": "high",
            "calorie_delta": 150,
            "carb_delta": 55,
        },
        "Saturday": {
            "label": "Chest",
            "split_type": "chest_day",
            "category": "strength",
            "expected_fatigue": "moderate",
            "recovery_demand": "moderate",
            "calorie_delta": 75,
            "carb_delta": 25,
        },
        "Sunday": {
            "label": "Run",
            "split_type": "run_day",
            "category": "run",
            "expected_fatigue": "low-moderate",
            "recovery_demand": "low-moderate",
            "calorie_delta": 75,
            "carb_delta": 30,
        },
    },
}

RUN_CARDIO_TERMS = (
    "run",
    "running",
    "jog",
    "jogging",
    "cardio",
    "treadmill",
    "zone 2",
    "zone2",
    "easy run",
    "tempo",
    "interval",
    "sprint",
    "mile",
    "5k",
    "10k",
    "strava",
    "elliptical",
    "bike",
    "cycling",
    "spin",
    "rower",
    "rowing",
    "stairmaster",
)

RUN_TERMS = (
    "run",
    "running",
    "jog",
    "jogging",
    "easy run",
    "tempo run",
    "interval run",
    "outdoor run",
    "treadmill run",
    "5k",
    "10k",
)

CARDIO_TERMS = (
    "cardio",
    "bike",
    "cycling",
    "spin",
    "elliptical",
    "stairmaster",
    "stair master",
    "rowing machine",
    "rower",
    "swim",
    "treadmill walk",
    "treadmill run",
    "cardio machine",
)

LIFT_TERMS = (
    "bench press",
    "squat",
    "deadlift",
    "romanian deadlift",
    "rdl",
    "overhead press",
    "shoulder press",
    "press",
    "curl",
    "curls",
    "skullcrusher",
    "skull crusher",
    "triceps",
    "pushdown",
    "leg extension",
    "leg curl",
    "calf raise",
    "row",
    "rows",
    "pulldown",
    "pull down",
    "pullup",
    "pull up",
    "lateral raise",
    "dumbbell",
    "barbell",
    "machine",
    "shrug",
    "shrugs",
    "fly",
    "extension",
    "raise",
)

LOWER_BODY_TERMS = (
    "leg",
    "legs",
    "quad",
    "quadriceps",
    "hamstring",
    "glute",
    "calf",
    "squat",
    "deadlift",
    "rdl",
    "lunge",
    "lower",
)

SPLIT_LABEL_TERMS = {
    "Pull": ("pull", "back", "row", "pulldown", "lat", "biceps", "curl"),
    "Legs": LOWER_BODY_TERMS,
    "Push": ("push", "shoulder", "press", "triceps", "overhead"),
    "Chest": ("chest", "bench", "pec", "incline", "fly"),
}

KNOWN_SPLIT_TYPES = {
    "pull_day",
    "push_day",
    "chest_day",
    "upper_day",
    "lower_day",
    "leg_day",
    "leg_day_quad",
    "leg_day_hamstring",
    "run_day",
    "cardio_day",
}

LEG_SPLIT_TYPES = {"leg_day", "leg_day_quad", "leg_day_hamstring"}

SPLIT_TYPE_LABELS = {
    "pull_day": "Pull",
    "push_day": "Push",
    "chest_day": "Chest",
    "upper_day": "Upper",
    "lower_day": "Lower",
    "leg_day": "Legs",
    "leg_day_quad": "Legs",
    "leg_day_hamstring": "Legs",
    "run_day": "Run",
    "cardio_day": "Cardio",
}

QUAD_SPLIT_TERMS = (
    "pendulum squat",
    "leg extension",
    "front squat",
    "hack squat",
    "bulgarian split squat",
    "split squat",
    "sissy squat",
    "leg press",
    "quad",
    "quads",
    "quadriceps",
    "knee dominant",
    "knee-dominant",
)

HAMSTRING_SPLIT_TERMS = (
    "romanian deadlift",
    "rdl",
    "lying leg curl",
    "seated leg curl",
    "leg curl",
    "hamstring curl",
    "glute ham raise",
    "g h r",
    "ghr",
    "good morning",
    "stiff leg deadlift",
    "stiff-legged deadlift",
    "hip hinge",
    "hip-hinge",
    "hamstring",
    "hamstrings",
)

SPLIT_TYPE_TITLE_TERMS = (
    ("leg_day_quad", ("quad day", "quad leg", "quads", "quadriceps", "knee dominant", "knee-dominant")),
    ("leg_day_hamstring", ("hamstring day", "hamstring leg", "hamstrings", "posterior", "hinge day", "hip hinge")),
    ("pull_day", ("pull day", "pull", "back biceps")),
    ("push_day", ("push day", "push", "shoulders triceps")),
    ("chest_day", ("chest day", "chest")),
    ("upper_day", ("upper day", "upper body")),
    ("lower_day", ("lower day", "lower body")),
    ("leg_day", ("leg day", "legs", "leg")),
    ("run_day", ("run day", "running", "run")),
    ("cardio_day", ("cardio",)),
)

SPLIT_TYPE_EXERCISE_TERMS = (
    ("pull_day", ("pull", "back", "row", "pulldown", "pull down", "lat", "biceps", "curl", "shrug")),
    ("leg_day", LOWER_BODY_TERMS),
    ("push_day", ("push", "shoulder", "press", "triceps", "overhead", "lateral raise")),
    ("chest_day", ("chest", "bench", "pec", "incline", "fly")),
)

METADATA_DISTANCE_TERMS = ("distance", "meters", "metres", "kilometers", "kilometres", "miles")
METADATA_DURATION_TERMS = ("duration", "elapsed", "moving_time", "seconds", "time_seconds")
TIMESTAMP_KEYS = {"start_time", "end_time", "created_at", "updated_at", "modified_at"}


@lru_cache(maxsize=1)
def _load_training_schedule_profile_cached() -> dict:
    try:
        profile = load_document("training_schedule_profile", TRAINING_SCHEDULE_PROFILE_PATH, DEFAULT_RECURRING_SCHEDULE_PROFILE)
    except Exception:
        profile = deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE)
    if not isinstance(profile, dict):
        return deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE)
    days = profile.get("days")
    if not isinstance(days, dict):
        profile = {**deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE), **profile, "days": deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE["days"])}
    else:
        merged_days = deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE["days"])
        for weekday, value in days.items():
            if isinstance(value, dict):
                merged_days[str(weekday)] = {**merged_days.get(str(weekday), {}), **value}
        profile = {**deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE), **profile, "days": merged_days}
    return profile


def load_training_schedule_profile() -> dict:
    """Load the configurable recurring split profile, falling back to defaults."""
    return deepcopy(_load_training_schedule_profile_cached())


def save_training_schedule_profile(profile: dict) -> dict:
    """Persist a training schedule profile for future dashboard/adaptive reads."""
    merged = {**deepcopy(DEFAULT_RECURRING_SCHEDULE_PROFILE), **(profile or {})}
    saved = save_document("training_schedule_profile", TRAINING_SCHEDULE_PROFILE_PATH, merged)
    _load_training_schedule_profile_cached.cache_clear()
    return saved


def _classification_plan(row: pd.Series | dict, profile: dict | None = None) -> dict:
    return planned_training_for_date(row.get("date"), profile=profile)


def _to_timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()


def planned_training_for_date(value: Any, profile: dict | None = None) -> dict:
    """Return the planned split entry for a date-like value."""
    day = _to_timestamp(value) or pd.Timestamp.today().normalize()
    resolved_profile = profile or load_training_schedule_profile()
    weekday = day.day_name()
    plan = dict((resolved_profile.get("days") or {}).get(weekday) or {})
    if not plan:
        plan = {"label": "Training", "category": "strength", "expected_fatigue": "moderate", "recovery_demand": "moderate", "calorie_delta": 75, "carb_delta": 25}
    label = str(plan.get("label") or "Training").strip()
    category = str(plan.get("category") or "strength").strip().lower()
    display_label = f"{weekday} {label}" if category in {"run", "cardio"} else label
    split_type = normalize_split_type(plan.get("split_type")) or _split_type_from_title(label)
    if not split_type and category in {"run", "cardio"}:
        split_type = "run_day" if category == "run" else "cardio_day"
    split_reason = [f"{weekday} recurring plan"] if split_type else []
    return {
        **plan,
        "weekday": weekday,
        "label": label,
        "display_label": display_label,
        "category": category,
        "split_type": split_type,
        "split_confidence": 1.0 if normalize_split_type(plan.get("split_type")) else 0.75 if split_type else 0.0,
        "classification_reason": split_reason,
        "is_run_day": category in {"run", "cardio"},
        "is_strength_day": category == "strength",
        "is_leg_day": split_type in LEG_SPLIT_TYPES or label.lower() in {"leg", "legs"} or any(term in label.lower() for term in LOWER_BODY_TERMS),
    }


def _flatten_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        parts: list[str] = []
        for key, item in value.items():
            parts.append(str(key))
            parts.extend(_flatten_strings(item))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten_strings(item))
        return parts
    if isinstance(value, (str, int, float, bool)):
        return [str(value)]
    return []


def _as_rows(workout: Any) -> list[dict[str, Any]]:
    if workout is None:
        return []
    if isinstance(workout, pd.DataFrame):
        return workout.to_dict(orient="records")
    if isinstance(workout, pd.Series):
        return [workout.to_dict()]
    if isinstance(workout, (list, tuple)):
        return [dict(row) for row in workout if isinstance(row, (dict, pd.Series))]
    if isinstance(workout, dict):
        details = workout.get("details")
        if isinstance(details, list) and details:
            base = {key: value for key, value in workout.items() if key != "details"}
            return [{**base, **dict(row)} for row in details if isinstance(row, dict)]
        exercises = workout.get("exercises")
        if isinstance(exercises, list) and exercises:
            rows = []
            base = {
                "source": workout.get("source") or "hevy",
                "workout_type": workout.get("workout_type") or workout.get("title") or workout.get("name") or "",
                "title": workout.get("title") or workout.get("name") or "",
                "notes": workout.get("description") or "",
                "date": workout.get("start_time") or workout.get("created_at") or "",
                "metadata": workout,
            }
            for exercise in exercises:
                if not isinstance(exercise, dict):
                    continue
                sets = exercise.get("sets") if isinstance(exercise.get("sets"), list) else []
                if sets:
                    for set_item in sets:
                        rows.append(
                            {
                                **base,
                                "exercise": exercise.get("title") or exercise.get("name") or "",
                                "exercise_notes": exercise.get("notes") or "",
                                "sets": 1,
                                "reps": (set_item or {}).get("reps"),
                                "weight": (set_item or {}).get("weight") or (set_item or {}).get("weight_kg"),
                                "rpe": (set_item or {}).get("rpe"),
                            }
                        )
                else:
                    rows.append({**base, "exercise": exercise.get("title") or exercise.get("name") or "", "exercise_notes": exercise.get("notes") or ""})
            return rows
        return [workout]
    return []


def _word_match(text: str, term: str) -> bool:
    escaped = re.escape(term.lower()).replace(r"\ ", r"\s+")
    return bool(re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", str(text or "").lower()))


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if _word_match(text, term)]


def _numeric(value: Any) -> float:
    parsed = pd.to_numeric(value, errors="coerce")
    if pd.isna(parsed):
        return 0.0
    return float(parsed)


def _compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def normalize_split_type(value: Any) -> str:
    """Normalize known split labels without mutating the source workout row."""
    text = _compact_text(value)
    if not text:
        return ""
    underscored = text.replace(" ", "_")
    if underscored in KNOWN_SPLIT_TYPES:
        return underscored
    aliases = {
        "pull": "pull_day",
        "pull_day": "pull_day",
        "push": "push_day",
        "push_day": "push_day",
        "chest": "chest_day",
        "chest_day": "chest_day",
        "upper": "upper_day",
        "upper_body": "upper_day",
        "upper_day": "upper_day",
        "lower": "lower_day",
        "lower_body": "lower_day",
        "lower_day": "lower_day",
        "legs": "leg_day",
        "leg": "leg_day",
        "leg_day": "leg_day",
        "quad": "leg_day_quad",
        "quads": "leg_day_quad",
        "quad_day": "leg_day_quad",
        "quad_leg_day": "leg_day_quad",
        "leg_day_quad": "leg_day_quad",
        "hamstring": "leg_day_hamstring",
        "hamstrings": "leg_day_hamstring",
        "hamstring_day": "leg_day_hamstring",
        "hamstring_leg_day": "leg_day_hamstring",
        "leg_day_hamstring": "leg_day_hamstring",
        "run": "run_day",
        "running": "run_day",
        "run_day": "run_day",
        "cardio": "cardio_day",
        "cardio_day": "cardio_day",
    }
    if underscored in aliases:
        return aliases[underscored]
    return _split_type_from_title(text)


def _split_type_from_title(value: Any) -> str:
    text = _compact_text(value)
    if not text:
        return ""
    for split_type, terms in SPLIT_TYPE_TITLE_TERMS:
        if any(_word_match(text, term) or ("-" in term and term.replace("-", " ") in text) for term in terms):
            return split_type
    return ""


def _dedupe_reasons(values: list[str], limit: int = 6) -> list[str]:
    reasons: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in reasons:
            reasons.append(text)
        if len(reasons) >= limit:
            break
    return reasons


def _note_field_value(note: Any, key: str) -> str:
    marker = f"{key}="
    if marker not in str(note or ""):
        return ""
    return str(note or "").split(marker, 1)[1].split("|", 1)[0].strip()


def _row_title_values(rows: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for row in rows:
        for column in ("workout_type", "title", "name"):
            if str(row.get(column) or "").strip():
                values.append(str(row.get(column) or ""))
        note_title = _note_field_value(row.get("notes"), "workout_title")
        if note_title:
            values.append(note_title)
    return values


def _row_working_sets(row: dict[str, Any]) -> float:
    sets = _numeric(row.get("sets"))
    reps = _numeric(row.get("reps"))
    weight = _numeric(row.get("weight"))
    if sets > 0:
        return sets
    if reps > 0 or weight > 0:
        return 1.0
    return 0.0


def _row_volume(row: dict[str, Any]) -> float:
    sets = max(_row_working_sets(row), 1.0)
    reps = _numeric(row.get("reps"))
    weight = _numeric(row.get("weight"))
    return max(0.0, sets * reps * weight)


def _display_evidence_name(row: dict[str, Any], terms: list[str]) -> str:
    exercise = str(row.get("exercise") or row.get("exercise_name") or "").strip()
    if exercise:
        return exercise
    muscle = str(row.get("muscle_group") or "").strip()
    if muscle:
        return muscle
    return terms[0].title() if terms else ""


def _leg_split_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    quad_sets = 0.0
    ham_sets = 0.0
    quad_volume = 0.0
    ham_volume = 0.0
    quad_reasons: list[str] = []
    ham_reasons: list[str] = []
    generic_leg = False

    for row in rows:
        text = " ".join(str(row.get(column, "") or "") for column in ("exercise", "exercise_name", "muscle_group", "notes")).lower()
        if not text.strip():
            continue
        quad_matches = _matched_terms(text, QUAD_SPLIT_TERMS)
        ham_matches = _matched_terms(text, HAMSTRING_SPLIT_TERMS)
        generic_leg = generic_leg or bool(_matched_terms(text, LOWER_BODY_TERMS))
        sets = _row_working_sets(row) or 1.0
        volume = _row_volume(row) or sets
        if quad_matches:
            quad_sets += sets
            quad_volume += volume
            quad_reasons.append(_display_evidence_name(row, quad_matches))
        if ham_matches:
            ham_sets += sets
            ham_volume += volume
            ham_reasons.append(_display_evidence_name(row, ham_matches))

    total_sets = quad_sets + ham_sets
    total_volume = quad_volume + ham_volume
    if total_sets <= 0:
        return {
            "split_type": "leg_day" if generic_leg else "",
            "split_confidence": 0.55 if generic_leg else 0.0,
            "classification_reason": ["Generic lower-body terms"] if generic_leg else [],
            "quad_sets": quad_sets,
            "hamstring_sets": ham_sets,
            "quad_volume": quad_volume,
            "hamstring_volume": ham_volume,
        }

    if quad_sets == ham_sets and quad_volume != ham_volume:
        dominant = "quad" if quad_volume > ham_volume else "hamstring"
    else:
        dominant = "quad" if quad_sets > ham_sets else "hamstring"
    dominant_sets = quad_sets if dominant == "quad" else ham_sets
    other_sets = ham_sets if dominant == "quad" else quad_sets
    dominant_volume = quad_volume if dominant == "quad" else ham_volume
    other_volume = ham_volume if dominant == "quad" else quad_volume
    set_ratio = dominant_sets / max(total_sets, 1.0)
    volume_ratio = dominant_volume / max(total_volume, 1.0) if total_volume > 0 else set_ratio
    dominance = max(set_ratio, volume_ratio)

    if dominance < 0.58 and abs(dominant_sets - other_sets) <= 1:
        return {
            "split_type": "leg_day",
            "split_confidence": 0.6,
            "classification_reason": ["Mixed quad and hamstring evidence"],
            "quad_sets": quad_sets,
            "hamstring_sets": ham_sets,
            "quad_volume": quad_volume,
            "hamstring_volume": ham_volume,
        }

    split_type = "leg_day_quad" if dominant == "quad" else "leg_day_hamstring"
    reasons = quad_reasons if dominant == "quad" else ham_reasons
    reasons = _dedupe_reasons(reasons)
    reasons.append("Quad dominant volume" if dominant == "quad" else "Hamstring dominant volume")
    confidence = min(0.93, 0.58 + dominance * 0.28 + min(0.07, dominant_sets / 30))
    return {
        "split_type": split_type,
        "split_confidence": round(confidence, 2),
        "classification_reason": _dedupe_reasons(reasons),
        "quad_sets": quad_sets,
        "hamstring_sets": ham_sets,
        "quad_volume": quad_volume,
        "hamstring_volume": ham_volume,
    }


def _exercise_split_type(rows: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(
        str(row.get(column, "") or "").lower()
        for row in rows
        for column in ("exercise", "exercise_name", "muscle_group", "notes")
    )
    for split_type, terms in SPLIT_TYPE_EXERCISE_TERMS:
        if _matched_terms(text, terms):
            return {
                "split_type": split_type,
                "split_confidence": 0.72,
                "classification_reason": _dedupe_reasons(_matched_terms(text, terms)),
            }
    return {"split_type": "", "split_confidence": 0.0, "classification_reason": []}


def classify_strength_split(workout: Any, planned: dict | None = None) -> dict:
    """Infer a stable split subtype from title/exercises without rewriting history."""
    rows = _as_rows(workout)
    explicit_reasons: list[str] = []
    for row in rows:
        for column in ("split_type", "normalized_split", "training_split"):
            split_type = normalize_split_type(row.get(column))
            if split_type:
                explicit_reasons.append(f"Stored {column}")
                return {
                    "split_type": split_type,
                    "split_label": SPLIT_TYPE_LABELS.get(split_type, "Lift"),
                    "split_confidence": 0.98,
                    "classification_reason": explicit_reasons,
                    "matched_by": "stored_split_type",
                }
        for key in ("split_type", "normalized_split", "training_split"):
            split_type = normalize_split_type(_note_field_value(row.get("notes"), key))
            if split_type:
                explicit_reasons.append(f"Stored {key} note")
                return {
                    "split_type": split_type,
                    "split_label": SPLIT_TYPE_LABELS.get(split_type, "Lift"),
                    "split_confidence": 0.95,
                    "classification_reason": explicit_reasons,
                    "matched_by": "stored_split_type",
                }

    title_values = _row_title_values(rows)
    title_text = " ".join(title_values)
    title_split = _split_type_from_title(title_text)
    if title_split in {"run_day", "cardio_day"}:
        title_split = ""
    title_reason = title_values[0] if title_values else ""
    leg_evidence = _leg_split_evidence(rows)
    evidence_split = str(leg_evidence.get("split_type") or "")
    if title_split in {"leg_day", "lower_day", ""} and evidence_split in {"leg_day_quad", "leg_day_hamstring"}:
        return {
            "split_type": evidence_split,
            "split_label": SPLIT_TYPE_LABELS.get(evidence_split, "Legs"),
            "split_confidence": leg_evidence.get("split_confidence", 0.0),
            "classification_reason": leg_evidence.get("classification_reason") or [],
            "matched_by": "dominant_leg_evidence",
        }
    if title_split in {"leg_day_quad", "leg_day_hamstring"}:
        reasons = [title_reason or SPLIT_TYPE_LABELS.get(title_split, "Legs"), *(leg_evidence.get("classification_reason") or [])]
        return {
            "split_type": title_split,
            "split_label": SPLIT_TYPE_LABELS.get(title_split, "Legs"),
            "split_confidence": 0.9,
            "classification_reason": _dedupe_reasons(reasons),
            "matched_by": "title",
        }
    if title_split:
        return {
            "split_type": title_split,
            "split_label": SPLIT_TYPE_LABELS.get(title_split, "Lift"),
            "split_confidence": 0.86,
            "classification_reason": _dedupe_reasons([title_reason or SPLIT_TYPE_LABELS.get(title_split, "Lift")]),
            "matched_by": "title",
        }
    if evidence_split:
        return {
            "split_type": evidence_split,
            "split_label": SPLIT_TYPE_LABELS.get(evidence_split, "Legs"),
            "split_confidence": leg_evidence.get("split_confidence", 0.0),
            "classification_reason": leg_evidence.get("classification_reason") or [],
            "matched_by": "dominant_leg_evidence" if evidence_split != "leg_day" else "exercise_terms",
        }

    exercise_split = _exercise_split_type(rows)
    if exercise_split.get("split_type"):
        split_type = str(exercise_split["split_type"])
        return {
            "split_type": split_type,
            "split_label": SPLIT_TYPE_LABELS.get(split_type, "Lift"),
            "split_confidence": exercise_split.get("split_confidence", 0.0),
            "classification_reason": exercise_split.get("classification_reason") or [],
            "matched_by": "exercise_terms",
        }

    planned_split = normalize_split_type((planned or {}).get("split_type"))
    if planned_split and (planned or {}).get("is_strength_day"):
        return {
            "split_type": planned_split,
            "split_label": SPLIT_TYPE_LABELS.get(planned_split, str((planned or {}).get("label") or "Lift")),
            "split_confidence": 0.5,
            "classification_reason": [f"Fallback to planned {planned.get('display_label') or planned.get('label') or 'training'}"],
            "matched_by": "planned_fallback",
        }

    return {"split_type": "", "split_label": "", "split_confidence": 0.0, "classification_reason": [], "matched_by": "none"}


def _contains_metadata_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text not in TIMESTAMP_KEYS and (
                any(term in key_text for term in METADATA_DISTANCE_TERMS)
                or any(term in key_text for term in METADATA_DURATION_TERMS)
            ):
                if not isinstance(item, (dict, list, tuple, set)) and _numeric(item) > 0:
                    return True
            if _contains_metadata_key(item):
                return True
    if isinstance(value, (list, tuple, set)):
        return any(_contains_metadata_key(item) for item in value)
    return False


def text_has_run_signal(text: str) -> bool:
    lower = str(text or "").lower()
    return bool(_matched_terms(lower, RUN_TERMS) or _matched_terms(lower, CARDIO_TERMS))


def row_training_text(row: pd.Series | dict) -> str:
    return " ".join(
        str(row.get(column, "") or "")
        for column in ["workout_type", "muscle_group", "exercise", "notes", "source", "external_id"]
    ).lower()


def _row_has_lift_numbers(row: dict[str, Any]) -> bool:
    sets = _numeric(row.get("sets"))
    reps = _numeric(row.get("reps"))
    weight = _numeric(row.get("weight"))
    source = str(row.get("source", "") or "").lower()
    notes = str(row.get("notes", "") or "").lower()
    exercise_text = str(row.get("exercise", "") or "").lower()
    cardio_exercise = bool(_matched_terms(exercise_text, RUN_TERMS) or _matched_terms(exercise_text, CARDIO_TERMS))
    if weight <= 0 and (cardio_exercise or _has_distance_or_pace_metadata(row)):
        return False
    if weight > 0 and reps > 0:
        return True
    if sets > 0 and reps > 0 and (source == "hevy" or "hevy_workout_id=" in notes):
        return True
    return False


def _has_distance_or_pace_metadata(row: dict[str, Any]) -> bool:
    text = " ".join(str(row.get(column, "") or "") for column in ["notes", "metadata", "external_id"]).lower()
    if "distance_miles=" in text or "pace_min_per_mile=" in text or "strava_activity_id=" in text or "estimated_run_load=" in text:
        return True
    for key, value in row.items():
        key_text = str(key).lower()
        if key_text in TIMESTAMP_KEYS:
            continue
        if any(term in key_text for term in ("distance", "pace", "miles", "kilometers", "metres", "meters")) and _numeric(value) > 0:
            return True
    return False


def classify_workout(workout: Any) -> dict:
    """Classify a workout from explicit lift/run/cardio evidence.

    Schedule labels and plain duration are intentionally not cardio evidence:
    a Hevy lift logged on a planned run day is still a lift unless it contains
    distance, pace, Strava, or cardio exercise signals.
    """
    rows = _as_rows(workout)
    strings = _flatten_strings(workout)
    title_text = " ".join(
        str(row.get(column, "") or "")
        for row in rows
        for column in ["workout_type", "title", "name"]
    )
    exercise_text = " ".join(
        str(row.get(column, "") or "")
        for row in rows
        for column in ["exercise", "exercise_name", "exercise_notes"]
    )
    lift_text = " ".join(
        str(row.get(column, "") or "")
        for row in rows
        for column in ["exercise", "exercise_name", "exercise_notes", "muscle_group"]
    )
    notes_text = " ".join(str(row.get("notes", "") or "") for row in rows)
    source_text = " ".join(str(row.get("source", "") or "") for row in rows).lower()
    full_text = " ".join([title_text, lift_text, notes_text, " ".join(strings)]).lower()

    matched_lift = _matched_terms(lift_text.lower(), LIFT_TERMS)
    matched_run_title = _matched_terms(title_text.lower(), RUN_TERMS)
    matched_run_exercise = _matched_terms(exercise_text.lower(), RUN_TERMS)
    matched_cardio_title = _matched_terms(title_text.lower(), CARDIO_TERMS)
    matched_cardio_exercise = _matched_terms(exercise_text.lower(), CARDIO_TERMS)
    has_strava = "strava" in source_text or "strava_activity_id=" in notes_text.lower()
    has_run_metadata = any(_has_distance_or_pace_metadata(row) for row in rows)
    has_lift_numbers = any(_row_has_lift_numbers(row) for row in rows)
    has_lift = bool(matched_lift or has_lift_numbers)
    hevy_lift_without_cardio_metadata = "hevy" in source_text and has_lift and not has_run_metadata
    matched_run = ([] if hevy_lift_without_cardio_metadata else matched_run_title) + matched_run_exercise
    matched_cardio = ([] if hevy_lift_without_cardio_metadata else matched_cardio_title) + matched_cardio_exercise
    has_run = bool(has_strava or has_run_metadata or matched_run)
    has_cardio = bool(matched_cardio)

    if has_lift and (has_run or has_cardio):
        kind = "lift_cardio"
    elif has_run:
        kind = "run"
    elif has_cardio:
        kind = "cardio"
    elif has_lift:
        kind = "lift"
    else:
        kind = "unknown"

    if has_lift and not (has_run or has_cardio):
        reason = "Resistance exercises detected; no distance/pace/cardio metadata."
    elif kind == "lift_cardio":
        reason = "Resistance exercises and clear run/cardio evidence detected."
    elif kind in {"run", "cardio"}:
        reason = "Clear run/cardio evidence detected."
    else:
        reason = "No clear lift, run, or cardio evidence detected."

    split = classify_strength_split(rows) if has_lift else {}

    return {
        "kind": kind,
        "has_lift": has_lift,
        "has_run": has_run,
        "has_cardio": has_cardio,
        "matched_lift_terms": list(dict.fromkeys(matched_lift))[:12],
        "matched_cardio_terms": list(dict.fromkeys([*matched_run, *matched_cardio]))[:12],
        "reason": reason,
        "split_type": split.get("split_type") or "",
        "split_label": split.get("split_label") or "",
        "split_confidence": split.get("split_confidence", 0.0),
        "classification_reason": split.get("classification_reason") or [],
        "split_matched_by": split.get("matched_by") or "none",
        "debug_text": full_text[:500],
    }


def is_run_row(row: pd.Series | dict, profile: dict | None = None) -> bool:
    return classify_workout(row).get("kind") in {"run", "cardio", "lift_cardio"}


def is_strength_row(row: pd.Series | dict, profile: dict | None = None) -> bool:
    return bool(classify_workout(row).get("has_lift"))


def classify_hevy_workout(workout: dict) -> dict:
    """Classify a Hevy workout using explicit lift/run/cardio evidence."""
    start = workout.get("start_time") or workout.get("created_at")
    plan = planned_training_for_date(start)
    classification = classify_workout({**workout, "source": "hevy"})
    kind = str(classification["kind"])
    is_run = kind in {"run", "cardio"}
    return {
        "workout_type": "Run" if kind == "run" else "Cardio" if kind == "cardio" else "Strength",
        "muscle_group": "Cardio" if kind in {"run", "cardio"} else "",
        "is_run": is_run,
        "kind": kind,
        "reasons": classification["matched_cardio_terms"] or [classification["reason"]],
        "split_type": classification.get("split_type") or "",
        "split_confidence": classification.get("split_confidence", 0.0),
        "classification_reason": classification.get("classification_reason") or [],
        "classification_debug": classification,
        "planned": plan,
    }


def _note_value(note: str, key: str) -> str:
    marker = f"{key}="
    if marker not in str(note):
        return ""
    return str(note).split(marker, 1)[1].split("|", 1)[0].strip()


def _first_non_empty(values: list[str]) -> str:
    return next((str(value).strip() for value in values if str(value or "").strip()), "")


def infer_strength_label(rows: pd.DataFrame, planned: dict | None = None) -> str:
    split = classify_strength_split(rows, planned=planned)
    if split.get("split_label"):
        return str(split.get("split_label"))
    text = " ".join(
        str(value).lower()
        for column in ["workout_type", "muscle_group", "exercise", "notes"]
        if column in rows.columns
        for value in rows[column].fillna("").tolist()
    )
    title = ""
    if "notes" in rows.columns:
        title = _first_non_empty([_note_value(str(note), "workout_title") for note in rows["notes"].fillna("").tolist()])
    title_lower = title.lower()
    for label, terms in SPLIT_LABEL_TERMS.items():
        if label.lower() in title_lower or any(term in text for term in terms):
            return label
    if planned and planned.get("is_strength_day"):
        return str(planned.get("label") or "Lift")
    return title or "Lift"


def _run_label(rows: pd.DataFrame, planned: dict | None = None) -> str:
    text = " ".join(
        str(value).lower()
        for column in ["exercise", "notes", "workout_type"]
        if column in rows.columns
        for value in rows[column].fillna("").tolist()
    )
    if "easy" in text or "zone 2" in text or "zone2" in text:
        return "Easy Run"
    if "interval" in text or "sprint" in text:
        return "Intervals"
    if "tempo" in text:
        return "Tempo Run"
    if planned and planned.get("is_run_day"):
        return "Run"
    return "Run/Cardio"


def _source_labels(rows: pd.DataFrame) -> list[str]:
    if "source" not in rows.columns:
        return []
    labels = []
    for source in rows["source"].fillna("").astype(str).str.lower().tolist():
        if source == "hevy":
            labels.append("Hevy")
        elif source == "strava":
            labels.append("Strava")
        elif source:
            labels.append(source.capitalize())
    return sorted(set(labels))


def summarize_training_day(training_df: pd.DataFrame | None, day: Any, profile: dict | None = None) -> dict:
    """Summarize planned and completed training for a dashboard day."""
    planned = planned_training_for_date(day, profile=profile)
    day_ts = _to_timestamp(day) or pd.Timestamp.today().normalize()
    empty_completed = {
        "planned": planned,
        "planned_workout": planned["display_label"],
        "completed_workouts": [],
        "completed_summary": "",
        "completed_count": 0,
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
    if training_df is None or training_df.empty or "date" not in training_df.columns:
        return empty_completed

    df = training_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["date"])
    today_rows = df[df["date"] == day_ts].copy()
    if today_rows.empty:
        return empty_completed

    for column in ["workout_id", "exercise", "muscle_group", "workout_type", "source", "notes", "sets", "reps", "weight"]:
        if column not in today_rows.columns:
            today_rows[column] = "" if column not in {"sets", "reps", "weight"} else 0
    today_rows["is_run"] = today_rows.apply(lambda row: is_run_row(row, profile=profile), axis=1)
    today_rows["is_lift"] = today_rows.apply(lambda row: is_strength_row(row, profile=profile), axis=1)

    completed: list[str] = []
    completed_split_types: list[str] = []
    completed_reasons: list[str] = []
    has_lift = bool(today_rows["is_lift"].any())
    has_run = bool(today_rows["is_run"].any())
    group_key = today_rows["workout_id"].fillna("").astype(str)
    group_key = group_key.where(group_key.str.strip() != "", today_rows.index.astype(str))
    for _, rows in today_rows.groupby(group_key, sort=False):
        group_has_lift = bool(rows["is_lift"].any())
        group_has_run = bool(rows["is_run"].any())
        split = classify_strength_split(rows[rows["is_lift"]] if group_has_lift else rows, planned=planned) if group_has_lift else {}
        if split.get("split_type"):
            completed_split_types.append(str(split.get("split_type")))
            completed_reasons.extend(split.get("classification_reason") or [])
        if group_has_lift and group_has_run:
            completed.append(f"{infer_strength_label(rows[rows['is_lift']], planned)} + {_run_label(rows[rows['is_run']], planned)}")
        elif group_has_run:
            completed.append(_run_label(rows, planned))
        elif group_has_lift:
            completed.append(infer_strength_label(rows, planned))
        else:
            completed.append("Workout")

    deduped_completed = list(dict.fromkeys(completed))
    deduped_split_types = list(dict.fromkeys(completed_split_types))
    planned_label = str(planned["label"])
    planned_split = normalize_split_type(planned.get("split_type"))
    split_matches = bool(planned_split and planned_split in deduped_split_types)
    label_matches = any(item.lower() == planned_label.lower() for item in deduped_completed)
    strength_matches = has_lift and (split_matches or (not planned_split and label_matches))
    run_matches = has_run and planned["is_run_day"]
    extra_run = has_run and has_lift and planned["is_strength_day"]

    if planned["is_run_day"]:
        schedule_match = "matched" if run_matches else "different" if deduped_completed else "missed"
    elif planned["is_strength_day"]:
        schedule_match = "matched_plus_extra_run" if strength_matches and extra_run else "matched" if strength_matches else "different" if deduped_completed else "missed"
    else:
        schedule_match = "logged" if deduped_completed else "missed"

    match_label = {
        "matched": "Matched schedule",
        "matched_plus_extra_run": "Matched + recovery run added",
        "different": "Different from planned",
        "logged": "Logged",
        "missed": "Workout not logged yet",
    }.get(schedule_match, "Logged")

    return {
        "planned": planned,
        "planned_workout": planned["display_label"],
        "completed_workouts": deduped_completed,
        "completed_summary": " + ".join(deduped_completed),
        "completed_count": len(deduped_completed),
        "has_lift": has_lift,
        "has_run": has_run,
        "sources": _source_labels(today_rows),
        "schedule_match": schedule_match,
        "match_label": match_label,
        "planned_split_type": planned_split,
        "completed_split_types": deduped_split_types,
        "split_match": split_matches,
        "classification_reason": _dedupe_reasons(completed_reasons),
        "cardio_indicator": "Run/cardio logged" if has_run else "Planned run/cardio" if planned["is_run_day"] else None,
        "extra_run_added": extra_run,
        "recovery_status_relative_to_plan": "Extra run added" if extra_run else "On plan" if schedule_match == "matched" else match_label,
    }
