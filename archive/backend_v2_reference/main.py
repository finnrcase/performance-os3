"""Stable FastAPI backend v2 for lightweight startup and dashboard routes."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend_v2.config import SERVICE_NAME, cors_origins
from backend_v2.routes import dashboard_core, debug, goals, health, nutrition, settings, training


app = FastAPI(
    title="Performance OS API v2",
    version="0.1.0",
    description="Stable lightweight backend for Performance OS core routes.",
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
app.include_router(settings.router)
app.include_router(goals.router)
app.include_router(dashboard_core.router)
app.include_router(nutrition.router)
app.include_router(training.router)


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}

