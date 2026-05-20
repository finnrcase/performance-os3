"""Small JSON and timing helpers for backend v2."""

from __future__ import annotations

from datetime import date, datetime, timezone
import math
import time
from typing import Any, Callable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


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


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def timed(name: str, fn: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    started = time.perf_counter()
    try:
        value = fn()
        return value, {"block": name, "name": name, "status": "ok", "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:
        return None, {"block": name, "name": name, "status": "error", "error_type": type(exc).__name__, "message": str(exc), "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
