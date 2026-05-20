"""Safe database helpers for backend_new.

This module opens database connections only when route code explicitly asks for
data. It does not create schema, import data, or run integration syncs.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
import math
import threading
import time
from typing import Any, Iterator

from backend_new.config import (
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_STATEMENT_TIMEOUT_MS,
    MAX_STATEMENT_TIMEOUT_MS,
    database_url,
)


SUPPORTED_JSONB_TABLES = {
    "food_logs",
    "food_shortcuts",
    "daily_nutrition_summary",
    "nutrition_recommendation_history",
    "workout_logs",
    "raw_hevy_workouts",
    "raw_hevy_sets",
    "weekly_training_summary",
    "monthly_training_summary",
    "training_cache_metadata",
    "training_summary_state",
    "integration_sync_state",
    "body_metric_logs",
    "recovery_logs",
    "sleep_logs",
    "macro_targets",
    "user_goal_settings",
    "api_connections",
}


class DatabaseNotConfigured(RuntimeError):
    pass


class UnsafeTableName(ValueError):
    pass


_connection: Any | None = None
_connection_lock = threading.RLock()


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def structured_error(exc: Exception, *, operation: str) -> dict[str, Any]:
    return {
        "status": "error",
        "operation": operation,
        "error_type": type(exc).__name__,
        "message": str(exc),
    }


def sanitize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if hasattr(value, "item"):
        return sanitize_json(value.item())
    return value


def _clamp_timeout_ms(timeout_ms: int | str | None = None) -> int:
    try:
        value = int(timeout_ms or DEFAULT_STATEMENT_TIMEOUT_MS)
    except (TypeError, ValueError):
        value = DEFAULT_STATEMENT_TIMEOUT_MS
    return max(1, min(value, MAX_STATEMENT_TIMEOUT_MS))


def _bounded_limit(limit: int | str | None = 500) -> int:
    try:
        value = int(limit or 500)
    except (TypeError, ValueError):
        value = 500
    return max(1, min(value, 5000))


def _safe_table(table: str) -> str:
    if table not in SUPPORTED_JSONB_TABLES:
        raise UnsafeTableName(f"Unsupported JSONB table: {table!r}")
    return table


def _safe_json_key(key: str | None) -> str | None:
    if key is None:
        return None
    if not key or not all(character.isalnum() or character == "_" for character in key):
        raise ValueError(f"Unsafe JSON field: {key!r}")
    return key


def _jsonb(value: dict[str, Any]) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(sanitize_json(value))


def get_connection() -> Any:
    """Return a reusable Postgres connection with a bounded connect timeout."""
    global _connection
    url = database_url()
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not configured.")
    with _connection_lock:
        if _connection is not None and not getattr(_connection, "closed", True):
            return _connection
        import psycopg

        _connection = psycopg.connect(url, connect_timeout=DEFAULT_CONNECT_TIMEOUT_SECONDS)
        return _connection


@contextmanager
def cursor(*, timeout_ms: int | str | None = None) -> Iterator[Any]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('statement_timeout', %s, true)", (f"{_clamp_timeout_ms(timeout_ms)}ms",))
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        global _connection
        if getattr(conn, "closed", False):
            _connection = None
        raise


def ping() -> dict[str, Any]:
    started = time.perf_counter()
    if not database_url():
        return {
            "status": "not_configured",
            "storage": "not_configured",
            "duration_ms": _duration_ms(started),
        }
    try:
        with cursor(timeout_ms=750) as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
        return {
            "status": "ok",
            "storage": "postgres",
            "result": int(row[0] if row else 0),
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        return {
            **structured_error(exc, operation="db_ping"),
            "storage": "postgres",
            "duration_ms": _duration_ms(started),
        }


def fetch_latest_document(table: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    fallback = dict(fallback or {})
    try:
        safe_table = _safe_table(table)
        with cursor(timeout_ms=1000) as cur:
            cur.execute(f"SELECT data FROM {safe_table} ORDER BY updated_at DESC, id DESC LIMIT 1")
            row = cur.fetchone()
        return sanitize_json(dict(row[0])) if row else fallback
    except DatabaseNotConfigured:
        return fallback
    except Exception as exc:
        return {**fallback, "_db_error": {**structured_error(exc, operation="fetch_latest_document"), "duration_ms": _duration_ms(started)}}


def fetch_json_rows(
    table: str,
    limit: int = 500,
    date_field: str | None = None,
    since_date: str | None = None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        safe_date_field = _safe_json_key(date_field)
        bounded_limit = _bounded_limit(limit)
        with cursor(timeout_ms=1500) as cur:
            if safe_date_field and since_date:
                cur.execute(
                    f"""
                    SELECT data
                    FROM {safe_table}
                    WHERE COALESCE(data->>%s, '') >= %s
                    ORDER BY data->>%s DESC, row_order DESC, id DESC
                    LIMIT %s
                    """,
                    (safe_date_field, str(since_date), safe_date_field, bounded_limit),
                )
            elif safe_date_field:
                cur.execute(
                    f"""
                    SELECT data
                    FROM {safe_table}
                    ORDER BY data->>%s DESC, row_order DESC, id DESC
                    LIMIT %s
                    """,
                    (safe_date_field, bounded_limit),
                )
            else:
                cur.execute(
                    f"""
                    SELECT data
                    FROM {safe_table}
                    ORDER BY updated_at DESC, id DESC
                    LIMIT %s
                    """,
                    (bounded_limit,),
                )
            return [sanitize_json(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []
    except Exception as exc:
        return [{"_db_error": {**structured_error(exc, operation="fetch_json_rows"), "duration_ms": _duration_ms(started)}}]


def fetch_json_rows_for_value(
    table: str,
    field: str,
    value: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        safe_field = _safe_json_key(field)
        if safe_field is None:
            raise ValueError("field is required.")
        bounded_limit = _bounded_limit(limit)
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"""
                SELECT data
                FROM {safe_table}
                WHERE COALESCE(data->>%s, '') = %s
                ORDER BY row_order DESC, id DESC
                LIMIT %s
                """,
                (safe_field, str(value), bounded_limit),
            )
            return [sanitize_json(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []
    except Exception as exc:
        return [{"_db_error": {**structured_error(exc, operation="fetch_json_rows_for_value"), "duration_ms": _duration_ms(started)}}]


def fetch_latest_json_rows(table: str, *, limit: int = 500) -> list[dict[str, Any]]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        bounded_limit = _bounded_limit(limit)
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"""
                SELECT data
                FROM {safe_table}
                ORDER BY id DESC
                LIMIT %s
                """,
                (bounded_limit,),
            )
            return [sanitize_json(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []
    except Exception as exc:
        return [{"_db_error": {**structured_error(exc, operation="fetch_latest_json_rows"), "duration_ms": _duration_ms(started)}}]


def insert_json_row(table: str, data: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    payload = sanitize_json(dict(data))
    try:
        safe_table = _safe_table(table)
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"INSERT INTO {safe_table} (data) VALUES (%s) RETURNING data",
                (_jsonb(payload),),
            )
            row = cur.fetchone()
            return sanitize_json(dict(row[0])) if row else payload
    except DatabaseNotConfigured:
        return payload
    except Exception as exc:
        return {**payload, "_db_error": {**structured_error(exc, operation="insert_json_row"), "duration_ms": _duration_ms(started)}}


def upsert_json_row(table: str, key_field: str, key_value: str, data: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    payload = sanitize_json(dict(data))
    try:
        safe_table = _safe_table(table)
        safe_key = _safe_json_key(key_field)
        if safe_key is None:
            raise ValueError("key_field is required.")
        payload = sanitize_json({**dict(data), safe_key: key_value})
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"""
                UPDATE {safe_table}
                SET data = data || %s::jsonb, updated_at = now()
                WHERE data->>%s = %s
                RETURNING data
                """,
                (_jsonb(payload), safe_key, str(key_value)),
            )
            row = cur.fetchone()
            if row:
                return sanitize_json(dict(row[0]))
            cur.execute(
                f"INSERT INTO {safe_table} (data) VALUES (%s) RETURNING data",
                (_jsonb(payload),),
            )
            inserted = cur.fetchone()
            return sanitize_json(dict(inserted[0])) if inserted else payload
    except DatabaseNotConfigured:
        return payload
    except Exception as exc:
        return {**payload, "_db_error": {**structured_error(exc, operation="upsert_json_row"), "duration_ms": _duration_ms(started)}}


def delete_json_row(table: str, key_field: str, key_value: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        safe_key = _safe_json_key(key_field)
        if safe_key is None:
            raise ValueError("key_field is required.")
        with cursor(timeout_ms=1500) as cur:
            cur.execute(f"DELETE FROM {safe_table} WHERE data->>%s = %s", (safe_key, str(key_value)))
            deleted = int(getattr(cur, "rowcount", 0) or 0)
        return {
            "status": "ok",
            "deleted": deleted,
            "duration_ms": _duration_ms(started),
        }
    except DatabaseNotConfigured:
        return {
            "status": "not_configured",
            "deleted": 0,
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        return {
            **structured_error(exc, operation="delete_json_row"),
            "deleted": 0,
            "duration_ms": _duration_ms(started),
        }


def count_rows(table: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        with cursor(timeout_ms=750) as cur:
            cur.execute("SELECT COALESCE(reltuples::bigint, 0) FROM pg_class WHERE oid = %s::regclass", (safe_table,))
            row = cur.fetchone()
        return {
            "status": "ok",
            "table": safe_table,
            "count_estimate": max(0, int(row[0] if row else 0)),
            "exact": False,
            "duration_ms": _duration_ms(started),
        }
    except DatabaseNotConfigured:
        return {
            "status": "not_configured",
            "table": table,
            "count_estimate": 0,
            "exact": False,
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        return {
            **structured_error(exc, operation="count_rows"),
            "table": table,
            "count_estimate": 0,
            "exact": False,
            "duration_ms": _duration_ms(started),
        }


def fetch_dashboard_core_bundle(today: str, *, food_limit: int = 500, body_limit: int = 90, training_limit: int = 500) -> dict[str, Any]:
    """Fetch dashboard core inputs in one bounded round trip.

    Training reads are intentionally latest-insert bounded. This avoids full raw
    Hevy history scans while still giving the dashboard a recent workout card.
    """
    started = time.perf_counter()
    try:
        with cursor(timeout_ms=1800) as cur:
            cur.execute(
                """
                SELECT
                  COALESCE((SELECT data FROM user_goal_settings ORDER BY updated_at DESC, id DESC LIMIT 1), '{}'::jsonb) AS goals,
                  COALESCE((SELECT data FROM macro_targets ORDER BY updated_at DESC, id DESC LIMIT 1), '{}'::jsonb) AS targets,
                  COALESCE((
                    SELECT jsonb_agg(data)
                    FROM (
                      SELECT data
                      FROM food_logs
                      WHERE COALESCE(data->>'date', '') = %s
                      ORDER BY row_order DESC, id DESC
                      LIMIT %s
                    ) rows
                  ), '[]'::jsonb) AS food_rows,
                  COALESCE((
                    SELECT jsonb_agg(data)
                    FROM (
                      SELECT data
                      FROM body_metric_logs
                      ORDER BY id DESC
                      LIMIT %s
                    ) rows
                  ), '[]'::jsonb) AS body_rows,
                  COALESCE((
                    SELECT jsonb_agg(data)
                    FROM (
                      SELECT data
                      FROM workout_logs
                      ORDER BY id DESC
                      LIMIT %s
                    ) rows
                  ), '[]'::jsonb) AS training_rows,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'food_logs'::regclass), 0) AS food_count,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'body_metric_logs'::regclass), 0) AS body_count,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'workout_logs'::regclass), 0) AS training_count
                """,
                (today, _bounded_limit(food_limit), _bounded_limit(body_limit), _bounded_limit(training_limit)),
            )
            row = cur.fetchone()
        if not row:
            return {
                "status": "ok",
                "goals": {},
                "targets": {},
                "food_rows": [],
                "body_rows": [],
                "training_rows": [],
                "counts": {"nutrition": 0, "body_metrics": 0, "training": 0},
                "duration_ms": _duration_ms(started),
            }
        return {
            "status": "ok",
            "goals": sanitize_json(dict(row[0] or {})),
            "targets": sanitize_json(dict(row[1] or {})),
            "food_rows": sanitize_json(list(row[2] or [])),
            "body_rows": sanitize_json(list(row[3] or [])),
            "training_rows": sanitize_json(list(row[4] or [])),
            "counts": {
                "nutrition": max(0, int(row[5] or 0)),
                "body_metrics": max(0, int(row[6] or 0)),
                "training": max(0, int(row[7] or 0)),
            },
            "duration_ms": _duration_ms(started),
        }
    except DatabaseNotConfigured:
        return {
            "status": "not_configured",
            "goals": {},
            "targets": {},
            "food_rows": [],
            "body_rows": [],
            "training_rows": [],
            "counts": {"nutrition": 0, "body_metrics": 0, "training": 0},
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        return {
            **structured_error(exc, operation="fetch_dashboard_core_bundle"),
            "goals": {},
            "targets": {},
            "food_rows": [],
            "body_rows": [],
            "training_rows": [],
            "counts": {"nutrition": 0, "body_metrics": 0, "training": 0},
            "duration_ms": _duration_ms(started),
        }
