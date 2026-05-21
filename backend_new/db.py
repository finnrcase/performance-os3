"""Safe database helpers for backend_new.

This module opens database connections only when route code explicitly asks for
data. It does not create schema, import data, or run integration syncs.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta
import logging
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

MAX_CORE_TRAINING_ROWS = 250
CORE_TRAINING_DAYS = 90
CORE_TRAINING_WORKOUTS = 5
CORE_TRAINING_CACHE_KEY = "core_training_summary"

logger = logging.getLogger(__name__)


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


def _core_training_limit(limit: int | str | None = MAX_CORE_TRAINING_ROWS) -> int:
    try:
        value = int(limit or MAX_CORE_TRAINING_ROWS)
    except (TypeError, ValueError):
        value = MAX_CORE_TRAINING_ROWS
    return max(1, min(value, MAX_CORE_TRAINING_ROWS))


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


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _training_row_volume(row: dict[str, Any]) -> float:
    return _number(row.get("sets"), 0) * _number(row.get("reps"), 0) * _number(row.get("weight"), 0)


def _cache_age_seconds(cached: dict[str, Any]) -> float | None:
    timestamp = str(cached.get("core_cached_at") or cached.get("updated_at") or "")
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return max(0.0, (datetime.now(parsed.tzinfo) - parsed).total_seconds())
    return max(0.0, (datetime.now() - parsed).total_seconds())


def _summarize_training_rows(rows: list[dict[str, Any]], *, limit_workouts: int, days: int, total_rows: int, started: float, source: str) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        workout_date = str(row.get("date") or "")[:10]
        if not workout_date:
            continue
        workout_id = str(row.get("workout_id") or row.get("hevy_workout_id") or row.get("source_id") or f"{workout_date}:unknown")
        grouped.setdefault((workout_date, workout_id), []).append(row)

    workouts: list[dict[str, Any]] = []
    for (workout_date, workout_id), workout_rows in grouped.items():
        first = workout_rows[0] if workout_rows else {}
        workout_type = str(first.get("workout_type") or first.get("title") or first.get("name") or "Workout")
        sources = sorted({str(row.get("source") or "manual") for row in workout_rows if row.get("source")})
        has_run = any("run" in str(row.get("workout_type") or row.get("exercise") or "").lower() or str(row.get("source") or "").lower() == "strava" for row in workout_rows)
        has_lift = any(not ("run" in str(row.get("workout_type") or row.get("exercise") or "").lower()) for row in workout_rows)
        workouts.append(
            {
                "date": workout_date,
                "workout_id": workout_id,
                "workout_type": workout_type,
                "total_sets": int(sum(max(0, int(_number(row.get("sets"), 0))) for row in workout_rows)),
                "total_volume": round(sum(_training_row_volume(row) for row in workout_rows), 1),
                "duration_minutes": round(max([_number(row.get("duration_minutes"), 0) for row in workout_rows] or [0]), 1),
                "source": ", ".join(sources) if sources else "manual",
                "has_run": has_run,
                "has_lift": has_lift,
            }
        )

    workouts.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("workout_id") or "")), reverse=True)
    latest = workouts[0] if workouts else None
    recent = workouts[: max(1, int(limit_workouts or CORE_TRAINING_WORKOUTS))]
    return {
        "status": "ok",
        "source": source,
        "latest_workout": latest,
        "latest_workout_date": latest.get("date") if latest else "",
        "latest_workout_type": latest.get("workout_type") if latest else "",
        "recent_workout_count": len(recent),
        "workout_count": len(workouts),
        "recent_rows": len(rows),
        "total_rows": total_rows,
        "days": days,
        "limit_workouts": limit_workouts,
        "max_core_training_rows": MAX_CORE_TRAINING_ROWS,
        "recent_volume_summary": {
            "total_volume": round(sum(_number(item.get("total_volume"), 0) for item in recent), 1),
            "total_sets": int(sum(_number(item.get("total_sets"), 0) for item in recent)),
            "duration_minutes": round(sum(_number(item.get("duration_minutes"), 0) for item in recent), 1),
        },
        "latest_flags": {
            "has_run": bool(latest and latest.get("has_run")),
            "has_lift": bool(latest and latest.get("has_lift")),
        },
        "items": recent,
        "full_raw_hevy_scan": False,
        "duration_ms": _duration_ms(started),
    }


def load_recent_training_summary(
    limit_workouts: int = CORE_TRAINING_WORKOUTS,
    days: int = CORE_TRAINING_DAYS,
    cached_metadata: dict[str, Any] | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return a cache-first lightweight dashboard training summary.

    This helper intentionally avoids pandas, strength trends, PRs, muscle
    balance, workload analysis, and full Hevy/raw history scans.
    """
    started = time.perf_counter()
    bounded_workouts = max(1, min(int(limit_workouts or CORE_TRAINING_WORKOUTS), CORE_TRAINING_WORKOUTS))
    bounded_days = max(1, min(int(days or CORE_TRAINING_DAYS), CORE_TRAINING_DAYS))
    cutoff = (date.today() - timedelta(days=bounded_days)).isoformat()

    try:
        cached = cached_metadata if isinstance(cached_metadata, dict) else {}
        if not cached:
            cached_rows = fetch_json_rows_for_value("training_cache_metadata", "metadata_key", CORE_TRAINING_CACHE_KEY, limit=1)
            cached = cached_rows[0] if cached_rows and "_db_error" not in cached_rows[0] else {}
        cached_summary = cached.get("core_summary") if isinstance(cached.get("core_summary"), dict) else {}
        if not force_refresh and cached_summary and _cache_age_seconds(cached) is not None and (_cache_age_seconds(cached) or 0) <= 900:
            logger.info(
                "[dashboard_core] training rows recent=%s total=%s",
                cached_summary.get("recent_rows", 0),
                cached_summary.get("total_rows", 0),
            )
            return {
                **cached_summary,
                "status": "ok",
                "source": "training_cache_metadata",
                "duration_ms": _duration_ms(started),
            }

        with cursor(timeout_ms=2000) as cur:
            cur.execute(
                """
                SELECT
                  COALESCE((
                    SELECT jsonb_agg(data)
                    FROM (
                      SELECT data
                      FROM workout_logs
                      WHERE COALESCE(data->>'date', '') >= %s
                      ORDER BY data->>'date' DESC, row_order DESC, id DESC
                      LIMIT %s
                    ) rows
                  ), '[]'::jsonb) AS rows,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'workout_logs'::regclass), 0) AS total_rows
                """,
                (cutoff, _core_training_limit(MAX_CORE_TRAINING_ROWS)),
            )
            row = cur.fetchone()
        rows = sanitize_json(list(row[0] or [])) if row else []
        total_rows = max(0, int(row[1] or 0)) if row else 0
        summary = _summarize_training_rows(rows, limit_workouts=bounded_workouts, days=bounded_days, total_rows=total_rows, started=started, source="bounded_workout_logs")
        upsert_json_row(
            "training_cache_metadata",
            "metadata_key",
            CORE_TRAINING_CACHE_KEY,
            {
                "metadata_key": CORE_TRAINING_CACHE_KEY,
                "core_summary": summary,
                "latest_workout_summary": summary.get("latest_workout"),
                "recent_workout_count": summary.get("recent_workout_count", 0),
                "latest_training_date": summary.get("latest_workout_date", ""),
                "latest_volume_summary": summary.get("recent_volume_summary", {}),
                "core_cached_at": datetime.now().isoformat(),
            },
        )
        logger.info("[dashboard_core] training rows recent=%s total=%s", summary.get("recent_rows", 0), summary.get("total_rows", 0))
        return summary
    except DatabaseNotConfigured:
        logger.info("[dashboard_core] training rows recent=%s total=%s", 0, 0)
        return {
            "status": "not_configured",
            "source": "not_configured",
            "latest_workout": None,
            "latest_workout_date": "",
            "latest_workout_type": "",
            "recent_workout_count": 0,
            "workout_count": 0,
            "recent_rows": 0,
            "total_rows": 0,
            "days": bounded_days,
            "limit_workouts": bounded_workouts,
            "max_core_training_rows": MAX_CORE_TRAINING_ROWS,
            "recent_volume_summary": {"total_volume": 0, "total_sets": 0, "duration_minutes": 0},
            "latest_flags": {"has_run": False, "has_lift": False},
            "items": [],
            "full_raw_hevy_scan": False,
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        logger.info("[dashboard_core] training rows recent=%s total=%s", 0, 0)
        return {
            **structured_error(exc, operation="load_recent_training_summary"),
            "source": "error",
            "latest_workout": None,
            "latest_workout_date": "",
            "latest_workout_type": "",
            "recent_workout_count": 0,
            "workout_count": 0,
            "recent_rows": 0,
            "total_rows": 0,
            "days": bounded_days,
            "limit_workouts": bounded_workouts,
            "max_core_training_rows": MAX_CORE_TRAINING_ROWS,
            "recent_volume_summary": {"total_volume": 0, "total_sets": 0, "duration_minutes": 0},
            "latest_flags": {"has_run": False, "has_lift": False},
            "items": [],
            "full_raw_hevy_scan": False,
            "duration_ms": _duration_ms(started),
        }


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
    empty_training_summary = {
        "status": "not_loaded",
        "latest_workout": None,
        "latest_workout_date": "",
        "latest_workout_type": "",
        "recent_workout_count": 0,
        "recent_rows": 0,
        "total_rows": 0,
        "items": [],
        "full_raw_hevy_scan": False,
        "duration_ms": 0,
    }
    try:
        with cursor(timeout_ms=2000) as cur:
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
                    SELECT data
                    FROM training_cache_metadata
                    WHERE COALESCE(data->>'metadata_key', '') = %s
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                  ), '{}'::jsonb) AS training_cache_metadata,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'food_logs'::regclass), 0) AS food_count,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'body_metric_logs'::regclass), 0) AS body_count,
                  COALESCE((SELECT reltuples::bigint FROM pg_class WHERE oid = 'workout_logs'::regclass), 0) AS training_count
                """,
                (today, _bounded_limit(food_limit), _bounded_limit(body_limit), CORE_TRAINING_CACHE_KEY),
            )
            row = cur.fetchone()
        cached_training_metadata = sanitize_json(dict(row[4] or {})) if row else {}
        training_summary = load_recent_training_summary(limit_workouts=CORE_TRAINING_WORKOUTS, days=CORE_TRAINING_DAYS, cached_metadata=cached_training_metadata)
        if not row:
            return {
                "status": "ok",
                "goals": {},
                "targets": {},
                "food_rows": [],
                "body_rows": [],
                "training_rows": [],
                "training_summary": training_summary,
                "counts": {"nutrition": 0, "body_metrics": 0, "training": 0},
                "duration_ms": _duration_ms(started),
            }
        return {
            "status": "ok",
            "goals": sanitize_json(dict(row[0] or {})),
            "targets": sanitize_json(dict(row[1] or {})),
            "food_rows": sanitize_json(list(row[2] or [])),
            "body_rows": sanitize_json(list(row[3] or [])),
            "training_rows": [],
            "training_summary": training_summary,
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
            "training_summary": empty_training_summary,
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
            "training_summary": empty_training_summary,
            "counts": {"nutrition": 0, "body_metrics": 0, "training": 0},
            "duration_ms": _duration_ms(started),
        }
