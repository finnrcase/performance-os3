import pandas as pd

from src.config import default_settings, integration_status, load_settings
from src.integrations import fitbit_client, google_health_client
from src.wearables import WEARABLE_METRIC_COLUMNS


def test_google_health_settings_fields_are_present():
    settings = default_settings()

    assert "google_health_client_id" in settings["integrations"]
    assert "google_health_client_secret" in settings["integrations"]
    assert "google_health_client_id" in load_settings()["integrations"]
    assert integration_status("google_health_client_id", settings) == "Not configured"


def test_fitbit_placeholder_functions_are_safe_without_credentials():
    settings = default_settings()

    assert fitbit_client.is_configured(settings) is False
    assert fitbit_client.get_auth_url(settings)["status"] == "not_configured"
    assert fitbit_client.exchange_code_for_token("code", settings)["status"] == "not_configured"
    assert fitbit_client.refresh_access_token("refresh", settings)["status"] == "not_configured"
    assert fitbit_client.fetch_daily_metrics("")["status"] == "missing_access_token"


def test_google_health_placeholder_functions_are_safe_without_credentials():
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
        }
    )

    fitbit = fitbit_client.get_auth_url(settings, redirect_uri="http://localhost/fitbit", state="abc")
    google = google_health_client.get_auth_url(settings, redirect_uri="http://localhost/google", state="xyz")

    assert fitbit["status"] == "placeholder"
    assert "fitbit-id" in fitbit["auth_url"]
    assert "fitbit-secret" not in fitbit["auth_url"]
    assert google["status"] == "placeholder"
    assert "google-id" in google["auth_url"]
    assert "google-secret" not in google["auth_url"]


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

