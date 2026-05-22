from __future__ import annotations

from datetime import date, datetime, timezone
import math
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from backend_new.db import (
    delete_json_row,
    fetch_json_rows,
    fetch_json_rows_for_value,
    fetch_latest_document,
    invalidate_dashboard_core_cache,
    insert_json_row,
    upsert_json_row,
)
from backend_new.utils import app_today_iso, utc_now_iso
from src.body_metrics import canonical_bodyweight_debug, canonical_daily_bodyweights

router = APIRouter(tags=["body-metrics"])

NUMERIC_FIELDS = (
    "bodyweight",
    "waist",
    "estimated_body_fat",
    "body_fat_percent",
    "lean_mass",
    "fat_mass",
    "muscle_mass",
    "hydration",
    "bmi",
)

MEASUREMENT_TIME_FIELDS = (
    "measured_at",
    "measurement_at",
    "measured_timestamp",
    "timestamp",
    "recorded_at",
)


def _today_iso() -> str:
    return app_today_iso()


def _number_or_none(value: Any) -> float | None:
    if value in {"", None}:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _metric_id(item: dict[str, Any]) -> str:
    for field in ("body_metric_id", "id", "source_id"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return str(item.get("date") or uuid4())


def _is_excluded(item: dict[str, Any]) -> bool:
    return item.get("excluded_from_analytics") is True or str(item.get("excluded_from_analytics") or "").lower() in {"true", "1", "yes"}


def _normalize_metric(payload: dict[str, Any], *, body_metric_id: str | None = None, partial: bool = False) -> dict[str, Any]:
    now = utc_now_iso()
    item = dict(payload)
    item["body_metric_id"] = body_metric_id or str(item.get("body_metric_id") or item.get("id") or item.get("source_id") or uuid4())
    item["id"] = item["body_metric_id"]
    if not partial or "date" in item:
        item["date"] = str(item.get("date") or _today_iso())
    for field in NUMERIC_FIELDS:
        if field in item:
            item[field] = _number_or_none(item.get(field))
    body_fat = item.get("body_fat_percent")
    estimated = item.get("estimated_body_fat")
    if body_fat is None and estimated is not None:
        item["body_fat_percent"] = estimated
    if estimated is None and body_fat is not None:
        item["estimated_body_fat"] = body_fat
    item["source"] = str(item.get("source") or "manual")
    item.setdefault("source_id", "")
    item.setdefault("notes", "")
    item.setdefault("created_at", now)
    item["updated_at"] = now
    return item


def _public_metric(item: dict[str, Any]) -> dict[str, Any]:
    public = _normalize_metric(item, body_metric_id=_metric_id(item), partial=True)
    public.setdefault("date", str(item.get("date") or ""))
    public.setdefault("bodyweight", _number_or_none(item.get("bodyweight")))
    public.setdefault("waist", _number_or_none(item.get("waist")))
    public.setdefault("notes", str(item.get("notes") or ""))
    return public


def _sort_by_date(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda row: str(row.get("date") or ""))


def _settings_document() -> dict[str, Any]:
    stored = fetch_latest_document("api_connections", {"integrations": {}, "metadata": {}})
    if not isinstance(stored, dict):
        return {"integrations": {}, "metadata": {}}
    stored.setdefault("integrations", {})
    stored.setdefault("metadata", {})
    return stored


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        return None


def _measurement_timestamp_text(row: dict[str, Any]) -> str:
    for field in MEASUREMENT_TIME_FIELDS:
        value = row.get(field)
        if value:
            return str(value)
    notes = str(row.get("notes") or "")
    for part in notes.split("|"):
        part = part.strip()
        if part.startswith("measured_at="):
            return part.split("=", 1)[1].strip()
    for field in ("created_at", "updated_at"):
        value = row.get(field)
        if value:
            return str(value)
    return str(row.get("date") or "")


def _measurement_timestamp(row: dict[str, Any]) -> tuple[datetime | None, str]:
    text = _measurement_timestamp_text(row)
    parsed = _parse_iso_timestamp(text)
    if parsed is None and row.get("date"):
        parsed = _parse_iso_timestamp(f"{str(row.get('date'))[:10]}T00:00:00")
    return parsed, text


def _withings_connected(settings: dict[str, Any]) -> bool:
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    tokens = metadata.get("withings_tokens") if isinstance(metadata.get("withings_tokens"), dict) else {}
    sync = metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}
    return bool((tokens.get("refresh_token") or tokens.get("access_token")) and not sync.get("needs_reconnect"))


