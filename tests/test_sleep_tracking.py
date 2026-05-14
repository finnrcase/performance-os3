import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from backend.main import app
from src import recovery as recovery_module


class SleepTrackingTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_sleep_entries_derive_from_manual_recovery_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            recovery_path = Path(temp_dir) / "recovery_log.csv"
            sleep_path = Path(temp_dir) / "sleep_entries.csv"
            pd.DataFrame(
                [
                    {
                        "date": "2026-05-13",
                        "sleep_hours": 7.7,
                        "sleep_quality": 8,
                        "fatigue": 4,
                        "soreness": 4,
                        "stress": 4,
                        "motivation": 8,
                        "resting_hr": 55,
                        "hrv": 70,
                        "notes": "",
                    }
                ]
            ).to_csv(recovery_path, index=False)

            with patch.object(recovery_module, "RECOVERY_LOG_PATH", recovery_path), patch.object(recovery_module, "SLEEP_ENTRIES_PATH", sleep_path):
                response = self.client.get("/api/recovery/sleep")

            self.assertEqual(response.status_code, 200)
            items = response.json()["items"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["source"], "manual")
            self.assertEqual(items[0]["durationMinutes"], 462)
            self.assertEqual(items[0]["efficiencyPercent"], 80)
            self.assertEqual(items[0]["restingHeartRate"], 55)
            self.assertEqual(items[0]["hrv"], 70)


if __name__ == "__main__":
    unittest.main()
