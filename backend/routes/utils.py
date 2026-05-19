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
SENSITIVE_VALUE = "••••"

_SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "access_token",
    "authorization",
    "client_secret",
    "cookie",
    "database_url",
    "db_url",
    "dsn",
    "id_token",
    "password",
    "postgres_url",
    "refresh_token",
    "secret",
    "session_secret",
    "session_token",
}

_SAFE_TOKEN_KEYS = {
    "token_status",
    "token_storage",
    "token_type",
}

_SAFE_STATUS_VALUES = {
    "auto from app url",
    "check integrations",
    "configured",
    "connected",
    "disconnected",
    "expired",
    "missing",
    "not configured",
    "ready to connect",
    "refresh soon",
    "valid",
}


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


def is_sensitive_key(key: object) -> bool:
    """Return true for fields that must not be echoed to frontend/debug output."""
    normalized = str(key).strip().lower().replace("-", "_")
    if not normalized or normalized in _SAFE_TOKEN_KEYS:
        return False
    if normalized in _SENSITIVE_KEY_NAMES:
        return True
    if normalized.endswith("_api_key"):
        return True
    if normalized.endswith("_access_token") or normalized.endswith("_refresh_token"):
        return True
    if normalized.endswith("_secret") or normalized.endswith("_password"):
        return True
    if "database_url" in normalized:
        return True
    return False


def mask_sensitive_value(value: Any) -> Any:
    """Preserve empty values while masking configured secrets."""
    if value in (None, ""):
        return value
    if isinstance(value, str) and value.strip().lower() in _SAFE_STATUS_VALUES:
        return value
    return SENSITIVE_VALUE


def sanitize_sensitive_data(value: Any) -> Any:
    """Recursively redact secret-like fields from API/debug/export payloads."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            sanitized[key] = mask_sensitive_value(item) if is_sensitive_key(key) else sanitize_sensitive_data(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_sensitive_data(item) for item in value]
    return value
