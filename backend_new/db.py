"""Safe database helpers for backend_new.

This module opens database connections only when route code explicitly asks for
data. It does not create schema, import data, or run integration syncs.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
from datetime import date, datetime, timedelta, timezone
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
from backend_new.utils import app_today_iso
from src.training_schedule import classify_workout


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
    "exercise_prs",
    "muscle_group_training_summary",
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
DASHBOARD_CORE_CACHE_TTL_SECONDS = 20

logger = logging.getLogger(__name__)


class DatabaseNotConfigured(RuntimeError):
    pass


class UnsafeTableName(ValueError):
    pass


_connection: Any | None = None
_connection_lock = threading.RLock()
_dashboard_core_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
_dashboard_core_cache_lock = threading.RLock()
_performance_indexed_tables: set[str] = set()
_performance_index_lock = threading.RLock()


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


def invalidate_dashboard_core_cache() -> None:
    with _dashboard_core_cache_lock:
        _dashboard_core_cache.clear()


def _dashboard_core_cache_key(
    today: str,
    *,
    food_limit: int,
    body_limit: int,
    recovery_limit: int,
    sleep_limit: int,
    include_training_summary: bool,
) -> tuple[Any, ...]:
    return (
        str(today),
        _bounded_limit(food_limit),
        _bounded_limit(body_limit),
        _bounded_limit(recovery_limit),
        _bounded_limit(sleep_limit),
        bool(include_training_summary),
    )


def _jsonb(value: dict[str, Any]) -> Any:
    from psycopg.types.json import Jsonb

    return Jsonb(sanitize_json(value))


def ensure_jsonb_table(table: str) -> dict[str, Any]:
    """Create one of the supported JSONB tables on demand.

    This is intentionally called by write paths, not startup, so deployment and
    health checks remain side-effect free.
    """
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        with cursor(timeout_ms=2500) as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {safe_table} (
                    id BIGSERIAL PRIMARY KEY,
                    data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    row_order BIGSERIAL
                )
                """
            )
            cur.execute(f"CREATE INDEX IF NOT EXISTS {safe_table}_updated_at_idx ON {safe_table} (updated_at DESC, id DESC)")
        return {"status": "ok", "table": safe_table, "duration_ms": _duration_ms(started)}
    except DatabaseNotConfigured:
        return {"status": "not_configured", "table": table, "duration_ms": _duration_ms(started)}
    except Exception as exc:
        logger.exception("[db] ensure_jsonb_table failed table=%s", table)
        return {**structured_error(exc, operation="ensure_jsonb_table"), "table": table, "duration_ms": _duration_ms(started)}


