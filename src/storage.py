"""Persistent storage adapter for local files and production Postgres.

Local development keeps using gitignored CSV/JSON files. When DATABASE_URL is
set, the backend stores durable app data in Postgres so redeploys and multiple
devices share the same history.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import time
from typing import Any

import pandas as pd


logger = logging.getLogger(__name__)


DATAFRAME_TABLES = {
    "nutrition_log": "food_logs",
    "frequent_foods": "frequent_foods",
    "food_shortcuts": "food_shortcuts",
    "meal_templates": "meal_templates",
    "body_metrics": "body_metric_logs",
    "training_log": "workout_logs",
    "recovery_log": "recovery_logs",
    "sleep_entries": "sleep_logs",
    "daily_nutrition_summary": "daily_nutrition_summaries",
    "ai_food_cache": "ai_food_cache",
    "usda_food_cache": "usda_food_cache",
    "verified_food_cache": "verified_food_cache",
}

DOCUMENT_TABLES = {
    "user_settings": "api_connections",
    "user_goals": "user_goal_settings",
    "nutrition_targets": "macro_targets",
    "nutrition_recommendation_history": "nutrition_recommendation_history",
    "personal_records": "personal_records",
    "hevy_sync_state": "integration_sync_state",
    "training_schedule_profile": "training_schedule_profiles",
}

ALL_DATASET_TABLES = sorted({*DATAFRAME_TABLES.values(), *DOCUMENT_TABLES.values()})
DB_CONNECT_TIMEOUT_SECONDS = 10

LOWERCASE_KEY_FIELDS = {
    "food_name",
    "shortcut_name",
    "template_name",
    "source",
}


def _stable_text(value: Any, *, lowercase: bool = False) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "<na>", "nat"}:
        return ""
    return text.lower() if lowercase else text


def _composite_key(dataset: str, record: dict[str, Any], fields: list[str]) -> str | None:
    parts = [
        _stable_text(record.get(field), lowercase=field in LOWERCASE_KEY_FIELDS)
        for field in fields
    ]
    if any(not part for part in parts):
        return None
    return f"{dataset}:" + "|".join(parts)


def dataframe_row_key(dataset: str, record: dict[str, Any], row_index: int | None = None) -> str | None:
    """Return the durable Postgres row identity for a dataset record when known."""
    if dataset == "nutrition_log":
        return _composite_key(dataset, record, ["food_log_id"]) or _composite_key(dataset, record, ["source", "source_id"])
    if dataset == "frequent_foods":
        return _composite_key(dataset, record, ["food_name"])
    if dataset == "food_shortcuts":
        return _composite_key(dataset, record, ["shortcut_id"]) or _composite_key(dataset, record, ["shortcut_name"])
    if dataset == "meal_templates":
        return _composite_key(dataset, record, ["template_name", "food_name", "calories", "protein", "carbs", "fat"])
    if dataset == "body_metrics":
        return _composite_key(dataset, record, ["source", "source_id"]) or _composite_key(dataset, record, ["date", "source", "notes"])
    if dataset == "training_log":
        return _composite_key(dataset, record, ["external_id"]) or _composite_key(dataset, record, ["workout_id", "exercise", "set_number"])
    if dataset == "recovery_log":
        return _composite_key(dataset, record, ["date"])
    if dataset == "sleep_entries":
        return _composite_key(dataset, record, ["id"])
    if dataset == "daily_nutrition_summary":
        return _composite_key(dataset, record, ["date"])
    if dataset in {"ai_food_cache", "usda_food_cache", "verified_food_cache"}:
        for fields in (["cache_key"], ["query"], ["normalized_name"], ["food_name"], ["fdc_id"]):
            key = _composite_key(dataset, record, fields)
            if key:
                return key
    return None


def dataframe_row_keys(dataset: str, records: list[dict[str, Any]]) -> list[str]:
    """Return known durable row keys for records, skipping records without one."""
    keys = []
    for index, record in enumerate(records):
        key = dataframe_row_key(dataset, record, index)
        if key:
            keys.append(key)
    return keys


def mark_dataframe_deletes(df: pd.DataFrame, dataset: str, deleted_records: list[dict[str, Any]]) -> pd.DataFrame:
    """Attach explicit Postgres row deletes to a filtered dataframe before saving."""
    keys = dataframe_row_keys(dataset, [_clean_record(record) for record in deleted_records])
    if keys:
        existing = list(df.attrs.get("delete_row_keys", []))
        df.attrs["delete_row_keys"] = [*existing, *keys]
    return df


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def use_database() -> bool:
    return bool(database_url())


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL is set but psycopg is not installed. Run pip install -r requirements.txt.") from exc

    return psycopg.connect(database_url(), connect_timeout=DB_CONNECT_TIMEOUT_SECONDS)


TRANSIENT_DB_ERROR_NAMES = {
    "AdminShutdown",
    "ConnectionException",
    "OperationalError",
    "InterfaceError",
    "ConnectionTimeout",
    "ConnectionFailure",
    "CannotConnectNow",
    "TooManyConnections",
}


def _is_transient_database_error(exc: Exception) -> bool:
    class_names = {cls.__name__ for cls in type(exc).mro()}
    if class_names & TRANSIENT_DB_ERROR_NAMES:
        return True
    message = str(exc).lower()
    transient_markers = [
        "terminating connection",
        "administrator command",
        "connection reset",
        "connection refused",
        "connection timeout",
        "connection already closed",
        "server closed the connection",
        "could not connect",
        "timeout expired",
    ]
    return any(marker in message for marker in transient_markers)


def is_database_unavailable_error(exc: Exception) -> bool:
    """Return True for Postgres lifecycle/connectivity failures callers can surface safely."""
    return _is_transient_database_error(exc)


def debug_database_connection() -> dict[str, Any]:
    """Open a fresh DB connection and run a tiny query for production diagnostics."""
    started = time.perf_counter()
    if not use_database():
        return {
            "status": "not_configured",
            "storage": "local_files",
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            "message": "DATABASE_URL is not configured.",
        }
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                value = cur.fetchone()[0]
        return {
            "status": "ok",
            "storage": "postgres",
            "result": int(value),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except Exception as exc:
        logger.exception("Database debug check failed.")
        return {
            "status": "error",
            "storage": "postgres",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }


def _with_database_retry(operation, *, attempts: int = 2):
    global _schema_ready
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            last_exc = exc
            if not _is_transient_database_error(exc) or attempt >= attempts - 1:
                raise
            _schema_ready = False
            delay_seconds = 0.2 * (attempt + 1)
            logger.warning(
                "Transient Postgres error; retrying storage operation in %.1fs: %s",
                delay_seconds,
                exc,
            )
            time.sleep(delay_seconds)
    if last_exc:
        raise last_exc
    return None


def _json_default(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_default(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_default(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_default(value) for key, value in record.items()}


# Set once the schema has been created in this process. Without this guard,
# every load_/save_ call would re-run 36 DDL statements against Postgres,
# adding tens of seconds of latency to data-heavy routes like /api/dashboard.
_schema_ready = False


def ensure_database_schema(force: bool = False) -> None:
    """Create durable JSONB-backed tables for every app dataset (once per process)."""
    global _schema_ready
    if not use_database():
        return
    if _schema_ready and not force:
        return

    def apply_schema() -> None:
        with _connect() as conn:
            with conn.cursor() as cur:
                for table in ALL_DATASET_TABLES:
                    cur.execute(
                        f"""
                        CREATE TABLE IF NOT EXISTS {table} (
                            id BIGSERIAL PRIMARY KEY,
                            row_key TEXT,
                            row_order INTEGER NOT NULL DEFAULT 0,
                            data JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                        )
                        """
                    )
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS row_key TEXT")
                    cur.execute(f"CREATE INDEX IF NOT EXISTS {table}_row_order_idx ON {table} (row_order)")
                    cur.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {table}_row_key_unique_idx ON {table} (row_key) WHERE row_key IS NOT NULL")
            conn.commit()

    _with_database_retry(apply_schema)
    _schema_ready = True


def _table_for_dataframe(dataset: str) -> str:
    try:
        return DATAFRAME_TABLES[dataset]
    except KeyError as exc:
        raise KeyError(f"No Postgres table mapping configured for dataframe dataset: {dataset}") from exc


def _table_for_document(key: str) -> str:
    try:
        return DOCUMENT_TABLES[key]
    except KeyError as exc:
        raise KeyError(f"No Postgres table mapping configured for JSON document: {key}") from exc


def load_dataframe(dataset: str, path: Path, columns: list[str]) -> pd.DataFrame:
    """Load a tabular dataset from Postgres or local CSV."""
    if use_database():
        def load_from_db() -> pd.DataFrame:
            ensure_database_schema()
            table = _table_for_dataframe(dataset)
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT data FROM {table} ORDER BY row_order, id")
                    rows = [row[0] for row in cur.fetchall()]
            if not rows:
                return pd.DataFrame(columns=columns)
            return pd.DataFrame(rows)

        df = _with_database_retry(load_from_db)
    else:
        if not path.exists():
            return pd.DataFrame(columns=columns)
        df = pd.read_csv(path)

    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df[columns]


def save_dataframe(dataset: str, path: Path, df: pd.DataFrame, columns: list[str]) -> None:
    """Save a tabular dataset to Postgres or local CSV."""
    data = (df.copy() if df is not None else pd.DataFrame(columns=columns)).reindex(columns=columns)

    if use_database():
        def save_to_db() -> None:
            ensure_database_schema()
            table = _table_for_dataframe(dataset)
            records = [_clean_record(record) for record in data.to_dict(orient="records")]
            row_keys = dataframe_row_keys(dataset, records)
            delete_row_keys = sorted(set(str(key) for key in data.attrs.get("delete_row_keys", []) if str(key).strip()))
            replace_all = bool(data.attrs.get("replace_all", False))
            with _connect() as conn:
                with conn.cursor() as cur:
                    if replace_all or (records and len(row_keys) != len(records)):
                        cur.execute(f"DELETE FROM {table}")
                        if records:
                            cur.executemany(
                                f"INSERT INTO {table} (row_key, row_order, data) VALUES (%s, %s, %s::jsonb)",
                                [
                                    (dataframe_row_key(dataset, record, index), index, json.dumps(record))
                                    for index, record in enumerate(records)
                                ],
                            )
                    else:
                        if delete_row_keys:
                            cur.execute(f"DELETE FROM {table} WHERE row_key = ANY(%s)", (delete_row_keys,))
                        if records:
                            cur.execute(f"DELETE FROM {table} WHERE row_key IS NULL")
                            cur.executemany(
                                f"""
                                INSERT INTO {table} (row_key, row_order, data)
                                VALUES (%s, %s, %s::jsonb)
                                ON CONFLICT (row_key) WHERE row_key IS NOT NULL
                                DO UPDATE SET
                                    row_order = EXCLUDED.row_order,
                                    data = EXCLUDED.data,
                                    updated_at = now()
                                """,
                                [
                                    (row_keys[index], index, json.dumps(record))
                                    for index, record in enumerate(records)
                                ],
                            )
                        elif delete_row_keys:
                            pass
                        else:
                            cur.execute(f"DELETE FROM {table}")
                conn.commit()

        _with_database_retry(save_to_db)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False)


def load_document(key: str, path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON document from Postgres or local JSON."""
    if use_database():
        def load_from_db() -> dict[str, Any]:
            ensure_database_schema()
            table = _table_for_document(key)
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT data FROM {table} ORDER BY updated_at DESC, id DESC LIMIT 1")
                    row = cur.fetchone()
            return dict(row[0]) if row else default.copy()

        return _with_database_retry(load_from_db)

    if not path.exists():
        return default.copy()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default.copy()


def save_document(key: str, path: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Save a JSON document to Postgres or local JSON."""
    data = json.loads(json.dumps(document, default=_json_default))

    if use_database():
        def save_to_db() -> dict[str, Any]:
            ensure_database_schema()
            table = _table_for_document(key)
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {table} (row_key, row_order, data)
                        VALUES ('document', 0, %s::jsonb)
                        ON CONFLICT (row_key) WHERE row_key IS NOT NULL
                        DO UPDATE SET
                            row_order = EXCLUDED.row_order,
                            data = EXCLUDED.data,
                            updated_at = now()
                        """,
                        (json.dumps(data),),
                    )
                    cur.execute(f"DELETE FROM {table} WHERE row_key IS NULL")
                conn.commit()
            return data

        return _with_database_retry(save_to_db)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def production_storage_warnings() -> list[str]:
    """Return deployment warnings for missing durable storage config."""
    production_like = any(
        os.getenv(name)
        for name in ["VERCEL", "RAILWAY_ENVIRONMENT", "RENDER", "RENDER_SERVICE_ID"]
    ) or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
    if production_like and not use_database():
        return ["DATABASE_URL is missing. Production data will not persist across deploys without Postgres."]
    return []
