"""Persistent storage adapter for local files and production Postgres.

Local development keeps using gitignored CSV/JSON files. When DATABASE_URL is
set, the backend stores durable app data in Postgres so redeploys and multiple
devices share the same history.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


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
}

ALL_DATASET_TABLES = sorted({*DATAFRAME_TABLES.values(), *DOCUMENT_TABLES.values()})


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def use_database() -> bool:
    return bool(database_url())


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL is set but psycopg is not installed. Run pip install -r requirements.txt.") from exc

    return psycopg.connect(database_url())


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

    with _connect() as conn:
        with conn.cursor() as cur:
            for table in ALL_DATASET_TABLES:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id BIGSERIAL PRIMARY KEY,
                        row_order INTEGER NOT NULL DEFAULT 0,
                        data JSONB NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(f"CREATE INDEX IF NOT EXISTS {table}_row_order_idx ON {table} (row_order)")
        conn.commit()
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
        ensure_database_schema()
        table = _table_for_dataframe(dataset)
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT data FROM {table} ORDER BY row_order, id")
                rows = [row[0] for row in cur.fetchall()]
        if not rows:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(rows)
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
        ensure_database_schema()
        table = _table_for_dataframe(dataset)
        records = [_clean_record(record) for record in data.to_dict(orient="records")]
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {table}")
                if records:
                    cur.executemany(
                        f"INSERT INTO {table} (row_order, data) VALUES (%s, %s::jsonb)",
                        [(index, json.dumps(record)) for index, record in enumerate(records)],
                    )
            conn.commit()
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False)


def load_document(key: str, path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """Load a JSON document from Postgres or local JSON."""
    if use_database():
        ensure_database_schema()
        table = _table_for_document(key)
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT data FROM {table} ORDER BY updated_at DESC, id DESC LIMIT 1")
                row = cur.fetchone()
        return dict(row[0]) if row else default.copy()

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
        ensure_database_schema()
        table = _table_for_document(key)
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {table}")
                cur.execute(f"INSERT INTO {table} (row_order, data) VALUES (0, %s::jsonb)", (json.dumps(data),))
            conn.commit()
        return data

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
