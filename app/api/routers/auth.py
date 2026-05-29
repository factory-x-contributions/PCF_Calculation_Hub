# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config.settings import settings
from app.core.protected_pages import _read_static_html, login_redirect
from app.core.stage_prefix import prepare_static_html_for_stage, stage_prefix
from app.services.login_rate_limit import failed_login_exceeds_rate_limit
from app.services.microsoft_entra_oauth import (
    authorization_url,
    exchange_code_for_tokens,
    microsoft_oauth_is_configured,
    principal_email_from_claims,
    validate_id_token,
)
from app.services.security_service import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    _effective_password,
    _effective_username,
    client_ip_for_rate_limit,
    create_session_token,
    oauth_state_cookie_delete_kwargs,
    oauth_state_cookie_set_kwargs,
    session_cookie_delete_kwargs,
    session_cookie_set_kwargs,
    sign_oauth_state,
    verify_oauth_state,
    verify_session_token,
)
from app.services.user_directory_service import (
    ensure_bootstrap_user_record,
    is_user_allowed_to_sign_in,
)

logger = logging.getLogger("pcf_creator_app")

router = APIRouter()

def _microsoft_redirect_uri() -> str:
    base = (settings.public_base_url or "").rstrip("/")
    return f"{base}{stage_prefix()}/api/auth/microsoft/callback"


def _config_redirect_url() -> str:
    return f"{stage_prefix()}/config" if stage_prefix() else "/config"


def _login_url_with_query(extra: str = "") -> str:
    prefix = stage_prefix()
    path = f"{prefix}/login" if prefix else "/login"
    return f"{path}?{extra}" if extra else path


def _oauth_redirect_clearing_state(target_url: str) -> RedirectResponse:
    """Redirect helper that always clears the one-shot OAuth state cookie.

    Every fail/deny/abort branch of ``microsoft_login_callback`` ends with the
    same three-line pattern; centralizing it here keeps the state machine
    readable and ensures the cookie is never left dangling.
    """
    response = RedirectResponse(url=target_url, status_code=302)
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, **oauth_state_cookie_delete_kwargs())
    return response


@router.get("/api/auth/options")
def auth_options() -> JSONResponse:
    """Public: login methods available for the sign-in page."""
    ms = microsoft_oauth_is_configured()
    legacy = bool(settings.enable_legacy_password_login) or not ms
    return JSONResponse(
        content={
            "microsoft": {
                "enabled": ms,
                "login_url": f"{stage_prefix()}/api/auth/microsoft/login" if stage_prefix() else "/api/auth/microsoft/login",
            },
            "legacy_password": {"enabled": legacy},
        }
    )


@router.get("/api/auth/session")
def auth_session(request: Request) -> JSONResponse:
    """Return current session principal and admin flag (401 when not signed in)."""
    from app.services.user_directory_service import is_user_admin

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")
    principal = verify_session_token(token)
    if not principal:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return JSONResponse(content={"principal": principal, "is_admin": is_user_admin(principal)})


@router.get("/login", response_class=HTMLResponse)
def login_page() -> HTMLResponse:
    """Serve the login page."""
    html = _read_static_html("login.html") or "<html><body><p>Login page not found.</p></body></html>"
    return HTMLResponse(content=prepare_static_html_for_stage(html))


