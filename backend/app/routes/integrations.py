from __future__ import annotations

import os

from fastapi import APIRouter

from backend.app.routes.settings import settings_payload


router = APIRouter(tags=["integrations"])


def _configured(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


@router.get("/api/integrations/status")
def integrations_status(external_checks: bool = False) -> dict:
    settings = settings_payload()
    return {
        **settings,
        "external_checks": external_checks,
        "services": {
            "hevy": {"configured": _configured("HEVY_API_KEY"), "status": "disabled"},
            "strava": {"configured": _configured("STRAVA_CLIENT_ID") and _configured("STRAVA_CLIENT_SECRET"), "status": "disabled"},
            "withings": {"configured": _configured("WITHINGS_CLIENT_ID") and _configured("WITHINGS_CLIENT_SECRET"), "status": "disabled"},
            "openai": {"configured": _configured("OPENAI_API_KEY"), "status": "disabled"},
        },
    }


@router.get("/api/integrations/test")
def integrations_test() -> dict:
    return {"status": "ok", "message": "External integration probes are disabled in the clean backend.", "results": {}}


@router.get("/api/integrations/strava/auth-url")
def strava_auth_url(reconnect: bool = False) -> dict:
    return {"status": "disabled", "reconnect": reconnect, "auth_url": "", "message": "Strava OAuth is disabled until explicitly re-enabled."}


@router.get("/api/integrations/withings/auth-url")
def withings_auth_url() -> dict:
    return {"status": "disabled", "auth_url": "", "message": "Withings OAuth is disabled until explicitly re-enabled."}


@router.post("/api/integrations/withings/disconnect")
def disconnect_withings() -> dict:
    return settings_payload()

