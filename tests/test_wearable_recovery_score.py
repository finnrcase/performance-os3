"""Tests for the wearable-based recovery/readiness score."""

import unittest
from datetime import date, timedelta

import pandas as pd

from src.wearables import calculate_wearable_recovery_score


def _wearable_rows(days: int, *, sleep_hours: float, resting_hr: float, hrv: float, provider: str = "fitbit") -> pd.DataFrame:
    """Build a steady wearable history with a final-day reading to score."""
    today = date.today()
    rows = []
    for i in range(days):
        d = today - timedelta(days=days - 1 - i)
        rows.append({
            "date": d.isoformat(),
            "provider": provider,
            "sleep_hours": sleep_hours,
            "sleep_efficiency": 92,
            "deep_sleep_minutes": 90,
            "rem_sleep_minutes": 100,
            "resting_hr": resting_hr,
            "hrv": hrv,
            "placeholder": False,
            "populated_metric_count": 5,
        })
    return pd.DataFrame(rows)


class WearableRecoveryScoreTest(unittest.TestCase):
    def test_insufficient_data_returns_null_score_not_zero(self):
        result = calculate_wearable_recovery_score(None)
        self.assertEqual(result["status"], "insufficient_wearable_data")
        self.assertIsNone(result["recovery_score"])  # never a misleading 0
        self.assertEqual(result["readiness_status"], "gray")

    def test_score_drops_when_sleep_drops(self):
        good = calculate_wearable_recovery_score(_wearable_rows(14, sleep_hours=8.0, resting_hr=52, hrv=70))
        poor = calculate_wearable_recovery_score(_wearable_rows(14, sleep_hours=4.5, resting_hr=52, hrv=70))
        self.assertEqual(good["status"], "ok")
        self.assertLess(poor["recovery_score"], good["recovery_score"])

    def test_score_drops_when_resting_hr_spikes(self):
        # 13 baseline days at 52, final day elevated to 64.
        rows = _wearable_rows(14, sleep_hours=7.5, resting_hr=52, hrv=70)
        rows.loc[rows.index[-1], "resting_hr"] = 64
        elevated = calculate_wearable_recovery_score(rows)
        baseline = calculate_wearable_recovery_score(_wearable_rows(14, sleep_hours=7.5, resting_hr=52, hrv=70))
        self.assertLess(elevated["recovery_score"], baseline["recovery_score"])
        self.assertIn("resting_hr", elevated["data_sources_used"])

    def test_score_drops_when_hrv_falls(self):
        rows = _wearable_rows(14, sleep_hours=7.5, resting_hr=52, hrv=70)
        rows.loc[rows.index[-1], "hrv"] = 45  # well below the 70 baseline
        low_hrv = calculate_wearable_recovery_score(rows)
        baseline = calculate_wearable_recovery_score(_wearable_rows(14, sleep_hours=7.5, resting_hr=52, hrv=70))
        self.assertLess(low_hrv["recovery_score"], baseline["recovery_score"])
        self.assertIn("hrv", low_hrv["data_sources_used"])

    def test_outputs_required_fields_and_recommendations(self):
        result = calculate_wearable_recovery_score(_wearable_rows(14, sleep_hours=8.0, resting_hr=50, hrv=80))
        for field in (
            "recovery_score",
            "readiness_status",
            "lift_recommendation",
            "run_recommendation",
            "same_day_lift_and_run_recommendation",
            "drivers",
            "confidence",
            "data_sources_used",
        ):
            self.assertIn(field, result)
        self.assertIn(result["readiness_status"], {"green", "yellow", "orange", "red"})
        self.assertTrue(0 <= result["recovery_score"] <= 100)

    def test_red_status_blocks_same_day_two_a_day(self):
        rows = _wearable_rows(14, sleep_hours=7.5, resting_hr=52, hrv=70)
        # Tank the final day across sleep + RHR + HRV.
        rows.loc[rows.index[-1], "sleep_hours"] = 3.5
        rows.loc[rows.index[-1], "resting_hr"] = 68
        rows.loc[rows.index[-1], "hrv"] = 38
        result = calculate_wearable_recovery_score(rows)
        self.assertIn(result["readiness_status"], {"orange", "red"})
        self.assertIn("No", result["same_day_lift_and_run_recommendation"]) if result["readiness_status"] == "red" else None


if __name__ == "__main__":
    unittest.main()
