import pandas as pd
from urllib.parse import parse_qs, urlparse

from src.config import default_settings, integration_status, load_settings
from src.integrations import fitbit_client, google_health_client
from src.wearables import WEARABLE_METRIC_COLUMNS


def _clear_fitbit_env(monkeypatch):
    for name in ("FITBIT_CLIENT_ID", "FITBIT_CLIENT_SECRET", "FITBIT_REDIRECT_URI", "FITBIT_SCOPES"):
        monkeypatch.delenv(name, raising=False)


def test_google_health_settings_fields_are_present():
    settings = default_settings()

    assert "google_health_client_id" in settings["integrations"]
    assert "google_health_client_secret" in settings["integrations"]
    assert "google_health_redirect_uri" in settings["integrations"]
    assert "google_health_client_id" in load_settings()["integrations"]
    assert integration_status("google_health_client_id", settings) == "Not configured"


def test_fitbit_functions_are_safe_without_credentials(monkeypatch):
    _clear_fitbit_env(monkeypatch)
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


def test_auth_urls_when_configured_do_not_require_secrets_in_url(monkeypatch):
    _clear_fitbit_env(monkeypatch)
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

    assert fitbit["status"] == "ok"
    assert "fitbit-id" in fitbit["auth_url"]
    assert "fitbit-secret" not in fitbit["auth_url"]
    assert google["status"] == "ok"
    assert "google-id" in google["auth_url"]
    assert "google-secret" not in google["auth_url"]
    google_query = parse_qs(urlparse(google["auth_url"]).query)
    assert google_query["include_granted_scopes"] == ["false"]
    assert all("/auth/fitness." not in scope for scope in google_query["scope"][0].split())


def test_google_health_scopes_filter_legacy_fitness_env(monkeypatch):
    monkeypatch.setenv(
        "GOOGLE_HEALTH_SCOPES",
        "https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly "
        "https://www.googleapis.com/auth/fitness.activity.read "
        "fitness_sleep_read",
    )

    configured_scopes = google_health_client.scopes()

    assert configured_scopes == ["https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly"]


def test_fitbit_token_exchange_and_refresh_parse_token_payloads(monkeypatch):
    settings = default_settings()
    settings["integrations"].update(
        {
            "fitbit_client_id": "fitbit-id",
            "fitbit_client_secret": "fitbit-secret",
            "fitbit_redirect_uri": "http://localhost/fitbit",
        }
    )

    def fake_post_form(_url, form, _settings):
        assert form["grant_type"] in {"authorization_code", "refresh_token"}
        return {
            "access_token": "access",
            "refresh_token": "refresh2" if form["grant_type"] == "refresh_token" else "refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
            "user_id": "user-1",
            "scope": "activity heartrate profile sleep",
        }

    monkeypatch.setattr(fitbit_client, "_post_form", fake_post_form)

    exchanged = fitbit_client.exchange_code_for_token("code", settings, redirect_uri="http://localhost/fitbit")
    refreshed = fitbit_client.refresh_access_token("refresh", settings)

    assert exchanged["status"] == "ok"
    assert exchanged["tokens"]["refresh_token"] == "refresh"
    assert exchanged["tokens"]["scopes"] == "activity heartrate profile sleep"
    assert refreshed["status"] == "ok"
    assert refreshed["tokens"]["refresh_token"] == "refresh2"


