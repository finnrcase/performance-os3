"""Single production FastAPI entrypoint for Performance OS."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import SERVICE_NAME, cors_origins
from backend.app.routes import auth, body_metrics, dashboard, debug, export, goals, health, integrations, nutrition, recommendations, recovery, settings, training, withings


app = FastAPI(
    title="Performance OS API",
    version="1.0.0",
    description="Clean FastAPI backend with frontend-compatible route names.",
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
app.include_router(auth.router)
app.include_router(debug.router)
app.include_router(integrations.router)
app.include_router(settings.router)
app.include_router(goals.router)
app.include_router(dashboard.router)
app.include_router(nutrition.router)
app.include_router(body_metrics.router)
app.include_router(recovery.router)
app.include_router(training.router)
app.include_router(recommendations.router)
app.include_router(export.router)
app.include_router(withings.router)


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": SERVICE_NAME}