def ensure_jsonb_performance_indexes(table: str) -> dict[str, Any]:
    """Create route-critical expression indexes for supported JSONB tables.

    Called lazily by hot routes instead of startup. The query helpers use
    literal, validated JSON keys so Postgres can match these expression indexes.
    """
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        with _performance_index_lock:
            if safe_table in _performance_indexed_tables:
                return {"status": "ok", "table": safe_table, "cached": True, "duration_ms": _duration_ms(started)}
            with cursor(timeout_ms=1000) as cur:
                cur.execute(
                    """
                    SELECT
                      to_regclass(%s)::text,
                      COALESCE(array_agg(indexname) FILTER (WHERE indexname IS NOT NULL), ARRAY[]::text[])
                    FROM pg_indexes
                    WHERE tablename = %s
                    """,
                    (safe_table, safe_table),
                )
                index_row = cur.fetchone()
            table_regclass = str(index_row[0] or "") if index_row else ""
            existing_indexes = {str(item) for item in (index_row[1] or [])} if index_row else set()
            ensure_result: dict[str, Any] = {"status": "ok", "table": safe_table}
            if not table_regclass:
                ensure_result = ensure_jsonb_table(safe_table)
                if ensure_result.get("status") in {"error", "not_configured"}:
                    return {**ensure_result, "operation": "ensure_jsonb_performance_indexes", "duration_ms": _duration_ms(started)}
                existing_indexes = set()
            statements: list[tuple[str, str]] = []
            if safe_table == "food_logs":
                statements = [
                    ("food_logs_date_row_order_idx", "CREATE INDEX IF NOT EXISTS food_logs_date_row_order_idx ON food_logs ((data->>'date') DESC, row_order DESC, id DESC)"),
                    ("food_logs_date_lookup_idx", "CREATE INDEX IF NOT EXISTS food_logs_date_lookup_idx ON food_logs ((data->>'date'), row_order DESC, id DESC)"),
                    ("food_logs_food_log_id_idx", "CREATE INDEX IF NOT EXISTS food_logs_food_log_id_idx ON food_logs ((data->>'food_log_id'))"),
                ]
            elif safe_table == "daily_nutrition_summary":
                statements = [
                    ("daily_nutrition_summary_date_row_order_idx", "CREATE INDEX IF NOT EXISTS daily_nutrition_summary_date_row_order_idx ON daily_nutrition_summary ((data->>'date') DESC, row_order DESC, id DESC)"),
                ]
            missing_statements = statements
            if statements:
                missing_statements = [(name, statement) for name, statement in statements if name not in existing_indexes]
            if missing_statements:
                with cursor(timeout_ms=10_000) as cur:
                    for _, statement in missing_statements:
                        cur.execute(statement)
            _performance_indexed_tables.add(safe_table)
            return {
                "status": "ok",
                "table": safe_table,
                "cached": False,
                "indexes": len(statements),
                "created_indexes": len(missing_statements),
                "duration_ms": _duration_ms(started),
            }
    except DatabaseNotConfigured:
        return {"status": "not_configured", "table": table, "duration_ms": _duration_ms(started)}
    except Exception as exc:
        logger.exception("[db] ensure performance indexes failed table=%s", table)
        return {**structured_error(exc, operation="ensure_jsonb_performance_indexes"), "table": table, "duration_ms": _duration_ms(started)}


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
    global _connection
    with _connection_lock:
        conn = get_connection()
        try:
            # Clear any previously aborted transaction on the reusable connection
            # before setting the per-query timeout. This keeps one failed optional
            # query from poisoning later dashboard blocks.
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('statement_timeout', %s, true)", (f"{_clamp_timeout_ms(timeout_ms)}ms",))
                yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            if getattr(conn, "closed", False):
                _connection = None
            raise


def table_exists(table: str) -> bool:
    try:
        safe_table = _safe_table(table)
        with cursor(timeout_ms=750) as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (safe_table,))
            row = cur.fetchone()
        return bool(row and row[0])
    except Exception as exc:
        logger.exception("[db] table existence check failed table=%s", table)
        return False


