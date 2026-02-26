"""FastAPI app factory + entry points (uvicorn, AWS Lambda via Mangum).

Concerns are split across:
  - ``app.config.settings`` — Pydantic Settings (single source of truth for env)
  - ``app.core.logging`` — terminal + in-memory ring-buffer logging
  - ``app.core.middleware`` — security headers, error handler, stage-prefix stripping
  - ``app.core.lifespan`` — AAS polling thread
  - ``app.core.static`` — /static and Swagger UI customization
  - ``app.core.stage_prefix`` — ``prepare_static_html_for_stage`` for stage-aware HTML pages
  - ``app.api.routers`` — FastAPI router modules (consumption, production, admin, …)
"""
from __future__ import annotations

import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mangum import Mangum

from app.config.settings import settings
from app.core.lifespan import lifespan
from app.core.logging import configure_logging
from app.core.middleware import install_middleware
from app.core.static import install_static_routes
from app.domain.errors import (
    ConfigurationError,
    DomainValidationError,
    IntegrationError,
    PCFError,
    PipelineSkipped,
)

logger = configure_logging()


_APP_DESCRIPTION = """REST API for production and consumption data, Product Carbon Footprint (PCF) computation, and SiGREEN integration.

**Purpose**

This application ingests consumption data (energy, materials) from MES or AAS (Asset Administration Shell), calculates carbon footprints, and submits PCF reports to SiGREEN. It supports both push-based flows (MES sends data via REST) and pull-based flows (AAS registry discovery and processing).

**Credits**

Developed by **Alireza Ranjbar** within the **Factory-X** project."""


_PCF_ERROR_STATUS_MAP: dict[type[PCFError], int] = {
    DomainValidationError: 400,
    ConfigurationError: 503,
    IntegrationError: 502,
}


def _install_pcf_error_handler(app: FastAPI) -> None:
    """Map every :class:`PCFError` subclass to the right HTTP code with a stable JSON body.

    External clients see ``{"detail": "<message>"}`` with the documented HTTP code; the
    full traceback stays in the server log. :class:`PipelineSkipped` is handled
    separately because it is not actually an error — it is a control-flow signal used
    by the AAS poller and must never reach an HTTP response (the poller catches it).
    """

    @app.exception_handler(PCFError)
    async def _pcf_error_handler(request: Request, exc: PCFError) -> JSONResponse:
        if isinstance(exc, PipelineSkipped):
            # Defensive: should never bubble out of background workers, but if it does,
            # treat it as no-op rather than crashing the request.
            logger.info("PipelineSkipped reached HTTP layer (path=%s): %s", request.url.path, exc)
            return JSONResponse(status_code=204, content=None)

        for cls, status_code in _PCF_ERROR_STATUS_MAP.items():
            if isinstance(exc, cls):
                logger.warning(
                    "%s on %s %s: %s",
                    exc.__class__.__name__, request.method, request.url.path, exc,
                )
                return JSONResponse(status_code=status_code, content={"detail": str(exc)})

        # PCFError raised directly (against the contract); treat as 500 — the original
        # exception is logged with traceback by FastAPI's default exception logging.
        logger.error("PCFError raised directly on %s %s: %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=500, content={"detail": "Internal error"})


def create_app() -> FastAPI:
    """Application factory used for both EC2 and Lambda deployments."""
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=_APP_DESCRIPTION,
        docs_url=None,  # custom /docs with logo and dark theme
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    install_middleware(app)
    install_static_routes(app)
    _install_pcf_error_handler(app)

    # Routers imported lazily so app.main remains importable even when route modules import settings.
    from app.api.routers import (
        admin,
        auth,
        config,
        consumption,
        general_consumption,
        production,
        users_admin,
    )

    app.include_router(consumption.router, prefix="", tags=["consumption"])
    app.include_router(general_consumption.router, prefix="", tags=["general consumption"])
    app.include_router(production.router, prefix="", tags=["production"])
    app.include_router(admin.router, prefix="", tags=["admin"])
    app.include_router(auth.router, prefix="", tags=["auth"])
    app.include_router(users_admin.router, prefix="", tags=["admin-users"])
    app.include_router(config.router, prefix="", tags=["config"])
    return app


app = create_app()
handler = Mangum(app)  # AWS Lambda


def _run_server() -> None:
    """Serve on a single port (``port_https``, default 8443): TLS when cert/key exist, else plain HTTP."""
    port = settings.port_https
    cert = Path(settings.ssl_certfile).expanduser() if settings.ssl_certfile else None
    key = Path(settings.ssl_keyfile).expanduser() if settings.ssl_keyfile else None
    use_tls = (
        cert is not None
        and key is not None
        and cert.is_file()
        and key.is_file()
    )
    if use_tls:
        logger.info("Serving HTTPS on port %s", port)
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            reload=False,
        )
    else:
        logger.warning(
            "SSL_CERTFILE/SSL_KEYFILE missing or not found; serving HTTP (not TLS) on port %s",
            port,
        )
        uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)


__all__ = ["app", "create_app", "handler", "logger", "settings"]


if __name__ == "__main__":  # pragma: no cover
    _run_server()
