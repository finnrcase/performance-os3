"""Safe, bounded Postgres access for backend v2."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
import threading
import time
from typing import Any, Iterator

from backend_v2.config import DEFAULT_CONNECT_TIMEOUT_SECONDS, DEFAULT_STATEMENT_TIMEOUT_MS, MAX_STATEMENT_TIMEOUT_MS, database_url
from backend_v2.schemas import DATAFRAME_TABLES, DOCUMENT_TABLES
from backend_v2.utils import json_safe


class DatabaseNotConfigured(RuntimeError):
    pass


_connection: Any | None = None
_connection_lock = threading.RLock()


def _clamp_timeout_ms(timeout_ms: int | str | None = None) -> int:
    try:
        value = int(timeout_ms or DEFAULT_STATEMENT_TIMEOUT_MS)
    except (TypeError, ValueError):
        value = DEFAULT_STATEMENT_TIMEOUT_MS
    return max(1, min(value, MAX_STATEMENT_TIMEOUT_MS))


def _safe_identifier(value: str) -> str:
    if not value or not all(character.isalnum() or character == "_" for character in value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return value


def _new_connection():
    url = database_url()
    if not url:
        raise DatabaseNotConfigured("DATABASE_URL is not configured.")
    import psycopg
    return psycopg.connect(url, connect_timeout=DEFAULT_CONNECT_TIMEOUT_SECONDS)


def _connect():
    global _connection
    if _connection is not None and not getattr(_connection, "closed", True):
        return _connection
    _connection = _new_connection()
    return _connection


@contextmanager
def cursor(*, timeout_ms: int | str | None = None) -> Iterator[Any]:
    with _connection_lock:
        conn = _connect()
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
        return {"status": "not_configured", "storage": "local_files", "duration_ms": round((time.perf_counter() - started) * 1000, 1)}
    with cursor(timeout_ms=750) as cur:
        cur.execute("SELECT 1")
        row = cur.fetchone()
    return {"status": "ok", "storage": "postgres", "result": int(row[0] if row else 0), "duration_ms": round((time.perf_counter() - started) * 1000, 1)}


def load_document(key: str, default: dict[str, Any] | None = None, *, timeout_ms: int | None = None) -> dict[str, Any]:
    table = _safe_identifier(DOCUMENT_TABLES[key])
    try:
        with cursor(timeout_ms=timeout_ms) as cur:
            cur.execute(f"SELECT data FROM {table} ORDER BY updated_at DESC, id DESC LIMIT 1")
            row = cur.fetchone()
    except DatabaseNotConfigured:
        return dict(default or {})
    return json_safe(dict(row[0])) if row else dict(default or {})


def load_recent_rows(dataset: str, *, days: int = 30, limit: int = 500, date_column: str = "date", timeout_ms: int | None = None) -> list[dict[str, Any]]:
    table = _safe_identifier(DATAFRAME_TABLES[dataset])
    json_key = _safe_identifier(date_column)
    cutoff = (date.today() - timedelta(days=max(0, min(int(days or 0), 3650)))).isoformat()
    bounded_limit = max(1, min(int(limit or 1), 20_000))
    try:
        with cursor(timeout_ms=timeout_ms) as cur:
            cur.execute(f"SELECT data FROM {table} WHERE COALESCE(data->>%s, '') >= %s ORDER BY data->>%s DESC, row_order DESC, id DESC LIMIT %s", (json_key, cutoff, json_key, bounded_limit))
            return [json_safe(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []


def load_rows_for_date(dataset: str, selected_date: str, *, limit: int = 500, date_column: str = "date", timeout_ms: int | None = None) -> list[dict[str, Any]]:
    table = _safe_identifier(DATAFRAME_TABLES[dataset])
    json_key = _safe_identifier(date_column)
    bounded_limit = max(1, min(int(limit or 1), 5000))
    try:
        with cursor(timeout_ms=timeout_ms) as cur:
            cur.execute(f"SELECT data FROM {table} WHERE COALESCE(data->>%s, '') = %s ORDER BY row_order DESC, id DESC LIMIT %s", (json_key, str(selected_date), bounded_limit))
            return [json_safe(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []


def count_estimates(keys: list[str]) -> dict[str, int]:
    tables = {key: _safe_identifier(DATAFRAME_TABLES.get(key) or DOCUMENT_TABLES.get(key) or "") for key in keys}
    tables = {key: table for key, table in tables.items() if table}
    if not tables:
        return {}
    try:
        with cursor(timeout_ms=750) as cur:
            cur.execute("SELECT relname, COALESCE(reltuples::bigint, 0) FROM pg_class WHERE relname = ANY(%s)", (list(tables.values()),))
            by_table = {str(row[0]): max(0, int(row[1] or 0)) for row in cur.fetchall()}
    except Exception:
        return {key: 0 for key in keys}
    return {key: by_table.get(table, 0) for key, table in tables.items()}


def load_dashboard_core_bundle(*, today: str, training_cutoff: str, body_cutoff: str, training_limit: int = 500, body_limit: int = 200, food_limit: int = 500, timeout_ms: int | None = None) -> dict[str, Any]:
    try:
        with cursor(timeout_ms=timeout_ms) as cur:
            cur.execute(
                """
                SELECT
                  COALESCE((SELECT data FROM user_goal_settings ORDER BY updated_at DESC, id DESC LIMIT 1), '{}'::jsonb),
                  COALESCE((SELECT data FROM macro_targets ORDER BY updated_at DESC, id DESC LIMIT 1), '{}'::jsonb),
                  COALESCE((SELECT jsonb_agg(data) FROM (SELECT data FROM food_logs WHERE COALESCE(data->>'date', '') = %s ORDER BY row_order DESC, id DESC LIMIT %s) rows), '[]'::jsonb),
                  COALESCE((SELECT jsonb_agg(data) FROM (SELECT data FROM workout_logs WHERE COALESCE(data->>'date', '') >= %s ORDER BY data->>'date' DESC, row_order DESC, id DESC LIMIT %s) rows), '[]'::jsonb),
                  COALESCE((SELECT jsonb_agg(data) FROM (SELECT data FROM body_metric_logs WHERE COALESCE(data->>'date', '') >= %s ORDER BY data->>'date' DESC, row_order DESC, id DESC LIMIT %s) rows), '[]'::jsonb),
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'food_logs'::regclass), 0),
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'workout_logs'::regclass), 0),
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'body_metric_logs'::regclass), 0)
                """,
                (today, int(food_limit), training_cutoff, int(training_limit), body_cutoff, int(body_limit)),
            )
            row = cur.fetchone()
    except DatabaseNotConfigured:
        return {}
    if not row:
        return {}
    return {"goals": json_safe(dict(row[0] or {})), "targets": json_safe(dict(row[1] or {})), "nutrition_rows": json_safe(list(row[2] or [])), "training_rows": json_safe(list(row[3] or [])), "body_rows": json_safe(list(row[4] or [])), "nutrition_rows_estimate": max(0, int(row[5] or 0)), "training_rows_estimate": max(0, int(row[6] or 0)), "body_metric_rows_estimate": max(0, int(row[7] or 0))}
