from __future__ import annotations

from fastapi import APIRouter


router = APIRouter(tags=["withings"])


@router.get("/api/withings/callback")
def withings_callback() -> dict:
    return {"status": "disabled", "message": "Withings OAuth callback is disabled in the clean backend."}


@router.post("/api/withings/sync")
def withings_sync() -> dict:
    return {"status": "disabled", "imported": 0, "message": "Withings sync is disabled in the clean backend."}


@router.get("/api/strava/callback")
def strava_callback() -> dict:
    return {"status": "disabled", "message": "Strava OAuth callback is disabled in the clean backend."}

