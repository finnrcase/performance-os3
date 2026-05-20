from fastapi import APIRouter
from pydantic import BaseModel

from backend.routes.utils import dataframe_records
from src.body_metrics import add_body_metric_entry, load_body_metrics


router = APIRouter(tags=["body_metrics"])


@router.get("/status")
def status() -> dict:
    """Return placeholder route status."""
    return {"status": "placeholder", "module": "body_metrics"}


class BodyMetricEntry(BaseModel):
    date: str
    bodyweight: float
    waist: float | None = None
    estimated_body_fat: float | None = None
    body_fat_percent: float | None = None
    lean_mass: float | None = None
    fat_mass: float | None = None
    muscle_mass: float | None = None
    hydration: float | None = None
    bmi: float | None = None
    notes: str = ""


@router.get("/api/body-metrics")
def get_body_metrics() -> dict:
    """Return saved body metrics."""
    return {"items": dataframe_records(load_body_metrics())}


@router.post("/api/body-metrics")
def add_body_metrics(entry: BodyMetricEntry) -> dict:
    """Add a local body metric entry."""
    metrics_df = add_body_metric_entry(**entry.model_dump())
    return {"items": dataframe_records(metrics_df)}
