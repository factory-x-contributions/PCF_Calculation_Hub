"""Admin API for the Microsoft sign-in user directory."""
from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.security_service import require_admin_session
from app.services.user_directory_service import (
    list_directory_users,
    normalize_email,
    remove_directory_user,
    upsert_directory_user,
)

logger = logging.getLogger("pcf_creator_app")

router = APIRouter(prefix="/api/admin", tags=["admin-users"])


class UserUpsertBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: Literal["admin", "user"] = "user"


@router.get("/users")
def list_users(
    _: Annotated[str, Depends(require_admin_session)],
) -> JSONResponse:
    return JSONResponse(content={"users": list_directory_users()})


@router.post("/users")
def add_or_update_user(
    body: UserUpsertBody,
    principal: Annotated[str, Depends(require_admin_session)],
) -> JSONResponse:
    try:
        row = upsert_directory_user(
            body.email,
            role=body.role,
            created_by=principal,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    logger.info("User directory updated by %s: email=%s role=%s", principal, row.get("email"), row.get("role"))
    return JSONResponse(content={"user": row})


@router.delete("/users/{email:path}")
def delete_user(
    email: str,
    principal: Annotated[str, Depends(require_admin_session)],
) -> JSONResponse:
    norm = normalize_email(email)
    if not norm:
        return JSONResponse(status_code=400, content={"detail": "Invalid email"})
    if not remove_directory_user(norm):
        return JSONResponse(status_code=404, content={"detail": "User not found"})
    logger.info("User directory entry removed by %s: email=%s", principal, norm)
    return JSONResponse(content={"status": "ok", "deleted": norm})
