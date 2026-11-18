"""FastAPI application entrypoint — API + server-rendered dashboard."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.api.auth_routes import router as auth_router
from app.api.dashboard_routes import router as dashboard_router
from app.api.fill_routes import router as fill_router
from app.api.schedule_routes import router as schedule_router
from app.api.template_routes import router as template_router
from app.api.timesheet_routes import health_router, router as timesheet_router
from app.clients.exceptions import (
    RepliconAPIError,
    RepliconAuthError,
    RepliconConnectionError,
    RepliconInvalidResponseError,
    RepliconNotFoundError,
    RepliconRateLimitError,
    RepliconTimeoutError,
    TimeEntryValidationError,
)
from app.config import get_settings
from app.db.session import init_db
from app.services.scheduler_service import shutdown_scheduler, start_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    try:
        start_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("scheduler_start_failed")
    yield
    try:
        shutdown_scheduler()
    except Exception:  # noqa: BLE001
        logger.exception("scheduler_shutdown_failed")


app = FastAPI(
    title=get_settings().app_name,
    description=(
        "Self-serve Replicon timesheet dashboard: each user registers, stores "
        "their own token once, configures fill templates, runs fills from the UI, "
        "and optionally schedules them. Legacy JSON timesheet endpoints remain "
        "under /timesheets for debugging."
    ),
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie=settings.session_cookie_name,
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=False,
)

_static_dir = Path(__file__).resolve().parent / "web" / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(fill_router)
app.include_router(template_router)
app.include_router(schedule_router)
app.include_router(timesheet_router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Turn auth redirects into browser Location redirects for HTML pages."""
    location = (exc.headers or {}).get("Location")
    if location and exc.status_code in {303, 307, 401, 403}:
        accepts = request.headers.get("accept", "")
        if "text/html" in accepts or request.url.path in {"/", "/setup"}:
            return RedirectResponse(location, status_code=303)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


def _map_replicon_error(exc: RepliconAPIError) -> tuple[int, dict[str, Any]]:
    if isinstance(exc, RepliconAuthError):
        http_status = 401 if exc.status_code == 401 else 403
        return http_status, {
            "detail": {
                **exc.to_detail(),
                "message": exc.message
                or (
                    "Replicon authentication/authorization failed. The access token "
                    "may be valid but lack the required permission for this operation."
                ),
            }
        }

    if isinstance(exc, RepliconNotFoundError):
        return 404, {"detail": exc.to_detail()}

    if isinstance(exc, RepliconRateLimitError):
        return 429, {"detail": exc.to_detail()}

    if isinstance(exc, (RepliconTimeoutError, RepliconConnectionError)):
        return 504, {"detail": exc.to_detail()}

    if isinstance(exc, RepliconInvalidResponseError):
        return 502, {"detail": exc.to_detail()}

    if exc.status_code == 400:
        return 400, {
            "detail": {
                **exc.to_detail(),
                "message": exc.message or "Replicon rejected the request as invalid",
            }
        }

    if exc.status_code is not None and 400 <= exc.status_code < 500:
        return 502, {
            "detail": {
                **exc.to_detail(),
                "message": exc.message or "Replicon API request failed",
            }
        }

    return 502, {
        "detail": {
            **exc.to_detail(),
            "message": exc.message or "Replicon API request failed",
        }
    }


@app.exception_handler(TimeEntryValidationError)
async def time_entry_validation_error_handler(
    _request: Request,
    exc: TimeEntryValidationError,
) -> JSONResponse:
    logger.warning(
        "time_entry_validation_error: %s",
        exc.message,
        extra={"details": exc.details},
    )
    return JSONResponse(
        status_code=400,
        content={
            "detail": {
                "message": exc.message,
                "error_type": "validation_error",
                "details": exc.details,
            }
        },
    )


@app.exception_handler(RepliconAPIError)
async def replicon_api_error_handler(
    _request: Request,
    exc: RepliconAPIError,
) -> JSONResponse:
    status_code, body = _map_replicon_error(exc)
    logger.error(
        "replicon_api_error",
        extra={
            "error_type": exc.error_type,
            "service": exc.service,
            "operation": exc.operation,
            "upstream_status": exc.status_code,
            "http_status": status_code,
        },
    )
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    logger.error("configuration_error: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": {
                "message": str(exc),
                "error_type": "configuration_error",
                "hint": (
                    "For the dashboard, register and configure your personal "
                    "Replicon token on /setup. For legacy JSON routes, set "
                    "REPLICON_ACCESS_TOKEN in .env."
                ),
            }
        },
    )