def test_fitbit_fetch_daily_metrics_parses_sleep_heart_and_activity(monkeypatch):
    def fake_get_json(path, _access_token):
        if "/activities/date/" in path:
            return {
                "summary": {
                    "steps": 9345,
                    "caloriesOut": 2637,
                    "activityCalories": 850,
                    "caloriesBMR": 1787,
                    "lightlyActiveMinutes": 35,
                    "fairlyActiveMinutes": 20,
                    "veryActiveMinutes": 12,
                    "distances": [{"activity": "total", "distance": 4.2}],
                }
            }
        if "/activities/heart/" in path:
            return {"activities-heart": [{"value": {"restingHeartRate": 52, "heartRateZones": [{"max": 120}, {"max": 185}]}}]}
        if "/sleep/date/" in path:
            return {
                "summary": {
                    "totalMinutesAsleep": 430,
                    "totalTimeInBed": 480,
                    "stages": {"rem": 92, "deep": 68, "light": 270, "wake": 50},
                },
                "sleep": [{"efficiency": 89}],
            }
        if "/hrv/" in path:
            return {"hrv": [{"value": {"dailyRmssd": 61}}]}
        if "/spo2/" in path:
            return {"value": {"avg": 97}}
        if "/temp/skin/" in path:
            return {"tempSkin": [{"value": {"nightlyRelative": 0.4}}]}
        if "/profile" in path:
            return {"user": {"encodedId": "user-1"}}
        return {}

    monkeypatch.setattr(fitbit_client, "_get_json", fake_get_json)

    fetched = fitbit_client.fetch_daily_metrics("token", start_date="2026-05-27", end_date="2026-05-27")
    normalized = fitbit_client.normalize_daily_metrics(fetched["items"])

    assert fetched["status"] == "ok"
    assert normalized.iloc[0]["source"] == "fitbit"
    assert int(normalized.iloc[0]["steps"]) == 9345
    assert int(normalized.iloc[0]["total_sleep_minutes"]) == 430
    assert int(normalized.iloc[0]["rem_sleep_minutes"]) == 92
    assert int(normalized.iloc[0]["deep_sleep_minutes"]) == 68
    assert int(normalized.iloc[0]["light_sleep_minutes"]) == 270
    assert int(normalized.iloc[0]["resting_hr"]) == 52
    assert int(normalized.iloc[0]["total_calories_burned"]) == 2637
    assert int(normalized.iloc[0]["active_minutes"]) == 67
    assert int(normalized.iloc[0]["hrv"]) == 61


def test_google_health_api_v4_response_normalizes_daily_metrics(monkeypatch):
    day = {"year": 2024, "month": 5, "day": 16}
    monkeypatch.setenv("GOOGLE_HEALTH_API_BASE_URL", "https://health.googleapis.com")

    def fake_get_json(url, _access_token, **_kwargs):
        if "/pairedDevices" in url:
            return {"pairedDevices": [{"displayName": "Pixel Watch", "manufacturer": "Google", "model": "PW"}]}
        if "/dataTypes/sleep/" in url:
            return {
                "dataPoints": [
                    {
                        "sleep": {
                            "interval": {"civilEndTime": {"date": day}},
                            "summary": {
                                "minutesAsleep": 480,
                                "minutesAwake": 30,
                                "stagesSummary": [
                                    {"type": "REM", "minutes": 60},
                                    {"type": "DEEP", "minutes": 70},
                                    {"type": "LIGHT", "minutes": 350},
                                ],
                            },
                        }
                    }
                ]
            }
        if "/dataTypes/daily-resting-heart-rate/" in url:
            return {"dataPoints": [{"dailyRestingHeartRate": {"date": day, "beatsPerMinute": 48}}]}
        if "/dataTypes/daily-heart-rate-variability/" in url:
            return {"dataPoints": [{"dailyHeartRateVariability": {"date": day, "averageHeartRateVariabilityMilliseconds": 61}}]}
        if "/dataTypes/daily-heart-rate-zones/" in url:
            return {"dataPoints": [{"dailyHeartRateZones": {"date": day, "heartRateZones": [{"zone": "CARDIO", "lowerBoundBpm": 120, "upperBoundBpm": 150}]}}]}
        if "/dataTypes/daily-respiratory-rate/" in url:
            return {"dataPoints": [{"dailyRespiratoryRate": {"date": day, "breathsPerMinute": 14.5}}]}
        return {"dataPoints": []}

    def fake_post_json(url, _body, _access_token, **_kwargs):
        assert "health.googleapis.com" in url
        if "/dataTypes/steps/" in url:
            value = {"steps": {"countSum": "9000"}}
        elif "/dataTypes/total-calories/" in url:
            value = {"totalCalories": {"kcalSum": 2450.5}}
        elif "/dataTypes/active-minutes/" in url:
            value = {"activeMinutes": {"activeMinutesRollupByActivityLevel": [{"activeMinutesSum": 62}]}}
        elif "/dataTypes/active-zone-minutes/" in url:
            value = {"activeZoneMinutes": {"sumInCardioHeartZone": 12, "sumInPeakHeartZone": 5, "sumInFatBurnHeartZone": 10}}
        elif "/dataTypes/heart-rate/" in url:
            value = {"heartRate": {"beatsPerMinuteAvg": 62, "beatsPerMinuteMax": 151, "beatsPerMinuteMin": 48}}
        else:
            value = {}
        return {"rollupDataPoints": [{"civilStartTime": {"date": day}, **value}]}

    monkeypatch.setattr(google_health_client, "_get_json", fake_get_json)
    monkeypatch.setattr(google_health_client, "_post_json", fake_post_json)

    fetched = google_health_client.fetch_daily_metrics("token", start_date="2024-05-16", end_date="2024-05-16")
    normalized = google_health_client.normalize_daily_metrics(fetched["items"])

    assert fetched["status"] == "ok"
    assert fetched["provider"] == "google_health"
    assert fetched["primary_provider"] == "google_health"
    assert fetched["api_path"] == "google_health_v4"
    assert fetched["deprecated_fitness_api_unused"] is True
    assert fetched["google_health_api_sync_available"] is True
    assert fetched["requests_sent_to_google_health_api"] > 0
    assert fetched["requests_sent_to_fitness_api"] == 0
    assert all("health.googleapis.com" in url for url in fetched["exact_endpoint_urls"])
    assert fetched["api_request_counts"]["google_fit_legacy"] == 0
    assert fetched["normalization_audit"]["steps"]["endpoint_url"].startswith("https://health.googleapis.com/")
    assert fetched["normalization_audit"]["steps"]["raw_datapoint_count"] == 1
    assert fetched["normalization_audit"]["steps"]["normalized_field_count"] >= 1
    assert fetched["normalization_audit"]["steps"]["dropped_field_count"] == 0
    assert "daily-respiratory-rate" in fetched["requested_data_types"]
    assert normalized.iloc[0]["source"] == "google_health"
    assert int(normalized.iloc[0]["steps"]) == 9000
    assert int(normalized.iloc[0]["active_minutes"]) == 62
    assert normalized.iloc[0]["sleep_hours"] == 8
    assert int(normalized.iloc[0]["rem_sleep_minutes"]) == 60
    assert int(normalized.iloc[0]["resting_hr"]) == 48
    assert normalized.iloc[0]["breathing_rate"] == 14.5
    assert fetched["records"]["sleep"][0]["rem_sleep_minutes"] == 60
    assert fetched["records"]["heart"][0]["max_hr"] == 151
    assert fetched["records"]["heart"][0]["hr_zones"][0]["zone"] == "CARDIO"
    assert fetched["empty_date_rows_count"] == 0
    assert fetched["fields_populated_count"] > 0


