from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter

from backend.app.core.database import insert_row, load_all_rows


router = APIRouter(tags=["body-metrics"])


@router.get("/api/body-metrics")
def get_body_metrics(limit: int = 365) -> dict:
    return {"items": load_all_rows("body_metrics", limit=limit, timeout_ms=1000)}


@router.post("/api/body-metrics")
def create_body_metric(payload: dict) -> dict:
    item = {**payload, "metric_id": payload.get("metric_id") or f"metric_{uuid4().hex[:12]}"}
    return {"item": insert_row("body_metrics", item, timeout_ms=1000)}

