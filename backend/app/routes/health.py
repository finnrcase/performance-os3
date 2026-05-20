from fastapi import APIRouter

from backend.app.core.config import SERVICE_NAME, database_url


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "storage": "postgres" if database_url() else "not_configured",
    }

