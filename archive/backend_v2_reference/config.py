"""Configuration for the stable backend v2 service."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env", override=False)


SERVICE_NAME = "performance-os-api-v2"
DEFAULT_CONNECT_TIMEOUT_SECONDS = int(os.getenv("BACKEND_V2_DB_CONNECT_TIMEOUT_SECONDS", "5"))
DEFAULT_STATEMENT_TIMEOUT_MS = int(os.getenv("BACKEND_V2_DB_STATEMENT_TIMEOUT_MS", "1500"))
MAX_STATEMENT_TIMEOUT_MS = 120_000


def database_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


def cors_origins() -> list[str]:
    configured = ",".join(
        value
        for value in [
            os.getenv("CORS_ALLOW_ORIGINS", ""),
            os.getenv("FRONTEND_ORIGIN", ""),
            os.getenv("NEXT_PUBLIC_APP_URL", ""),
            f"https://{os.getenv('VERCEL_URL', '').strip()}" if os.getenv("VERCEL_URL", "").strip() else "",
        ]
        if value
    )
    origins = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "https://performance-os-rho.vercel.app",
    ]
    if configured:
        origins.extend(origin.strip() for origin in configured.split(",") if origin.strip())
    return origins
