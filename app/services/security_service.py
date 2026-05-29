# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import secrets
import time
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config.settings import settings

security = HTTPBasic()

SESSION_COOKIE_NAME = "pcf_session"
SESSION_MAX_AGE_SECONDS = 86400 * 7  # 7 days
OAUTH_STATE_COOKIE_NAME = "pcf_oauth_state"
OAUTH_STATE_MAX_AGE_SECONDS = 600


def _effective_username() -> str:
    """Username to accept; default admin when env is empty."""
    v = (settings.basic_auth_username or "").strip()
    return v if v else "admin"


def _effective_password() -> str:
    """Password to accept; default admin when env is empty."""
    v = (settings.basic_auth_password or "").strip()
    return v if v else "admin"


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.session_secret_key,
        salt="pcf-login-session",
        signer_kwargs={"key_derivation": "hmac", "digest_method": "sha256"},
    )


def _get_oauth_state_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        settings.session_secret_key,
        salt="pcf-oauth-state",
        signer_kwargs={"key_derivation": "hmac", "digest_method": "sha256"},
    )


def create_session_token(
    principal: str,
    *,
    kind: Literal["local", "entra"] = "local",
) -> str:
    """Create a signed session token (*principal* is local username or Microsoft email)."""
    payload = json.dumps(
        {"v": 2, "kind": kind, "principal": principal.strip(), "iat": int(time.time())},
        separators=(",", ":"),
    )
    return _get_serializer().dumps(payload)


def verify_session_token(token: str) -> str | None:
    """Return signed-in principal (username or email) if valid, else None."""
    if not token:
        return None
    try:
        raw = _get_serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, TypeError, ValueError):
        return None

    if isinstance(raw, str) and raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if data.get("v") != 2:
            return None
        kind = data.get("kind")
        principal = (data.get("principal") or "").strip()
        if kind not in ("local", "entra") or not principal:
            return None

        from app.services.user_directory_service import is_user_allowed_to_sign_in

        if kind == "local":
            if not secrets.compare_digest(principal, _effective_username()):
                return None
            return principal
        if not is_user_allowed_to_sign_in(principal):
            return None
        return principal

    # Legacy: username|timestamp
    if isinstance(raw, str) and "|" in raw:
        parts = raw.split("|", 1)
        if len(parts) == 2:
            user = parts[0]
            if user == _effective_username():
                return user
    return None


def sign_oauth_state(nonce: str) -> str:
    return _get_oauth_state_serializer().dumps(nonce)


def verify_oauth_state(token: str) -> str | None:
    try:
        raw = _get_oauth_state_serializer().loads(token, max_age=OAUTH_STATE_MAX_AGE_SECONDS)
    except (BadSignature, TypeError, ValueError):
        return None
    return str(raw) if raw else None


def verify_basic_auth(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> bool:
    """Basic authentication guard for admin endpoints."""

    correct_username = secrets.compare_digest(
        credentials.username, _effective_username()
    )
    correct_password = secrets.compare_digest(
        credentials.password, _effective_password()
    )

    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


def require_session(request: Request) -> str:
    """Dependency: require valid session cookie for config UI; raises 401 if missing/invalid."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not logged in",
        )
    principal = verify_session_token(token)
    if not principal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    return principal


def require_admin_session(request: Request) -> str:
    """Like :func:`require_session` but requires an admin (directory role or bootstrap)."""
    principal = require_session(request)
    from app.services.user_directory_service import is_user_admin

    if not is_user_admin(principal):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required",
        )
    return principal


def client_ip_for_rate_limit(request: Request) -> str:
    """Client identifier for login throttling (direct socket or first X-Forwarded-For if trusted)."""
    if settings.trust_forwarded_headers:
        forwarded = (request.headers.get("x-forwarded-for") or "").strip()
        if forwarded:
            return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def session_cookie_set_kwargs() -> dict[str, Any]:
    """Keyword arguments for Response.set_cookie for the session cookie."""
    return {
        "max_age": SESSION_MAX_AGE_SECONDS,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": bool(settings.session_cookie_secure),
    }


def session_cookie_delete_kwargs() -> dict[str, Any]:
    """Keyword arguments for Response.delete_cookie (must match set_cookie for reliable removal)."""
    return {
        "path": "/",
        "secure": bool(settings.session_cookie_secure),
        "httponly": True,
        "samesite": "lax",
    }


def oauth_state_cookie_set_kwargs() -> dict[str, Any]:
    return {
        "max_age": OAUTH_STATE_MAX_AGE_SECONDS,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
        "secure": bool(settings.session_cookie_secure),
    }


def oauth_state_cookie_delete_kwargs() -> dict[str, Any]:
    return {
        "path": "/",
        "secure": bool(settings.session_cookie_secure),
        "httponly": True,
        "samesite": "lax",
    }
