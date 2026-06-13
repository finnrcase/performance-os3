"""Tests for the adaptive calorie engine (wearable-aware maintenance)."""

import unittest
from datetime import date, timedelta

import pandas as pd

from src.nutrition_targets import (
    calculate_macro_targets,
    estimate_adaptive_maintenance_calories,
    estimate_maintenance_calories,
)


def _goals() -> dict:
    return {
        "current_bodyweight": 180,
        "goal_bodyweight": 188,
        "timeline_weeks": 20,
        "goal_type": "Lean Bulk",
        "training_frequency_per_week": 4,
        "cardio_frequency_per_week": 2,
        "estimated_body_fat": None,
        "activity_level": "Moderate",
        "aggressiveness": "Conservative",
    }


def _wearable_rows(days: int, burn: float, *, provider: str = "fitbit", end_offset: int = 0) -> pd.DataFrame:
    today = date.today()
    rows = []
    for i in range(days):
        d = today - timedelta(days=i + end_offset)
        rows.append({
            "date": d.isoformat(),
            "provider": provider,
            "source": provider,
            "total_calories_burned": burn,
            "steps": 9000,
            "active_minutes": 45,
            "placeholder": False,
            "populated_metric_count": 4,
        })
    return pd.DataFrame(rows)


class AdaptiveCalorieEngineTest(unittest.TestCase):
    def test_target_changes_when_wearable_burn_changes(self):
        goals = _goals()
        low = calculate_macro_targets(goals, wearable_df=_wearable_rows(14, 2500))
        high = calculate_macro_targets(goals, wearable_df=_wearable_rows(14, 3200))
        # Higher measured energy burn must raise the calorie target.
        self.assertGreater(high["target_calories"], low["target_calories"])
        self.assertTrue(low["wearable_included_in_target"])
        self.assertTrue(high["wearable_included_in_target"])
        self.assertGreater(high["adaptive_maintenance_calories"], low["adaptive_maintenance_calories"])

    def test_target_does_not_change_when_wearable_is_stale(self):
        goals = _goals()
        # Same high burn, but the latest row is 20 days old -> must be ignored.
        stale = calculate_macro_targets(goals, wearable_df=_wearable_rows(14, 3200, end_offset=20))
        missing = calculate_macro_targets(goals, wearable_df=None)
        self.assertFalse(stale["wearable_included_in_target"])
        self.assertEqual(stale["adaptive_maintenance_calories"], missing["adaptive_maintenance_calories"])
        self.assertEqual(stale["target_calories"], missing["target_calories"])

    def test_fallback_when_wearable_missing(self):
        goals = _goals()
        result = estimate_adaptive_maintenance_calories(goals, wearable_df=None)
        self.assertEqual(result["calorie_engine_confidence"], "low")
        self.assertEqual(result["data_sources_used"], ["profile"])
        self.assertEqual(
            result["adaptive_maintenance_calories"],
            result["profile_estimated_maintenance"],
        )
        # Falls back to the profile (bodyweight x activity) estimate.
        self.assertEqual(
            result["adaptive_maintenance_calories"],
            int(round(estimate_maintenance_calories(goals), -1)),
        )

    def test_bodyweight_trend_correction_still_applies(self):
        goals = _goals()
        today = date.today()
        # 14 days of fast weight gain -> "gaining too fast" -> negative adjustment.
        fast_gain = pd.DataFrame([
            {"date": (today - timedelta(days=13 - i)).isoformat(), "bodyweight": 180 + i * 0.4}
            for i in range(14)
        ])
        flat = pd.DataFrame([
            {"date": (today - timedelta(days=13 - i)).isoformat(), "bodyweight": 180.0}
            for i in range(14)
        ])
        gaining_fast = calculate_macro_targets(goals, body_metrics_df=fast_gain, wearable_df=None)
        stable = calculate_macro_targets(goals, body_metrics_df=flat, wearable_df=None)
        self.assertEqual(gaining_fast["bodyweight_trend_signal"]["status"], "gaining too fast")
        # Fast gain pulls the target below the otherwise-stable target.
        self.assertLess(gaining_fast["target_calories"], stable["target_calories"])

    def test_fitbit_and_google_health_normalize_to_same_path(self):
        goals = _goals()
        fitbit = estimate_adaptive_maintenance_calories(goals, wearable_df=_wearable_rows(14, 2900, provider="fitbit"))
        google = estimate_adaptive_maintenance_calories(goals, wearable_df=_wearable_rows(14, 2900, provider="google_health"))
        # Identical burn from either provider yields identical maintenance.
        self.assertEqual(
            fitbit["adaptive_maintenance_calories"],
            google["adaptive_maintenance_calories"],
        )
        self.assertTrue(fitbit["wearable_included_in_target"])
        self.assertTrue(google["wearable_included_in_target"])
        self.assertEqual(fitbit["wearable_provider"], "fitbit")
        self.assertEqual(google["wearable_provider"], "google_health")


if __name__ == "__main__":
    unittest.main()
