"""Single clean FastAPI app for the backend rebuild foundation."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend_new.config import SERVICE_NAME, cors_origins
from backend_new.routes import (
    auth,
    body_metrics,
    dashboard,
    debug,
    export,
    goals,
    health,
    integrations,
    nutrition,
    recommendations,
    recovery,
    settings,
    training,
)


app = FastAPI(
    title="Performance OS API New",
    version="0.1.0",
    description="Clean backend rebuild foundation with frontend-compatible route modules.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(health.router)
app.include_router(debug.router)
app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(goals.router)
app.include_router(dashboard.router)
app.include_router(nutrition.router)
app.include_router(recommendations.router)
app.include_router(training.router)
app.include_router(body_metrics.router)
app.include_router(recovery.router)
app.include_router(integrations.router)
app.include_router(export.router)


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}
