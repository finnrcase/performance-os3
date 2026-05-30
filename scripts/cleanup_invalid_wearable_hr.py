#!/usr/bin/env python3
"""Clean invalid wearable heart-rate values from local/DB wearable storage.

Defaults to dry-run. Use --apply to persist cleaned rows.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend_new.db import fetch_json_rows, upsert_json_row
from src.wearables import (
    WEARABLE_HEART_RATE_COLUMNS,
    clean_heart_rate_value,
    clean_hrv_value,
    load_wearable_metrics,
    normalize_wearable_metric_rows,
    save_wearable_metrics,
)


DB_TABLES = {
    "wearable_metrics": "metric_id",
    "google_health_daily_summary": "summary_id",
    "google_health_heart": "heart_id",
    "google_health_recovery_signals": "signal_id",
}
HRV_FIELDS = {"hrv"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _clean_record(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    cleaned = dict(record)
    counts = {"invalid_hr_values_nulled": 0, "invalid_hrv_values_nulled": 0, "changed": 0}
    for field in WEARABLE_HEART_RATE_COLUMNS:
        if field not in cleaned:
            continue
        before = cleaned.get(field)
        if before in (None, ""):
            continue
        after = clean_heart_rate_value(before)
        if after is None:
            cleaned[field] = None
            counts["invalid_hr_values_nulled"] += 1
            counts["changed"] += 1
        elif after != before:
            cleaned[field] = after
            counts["changed"] += 1
    for field in HRV_FIELDS:
        if field not in cleaned:
            continue
        before = cleaned.get(field)
        if before in (None, ""):
            continue
        after = clean_hrv_value(before)
        if after is None:
            cleaned[field] = None
            counts["invalid_hrv_values_nulled"] += 1
            counts["changed"] += 1
        elif after != before:
            cleaned[field] = after
            counts["changed"] += 1
    if "resting_hr_deviation" in cleaned and (
        clean_heart_rate_value(cleaned.get("resting_hr")) is None
        or clean_heart_rate_value(cleaned.get("resting_hr_baseline")) is None
    ):
        if cleaned.get("resting_hr_deviation") is not None:
            cleaned["resting_hr_deviation"] = None
            counts["changed"] += 1
    return cleaned, counts


def _recompute_resting_hr_baselines(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        source = _text(row.get("provider") or row.get("source") or "unknown")
        grouped[source].append(row)
    recomputed: list[dict[str, Any]] = []
    for _, items in grouped.items():
        history: list[float] = []
        for row in sorted(items, key=lambda item: _text(item.get("date"))):
            cleaned = dict(row)
            rhr = clean_heart_rate_value(cleaned.get("resting_hr"))
            cleaned["resting_hr"] = rhr
            baseline_values = history[-7:]
            if rhr is not None and len(baseline_values) >= 3:
                baseline = round(sum(baseline_values) / len(baseline_values), 1)
                cleaned["resting_hr_baseline"] = baseline
                cleaned["resting_hr_deviation"] = round(rhr - baseline, 1)
            else:
                cleaned["resting_hr_baseline"] = None
                cleaned["resting_hr_deviation"] = None
            if rhr is not None:
                history.append(float(rhr))
            recomputed.append(cleaned)
    return recomputed


def _recompute_recovery_signal_rows(rows: list[dict[str, Any]], heart_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    heart_by_date = {_text(row.get("date"))[:10]: row for row in heart_rows if _text(row.get("date"))}
    recomputed: list[dict[str, Any]] = []
    for row in rows:
        cleaned = dict(row)
        day = _text(cleaned.get("date"))[:10]
        heart = heart_by_date.get(day, {})
        deviation = _num(heart.get("resting_hr_deviation"))
        if deviation is None:
            cleaned["resting_hr_deviation"] = None
        else:
            cleaned["resting_hr_deviation"] = round(deviation, 1)
        spo2 = _num(cleaned.get("spo2"))
        breathing_rate = _num(cleaned.get("breathing_rate"))
        skin_temperature = _num(cleaned.get("skin_temperature"))
        body_temperature = _num(cleaned.get("body_temperature"))
        sickness_warning = bool(
            (spo2 is not None and spo2 < 94)
            or (breathing_rate is not None and breathing_rate >= 22)
            or (skin_temperature is not None and 1 <= abs(skin_temperature) <= 5)
            or (body_temperature is not None and body_temperature >= 37.8)
        )
        cleaned["sickness_warning"] = sickness_warning
        cleaned["recovery_warning"] = bool(sickness_warning or (deviation is not None and deviation >= 5))
        recomputed.append(cleaned)
    return recomputed


def _clean_db_table(table: str, key_field: str, *, apply: bool) -> dict[str, Any]:
    rows = fetch_json_rows(table, limit=5000, date_field="date")
    if rows and isinstance(rows[0], dict) and "_db_error" in rows[0]:
        return {"table": table, "status": "error", "error": rows[0].get("_db_error"), "rows_checked": 0, "rows_changed": 0}
    cleaned_rows = []
    totals = {"table": table, "status": "dry_run" if not apply else "applied", "rows_checked": len(rows), "rows_changed": 0, "invalid_hr_values_nulled": 0, "invalid_hrv_values_nulled": 0}
    for row in rows:
        cleaned, counts = _clean_record(dict(row))
        cleaned_rows.append(cleaned)
        totals["invalid_hr_values_nulled"] += counts["invalid_hr_values_nulled"]
        totals["invalid_hrv_values_nulled"] += counts["invalid_hrv_values_nulled"]
        if counts["changed"]:
            totals["rows_changed"] += 1
    if table in {"wearable_metrics", "google_health_daily_summary", "google_health_heart"}:
        cleaned_rows = _recompute_resting_hr_baselines(cleaned_rows)
    if table == "google_health_recovery_signals":
        heart_rows = fetch_json_rows("google_health_heart", limit=5000, date_field="date")
        if not (heart_rows and isinstance(heart_rows[0], dict) and "_db_error" in heart_rows[0]):
            heart_rows = _recompute_resting_hr_baselines([_clean_record(dict(row))[0] for row in heart_rows])
            cleaned_rows = _recompute_recovery_signal_rows(cleaned_rows, heart_rows)
    if apply:
        for row in cleaned_rows:
            key_value = _text(row.get(key_field))
            if key_value:
                upsert_json_row(table, key_field, key_value, row)
    return totals


def _clean_local_csv(*, apply: bool) -> dict[str, Any]:
    raw = load_wearable_metrics()
    cleaned = normalize_wearable_metric_rows(raw)
    result = {
        "table": "local_csv:wearable_metrics",
        "status": "dry_run" if not apply else "applied",
        "rows_checked": int(len(raw)),
        "rows_changed": int((raw.astype(str) != cleaned.astype(str)).any(axis=1).sum()) if len(raw) == len(cleaned) else int(len(raw)),
    }
    if apply:
        save_wearable_metrics(cleaned)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Null invalid wearable HR values and recompute HR-derived baselines.")
    parser.add_argument("--apply", action="store_true", help="Persist cleanup changes. Without this flag, runs as dry-run.")
    parser.add_argument("--skip-local-csv", action="store_true", help="Skip processed_data wearable_metrics.csv cleanup.")
    args = parser.parse_args()

    results = []
    for table, key_field in DB_TABLES.items():
        results.append(_clean_db_table(table, key_field, apply=args.apply))
    if not args.skip_local_csv:
        results.append(_clean_local_csv(apply=args.apply))
    for result in results:
        print(result)
    print("Dashboard readiness, sickness warning, and recovery confidence recalculate from cleaned wearable rows on next API read.")


if __name__ == "__main__":
    main()
