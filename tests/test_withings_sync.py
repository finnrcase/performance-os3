import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend_new.main import app
from src import body_metrics as body_metrics_module
from src.integrations import withings_client


WITHINGS_MEASURE_RESPONSE = {
    "status": 0,
    "body": {
        "measuregrps": [
            {
                "grpid": 123,
                "date": 1_715_769_600,
                "measures": [
                    {"type": 1, "value": 82500, "unit": -3},
                    {"type": 4, "value": 180, "unit": -2},
                    {"type": 5, "value": 67031, "unit": -3},
                    {"type": 6, "value": 1875, "unit": -2},
                    {"type": 8, "value": 15469, "unit": -3},
                    {"type": 76, "value": 62000, "unit": -3},
                    {"type": 77, "value": 45000, "unit": -3},
                ],
            }
        ]
    },
}


class WithingsSyncTest(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {"DATABASE_URL": ""})
        self.env_patch.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.env_patch.stop()

    def test_sync_imports_scale_measurements_into_body_metrics_idempotently(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "body_metrics.csv"
            with patch.object(body_metrics_module, "BODY_METRICS_PATH", metrics_path), patch(
                "src.integrations.withings_client.refresh_withings_token_if_needed",
                return_value={"access_token": "token"},
            ), patch("src.integrations.withings_client._post_form", return_value=WITHINGS_MEASURE_RESPONSE), patch(
                "src.integrations.withings_client._save_withings_sync_state",
                side_effect=lambda updates: updates,
            ):
                first = withings_client.sync_withings_measurements(days=30)
                second = withings_client.sync_withings_measurements(days=30)
                saved = body_metrics_module.load_body_metrics()

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["imported_measurements"], 1)
        self.assertEqual(len(saved), 1)
        self.assertAlmostEqual(float(saved["bodyweight"].iloc[0]), 181.88, places=2)
        self.assertAlmostEqual(float(saved["estimated_body_fat"].iloc[0]), 18.75, places=2)
        self.assertAlmostEqual(float(saved["body_fat_percent"].iloc[0]), 18.75, places=2)
        self.assertAlmostEqual(float(saved["fat_mass"].iloc[0]), 34.1, places=2)
        self.assertAlmostEqual(float(saved["lean_mass"].iloc[0]), 147.78, places=2)
        self.assertAlmostEqual(float(saved["muscle_mass"].iloc[0]), 136.69, places=2)
        self.assertAlmostEqual(float(saved["hydration"].iloc[0]), 99.21, places=2)
        self.assertAlmostEqual(float(saved["bmi"].iloc[0]), 25.46, places=2)
        self.assertIn("source=withings", saved["notes"].iloc[0])
        self.assertIn("withings_measure_group_id=123", saved["notes"].iloc[0])

    def test_history_sync_paginates_measurement_groups(self):
        page_one = {
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "grpid": 201,
                        "date": 1_715_769_600,
                        "measures": [{"type": 1, "value": 70000, "unit": -3}],
                    }
                ],
                "more": 1,
                "offset": "next-page",
            },
        }
        page_two = {
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "grpid": 202,
                        "date": 1_715_856_000,
                        "measures": [{"type": 1, "value": 70500, "unit": -3}],
                    }
                ],
                "more": 0,
            },
        }
        captured_bodies = []

        def fake_post(_url, body, **_kwargs):
            captured_bodies.append(dict(body))
            return [page_one, page_two][len(captured_bodies) - 1]

        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "body_metrics.csv"
            with patch.object(body_metrics_module, "BODY_METRICS_PATH", metrics_path), patch(
                "src.integrations.withings_client.refresh_withings_token_if_needed",
                return_value="token",
            ), patch("src.integrations.withings_client._post_form", side_effect=fake_post), patch(
                "src.integrations.withings_client._save_withings_sync_state",
                side_effect=lambda updates: updates,
            ):
                result = withings_client.sync_withings_measurements(days=3650, history=True)
                saved = body_metrics_module.load_body_metrics()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["pages_fetched"], 2)
        self.assertTrue(result["pagination_complete"])
        self.assertEqual(result["withings_measurement_groups"], 2)
        self.assertEqual(result["imported_measurements"], 2)
        self.assertEqual(len(saved), 2)
        self.assertNotIn("offset", captured_bodies[0])
        self.assertEqual(captured_bodies[1]["offset"], "next-page")
        self.assertEqual(sorted(saved["source_id"].astype(str).tolist()), ["201", "202"])

    def test_history_sync_retries_unbounded_when_date_window_is_shallow(self):
        shallow = {
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "grpid": 301,
                        "date": 1_715_769_600,
                        "measures": [{"type": 1, "value": 70000, "unit": -3}],
                    }
                ],
                "more": 0,
            },
        }
        full = {
            "status": 0,
            "body": {
                "measuregrps": [
                    {
                        "grpid": 301,
                        "date": 1_715_769_600,
                        "measures": [{"type": 1, "value": 70000, "unit": -3}],
                    },
                    {
                        "grpid": 302,
                        "date": 1_715_856_000,
                        "measures": [{"type": 1, "value": 70500, "unit": -3}],
                    },
                    {
                        "grpid": 303,
                        "date": 1_715_942_400,
                        "measures": [{"type": 1, "value": 71000, "unit": -3}],
                    },
                    {
                        "grpid": 304,
                        "date": 1_716_028_800,
                        "measures": [{"type": 1, "value": 71500, "unit": -3}],
                    },
                    {
                        "grpid": 305,
                        "date": 1_716_115_200,
                        "measures": [{"type": 1, "value": 72000, "unit": -3}],
                    },
                    {
                        "grpid": 306,
                        "date": 1_716_201_600,
                        "measures": [{"type": 1, "value": 72500, "unit": -3}],
                    },
                ],
                "more": 0,
            },
        }
        captured_bodies = []

        def fake_post(_url, body, **_kwargs):
            captured_bodies.append(dict(body))
            return shallow if len(captured_bodies) == 1 else full

        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_path = Path(temp_dir) / "body_metrics.csv"
            with patch.object(body_metrics_module, "BODY_METRICS_PATH", metrics_path), patch(
                "src.integrations.withings_client.refresh_withings_token_if_needed",
                return_value="token",
            ), patch("src.integrations.withings_client._post_form", side_effect=fake_post), patch(
                "src.integrations.withings_client._save_withings_sync_state",
                side_effect=lambda updates: updates,
            ):
                result = withings_client.sync_withings_measurements(days=3650, history=True, include_rows=True)
                saved = body_metrics_module.load_body_metrics()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["history_strategy"], "unbounded_fallback")
        self.assertEqual(result["withings_measurement_groups"], 6)
        self.assertEqual(len(result["_measurement_rows"]), 6)
        self.assertEqual(len(saved), 6)
        self.assertIn("startdate", captured_bodies[0])
        self.assertNotIn("startdate", captured_bodies[1])

    def test_backend_new_sync_history_persists_withings_rows_to_body_metric_logs(self):
        result = {
            "status": "ok",
            "imported_measurements": 1,
            "created_measurements": 1,
            "updated_measurements": 0,
            "fetched_groups": 1,
            "withings_measurement_groups": 1,
            "earliest_date": "2026-05-20",
            "latest_date": "2026-05-20",
            "_measurement_rows": [
                {
                    "date": "2026-05-20",
                    "bodyweight": 156.9,
                    "source": "withings",
                    "source_id": "withings-1",
                }
            ],
        }
        saved = []

        def fake_upsert(table, key_field, key_value, data):
            saved.append((table, key_field, key_value, data))
            return data

        with patch("src.integrations.withings_client.sync_withings_measurements", return_value=result), patch(
            "backend_new.routes.body_metrics.upsert_json_row",
            side_effect=fake_upsert,
        ), patch("backend_new.routes.body_metrics.fetch_json_rows", return_value=[]):
            response = self.client.post("/api/withings/sync-history", json={"days": 3650})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["db_persisted_rows"], 1)
        self.assertEqual(saved[0][0], "body_metric_logs")
        self.assertEqual(saved[0][1], "source_id")
        self.assertEqual(saved[0][2], "withings-1")
        self.assertEqual(saved[0][3]["body_metric_id"], "withings-1")

    def test_body_metrics_withings_sync_endpoint_persists_and_reports_freshness(self):
        result = {
            "status": "ok",
            "imported_measurements": 1,
            "created_measurements": 1,
            "updated_measurements": 0,
            "fetched_groups": 1,
            "withings_measurement_groups": 1,
            "earliest_date": "2026-05-20",
            "latest_date": "2026-05-20",
            "latest_measure_date": "2026-05-20",
            "last_synced_at": "2026-05-21T12:00:00+00:00",
            "_measurement_rows": [
                {
                    "date": "2026-05-20",
                    "bodyweight": 156.9,
                    "source": "withings",
                    "source_id": "withings-2",
                    "notes": "source=withings | measured_at=2026-05-20T14:15:00+00:00",
                }
            ],
        }
        saved = []

        def fake_upsert(table, key_field, key_value, data):
            saved.append((table, key_field, key_value, data))
            return data

        def fake_fetch(_table, **_kwargs):
            return [entry[3] for entry in saved]

        with patch("src.integrations.withings_client.sync_withings_measurements", return_value=result), patch(
            "backend_new.routes.body_metrics.upsert_json_row",
            side_effect=fake_upsert,
        ), patch("backend_new.routes.body_metrics.fetch_json_rows", side_effect=fake_fetch), patch(
            "backend_new.routes.body_metrics.fetch_latest_document",
            return_value={
                "integrations": {},
                "metadata": {
                    "withings_tokens": {"access_token": "access", "refresh_token": "refresh"},
                    "withings_sync": {"last_synced_at": "2026-05-21T12:00:00+00:00"},
                },
            },
        ):
            response = self.client.post("/api/body-metrics/sync/withings", json={"days": 30})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["db_persisted_rows"], 1)
        self.assertTrue(payload["cache_invalidated"])
        self.assertEqual(payload["freshness"]["raw_body_metric_rows"], 1)
        self.assertEqual(payload["freshness"]["latest_raw_measurement_at"], "2026-05-20T14:15:00+00:00")
        self.assertEqual(payload["freshness"]["canonical_daily_rows"], 1)
        self.assertEqual(payload["freshness"]["latest_canonical_weight"], 156.9)
        self.assertEqual(payload["freshness"]["latest_canonical_date"], "2026-05-20")
        self.assertEqual(saved[0][0], "body_metric_logs")
        self.assertEqual(saved[0][1], "source_id")
        self.assertEqual(saved[0][2], "withings-2")

    def test_connect_route_redirects_to_withings_authorization(self):
        with patch.dict(
            "os.environ",
            {
                "WITHINGS_CLIENT_ID": "client-id",
                "WITHINGS_CLIENT_SECRET": "secret",
                "WITHINGS_REDIRECT_URI": "https://example.com/api/withings/callback",
            },
            clear=False,
        ):
            response = self.client.get("/api/withings/connect", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertIn("https://account.withings.com/oauth2_user/authorize2", location)
        self.assertIn("client_id=client-id", location)
        self.assertIn("scope=user.metrics", location)

    def test_auth_url_route_returns_backend_generated_withings_authorization_url(self):
        with patch.dict(
            "os.environ",
            {
                "WITHINGS_CLIENT_ID": "client-id",
                "WITHINGS_CLIENT_SECRET": "secret",
                "WITHINGS_REDIRECT_URI": "https://api-production-b3ff.up.railway.app/api/withings/callback",
            },
            clear=False,
        ):
            response = self.client.get("/api/integrations/withings/auth-url")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["redirect_uri"], "https://api-production-b3ff.up.railway.app/api/withings/callback")
        self.assertIn("https://account.withings.com/oauth2_user/authorize2", data["auth_url"])
        self.assertIn("client_id=client-id", data["auth_url"])

    def test_callback_validation_methods_accept_empty_provider_checks(self):
        get_response = self.client.get("/api/withings/callback")
        post_response = self.client.post("/api/withings/callback")
        head_response = self.client.head("/api/withings/callback")
        options_response = self.client.options("/api/withings/callback")

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(get_response.json()["provider"], "withings")
        self.assertIn("callback reachable", get_response.json()["message"])
        self.assertEqual(post_response.status_code, 200)
        self.assertEqual(post_response.json()["provider"], "withings")
        self.assertIn("callback reachable", post_response.json()["message"])
        self.assertEqual(head_response.status_code, 200)
        self.assertIn(options_response.status_code, {200, 204})

    def test_sync_route_returns_error_when_not_connected(self):
        with patch(
            "src.integrations.withings_client.sync_withings_measurements",
            side_effect=withings_client.WithingsIntegrationError("Withings is not connected."),
        ):
            response = self.client.post("/api/withings/sync")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "error")
        self.assertIn("not connected", response.json()["message"])


if __name__ == "__main__":
    unittest.main()
