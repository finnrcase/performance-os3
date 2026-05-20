from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import Response

from backend_new.db import count_rows, fetch_json_rows, fetch_latest_document, insert_json_row, upsert_json_row
from backend_new.utils import utc_now_iso

router = APIRouter(tags=["export"])

BACKUP_DATASETS = {
    "nutrition_log": ("food_logs", "food_log_id"),
    "daily_nutrition_summary": ("daily_nutrition_summary", "date"),
    "nutrition_recommendation_history": ("nutrition_recommendation_history", "recommendation_id"),
    "food_shortcuts": ("food_shortcuts", "shortcut_id"),
    "body_metrics": ("body_metric_logs", "body_metric_id"),
    "raw_hevy_workouts": ("raw_hevy_workouts", "hevy_workout_id"),
    "raw_hevy_sets": ("raw_hevy_sets", "external_id"),
    "training_log": ("workout_logs", "external_id"),
    "recovery_log": ("recovery_logs", "recovery_log_id"),
    "sleep_entries": ("sleep_logs", "id"),
}

BACKUP_DOCUMENTS = {
    "user_settings": "api_connections",
    "user_goals": "user_goal_settings",
    "nutrition_targets": "macro_targets",
    "hevy_sync_state": "integration_sync_state",
    "training_cache_metadata": "training_cache_metadata",
    "training_summary_state": "training_summary_state",
}

EXPORT_ROW_LIMIT = 5000


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def _json_response(payload: dict[str, Any], filename: str) -> Response:
    content = json.dumps(payload, indent=2, sort_keys=True, default=str)
    return Response(
        content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _rows(dataset: str, limit: int = EXPORT_ROW_LIMIT) -> list[dict[str, Any]]:
    table, _ = BACKUP_DATASETS[dataset]
    rows = fetch_json_rows(
        table,
        limit=limit,
        date_field="date" if dataset in {"nutrition_log", "daily_nutrition_summary", "nutrition_recommendation_history", "body_metrics", "training_log", "recovery_log", "sleep_entries"} else None,
    )
    return [row for row in rows if isinstance(row, dict) and "_db_error" not in row]


def _backup_payload() -> dict[str, Any]:
    datasets = {name: _rows(name) for name in BACKUP_DATASETS}
    documents = {name: fetch_latest_document(table, {}) for name, table in BACKUP_DOCUMENTS.items()}
    row_counts = {name: count_rows(table) for name, (table, _) in BACKUP_DATASETS.items()}
    latest_sync = fetch_latest_document("integration_sync_state", {})
    return {
        "schema": "performance-os-backup-v2",
        "generated_at": utc_now_iso(),
        "row_limit_per_dataset": EXPORT_ROW_LIMIT,
        "dataframes": datasets,
        "documents": documents,
        "metadata": {
            "row_counts": row_counts,
            "latest_sync_date": latest_sync.get("last_sync_at") or latest_sync.get("last_synced_at") or "",
            "export_notes": "Explicit backup export reads bounded JSONB tables. Normal page loads do not read all rows.",
        },
    }


def _dedupe_key(row: dict[str, Any], key_field: str) -> str:
    if key_field and row.get(key_field):
        return str(row.get(key_field))
    parts = [str(row.get(field) or "") for field in ("date", "source", "source_id", "external_id", "food_name", "exercise")]
    return "|".join(parts).strip("|")


def _import_dataset(name: str, incoming: Any, *, dry_run: bool, mode: str) -> dict[str, int]:
    if name not in BACKUP_DATASETS or not isinstance(incoming, list):
        return {"incoming_rows": 0, "current_rows_before": 0, "saved_rows": 0, "created_rows": 0, "updated_rows": 0, "skipped_rows": 0, "duplicates_skipped": 0}
    table, key_field = BACKUP_DATASETS[name]
    current_count = count_rows(table).get("count_estimate", 0)
    created = updated = skipped = duplicates = 0
    seen: set[str] = set()
    for raw in incoming[:EXPORT_ROW_LIMIT]:
        if not isinstance(raw, dict):
            skipped += 1
            continue
        key = _dedupe_key(raw, key_field)
        if key and key in seen:
            duplicates += 1
            continue
        if key:
            seen.add(key)
        if dry_run:
            created += 1
            continue
        if mode == "update" and key:
            result = upsert_json_row(table, key_field, key, raw)
            if result.get("_db_error"):
                skipped += 1
            else:
                updated += 1
        else:
            result = insert_json_row(table, raw)
            if result.get("_db_error"):
                skipped += 1
            else:
                created += 1
    return {
        "incoming_rows": len([row for row in incoming if isinstance(row, dict)]),
        "current_rows_before": int(current_count or 0),
        "saved_rows": 0 if dry_run else created + updated,
        "created_rows": created if not dry_run else created,
        "updated_rows": updated,
        "skipped_rows": skipped,
        "duplicates_skipped": duplicates,
    }


async def _import_backup_file(file: UploadFile, *, skip_documents: bool, import_mode: str, dry_run: bool) -> dict[str, Any]:
    raw = await file.read()
    payload = json.loads(raw.decode("utf-8"))
    dataframes = payload.get("dataframes") if isinstance(payload, dict) else {}
    documents = payload.get("documents") if isinstance(payload, dict) else {}
    mode = "update" if import_mode == "update" else "skip"
    dataset_results = {
        name: _import_dataset(name, dataframes.get(name), dry_run=dry_run, mode=mode)
        for name in BACKUP_DATASETS
    }
    documents_imported = 0
    documents_skipped = 0
    if isinstance(documents, dict):
        for name, table in BACKUP_DOCUMENTS.items():
            value = documents.get(name)
            if skip_documents or not isinstance(value, dict):
                documents_skipped += 1
                continue
            if not dry_run:
                insert_json_row(table, {**value, "restored_at": utc_now_iso()})
            documents_imported += 1
    return {
        "status": "ok",
        "datasets": dataset_results,
        "documents_imported": documents_imported,
        "documents_skipped": documents_skipped,
        "skip_documents": skip_documents,
        "import_mode": mode,
        "dry_run": dry_run,
    }


@router.get("/api/export/all")
@router.get("/api/export/full-backup")
def export_all() -> Response:
    return _json_response(_backup_payload(), f"performance-os-backup-{_today()}.json")


@router.post("/api/import/backup")
@router.post("/api/import/full-backup")
async def import_backup(
    file: UploadFile = File(...),
    skip_documents: bool = Query(default=True),
    import_mode: str = Query(default="skip"),
    dry_run: bool = Query(default=False),
) -> dict[str, Any]:
    return await _import_backup_file(file, skip_documents=skip_documents, import_mode=import_mode, dry_run=dry_run)


@router.get("/api/export/daily-csv")
def export_daily_csv(startDate: str | None = None, endDate: str | None = None) -> Response:
    rows = _rows("nutrition_log")
    if startDate:
        rows = [row for row in rows if str(row.get("date") or "") >= startDate]
    if endDate:
        rows = [row for row in rows if str(row.get("date") or "") <= endDate]
    output = io.StringIO()
    fields = sorted({key for row in rows for key in row.keys()}) or ["date", "food_name", "calories", "protein", "carbs", "fat"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="daily-nutrition-{_today()}.csv"'},
    )