def existing_tables(tables: list[str] | tuple[str, ...] | set[str]) -> set[str]:
    safe_tables = sorted({_safe_table(table) for table in tables})
    if not safe_tables:
        return set()
    try:
        placeholders = ", ".join(["(%s)"] * len(safe_tables))
        with cursor(timeout_ms=1000) as cur:
            cur.execute(
                f"""
                SELECT requested.name
                FROM (VALUES {placeholders}) AS requested(name)
                WHERE to_regclass(requested.name) IS NOT NULL
                """,
                tuple(safe_tables),
            )
            return {str(row[0]) for row in cur.fetchall()}
    except Exception:
        logger.exception("[db] existing table check failed")
        return set()


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
                    WHERE data->>'{safe_date_field}' >= %s
                    ORDER BY data->>'{safe_date_field}' DESC, row_order DESC, id DESC
                    LIMIT %s
                    """,
                    (str(since_date), bounded_limit),
                )
            elif safe_date_field:
                cur.execute(
                    f"""
                    SELECT data
                    FROM {safe_table}
                    ORDER BY data->>'{safe_date_field}' DESC, row_order DESC, id DESC
                    LIMIT %s
                    """,
                    (bounded_limit,),
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
                WHERE data->>'{safe_field}' = %s
                ORDER BY row_order DESC, id DESC
                LIMIT %s
                """,
                (str(value), bounded_limit),
            )
            return [sanitize_json(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []
    except Exception as exc:
        return [{"_db_error": {**structured_error(exc, operation="fetch_json_rows_for_value"), "duration_ms": _duration_ms(started)}}]


def fetch_json_rows_matching_any(
    table: str,
    fields: tuple[str, ...],
    value: str,
    *,
    limit: int = 500,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        safe_fields = tuple(field for field in (_safe_json_key(field) for field in fields) if field)
        if not safe_fields:
            raise ValueError("At least one field is required.")
        bounded_limit = _bounded_limit(limit)
        where_clause = " OR ".join([f"data->>'{field}' = %s" for field in safe_fields])
        params = [str(value) for _ in safe_fields]
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"""
                SELECT data
                FROM {safe_table}
                WHERE {where_clause}
                ORDER BY row_order DESC, id DESC
                LIMIT %s
                """,
                (*params, bounded_limit),
            )
            return [sanitize_json(dict(row[0])) for row in cur.fetchall()]
    except DatabaseNotConfigured:
        return []
    except Exception as exc:
        return [{"_db_error": {**structured_error(exc, operation="fetch_json_rows_matching_any"), "duration_ms": _duration_ms(started)}}]


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


def _training_row_reps(row: dict[str, Any]) -> int:
    return max(0, int(_number(row.get("sets"), 0))) * max(0, int(_number(row.get("reps"), 0)))


def _infer_training_muscle_group(exercise: Any) -> str:
    name = str(exercise or "").lower()
    terms = [
        ("Chest", ("bench", "chest press", "fly", "pec", "push up", "push-up", "incline press")),
        ("Back", ("row", "pulldown", "pull down", "pullup", "pull-up", "chin", "lat ", "shrug")),
        ("Shoulders", ("overhead press", "shoulder press", "lateral raise", "front raise", "rear delt", "face pull", "arnold")),
        ("Biceps", ("curl", "preacher", "hammer curl")),
        ("Triceps", ("triceps", "skullcrusher", "skull crusher", "pushdown", "push down", "dip", "extension")),
        ("Quads", ("squat", "leg press", "leg extension", "lunge", "split squat", "hack squat")),
        ("Hamstrings", ("leg curl", "hamstring", "romanian", "rdl", "good morning")),
        ("Glutes", ("hip thrust", "glute", "kickback")),
        ("Calves", ("calf",)),
        ("Core", ("crunch", "plank", "sit up", "sit-up", "cable crunch", "leg raise")),
        ("Cardio", ("run", "treadmill", "bike", "cycling", "elliptical", "stair", "rower", "swim")),
    ]
    for group, needles in terms:
        if any(needle in name for needle in needles):
            return group
    return ""


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
        muscle_groups = sorted(
            {
                group
                for row in workout_rows
                for group in (str(row.get("muscle_group") or "").strip(), _infer_training_muscle_group(row.get("exercise")))
                if group
            }
        )
        classification = classify_workout(workout_rows)
        has_run = bool(classification.get("kind") in {"run", "cardio", "lift_cardio"})
        has_lift = bool(classification.get("has_lift"))
        workouts.append(
            {
                "date": workout_date,
                "workout_id": workout_id,
                "workout_type": workout_type,
                "classification": classification.get("kind", "unknown"),
                "split_type": classification.get("split_type") or "",
                "split_confidence": classification.get("split_confidence", 0.0),
                "classification_reason": classification.get("classification_reason") or [],
                "classification_debug": {
                    "has_lift": has_lift,
                    "has_cardio": bool(classification.get("has_cardio") or classification.get("has_run")),
                    "matched_lift_terms": classification.get("matched_lift_terms") or [],
                    "matched_cardio_terms": classification.get("matched_cardio_terms") or [],
                    "reason": classification.get("reason") or "",
                    "split_type": classification.get("split_type") or "",
                    "split_confidence": classification.get("split_confidence", 0.0),
                    "classification_reason": classification.get("classification_reason") or [],
                    "split_matched_by": classification.get("split_matched_by") or "none",
                },
                "muscle_groups": muscle_groups,
                "total_sets": int(sum(max(0, int(_number(row.get("sets"), 0))) for row in workout_rows)),
                "total_reps": int(sum(_training_row_reps(row) for row in workout_rows)),
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
            "total_reps": int(sum(_number(item.get("total_reps"), 0) for item in recent)),
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
    cutoff = (date.fromisoformat(app_today_iso()) - timedelta(days=bounded_days)).isoformat()

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
            "recent_volume_summary": {"total_volume": 0, "total_sets": 0, "total_reps": 0, "duration_minutes": 0},
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
            "recent_volume_summary": {"total_volume": 0, "total_sets": 0, "total_reps": 0, "duration_minutes": 0},
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
        ensure_result = ensure_jsonb_table(safe_table)
        if ensure_result.get("status") == "error":
            raise RuntimeError(ensure_result.get("message") or "Could not ensure JSONB table.")
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"INSERT INTO {safe_table} (data) VALUES (%s) RETURNING data",
                (_jsonb(payload),),
            )
            row = cur.fetchone()
            invalidate_dashboard_core_cache()
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
        ensure_result = ensure_jsonb_table(safe_table)
        if ensure_result.get("status") == "error":
            raise RuntimeError(ensure_result.get("message") or "Could not ensure JSONB table.")
        safe_key = _safe_json_key(key_field)
        if safe_key is None:
            raise ValueError("key_field is required.")
        payload = sanitize_json({**dict(data), safe_key: key_value})
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"""
                UPDATE {safe_table}
                SET data = data || %s::jsonb, updated_at = now()
                WHERE data->>'{safe_key}' = %s
                RETURNING data
                """,
                (_jsonb(payload), str(key_value)),
            )
            row = cur.fetchone()
            if row:
                invalidate_dashboard_core_cache()
                return sanitize_json(dict(row[0]))
            cur.execute(
                f"INSERT INTO {safe_table} (data) VALUES (%s) RETURNING data",
                (_jsonb(payload),),
            )
            inserted = cur.fetchone()
            invalidate_dashboard_core_cache()
            return sanitize_json(dict(inserted[0])) if inserted else payload
    except DatabaseNotConfigured:
        return payload
    except Exception as exc:
        return {**payload, "_db_error": {**structured_error(exc, operation="upsert_json_row"), "duration_ms": _duration_ms(started)}}


def update_json_rows_for_value(table: str, field: str, value: str, patch: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    payload = sanitize_json(dict(patch))
    try:
        safe_table = _safe_table(table)
        ensure_result = ensure_jsonb_table(safe_table)
        if ensure_result.get("status") == "error":
            raise RuntimeError(ensure_result.get("message") or "Could not ensure JSONB table.")
        safe_field = _safe_json_key(field)
        if safe_field is None:
            raise ValueError("field is required.")
        with cursor(timeout_ms=2500) as cur:
            cur.execute(
                f"""
                UPDATE {safe_table}
                SET data = data || %s::jsonb, updated_at = now()
                WHERE data->>'{safe_field}' = %s
                """,
                (_jsonb(payload), str(value)),
            )
            updated = int(getattr(cur, "rowcount", 0) or 0)
        if updated:
            invalidate_dashboard_core_cache()
        return {
            "status": "ok",
            "table": safe_table,
            "field": safe_field,
            "value": str(value),
            "updated_rows": updated,
            "duration_ms": _duration_ms(started),
        }
    except DatabaseNotConfigured:
        return {
            "status": "not_configured",
            "table": table,
            "field": field,
            "value": str(value),
            "updated_rows": 0,
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        return {
            **structured_error(exc, operation="update_json_rows_for_value"),
            "table": table,
            "field": field,
            "value": str(value),
            "updated_rows": 0,
            "duration_ms": _duration_ms(started),
        }


def move_workout_date_rows(
    table: str,
    workout_id: str,
    new_date: str,
    *,
    match_fields: tuple[str, ...] = ("workout_id", "hevy_workout_id", "external_id", "source_id"),
    annotate_notes: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    workout_id = str(workout_id or "").strip()
    if not workout_id:
        return {"status": "error", "message": "workout_id is required.", "updated_rows": 0, "duration_ms": _duration_ms(started)}
    parsed_date = str(new_date or "").strip()[:10]
    try:
        normalized_date = date.fromisoformat(parsed_date).isoformat()
    except ValueError:
        return {"status": "error", "message": "new_date must be a valid YYYY-MM-DD date.", "updated_rows": 0, "duration_ms": _duration_ms(started)}

    try:
        safe_table = _safe_table(table)
        if not table_exists(safe_table):
            return {
                "status": "ok",
                "table": safe_table,
                "workout_id": workout_id,
                "old_dates": [],
                "old_date": "",
                "new_date": normalized_date,
                "updated_rows": 0,
                "duration_ms": _duration_ms(started),
            }
        safe_fields = tuple(field for field in (_safe_json_key(field) for field in match_fields) if field)
        if not safe_fields:
            raise ValueError("At least one match field is required.")
        where_clause = " OR ".join([f"data->>'{field}' = %s" for field in safe_fields])
        params = [workout_id for _ in safe_fields]

        updated_rows = 0
        old_dates: list[str] = []
        now = datetime.now(timezone.utc).isoformat()
        with cursor(timeout_ms=2500) as cur:
            cur.execute(f"SELECT id, data FROM {safe_table} WHERE {where_clause} ORDER BY id", params)
            rows = cur.fetchall()
            for row_id, data in rows:
                payload = sanitize_json(dict(data or {}))
                old_date = str(payload.get("date") or "")[:10]
                if old_date:
                    old_dates.append(old_date)
                payload["date"] = normalized_date
                payload["date_corrected_at"] = now
                if annotate_notes:
                    previous = str(payload.get("notes") or "").strip()
                    if old_date and "date_corrected_from=" not in previous:
                        marker = f"date_corrected_from={old_date}"
                        payload["notes"] = f"{previous} | {marker}" if previous else marker
                    payload["updated_at"] = now
                cur.execute(
                    f"UPDATE {safe_table} SET data = %s, updated_at = now() WHERE id = %s",
                    (_jsonb(payload), row_id),
                )
                updated_rows += int(getattr(cur, "rowcount", 0) or 0)
        if updated_rows:
            invalidate_dashboard_core_cache()
        return {
            "status": "ok",
            "table": safe_table,
            "workout_id": workout_id,
            "old_dates": sorted(set(old_dates)),
            "old_date": sorted(set(old_dates))[0] if old_dates else "",
            "new_date": normalized_date,
            "updated_rows": updated_rows,
            "duration_ms": _duration_ms(started),
        }
    except DatabaseNotConfigured:
        return {
            "status": "not_configured",
            "message": "DATABASE_URL is not configured.",
            "table": table,
            "workout_id": workout_id,
            "old_date": "",
            "new_date": parsed_date,
            "updated_rows": 0,
            "duration_ms": _duration_ms(started),
        }
    except Exception as exc:
        return {**structured_error(exc, operation="move_workout_date_rows"), "table": table, "workout_id": workout_id, "new_date": parsed_date, "updated_rows": 0, "duration_ms": _duration_ms(started)}


def delete_json_row(table: str, key_field: str, key_value: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        safe_table = _safe_table(table)
        safe_key = _safe_json_key(key_field)
        if safe_key is None:
            raise ValueError("key_field is required.")
        with cursor(timeout_ms=1500) as cur:
            cur.execute(f"DELETE FROM {safe_table} WHERE data->>'{safe_key}' = %s", (str(key_value),))
            deleted = int(getattr(cur, "rowcount", 0) or 0)
        if deleted:
            invalidate_dashboard_core_cache()
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
            cur.execute(
                """
                SELECT COALESCE((
                    SELECT reltuples::bigint
                    FROM pg_class
                    WHERE oid = to_regclass(%s)
                ), 0)
                """,
                (safe_table,),
            )
            row = cur.fetchone()
        exists = table_exists(safe_table)
        return {
            "status": "ok" if exists else "missing",
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


def count_rows_many(tables: list[str] | tuple[str, ...] | set[str]) -> dict[str, dict[str, Any]]:
    started = time.perf_counter()
    safe_tables = sorted({_safe_table(table) for table in tables})
    defaults = {
        table: {
            "status": "not_configured" if not database_url() else "missing",
            "table": table,
            "count_estimate": 0,
            "exact": False,
            "duration_ms": 0,
        }
        for table in safe_tables
    }
    if not safe_tables:
        return {}
    if not database_url():
        duration = _duration_ms(started)
        return {table: {**value, "duration_ms": duration} for table, value in defaults.items()}
    try:
        placeholders = ", ".join(["(%s)"] * len(safe_tables))
        with cursor(timeout_ms=1500) as cur:
            cur.execute(
                f"""
                SELECT requested.table_name,
                       to_regclass(requested.table_name) IS NOT NULL AS exists,
                       COALESCE((
                         SELECT reltuples::bigint
                         FROM pg_class
                         WHERE oid = to_regclass(requested.table_name)
                       ), 0) AS estimate
                FROM (VALUES {placeholders}) AS requested(table_name)
                """,
                tuple(safe_tables),
            )
            rows = cur.fetchall()
        duration = _duration_ms(started)
        return {
            str(table): {
                "status": "ok" if exists else "missing",
                "table": str(table),
                "count_estimate": max(0, int(estimate or 0)),
                "exact": False,
                "duration_ms": duration,
            }
            for table, exists, estimate in rows
        }
    except DatabaseNotConfigured:
        duration = _duration_ms(started)
        return {table: {**value, "duration_ms": duration} for table, value in defaults.items()}
    except Exception as exc:
        duration = _duration_ms(started)
        return {
            table: {
                **structured_error(exc, operation="count_rows_many"),
                "table": table,
                "count_estimate": 0,
                "exact": False,
                "duration_ms": duration,
            }
            for table in safe_tables
        }


def fetch_dashboard_core_bundle(
    today: str,
    *,
    food_limit: int = 500,
    body_limit: int = 90,
    recovery_limit: int = 90,
    sleep_limit: int = 90,
    include_training_summary: bool = True,
) -> dict[str, Any]:
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
    if not database_url():
        return {
            "status": "not_configured",
            "goals": {},
            "targets": {},
            "food_rows": [],
            "body_rows": [],
            "recovery_rows": [],
            "sleep_rows": [],
            "training_rows": [],
            "training_summary": empty_training_summary,
            "counts": {"nutrition": 0, "body_metrics": 0, "training": 0, "recovery": 0, "sleep": 0},
            "blocks": [],
            "warnings": [],
            "duration_ms": _duration_ms(started),
        }

    cache_key = _dashboard_core_cache_key(
        today,
        food_limit=food_limit,
        body_limit=body_limit,
        recovery_limit=recovery_limit,
        sleep_limit=sleep_limit,
        include_training_summary=include_training_summary,
    )
    with _dashboard_core_cache_lock:
        cached = _dashboard_core_cache.get(cache_key)
        if cached and time.time() - float(cached.get("_cached_epoch", 0)) <= DASHBOARD_CORE_CACHE_TTL_SECONDS:
            payload = copy.deepcopy(cached.get("payload", {}))
            payload["cache"] = {
                "status": "hit",
                "ttl_seconds": DASHBOARD_CORE_CACHE_TTL_SECONDS,
                "created_at": cached.get("_cached_at", ""),
            }
            payload["duration_ms"] = _duration_ms(started)
            return payload

    blocks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    core_table_names = {
        "user_goal_settings",
        "macro_targets",
        "food_logs",
        "body_metric_logs",
        "training_cache_metadata",
        "recovery_logs",
        "sleep_logs",
    }
    # Optimistic fast path: production should have these lightweight JSONB
    # tables. Avoid a separate table-metadata round trip on every cold
    # dashboard miss; if a table is missing, the fallback below isolates blocks.
    core_tables = set(core_table_names)

    def read_block(block_name: str, table: str, default: Any, query: Any) -> Any:
        block_started = time.perf_counter()
        if table not in core_tables:
            warning = {
                "block": block_name,
                "name": block_name,
                "table": table,
                "status": "warning",
                "message": f"Optional table {table} is missing; using empty/default data.",
                "duration_ms": _duration_ms(block_started),
            }
            blocks.append(warning)
            warnings.append(warning)
            return default
        try:
            value = query()
            blocks.append(
                {
                    "block": block_name,
                    "name": block_name,
                    "table": table,
                    "status": "ok",
                    "duration_ms": _duration_ms(block_started),
                }
            )
            return value
        except Exception as exc:
            logger.exception("[dashboard_core] block failed block=%s table=%s", block_name, table)
            warning = {
                **structured_error(exc, operation=block_name),
                "block": block_name,
                "name": block_name,
                "table": table,
                "status": "warning",
                "duration_ms": _duration_ms(block_started),
            }
            blocks.append(warning)
            warnings.append(warning)
            return default

    def latest_document_block(table: str, block_name: str) -> dict[str, Any]:
        def query() -> dict[str, Any]:
            with cursor(timeout_ms=1000) as cur:
                cur.execute(f"SELECT data FROM {table} ORDER BY updated_at DESC, id DESC LIMIT 1")
                row = cur.fetchone()
            return sanitize_json(dict(row[0])) if row else {}

        return read_block(block_name, table, {}, query)

    def rows_block(table: str, block_name: str, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
        def query() -> list[dict[str, Any]]:
            with cursor(timeout_ms=1500) as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
            return sanitize_json(list(row[0] or [])) if row else []

        return read_block(block_name, table, [], query)

    goals: dict[str, Any] = {}
    targets: dict[str, Any] = {}
    food_rows: list[dict[str, Any]] = []
    body_rows: list[dict[str, Any]] = []
    cached_training_metadata: dict[str, Any] = {}
    recovery_rows: list[dict[str, Any]] = []
    sleep_rows: list[dict[str, Any]] = []
    combined_started = time.perf_counter()
    try:
        expressions = [
            "(SELECT data FROM user_goal_settings ORDER BY updated_at DESC, id DESC LIMIT 1)" if "user_goal_settings" in core_tables else "'{}'::jsonb",
            "(SELECT data FROM macro_targets ORDER BY updated_at DESC, id DESC LIMIT 1)" if "macro_targets" in core_tables else "'{}'::jsonb",
            """
            (SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
             FROM (
               SELECT data
               FROM food_logs
               WHERE data->>'date' = %s
                 AND COALESCE(data->>'excluded_from_analytics', 'false') <> 'true'
               ORDER BY row_order DESC, id DESC
               LIMIT %s
             ) rows)
            """ if "food_logs" in core_tables else "'[]'::jsonb",
            """
            (SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
             FROM (
               SELECT data
               FROM body_metric_logs
               WHERE COALESCE(data->>'excluded_from_analytics', 'false') <> 'true'
               ORDER BY id DESC
               LIMIT %s
             ) rows)
            """ if "body_metric_logs" in core_tables else "'[]'::jsonb",
            "(SELECT data FROM training_cache_metadata ORDER BY updated_at DESC, id DESC LIMIT 1)" if "training_cache_metadata" in core_tables else "'{}'::jsonb",
            """
            (SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
             FROM (
               SELECT data
               FROM recovery_logs
               ORDER BY data->>'date' DESC, row_order DESC, id DESC
               LIMIT %s
             ) rows)
            """ if "recovery_logs" in core_tables else "'[]'::jsonb",
            """
            (SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
             FROM (
               SELECT data
               FROM sleep_logs
               ORDER BY data->>'date' DESC, row_order DESC, id DESC
               LIMIT %s
             ) rows)
            """ if "sleep_logs" in core_tables else "'[]'::jsonb",
        ]
        params: list[Any] = []
        if "food_logs" in core_tables:
            params.extend([today, _bounded_limit(food_limit)])
        if "body_metric_logs" in core_tables:
            params.append(_bounded_limit(body_limit))
        if "recovery_logs" in core_tables:
            params.append(_bounded_limit(recovery_limit))
        if "sleep_logs" in core_tables:
            params.append(_bounded_limit(sleep_limit))
        with cursor(timeout_ms=2500) as cur:
            cur.execute(
                "SELECT " + ", ".join(f"{expression} AS col_{index}" for index, expression in enumerate(expressions)),
                tuple(params),
            )
            row = cur.fetchone()
        if row:
            goals = sanitize_json(dict(row[0] or {}))
            targets = sanitize_json(dict(row[1] or {}))
            food_rows = sanitize_json(list(row[2] or []))
            body_rows = sanitize_json(list(row[3] or []))
            cached_training_metadata = sanitize_json(dict(row[4] or {}))
            recovery_rows = sanitize_json(list(row[5] or []))
            sleep_rows = sanitize_json(list(row[6] or []))
        combined_duration = _duration_ms(combined_started)
        logger.info("[dashboard_core] block=combined_snapshot duration_ms=%s", combined_duration)
        for block_name, table in (
            ("goals", "user_goal_settings"),
            ("targets", "macro_targets"),
            ("today_food_rows", "food_logs"),
            ("body_metric_rows", "body_metric_logs"),
            ("training_cache_metadata", "training_cache_metadata"),
            ("recovery_rows", "recovery_logs"),
            ("sleep_rows", "sleep_logs"),
        ):
            if table in core_tables:
                blocks.append({"block": block_name, "name": block_name, "table": table, "status": "ok", "duration_ms": combined_duration, "source": "combined_snapshot"})
            else:
                warning = {
                    "block": block_name,
                    "name": block_name,
                    "table": table,
                    "status": "warning",
                    "message": f"Optional table {table} is missing; using empty/default data.",
                    "duration_ms": combined_duration,
                }
                blocks.append(warning)
                warnings.append(warning)
    except Exception:
        logger.exception("[dashboard_core] combined snapshot failed; falling back to isolated blocks")
        core_tables = existing_tables(core_table_names)
        goals = latest_document_block("user_goal_settings", "goals")
        targets = latest_document_block("macro_targets", "targets")
        food_rows = rows_block(
            "food_logs",
            "today_food_rows",
            """
            SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
            FROM (
              SELECT data
              FROM food_logs
              WHERE data->>'date' = %s
                AND COALESCE(data->>'excluded_from_analytics', 'false') <> 'true'
              ORDER BY row_order DESC, id DESC
              LIMIT %s
            ) rows
            """,
            (today, _bounded_limit(food_limit)),
        )
        body_rows = rows_block(
            "body_metric_logs",
            "body_metric_rows",
            """
            SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
            FROM (
              SELECT data
              FROM body_metric_logs
              WHERE COALESCE(data->>'excluded_from_analytics', 'false') <> 'true'
              ORDER BY id DESC
              LIMIT %s
            ) rows
            """,
            (_bounded_limit(body_limit),),
        )
        cached_training_metadata = latest_document_block("training_cache_metadata", "training_cache_metadata")
        recovery_rows = rows_block(
            "recovery_logs",
            "recovery_rows",
            """
            SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
            FROM (
              SELECT data
              FROM recovery_logs
              ORDER BY data->>'date' DESC, row_order DESC, id DESC
              LIMIT %s
            ) rows
            """,
            (_bounded_limit(recovery_limit),),
        )
        sleep_rows = rows_block(
            "sleep_logs",
            "sleep_rows",
            """
            SELECT COALESCE(jsonb_agg(data), '[]'::jsonb)
            FROM (
              SELECT data
              FROM sleep_logs
              ORDER BY data->>'date' DESC, row_order DESC, id DESC
              LIMIT %s
            ) rows
            """,
            (_bounded_limit(sleep_limit),),
        )

    training_summary = empty_training_summary
    if include_training_summary:
        block_started = time.perf_counter()
        training_summary = load_recent_training_summary(limit_workouts=CORE_TRAINING_WORKOUTS, days=CORE_TRAINING_DAYS, cached_metadata=cached_training_metadata)
        training_duration = _duration_ms(block_started)
        logger.info("[dashboard_core] block=training_summary_cache duration_ms=%s", training_duration)
        blocks.append(
            {
                "block": "training_summary_cache",
                "name": "training_summary_cache",
                "table": "training_cache_metadata",
                "status": "ok" if str(training_summary.get("status") or "") in {"ok", "not_configured"} else "warning",
                "duration_ms": training_duration,
                "message": training_summary.get("message", ""),
                "error_type": training_summary.get("error_type"),
            }
        )

    count_started = time.perf_counter()
    counts = {
        "nutrition": len(food_rows),
        "body_metrics": len(body_rows),
        "training": max(0, int(training_summary.get("total_rows") or training_summary.get("recent_rows") or 0)),
        "recovery": len(recovery_rows),
        "sleep": len(sleep_rows),
    }
    count_duration = _duration_ms(count_started)
    logger.info("[dashboard_core] block=derived_counts duration_ms=%s", count_duration)
    blocks.append(
        {
            "block": "derived_counts",
            "name": "derived_counts",
            "status": "ok",
            "source": "bounded_snapshot",
            "duration_ms": count_duration,
        }
    )

    result = {
        "status": "ok",
        "goals": goals,
        "targets": targets,
        "food_rows": food_rows,
        "body_rows": body_rows,
        "recovery_rows": recovery_rows,
        "sleep_rows": sleep_rows,
        "training_rows": [],
        "training_summary": training_summary,
        "counts": counts,
        "blocks": blocks,
        "warnings": warnings,
        "cache": {
            "status": "miss",
            "ttl_seconds": DASHBOARD_CORE_CACHE_TTL_SECONDS,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "duration_ms": _duration_ms(started),
    }
    with _dashboard_core_cache_lock:
        _dashboard_core_cache[cache_key] = {
            "payload": copy.deepcopy(result),
            "_cached_epoch": time.time(),
            "_cached_at": result["cache"]["created_at"],
        }
    logger.info("[dashboard_core] block=total duration_ms=%s cache=miss", result["duration_ms"])
    return result