def _latest_raw_weight(rows: list[dict[str, Any]]) -> tuple[str, float | None]:
    latest_key: datetime | None = None
    latest_text = ""
    latest_weight: float | None = None
    for row in rows:
        if _is_excluded(row):
            continue
        bodyweight = _number_or_none(row.get("bodyweight"))
        if bodyweight is None or bodyweight <= 0:
            continue
        parsed, text = _measurement_timestamp(row)
        if latest_key is None or (parsed is not None and parsed > latest_key):
            latest_key = parsed
            latest_text = text
            latest_weight = bodyweight
    return latest_text, latest_weight


def body_metric_freshness_debug(
    rows: list[dict[str, Any]],
    *,
    cache_invalidated: bool = False,
) -> dict[str, Any]:
    clean_rows = [row for row in rows if isinstance(row, dict) and "_db_error" not in row]
    analytics_rows = [row for row in clean_rows if not _is_excluded(row)]
    debug = canonical_bodyweight_debug(clean_rows)
    canonical_items = _canonical_public_metrics(analytics_rows)
    latest_canonical = canonical_items[-1] if canonical_items else {}
    latest_raw_measurement_at, latest_raw_weight = _latest_raw_weight(clean_rows)
    settings = _settings_document()
    metadata = settings.get("metadata") if isinstance(settings.get("metadata"), dict) else {}
    sync = metadata.get("withings_sync") if isinstance(metadata.get("withings_sync"), dict) else {}
    return {
        "withings_connected": _withings_connected(settings),
        "last_withings_sync_at": sync.get("last_synced_at", ""),
        "raw_body_metric_rows": debug.get("raw_body_metric_rows", len(clean_rows)),
        "latest_raw_measurement_at": latest_raw_measurement_at,
        "latest_raw_weight": latest_raw_weight,
        "canonical_daily_rows": debug.get("canonical_daily_weight_rows", len(canonical_items)),
        "latest_canonical_date": latest_canonical.get("date", ""),
        "latest_canonical_weight": latest_canonical.get("bodyweight"),
        "dates_with_multiple_weighins": debug.get("dates_with_multiple_weighins", 0),
        "dropped_invalid_rows": debug.get("dropped_invalid_rows", 0),
        "cache_invalidated": cache_invalidated,
        "rule": "lowest_weight_per_day",
    }


def persist_withings_rows_to_body_metric_logs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    persisted = 0
    errors: list[dict[str, Any]] = []
    earliest = ""
    latest = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "").strip()
        if not source_id:
            continue
        payload = {
            **row,
            "body_metric_id": str(row.get("body_metric_id") or source_id),
            "id": str(row.get("id") or row.get("body_metric_id") or source_id),
            "source": "withings",
            "updated_at": utc_now_iso(),
        }
        saved = upsert_json_row("body_metric_logs", "source_id", source_id, payload)
        if isinstance(saved, dict) and saved.get("_db_error"):
            errors.append({"source_id": source_id, "error": saved.get("_db_error")})
            continue
        persisted += 1
        row_date = str(payload.get("date") or "")[:10]
        if row_date:
            earliest = min([value for value in (earliest, row_date) if value], default=row_date)
            latest = max(latest, row_date)
    invalidate_dashboard_core_cache()
    return {
        "db_persisted_rows": persisted,
        "db_persist_errors": errors[:5],
        "db_persist_error_count": len(errors),
        "earliest_db_date": earliest,
        "latest_db_date": latest,
        "cache_invalidated": True,
    }


