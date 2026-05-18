"""Shared API helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import os
import time
from typing import Any

import pandas as pd
from fastapi import HTTPException, Request, status


ACCESS_COOKIE = "performance_os_access"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30


def sign_session(timestamp: str, secret: str) -> str:
    signature = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(signature).decode("utf-8").replace("+", "-").replace("/", "_").replace("=", "")


def create_session_token(secret: str, timestamp_ms: int | None = None) -> str:
    timestamp = str(timestamp_ms or int(time.time() * 1000))
    return f"{timestamp}.{sign_session(timestamp, secret)}"


def require_authenticated_request(request: Request) -> None:
    """Require the same signed access cookie used by the Next.js access gate."""
    if not os.getenv("APP_PASSWORD"):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="APP_PASSWORD is not configured")
    session_secret = os.getenv("SESSION_SECRET")
    if not session_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="SESSION_SECRET is not configured")

    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    timestamp, separator, signature = token.partition(".")
    if not separator:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    try:
        timestamp_ms = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session") from exc

    if int(time.time() * 1000) - timestamp_ms > SESSION_MAX_AGE_SECONDS * 1000:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")

    if not hmac.compare_digest(signature, sign_session(timestamp, session_secret)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")


def clean_value(value: Any) -> Any:
    """Convert pandas/numpy missing values into JSON-safe None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def dataframe_records(df: pd.DataFrame) -> list[dict]:
    """Return JSON-safe records from a DataFrame."""
    if df.empty:
        return []
    return [
        {key: clean_value(value) for key, value in row.items()}
        for row in df.to_dict(orient="records")
    ]
