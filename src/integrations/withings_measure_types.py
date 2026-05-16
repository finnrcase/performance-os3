"""Withings Measure API ``meastype`` mapping for Performance OS.

Withings ``Measure v2 - Getmeas`` returns each weigh-in as a ``measuregrp`` with a
list of ``measures``. Each measure has an integer ``type`` (the ``meastype``) and a
``value``/``unit`` pair where the real value is ``value * 10 ** unit``.

The integer codes below come from the official Withings developer documentation
(Measure > Getmeas, "Measurement Types" table). Only body-composition types used
by Performance OS are mapped here. If Withings adds or changes a code, update this
file — do not guess elsewhere in the codebase.

Reference: https://developer.withings.com/api-reference/#tag/measure
"""

from __future__ import annotations

KG_TO_LB = 2.2046226218

# meastype -> normalized field name. All mass fields are reported by Withings in
# kilograms; "fat_ratio" is a percentage; "height" is in meters.
WITHINGS_MEASURE_TYPES: dict[int, str] = {
    1: "weight_kg",        # Weight (kg)
    4: "height_m",         # Height (meter) — used to derive BMI
    5: "lean_mass_kg",     # Fat Free Mass (kg)
    6: "body_fat_percent", # Fat Ratio (%)
    8: "fat_mass_kg",      # Fat Mass Weight (kg)
    76: "muscle_mass_kg",  # Muscle Mass (kg)
    77: "hydration_kg",    # Hydration (kg)
    88: "bone_mass_kg",    # Bone Mass (kg)
}

# Comma-separated meastypes requested from the Getmeas endpoint.
WITHINGS_REQUESTED_MEASTYPES = ",".join(str(code) for code in sorted(WITHINGS_MEASURE_TYPES))

# Fields that are a mass in kilograms and should also be exposed in pounds.
WITHINGS_MASS_FIELDS = {
    "weight_kg": "weight_lb",
    "lean_mass_kg": "lean_mass_lb",
    "fat_mass_kg": "fat_mass_lb",
    "muscle_mass_kg": "muscle_mass_lb",
    "bone_mass_kg": "bone_mass_lb",
    "hydration_kg": "hydration_lb",
}


def measure_value(measure: dict) -> float | None:
    """Return the real value for one Withings ``measures`` entry, or None."""
    try:
        raw = float(measure["value"])
        unit = int(measure.get("unit", 0))
    except (KeyError, TypeError, ValueError):
        return None
    return raw * (10 ** unit)


def parse_measure_group(group: dict) -> dict:
    """Convert one Withings ``measuregrp`` into a normalized measurement dict.

    Returns a dict with the kg fields present in the group, plus pound
    conversions for every mass field. Missing measures are simply absent.
    """
    parsed: dict[str, float] = {}
    for measure in group.get("measures", []) or []:
        field = WITHINGS_MEASURE_TYPES.get(int(measure.get("type", -1)))
        if not field:
            continue
        value = measure_value(measure)
        if value is None:
            continue
        parsed[field] = round(value, 4)

    for kg_field, lb_field in WITHINGS_MASS_FIELDS.items():
        if kg_field in parsed:
            parsed[lb_field] = round(parsed[kg_field] * KG_TO_LB, 2)

    return parsed


def derive_bmi(weight_kg: float | None, height_m: float | None) -> float | None:
    """Compute BMI from weight (kg) and height (m). Withings has no BMI meastype."""
    if not weight_kg or not height_m or height_m <= 0:
        return None
    return round(weight_kg / (height_m * height_m), 1)
