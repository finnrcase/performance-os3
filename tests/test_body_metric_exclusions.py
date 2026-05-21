import pandas as pd
from fastapi.testclient import TestClient

from backend_new.main import app
from backend_new.routes import body_metrics
from src.body_metrics import canonical_bodyweight_debug, canonical_daily_bodyweights


BAD_WITHINGS_ROW = {
    "date": "2024-05-15",
    "bodyweight": 181.88,
    "source": "withings",
    "source_id": "123",
    "excluded_from_analytics": True,
}


def test_canonical_daily_bodyweights_ignores_excluded_rows():
    frame = pd.DataFrame(
        [
            BAD_WITHINGS_ROW,
            {"date": "2026-05-15", "bodyweight": 156.9, "source": "withings"},
            {"date": "2026-05-15T21:00:00", "bodyweight": 159.2, "source": "withings"},
        ]
    )

    canonical = canonical_daily_bodyweights(frame)

    assert canonical["date"].dt.date.astype(str).tolist() == ["2026-05-15"]
    assert float(canonical.iloc[0]["bodyweight"]) == 156.9
    debug = canonical_bodyweight_debug(frame)
    assert debug["excluded_from_analytics_count"] == 1
    assert debug["canonical_daily_weight_count"] == 1


def test_body_metrics_api_hides_excluded_rows_from_history(monkeypatch):
    monkeypatch.setattr(
        body_metrics,
        "fetch_json_rows",
        lambda *args, **kwargs: [
            BAD_WITHINGS_ROW,
            {"date": "2026-05-15", "bodyweight": 156.9, "source": "withings"},
        ],
    )

    response = TestClient(app).get("/api/body-metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["excluded_raw_count"] == 1
    assert [item["date"] for item in payload["items"]] == ["2026-05-15"]
    assert all(item["bodyweight"] != 181.88 for item in payload["items"])
