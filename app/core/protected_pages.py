"""Helpers for serving session-protected static HTML pages.

Replaces the three near-identical 5-line route handlers in app.api.routers.config.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.stage_prefix import prepare_static_html_for_stage, stage_prefix
from app.services.security_service import SESSION_COOKIE_NAME, verify_session_token

_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def _read_static_html(name: str) -> str:
    path = _STATIC_DIR / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def login_redirect() -> RedirectResponse:
    prefix = stage_prefix()
    return RedirectResponse(url=(f"{prefix}/login" if prefix else "/login"), status_code=302)


def serve_protected_html(request: Request, html_filename: str) -> HTMLResponse | RedirectResponse:
    """Return the file when the session cookie is valid; redirect to /login otherwise."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not verify_session_token(token):
        return login_redirect()
    html = _read_static_html(html_filename) or "<html><body><p>Page not found.</p></body></html>"
    return HTMLResponse(content=prepare_static_html_for_stage(html))
