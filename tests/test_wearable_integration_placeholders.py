import pandas as pd

from src.config import default_settings, integration_status, load_settings
from src.integrations import fitbit_client, google_health_client
from src.wearables import WEARABLE_METRIC_COLUMNS


def test_google_health_settings_fields_are_present():
    settings = default_settings()

    assert "google_health_client_id" in settings["integrations"]
    assert "google_health_client_secret" in settings["integrations"]
    assert "google_health_redirect_uri" in settings["integrations"]
    assert "google_health_client_id" in load_settings()["integrations"]
    assert integration_status("google_health_client_id", settings) == "Not configured"


def test_fitbit_placeholder_functions_are_safe_without_credentials():
    settings = default_settings()

    assert fitbit_client.is_configured(settings) is False
    assert fitbit_client.get_auth_url(settings)["status"] == "not_configured"
    assert fitbit_client.exchange_code_for_token("code", settings)["status"] == "not_configured"
    assert fitbit_client.refresh_access_token("refresh", settings)["status"] == "not_configured"
    assert fitbit_client.fetch_daily_metrics("")["status"] == "missing_access_token"


def test_google_health_functions_are_safe_without_credentials():
    settings = default_settings()

    assert google_health_client.is_configured(settings) is False
    assert google_health_client.get_auth_url(settings)["status"] == "not_configured"
    assert google_health_client.exchange_code_for_token("code", settings)["status"] == "not_configured"
    assert google_health_client.refresh_access_token("refresh", settings)["status"] == "not_configured"
    assert google_health_client.fetch_daily_metrics("")["status"] == "missing_access_token"


def test_placeholder_auth_urls_when_configured_do_not_require_secrets_in_url():
    settings = default_settings()
    settings["integrations"].update(
        {
            "fitbit_client_id": "fitbit-id",
            "fitbit_client_secret": "fitbit-secret",
            "google_health_client_id": "google-id",
            "google_health_client_secret": "google-secret",
            "google_health_redirect_uri": "http://localhost/google",
        }
    )

    fitbit = fitbit_client.get_auth_url(settings, redirect_uri="http://localhost/fitbit", state="abc")
    google = google_health_client.get_auth_url(settings, redirect_uri="http://localhost/google", state="xyz")

    assert fitbit["status"] == "placeholder"
    assert "fitbit-id" in fitbit["auth_url"]
    assert "fitbit-secret" not in fitbit["auth_url"]
    assert google["status"] == "ok"
    assert "google-id" in google["auth_url"]
    assert "google-secret" not in google["auth_url"]


def test_google_health_aggregate_response_normalizes_daily_metrics(monkeypatch):
    def fake_post_json(_url, body, _access_token, **_kwargs):
        requested = {item["dataTypeName"] for item in body.get("aggregateBy", [])}
        points = []
        if "com.google.step_count.delta" in requested:
            points.append({"dataTypeName": "com.google.step_count.delta", "value": [{"intVal": 9000}]})
        if "com.google.calories.expended" in requested:
            points.append({"dataTypeName": "com.google.calories.expended", "value": [{"fpVal": 2450.5}]})
        if "com.google.active_minutes" in requested:
            points.append({"dataTypeName": "com.google.active_minutes", "value": [{"intVal": 62}]})
        if "com.google.sleep.segment" in requested:
            points.append(
                {
                    "dataTypeName": "com.google.sleep.segment",
                    "startTimeNanos": "0",
                    "endTimeNanos": "3600000000000",
                    "value": [{"intVal": 6}],
                }
            )
        if "com.google.heart_rate.summary" in requested:
            points.append({"dataTypeName": "com.google.heart_rate.summary", "value": [{"fpVal": 62}, {"fpVal": 151}, {"fpVal": 48}]})
        return {
            "bucket": [
                {
                    "startTimeMillis": 1_715_817_600_000,
                    "dataset": [{"point": points}],
                }
            ]
        }

    monkeypatch.setattr(google_health_client, "_post_json", fake_post_json)

    fetched = google_health_client.fetch_daily_metrics("token", start_date="2024-05-16", end_date="2024-05-16")
    normalized = google_health_client.normalize_daily_metrics(fetched["items"])

    assert fetched["status"] == "ok"
    assert normalized.iloc[0]["source"] == "google_health"
    assert int(normalized.iloc[0]["steps"]) == 9000
    assert int(normalized.iloc[0]["active_minutes"]) == 62
    assert normalized.iloc[0]["sleep_hours"] == 1
    assert int(normalized.iloc[0]["rem_sleep_minutes"]) == 60
    assert int(normalized.iloc[0]["resting_hr"]) == 48
    assert fetched["records"]["sleep"][0]["rem_sleep_minutes"] == 60
    assert fetched["records"]["heart"][0]["max_hr"] == 151


def test_google_health_records_include_rhr_baseline_and_activity_model():
    rows = []
    for index in range(8):
        rows.append(
            {
                "date": f"2026-05-{10 + index:02d}",
                "source": "google_health",
                "resting_hr": 55 if index < 7 else 62,
                "sleep_hours": 7.5 if index < 7 else 6.0,
                "steps": 7000,
                "active_minutes": 45,
                "active_zone_minutes": 12,
                "total_calories_burned": 2500,
            }
        )

    records = google_health_client.build_google_health_records(rows)
    latest_summary = records["daily_summary"][-1]
    latest_recovery = records["recovery_signals"][-1]

    assert latest_summary["resting_hr_baseline"] == 55
    assert latest_summary["resting_hr_deviation"] == 7
    assert latest_recovery["recovery_warning"] is True
    assert records["activity"][-1]["total_calories_burned"] == 2500


def test_placeholder_normalizers_return_wearable_schema():
    fitbit_df = fitbit_client.normalize_daily_metrics(
        [{"date": "2026-05-24", "sleep_hours": 7.5, "steps": 9000}]
    )
    google_df = google_health_client.normalize_daily_metrics(
        pd.DataFrame([{"date": "2026-05-24", "hrv": 62}])
    )

    assert fitbit_df.columns.tolist() == WEARABLE_METRIC_COLUMNS
    assert google_df.columns.tolist() == WEARABLE_METRIC_COLUMNS
    assert fitbit_df.iloc[0]["source"] == "fitbit"
    assert google_df.iloc[0]["source"] == "google_health"