def withings_body_metric_sync_response(result: dict[str, Any], *, items_limit: int) -> dict[str, Any]:
    measurement_rows = result.pop("_measurement_rows", []) if isinstance(result.get("_measurement_rows"), list) else []
    persist_result = persist_withings_rows_to_body_metric_logs(measurement_rows)
    rows = fetch_json_rows("body_metric_logs", limit=items_limit, date_field="date")
    clean_rows = rows if not (rows and "_db_error" in rows[0]) else []
    analytics_rows = [row for row in clean_rows if not _is_excluded(row)]
    canonical_items = _canonical_public_metrics(analytics_rows)
    return {
        **result,
        **persist_result,
        "items": canonical_items,
        "canonical_items": canonical_items,
        "raw_items": _sort_by_date([_public_metric(row) for row in analytics_rows]),
        "freshness": body_metric_freshness_debug(clean_rows, cache_invalidated=True),
    }


def _withings_sync_error(message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "message": message,
        "imported_measurements": 0,
        "fetched_groups": 0,
        "latest_measure_date": "",
        "last_synced_at": "",
        "freshness": body_metric_freshness_debug(fetch_json_rows("body_metric_logs", limit=1000, date_field="date")),
    }


def _canonical_public_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    canonical = canonical_daily_bodyweights(rows)
    if canonical.empty:
        return []
    records = canonical.to_dict(orient="records")
    items = []
    for row in records:
        item = _public_metric(row)
        try:
            item["date"] = row["date"].date().isoformat()
        except Exception:
            item["date"] = str(row.get("date") or "")
        item["canonical_rule"] = "lowest_weight_per_day"
        items.append(item)
    return _sort_by_date(items)


def _body_comp_trends(items: list[dict[str, Any]]) -> dict[str, Any]:
    if not items:
        return {
            "windows": {},
            "summary": "No canonical body-composition data yet.",
            "confidence": {"body_comp": "low", "missing_data": ["No canonical bodyweight/body-composition rows available."]},
        }
    latest_date = str(items[-1].get("date") or "")
    windows: dict[str, Any] = {}
    missing: list[str] = []
    try:
        latest_day = date.fromisoformat(latest_date[:10])
    except ValueError:
        latest_day = date.fromisoformat(app_today_iso())
    fields = ("bodyweight", "body_fat_percent", "lean_mass", "fat_mass", "muscle_mass")
    for days in (7, 14, 28):
        cutoff = (latest_day.toordinal() - days)
        window_rows = []
        for item in items:
            try:
                item_day = date.fromisoformat(str(item.get("date") or "")[:10])
            except ValueError:
                continue
            if item_day.toordinal() >= cutoff:
                window_rows.append(item)
        changes: dict[str, float | None] = {}
        for field in fields:
            values = [(_number_or_none(row.get(field)), row) for row in window_rows if _number_or_none(row.get(field)) is not None]
            if len(values) >= 2 and values[0][0] is not None and values[-1][0] is not None:
                changes[f"{field}_change"] = round(float(values[-1][0]) - float(values[0][0]), 2)
            else:
                changes[f"{field}_change"] = None
        windows[f"{days}d"] = {
            "days": days,
            "data_points": len(window_rows),
            **changes,
        }
    body_comp_points = sum(1 for item in items if _number_or_none(item.get("body_fat_percent")) is not None or _number_or_none(item.get("lean_mass")) is not None)
    if body_comp_points < 4:
        missing.append("Need more Withings/body-composition rows for reliable lean-mass and fat-mass trends.")
    confidence = "high" if body_comp_points >= 14 else "medium" if body_comp_points >= 6 else "low"
    recent_28 = windows.get("28d", {})
    lean_change = recent_28.get("lean_mass_change")
    fat_change = recent_28.get("fat_mass_change")
    summary_parts = []
    if lean_change is not None:
        summary_parts.append(f"lean mass {lean_change:+.2f} lb over 28d")
    if fat_change is not None:
        summary_parts.append(f"fat mass {fat_change:+.2f} lb over 28d")
    return {
        "windows": windows,
        "summary": "; ".join(summary_parts) if summary_parts else "Bodyweight is canonical; body-composition trend confidence is limited.",
        "confidence": {
            "body_comp": confidence,
            "data_points": body_comp_points,
            "missing_data": missing,
            "rule": "lowest_weight_per_day",
        },
    }


