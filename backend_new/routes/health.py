from __future__ import annotations

from fastapi import APIRouter

from backend_new.config import SERVICE_NAME, environment, storage_name


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "environment": environment(),
        "storage": storage_name(),
    }