def test_google_health_optional_heart_rate_warning_is_nonfatal(monkeypatch):
    requested_urls = []
    day = {"year": 2024, "month": 5, "day": 16}
    monkeypatch.setenv("GOOGLE_HEALTH_API_BASE_URL", "https://health.googleapis.com")

    def fake_get_json(url, _access_token, **_kwargs):
        requested_urls.append(url)
        if "/pairedDevices" in url:
            return {"pairedDevices": []}
        if "/dataTypes/sleep/" in url:
            return {
                "dataPoints": [
                    {
                        "sleep": {
                            "interval": {"civilEndTime": {"date": day}},
                            "summary": {"minutesAsleep": 420, "minutesAwake": 30, "stagesSummary": []},
                        }
                    }
                ]
            }
        return {"dataPoints": []}

    def fake_post_json(url, _body, _access_token, **_kwargs):
        requested_urls.append(url)
        if "/dataTypes/steps/" in url:
            value = {"steps": {"countSum": "8000"}}
        elif "/dataTypes/total-calories/" in url:
            value = {"totalCalories": {"kcalSum": 2400}}
        elif "/dataTypes/active-minutes/" in url:
            value = {"activeMinutes": {"activeMinutesRollupByActivityLevel": [{"activeMinutesSum": 45}]}}
        elif "/dataTypes/heart-rate/" in url:
            value = {}
        else:
            value = {}
        return {"rollupDataPoints": [{"civilStartTime": {"date": day}, **value}]}

    monkeypatch.setattr(google_health_client, "_get_json", fake_get_json)
    monkeypatch.setattr(google_health_client, "_post_json", fake_post_json)

    fetched = google_health_client.fetch_daily_metrics("token", start_date="2024-05-16", end_date="2024-05-16")
    normalized = google_health_client.normalize_daily_metrics(fetched["items"])

    assert fetched["status"] == "ok"
    assert google_health_client.GOOGLE_HEALTH_OPTIONAL_HEART_RATE_WARNING in fetched["optional_metric_warnings"]
    assert fetched["required_metric_failures"] == []
    assert fetched["requests_sent_to_google_health_api"] > 0
    assert fetched["requests_sent_to_fitness_api"] == 0
    assert fetched["normalization_audit"]["sleep"]["raw_datapoint_count"] == 1
    assert fetched["normalization_audit"]["sleep"]["normalized_field_count"] >= 1
    assert len(normalized) == 1
    assert normalized.iloc[0]["resting_hr"] is None
    assert requested_urls


