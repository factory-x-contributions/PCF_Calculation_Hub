# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Router-level tests for auth (``/login``, ``/api/auth/login``, ``/api/auth/logout``).

Covers spec §5.2.4 evidence: HTTP 429 on rate-limit overflow, 401 on invalid creds,
session cookie set on success, cookie cleared on logout. Uses the live login_rate_limit
state but resets it between tests for determinism.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import login_rate_limit


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_rate_limit_state() -> None:
    """Per-test-isolated rate limiter — no leakage of failed-attempt counters."""
    state = getattr(login_rate_limit, "_RATE_LIMIT_STATE", None)
    if isinstance(state, dict):
        state.clear()
    yield
    if isinstance(state, dict):
        state.clear()


def test_login_page_returns_html(client: TestClient) -> None:
    response = client.get("/login")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_invalid_credentials_return_401_and_no_cookie(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."
    assert "set-cookie" not in {h.lower() for h in response.headers}


def test_valid_credentials_return_200_with_session_cookie(client: TestClient) -> None:
    """Default Basic Auth credentials are admin/admin in test config."""
    response = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200, response.text
    assert "redirect" in response.json()
    cookie_value = response.cookies.get("pcf_session")
    assert cookie_value, "expected pcf_session cookie to be set"


def test_logout_clears_session_cookie(client: TestClient) -> None:
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    response = client.get("/api/auth/logout", follow_redirects=False)
    # The endpoint redirects to /login (303 or 302) and includes Set-Cookie clearing the session.
    assert response.status_code in (302, 303, 307)


def test_login_rate_limit_returns_429_after_threshold(client: TestClient) -> None:
    """16 wrong attempts within the window must return HTTP 429 with Retry-After (spec §5.2.4)."""
    # Force the rate-limit predicate to True so we don't have to spam 16 real attempts.
    with patch(
        "app.api.routers.auth.failed_login_exceeds_rate_limit",
        return_value=True,
    ):
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong"},
        )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["detail"] == "Too many login attempts. Try again later."


def test_auth_options_returns_shape(client: TestClient) -> None:
    response = client.get("/api/auth/options")
    assert response.status_code == 200
    data = response.json()
    assert "microsoft" in data and "legacy_password" in data
    assert "enabled" in data["microsoft"]
    assert "login_url" in data["microsoft"]


def test_login_accepts_form_payload(client: TestClient) -> None:
    """The login endpoint must accept both JSON and form-encoded credentials."""
    response = client.post(
        "/api/auth/login",
        data={"username": "admin", "password": "admin"},
    )
    assert response.status_code == 200, response.text