async def _read_credentials(request: Request) -> tuple[str, str]:
    """Accept username/password from form or JSON; trim whitespace."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type == "application/json":
        try:
            body = await request.json()
            return (body.get("username") or "").strip(), (body.get("password") or "").strip()
        except Exception:
            return "", ""
    form = await request.form()
    return (form.get("username") or "").strip(), (form.get("password") or "").strip()


@router.post("/api/auth/login")
async def login(request: Request) -> JSONResponse:
    """Authenticate; on success set the session cookie and return a redirect target."""
    if microsoft_oauth_is_configured() and not settings.enable_legacy_password_login:
        return JSONResponse(
            status_code=403,
            content={"detail": "Password sign-in is disabled. Use Microsoft."},
        )

    username, password = await _read_credentials(request)
    expected_user = _effective_username()
    expected_pass = _effective_password()

    if not (
        secrets.compare_digest(username, expected_user)
        and secrets.compare_digest(password, expected_pass)
    ):
        client_id = client_ip_for_rate_limit(request)
        if failed_login_exceeds_rate_limit(client_id):
            logger.warning("Login rate limited after repeated failures for client_id=%s", client_id)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many login attempts. Try again later."},
                headers={"Retry-After": "60"},
            )
        logger.info(
            "Login failed: username_len=%s password_len=%s expected_username_len=%s",
            len(username), len(password), len(expected_user),
        )
        return JSONResponse(status_code=401, content={"detail": "Invalid username or password."})

    redirect_to = _config_redirect_url()
    response = JSONResponse(content={"redirect": redirect_to})
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(username, kind="local"),
        **session_cookie_set_kwargs(),
    )
    return response


@router.get("/api/auth/microsoft/login")
def microsoft_login_start() -> RedirectResponse:
    if not microsoft_oauth_is_configured():
        raise HTTPException(status_code=503, detail="Microsoft sign-in is not configured.")
    nonce = secrets.token_urlsafe(32)
    state = sign_oauth_state(nonce)
    redirect_uri = _microsoft_redirect_uri()
    url = authorization_url(redirect_uri=redirect_uri, state=state)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(OAUTH_STATE_COOKIE_NAME, state, **oauth_state_cookie_set_kwargs())
    return response


@router.get("/api/auth/microsoft/callback")
def microsoft_login_callback(request: Request, code: str = "", state: str = "", error: str = "") -> RedirectResponse:
    login_err = _login_url_with_query("signin=error")

    if error:
        logger.info("Microsoft OAuth error param: %s", error)
        return _oauth_redirect_clearing_state(login_err)

    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME) or ""
    if not state or not cookie_state or state != cookie_state:
        logger.warning("OAuth state mismatch (possible CSRF).")
        return _oauth_redirect_clearing_state(login_err)
    if verify_oauth_state(state) is None:
        logger.warning("Invalid or expired OAuth state signature.")
        return _oauth_redirect_clearing_state(login_err)

    if not code:
        return _oauth_redirect_clearing_state(login_err)

    redirect_uri = _microsoft_redirect_uri()
    try:
        tokens = exchange_code_for_tokens(code=code, redirect_uri=redirect_uri)
    except ValueError:
        return _oauth_redirect_clearing_state(login_err)

    id_token = tokens.get("id_token")
    if not id_token or not isinstance(id_token, str):
        return _oauth_redirect_clearing_state(login_err)

    try:
        claims = validate_id_token(id_token)
    except Exception:
        logger.exception("id_token validation failed")
        return _oauth_redirect_clearing_state(login_err)

    if not isinstance(claims, dict):
        return _oauth_redirect_clearing_state(login_err)

    email = principal_email_from_claims(claims)
    display_name = str(claims.get("name") or "").strip()
    if not email:
        logger.warning("Microsoft token had no email or UPN claim.")
        return _oauth_redirect_clearing_state(_login_url_with_query("signin=no_email"))

    if not is_user_allowed_to_sign_in(email):
        logger.info("Sign-in denied (not invited): %s", email)
        return _oauth_redirect_clearing_state(_login_url_with_query("signin=not_invited"))

    ensure_bootstrap_user_record(email, display_name=display_name)

    ok = _oauth_redirect_clearing_state(_config_redirect_url())
    ok.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(email, kind="entra"),
        **session_cookie_set_kwargs(),
    )
    return ok


@router.get("/api/auth/logout")
def logout() -> RedirectResponse:
    """Clear the session cookie and redirect to /login."""
    response = login_redirect()
    response.delete_cookie(SESSION_COOKIE_NAME, **session_cookie_delete_kwargs())
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME, **oauth_state_cookie_delete_kwargs())
    return response
