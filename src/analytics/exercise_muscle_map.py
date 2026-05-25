"""Exercise-to-muscle-group mapping used when imported data lacks metadata."""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)
_WARNED_UNMAPPED: set[str] = set()

MUSCLE_GROUPS = [
    "Chest",
    "Back",
    "Shoulders",
    "Biceps",
    "Triceps",
    "Quads",
    "Hamstrings",
    "Glutes",
    "Calves",
    "Abs/Core",
    "Forearms",
    "Other",
]

GROUP_ALIASES = {
    "abs": "Abs/Core",
    "core": "Abs/Core",
    "abdominals": "Abs/Core",
    "rear delts": "Shoulders",
    "rear delt": "Shoulders",
    "legs": "Quads",
    "quadriceps": "Quads",
}

EXERCISE_MUSCLE_MAP = {
    "bench press": ("Chest", ["Triceps", "Shoulders"]),
    "incline dumbbell press": ("Chest", ["Shoulders", "Triceps"]),
    "incline bench press": ("Chest", ["Shoulders", "Triceps"]),
    "chest fly": ("Chest", []),
    "fly crossover": ("Chest", []),
    "cable fly": ("Chest", []),
    "pec deck": ("Chest", []),
    "push-up": ("Chest", ["Triceps", "Shoulders"]),
    "pushup": ("Chest", ["Triceps", "Shoulders"]),
    "overhead press": ("Shoulders", ["Triceps"]),
    "shoulder press": ("Shoulders", ["Triceps"]),
    "lateral raise": ("Shoulders", []),
    "rear delt fly": ("Shoulders", ["Back"]),
    "reverse fly": ("Shoulders", ["Back"]),
    "pull-up": ("Back", ["Biceps"]),
    "pullup": ("Back", ["Biceps"]),
    "chin-up": ("Back", ["Biceps"]),
    "lat pulldown": ("Back", ["Biceps"]),
    "barbell row": ("Back", ["Biceps"]),
    "dumbbell row": ("Back", ["Biceps"]),
    "seated cable row": ("Back", ["Biceps"]),
    "t-bar row": ("Back", ["Biceps"]),
    "t bar row": ("Back", ["Biceps"]),
    "straight arm pulldown": ("Back", []),
    "shrug": ("Back", []),
    "deadlift": ("Back", ["Hamstrings", "Glutes", "Abs/Core"]),
    "squat": ("Quads", ["Glutes", "Abs/Core"]),
    "front squat": ("Quads", ["Glutes", "Abs/Core"]),
    "split squat": ("Quads", ["Glutes", "Abs/Core"]),
    "lunge": ("Quads", ["Glutes", "Abs/Core"]),
    "leg press": ("Quads", ["Glutes"]),
    "leg extension": ("Quads", []),
    "romanian deadlift": ("Hamstrings", ["Glutes"]),
    "rdl": ("Hamstrings", ["Glutes"]),
    "leg curl": ("Hamstrings", []),
    "hip thrust": ("Glutes", ["Hamstrings"]),
    "glute bridge": ("Glutes", ["Hamstrings"]),
    "calf raise": ("Calves", []),
    "barbell curl": ("Biceps", []),
    "dumbbell curl": ("Biceps", []),
    "incline curl": ("Biceps", []),
    "hammer curl": ("Biceps", ["Forearms"]),
    "preacher curl": ("Biceps", []),
    "triceps pushdown": ("Triceps", []),
    "tricep pushdown": ("Triceps", []),
    "rope pushdown": ("Triceps", []),
    "skull crusher": ("Triceps", []),
    "skullcrusher": ("Triceps", []),
    "close grip bench": ("Triceps", ["Chest"]),
    "plank": ("Abs/Core", []),
    "cable crunch": ("Abs/Core", []),
    "crunch": ("Abs/Core", []),
    "wrist curl": ("Forearms", []),
    "wrist extension": ("Forearms", []),
    "reverse curl": ("Forearms", ["Biceps"]),
    "farmer": ("Forearms", ["Back"]),
}


def _canonical_group(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    lowered = clean.lower()
    if lowered in GROUP_ALIASES:
        return GROUP_ALIASES[lowered]
    for group in MUSCLE_GROUPS:
        if lowered == group.lower():
            return group
    return ""


def get_exercise_muscle_group(exercise_name: str, hevy_exercise_data: dict | None = None) -> dict:
    """Resolve primary/secondary muscle groups from Hevy metadata or local mapping."""
    hevy_exercise_data = hevy_exercise_data or {}
    explicit = (
        hevy_exercise_data.get("primaryMuscleGroup")
        or hevy_exercise_data.get("primary_muscle_group")
        or hevy_exercise_data.get("muscle_group")
        or ""
    )
    if isinstance(explicit, list):
        explicit = explicit[0] if explicit else ""
    primary = _canonical_group(str(explicit).split(",", 1)[0])
    secondary_values = hevy_exercise_data.get("secondaryMuscleGroups") or hevy_exercise_data.get("secondary_muscle_groups") or []
    if isinstance(secondary_values, str):
        secondary_values = [value.strip() for value in secondary_values.split(",")]
    secondary = [_canonical_group(str(value)) for value in secondary_values]
    secondary = [value for value in secondary if value]
    if primary:
        return {"primaryMuscleGroup": primary, "secondaryMuscleGroups": secondary, "muscleGroupSource": "hevy"}

    lowered = str(exercise_name or "").strip().lower()
    for key, (mapped_primary, mapped_secondary) in EXERCISE_MUSCLE_MAP.items():
        if key in lowered:
            return {
                "primaryMuscleGroup": mapped_primary,
                "secondaryMuscleGroups": mapped_secondary,
                "muscleGroupSource": "local_mapping",
            }

    if lowered and lowered not in _WARNED_UNMAPPED:
        _WARNED_UNMAPPED.add(lowered)
        logger.warning("Unmapped exercise muscle group: %s", exercise_name)
    return {"primaryMuscleGroup": "Other", "secondaryMuscleGroups": [], "muscleGroupSource": "unknown"}
