"""Optional Sentry and profiling helpers for backend diagnostics."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)
_SENTRY_ENABLED = False
_SENTRY_SDK = None

_SECRET_KEY_RE = re.compile(r"(password|secret|token|api[_-]?key|client[_-]?secret|database_url)", re.IGNORECASE)


def _safe_float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        scrubbed = {}
        for key, item in value.items():
            text_key = str(key)
            scrubbed[text_key] = "[redacted]" if _SECRET_KEY_RE.search(text_key) else _scrub(item)
        return scrubbed
    if isinstance(value, list):
        return [_scrub(item) for item in value[:50]]
    if isinstance(value, tuple):
        return tuple(_scrub(item) for item in value[:50])
    text = str(value) if value is not None else ""
    if len(text) > 1200:
        return f"{text[:1200]}..."
    return value


def init_sentry() -> bool:
    """Initialize Sentry only when a DSN is configured.

    Missing sentry-sdk or missing DSN must never break local dev, tests, or
    production startup. This keeps observability additive and low risk.
    """
    global _SENTRY_ENABLED, _SENTRY_SDK
    dsn = os.getenv("SENTRY_DSN") or os.getenv("BACKEND_SENTRY_DSN")
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=os.getenv("SENTRY_ENVIRONMENT") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "development",
            release=os.getenv("SENTRY_RELEASE") or os.getenv("RAILWAY_GIT_COMMIT_SHA"),
            traces_sample_rate=_safe_float_env("SENTRY_TRACES_SAMPLE_RATE", 0.1),
            profiles_sample_rate=_safe_float_env("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
            send_default_pii=False,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            before_send=lambda event, hint: _scrub(event),
        )
        _SENTRY_SDK = sentry_sdk
        _SENTRY_ENABLED = True
        logger.info("Sentry backend monitoring initialized.")
        return True
    except Exception as exc:
        logger.warning("Sentry backend monitoring disabled: %s", exc)
        _SENTRY_ENABLED = False
        return False


def capture_exception(exc: BaseException, *, tags: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> None:
    if not _SENTRY_ENABLED or _SENTRY_SDK is None:
        return
    try:
        with _SENTRY_SDK.push_scope() as scope:
            for key, value in (tags or {}).items():
                scope.set_tag(str(key), str(value))
            for key, value in (extra or {}).items():
                scope.set_extra(str(key), _scrub(value))
            _SENTRY_SDK.capture_exception(exc)
    except Exception:
        logger.debug("Failed to send exception to Sentry.", exc_info=True)


def capture_message(message: str, *, level: str = "info", tags: dict[str, Any] | None = None, extra: dict[str, Any] | None = None) -> None:
    if not _SENTRY_ENABLED or _SENTRY_SDK is None:
        return
    try:
        with _SENTRY_SDK.push_scope() as scope:
            for key, value in (tags or {}).items():
                scope.set_tag(str(key), str(value))
            for key, value in (extra or {}).items():
                scope.set_extra(str(key), _scrub(value))
            _SENTRY_SDK.capture_message(message, level=level)
    except Exception:
        logger.debug("Failed to send message to Sentry.", exc_info=True)
