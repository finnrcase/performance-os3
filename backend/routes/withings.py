import logging
import os
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from backend.routes.utils import dataframe_records
from src.body_metrics import load_body_metrics
from src.integrations.withings_client import (
    WithingsIntegrationError,
    build_withings_auth_url,
    exchange_withings_code,
    get_withings_connection_status,
    load_withings_sync_state,
    save_withings_sync_error,
    sync_withings_measurements,
)


router = APIRouter(tags=["withings"])
logger = logging.getLogger(__name__)


def _read_dotenv_value(key: str) -> str:
    from pathlib import Path

    dotenv_path = Path(__file__).resolve().parents[2] / ".env"
    if not dotenv_path.exists():
        return ""
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _withings_redirect_uri(request: Request) -> str:
    configured = os.getenv("WITHINGS_REDIRECT_URI", "").strip() or _read_dotenv_value("WITHINGS_REDIRECT_URI").strip()
    if configured:
        return configured
    origin = request.headers.get("origin", "").strip().rstrip("/")
    if not origin:
        referer = request.headers.get("referer", "").strip()
        if referer:
            parsed = urlparse(referer)
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    app_url = (
        os.getenv("NEXT_PUBLIC_APP_URL", "").strip().rstrip("/")
        or os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
        or _read_dotenv_value("NEXT_PUBLIC_APP_URL").strip().rstrip("/")
        or origin
    )
    if app_url:
        return f"{app_url}/api/withings/callback"
    return str(request.url_for("withings_callback"))


def _frontend_return_url(request: Request, status: str, message: str = "") -> str:
    app_url = (
        os.getenv("NEXT_PUBLIC_APP_URL", "").strip().rstrip("/")
        or os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
        or _read_dotenv_value("NEXT_PUBLIC_APP_URL").strip().rstrip("/")
    )
    if not app_url:
        referer = request.headers.get("referer", "").strip()
        if referer:
            parsed = urlparse(referer)
            app_url = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    if not app_url:
        app_url = str(request.base_url).rstrip("/")
    query = urlencode({"withings": status, "message": message})
    return f"{app_url}/?{query}"


@router.get("/api/withings/connect")
def connect_withings(request: Request):
    redirect_uri = _withings_redirect_uri(request)
    production_like = os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("VERCEL") or os.getenv("RENDER") or os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
    if production_like and "localhost" in redirect_uri:
        return {
            "status": "error",
            "message": "WITHINGS_REDIRECT_URI is still localhost. Set it to your deployed callback URL.",
        }
    try:
        auth_url = build_withings_auth_url(redirect_uri=redirect_uri, state="performance-os")
    except WithingsIntegrationError as exc:
        return {"status": "error", "message": str(exc)}
    return RedirectResponse(auth_url, status_code=303)


@router.get("/api/withings/callback", name="withings_callback")
def withings_callback(
    request: Request,
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    if error:
        message = f"Withings authorization failed: {error}"
        logger.error("Withings OAuth callback failed: %s", error)
        return RedirectResponse(_frontend_return_url(request, "error", message), status_code=303)
    if not code:
        logger.error("Withings OAuth callback missing code.")
        return RedirectResponse(_frontend_return_url(request, "error", "Missing authorization code."), status_code=303)
    try:
        exchange_withings_code(code, _withings_redirect_uri(request))
        logger.info("Withings OAuth callback connected.")
    except WithingsIntegrationError as exc:
        logger.exception("Withings OAuth callback token exchange failed.")
        return RedirectResponse(_frontend_return_url(request, "error", str(exc)), status_code=303)
    return RedirectResponse(_frontend_return_url(request, "connected", "Withings connected."), status_code=303)


@router.get("/api/withings/status")
def withings_status() -> dict:
    return {
        "status": get_withings_connection_status(),
        "sync": load_withings_sync_state(),
    }


@router.post("/api/withings/sync")
def sync_withings_now() -> dict:
    try:
        result = sync_withings_measurements()
    except WithingsIntegrationError as exc:
        return {"status": "error", "message": str(exc), "sync": save_withings_sync_error(str(exc))}
    return {
        **result,
        "items": dataframe_records(load_body_metrics()),
    }