def test_google_health_empty_api_responses_do_not_return_placeholder_rows(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_API_BASE_URL", "https://health.googleapis.com")

    def fake_get_json(url, _access_token, **_kwargs):
        if "/pairedDevices" in url:
            return {"pairedDevices": []}
        return {"dataPoints": []}

    def fake_post_json(_url, _body, _access_token, **_kwargs):
        return {"rollupDataPoints": []}

    monkeypatch.setattr(google_health_client, "_get_json", fake_get_json)
    monkeypatch.setattr(google_health_client, "_post_json", fake_post_json)

    fetched = google_health_client.fetch_daily_metrics("token", start_date="2024-05-16", end_date="2024-05-16")
    normalized = google_health_client.normalize_daily_metrics(fetched["items"])

    assert fetched["status"] == "ok"
    assert fetched["items"] == []
    assert normalized.empty
    assert fetched["data_available"] is False
    assert fetched["data_sources"]["data_source_count"] == 0
    assert fetched["api_path"] == "google_health_v4"
    assert fetched["requests_sent_to_google_health_api"] > 0
    assert fetched["requests_sent_to_fitness_api"] == 0
    assert all(item["raw_datapoint_count"] == 0 for item in fetched["normalization_audit"].values())
    assert google_health_client.GOOGLE_HEALTH_NO_SOURCES_MESSAGE in fetched["warnings"]
    assert fetched["recommended_next_action"] == google_health_client.GOOGLE_HEALTH_NO_SOURCES_MESSAGE


def test_google_health_rejects_legacy_google_fit_rest_base_url(monkeypatch):
    monkeypatch.setenv("GOOGLE_HEALTH_API_BASE_URL", "https://fitness.googleapis.com")

    def fail_network(*_args, **_kwargs):
        raise AssertionError("Legacy Google Fit REST must not be queried as Google Health.")

    monkeypatch.setattr(google_health_client, "_get_json", fail_network)
    monkeypatch.setattr(google_health_client, "_post_json", fail_network)

    fetched = google_health_client.fetch_daily_metrics("token", start_date="2024-05-16", end_date="2024-05-16")
    sources = google_health_client.list_data_sources("token")
    normalized = google_health_client.normalize_daily_metrics(fetched["items"])

    assert fetched["status"] == "ok"
    assert fetched["items"] == []
    assert normalized.empty
    assert fetched["api_path"] == "google_fit_legacy"
    assert fetched["provider"] == "google_fit_legacy"
    assert fetched["primary_provider"] == "google_health"
    assert fetched["api_path_label"] == "Deprecated Google Fit REST API"
    assert fetched["legacy_google_fit_detected"] is True
    assert fetched["google_health_api_sync_available"] is False
    assert fetched["google_fit_legacy_data_source_status"] == "found"
    assert fetched["google_fit_unused"] is False
    assert fetched["data_available"] is False
    assert fetched["populated_days"] == 0
    assert fetched["recommended_next_action"] == google_health_client.GOOGLE_FIT_LEGACY_CONFIG_MESSAGE
    assert fetched["requests_sent_to_google_health_api"] == 0
    assert fetched["requests_sent_to_fitness_api"] == 0
    assert fetched["exact_endpoint_urls"] == []
    assert sources["status"] == "legacy_google_fit_configured"
    assert sources["api_path"] == "google_fit_legacy"
    assert sources["requests_sent_to_google_health_api"] == 0
    assert sources["requests_sent_to_fitness_api"] == 0


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
    assert fitbit_df.iloc[0]["provider"] == "fitbit"
    assert google_df.iloc[0]["source"] == "google_health"
    assert google_df.iloc[0]["provider"] == "google_health"
    assert google_df.iloc[0]["populated_metric_count"] == 1
    assert bool(google_df.iloc[0]["placeholder"]) is False
