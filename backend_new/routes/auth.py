from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

router = APIRouter(tags=["auth"])

ACCESS_COOKIE = "performance_os_access"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def _production_like() -> bool:
    return bool(
        os.getenv("RAILWAY_ENVIRONMENT")
        or os.getenv("VERCEL")
        or os.getenv("RENDER")
        or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
        or os.getenv("APP_ENV", "").lower() in {"production", "prod"}
    )


def _base64_url_digest(secret: str, timestamp: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _create_session_token(secret: str) -> str:
    timestamp = str(int(time.time() * 1000))
    return f"{timestamp}.{_base64_url_digest(secret, timestamp)}"


def _is_valid_session_token(token: str | None, secret: str) -> bool:
    if not token or "." not in token:
        return False
    timestamp, signature = token.split(".", 1)
    try:
        timestamp_ms = int(timestamp)
    except ValueError:
        return False
    if int(time.time() * 1000) - timestamp_ms > SESSION_MAX_AGE_SECONDS * 1000:
        return False
    expected = _base64_url_digest(secret, timestamp)
    return hmac.compare_digest(signature, expected)


def _cookie_options() -> dict[str, Any]:
    production = _production_like()
    return {
        "httponly": True,
        "secure": production,
        "samesite": "none" if production else "lax",
        "path": "/",
        "max_age": SESSION_MAX_AGE_SECONDS,
    }


@router.post("/api/auth/login")
def login(payload: dict[str, Any], response: Response) -> dict[str, Any]:
    expected_password = os.getenv("APP_PASSWORD", "").strip()
    session_secret = os.getenv("SESSION_SECRET", "").strip()
    if not expected_password:
        raise HTTPException(status_code=500, detail="APP_PASSWORD is not configured on the backend")
    if not session_secret:
        raise HTTPException(status_code=500, detail="SESSION_SECRET is not configured on the backend")
    if str(payload.get("password") or "") != expected_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    response.set_cookie(ACCESS_COOKIE, _create_session_token(session_secret), **_cookie_options())
    return {"ok": True, "status": "authenticated", "authenticated": True}


@router.get("/api/auth/session")
def session(request: Request) -> dict[str, Any]:
    session_secret = os.getenv("SESSION_SECRET", "").strip()
    if not session_secret:
        raise HTTPException(status_code=500, detail="SESSION_SECRET is not configured on the backend")
    token = request.cookies.get(ACCESS_COOKIE)
    if not _is_valid_session_token(token, session_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return {"ok": True, "status": "authenticated"}


@router.post("/api/auth/logout")
def logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(
        ACCESS_COOKIE,
        path="/",
        secure=_production_like(),
        samesite="none" if _production_like() else "lax",
    )
    return {"ok": True, "status": "logged_out"}
