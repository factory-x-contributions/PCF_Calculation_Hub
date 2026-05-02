"""Unit tests for session-gated static HTML helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.responses import HTMLResponse, RedirectResponse

from app.core import protected_pages


def test_login_redirect_local_no_prefix() -> None:
    with patch.object(protected_pages, "stage_prefix", return_value=""):
        r = protected_pages.login_redirect()
    assert isinstance(r, RedirectResponse)
    assert r.status_code == 302
    assert r.headers["location"] == "/login"


def test_login_redirect_with_stage_prefix() -> None:
    with patch.object(protected_pages, "stage_prefix", return_value="/pcf"):
        r = protected_pages.login_redirect()
    assert r.headers["location"] == "/pcf/login"


def test_serve_protected_html_redirects_without_cookie() -> None:
    req = MagicMock()
    req.cookies.get.return_value = None
    with patch.object(protected_pages, "stage_prefix", return_value=""):
        r = protected_pages.serve_protected_html(req, "config.html")
    assert isinstance(r, RedirectResponse)


def test_serve_protected_html_invalid_token() -> None:
    req = MagicMock()
    req.cookies.get.return_value = "bad"
    with patch.object(protected_pages, "verify_session_token", return_value=None):
        with patch.object(protected_pages, "stage_prefix", return_value=""):
            r = protected_pages.serve_protected_html(req, "config.html")
    assert isinstance(r, RedirectResponse)


def test_serve_protected_html_serves_when_valid() -> None:
    req = MagicMock()
    req.cookies.get.return_value = "ok-token"
    with patch.object(protected_pages, "verify_session_token", return_value="admin"):
        with patch.object(protected_pages, "_read_static_html", return_value="<html>x</html>"):
            with patch.object(protected_pages, "prepare_static_html_for_stage", side_effect=lambda h: h):
                r = protected_pages.serve_protected_html(req, "config.html")
    assert isinstance(r, HTMLResponse)
    assert b"x" in r.body


def test_serve_protected_html_missing_file_fallback() -> None:
    req = MagicMock()
    req.cookies.get.return_value = "ok-token"
    with patch.object(protected_pages, "verify_session_token", return_value="admin"):
        with patch.object(protected_pages, "_read_static_html", return_value=""):
            r = protected_pages.serve_protected_html(req, "nope.html")
    assert isinstance(r, HTMLResponse)
    assert b"Page not found" in r.body
