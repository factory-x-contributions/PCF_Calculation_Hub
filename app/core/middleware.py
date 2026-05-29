# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Application middleware: stage-prefix stripping, security headers, global error handler, validation logging."""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette import status

from app.config.settings import settings

logger = logging.getLogger("pcf_creator_app")


class ErrorResponse(BaseModel):
    detail: str


class ValidationErrorResponse(BaseModel):
    detail: str
    errors: list[dict]


def install_middleware(app: FastAPI) -> None:
    """Attach all HTTP middleware and exception handlers to *app*."""

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        """Log raw body alongside 422 errors so misformed clients can be debugged from CloudWatch."""
        raw_body: str | None = None
        try:
            body_bytes = await request.body()
            if body_bytes:
                raw_body = body_bytes.decode("utf-8", errors="replace")[:16384]
        except Exception as read_err:
            raw_body = f"<unreadable: {read_err}>"
        logger.warning(
            "Request validation failed (422): %s %s | errors=%s | raw_body=%s | exc.body=%s",
            request.method, request.url.path,
            json.dumps(exc.errors(), ensure_ascii=False), raw_body, getattr(exc, "body", None),
        )
        content: dict[str, Any] = ValidationErrorResponse(
            detail="Request validation failed", errors=exc.errors(),
        ).model_dump()
        if raw_body:
            content["received_body_preview"] = raw_body[:4096]
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=content)

    @app.middleware("http")
    async def _strip_stage(request: Request, call_next: Callable):
        """Behind API Gateway with a stage (e.g. /dev), strip the stage prefix so route matching works."""
        path = request.scope.get("path", "")
        stage_prefix_str = f"/{settings.environment}/"
        if settings.environment != "local" and path.startswith(stage_prefix_str):
            request.scope["path"] = "/" + path[len(stage_prefix_str):].lstrip("/") or "/"
        return await call_next(request)

    @app.middleware("http")
    async def _global_errors(request: Request, call_next: Callable):
        try:
            return await call_next(request)
        except Exception:
            logger.exception("Unhandled application error", extra={"path": str(request.url)})
            return JSONResponse(status_code=500, content=ErrorResponse(detail="Internal server error").model_dump())

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Callable):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response
