"""Small JSON, masking, and timing helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
import os
import time
from typing import Any, Callable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return json_safe(value.item())
    return value


def mask_value(name: str, value: str | None) -> dict[str, Any]:
    text = str(value or "")
    if not text:
        return {"present": False, "masked": ""}
    return {"present": True, "masked": "***"}


def env_presence(names: list[str]) -> dict[str, dict[str, Any]]:
    return {name: mask_value(name, os.getenv(name)) for name in names}


def timed(name: str, fn: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    try:
        value = fn()
        return value, {"name": name, "status": "ok", "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        return None, {
            "name": name,
            "status": "error",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
