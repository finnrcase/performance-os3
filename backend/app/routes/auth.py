from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Response


router = APIRouter(tags=["auth"])


@router.post("/api/auth/login")
def login(payload: dict, response: Response) -> dict:
    expected = os.getenv("APP_PASSWORD", "").strip()
    supplied = str(payload.get("password") or "").strip()
    if expected and supplied != expected:
        raise HTTPException(status_code=401, detail="Invalid password")
    response.set_cookie("performance_os_session", "local", httponly=True, secure=True, samesite="none", path="/")
    return {"status": "ok", "authenticated": True}


@router.get("/api/auth/session")
def session() -> dict:
    return {"status": "ok", "authenticated": True}