def _find_metric(metric_id: str) -> dict[str, Any] | None:
    for field in ("body_metric_id", "id", "source_id"):
        rows = fetch_json_rows_for_value("body_metric_logs", field, metric_id, limit=1)
        if rows and "_db_error" not in rows[0]:
            return rows[0]
    return None


@router.get("/api/body-metrics")
def get_body_metrics(limit: int = 5000) -> dict[str, Any]:
    rows = fetch_json_rows("body_metric_logs", limit=limit, date_field="date")
    if rows and "_db_error" in rows[0]:
        return {"items": [], "status": "error", "error": rows[0]["_db_error"]}
    analytics_rows = [row for row in rows if not _is_excluded(row)]
    raw_items = _sort_by_date([_public_metric(row) for row in analytics_rows])
    canonical_items = _canonical_public_metrics(analytics_rows)
    debug = canonical_bodyweight_debug(rows)
    return {
        "items": canonical_items,
        "canonical_items": canonical_items,
        "raw_items": raw_items,
        "body_comp_trends": _body_comp_trends(canonical_items),
        "excluded_raw_count": len(rows) - len(analytics_rows),
        "raw_body_metric_rows": debug.get("raw_body_metric_rows", len(rows)),
        "canonical_daily_weight_rows": debug.get("canonical_daily_weight_rows", len(canonical_items)),
        "date_min": debug.get("date_min", ""),
        "date_max": debug.get("date_max", ""),
        "rule": "lowest_weight_per_day",
        "status": "ok",
        "debug": debug,
        "freshness": body_metric_freshness_debug(rows),
    }


@router.post("/api/body-metrics/sync/withings")
def sync_body_metrics_withings(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    history = bool(payload.get("history"))
    try:
        from src.integrations.withings_client import DEFAULT_HISTORY_SYNC_DAYS, sync_withings_measurements

        result = sync_withings_measurements(
            days=payload.get("days") or (DEFAULT_HISTORY_SYNC_DAYS if history else None),
            start_date=payload.get("start_date"),
            end_date=payload.get("end_date"),
            history=history,
            include_rows=True,
        )
    except Exception as exc:
        return _withings_sync_error(str(exc))
    return withings_body_metric_sync_response(result, items_limit=5000 if history else 1000)


@router.post("/api/body-metrics")
def post_body_metric(payload: dict[str, Any]) -> dict[str, Any]:
    item = insert_json_row("body_metric_logs", _normalize_metric(payload))
    items = get_body_metrics()["items"]
    return {"item": _public_metric(item), "items": items, "status": "ok"}


@router.put("/api/body-metrics/{body_metric_id}")
def put_body_metric(body_metric_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = _find_metric(body_metric_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Body metric not found")
    key = "body_metric_id" if existing.get("body_metric_id") else "source_id" if existing.get("source_id") else "id"
    item = upsert_json_row("body_metric_logs", key, body_metric_id, _normalize_metric({**existing, **payload}, body_metric_id=body_metric_id, partial=True))
    return {"item": _public_metric(item), "status": "ok"}


@router.delete("/api/body-metrics/{body_metric_id}")
def delete_body_metric(body_metric_id: str) -> dict[str, Any]:
    deleted = 0
    errors = []
    for field in ("body_metric_id", "id", "source_id"):
        result = delete_json_row("body_metric_logs", field, body_metric_id)
        if result.get("status") == "error":
            errors.append(result)
        deleted += int(result.get("deleted") or 0)
        if deleted:
            break
    if errors and not deleted:
        raise HTTPException(status_code=500, detail=errors[0])
    return {"status": "ok", "deleted": deleted}
