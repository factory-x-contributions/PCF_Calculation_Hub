# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Router tests for ``/api/admin/users`` — the Entra allowlist management API.

These are the endpoints behind the Users tab of the config UI. The router is
guarded by ``require_admin_session``, so each test attaches a valid local-admin
session cookie. The user directory itself is redirected to a temp JSON file to
keep tests hermetic.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app
from app.services.security_service import (
    SESSION_COOKIE_NAME,
    create_session_token,
)


@pytest.fixture
def admin_session_cookie() -> str:
    """Session cookie for the local 'admin' user (always an admin)."""
    return create_session_token("admin")


@pytest.fixture
def isolated_user_directory(monkeypatch, tmp_path) -> Path:
    """Redirect the allowlist JSON store to a per-test temp file."""
    path = tmp_path / "allowed_users.json"
    monkeypatch.setattr(settings, "allowed_users_path", str(path))
    monkeypatch.setattr(settings, "allowed_users_s3_bucket", "")
    monkeypatch.setattr(settings, "allowed_users_s3_key", "")
    return path


@pytest.fixture
def client(isolated_user_directory) -> TestClient:
    return TestClient(app)


# -- GET /api/admin/users ------------------------------------------------------


def test_list_users_returns_empty_for_fresh_directory(
    client: TestClient, admin_session_cookie: str
) -> None:
    response = client.get(
        "/api/admin/users",
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 200
    assert response.json() == {"users": []}


def test_list_users_requires_session(client: TestClient) -> None:
    """No cookie → 401 from require_admin_session ⇒ require_session."""
    response = client.get("/api/admin/users")
    assert response.status_code == 401


def test_list_users_rejects_non_admin(client: TestClient, monkeypatch) -> None:
    """A valid session whose principal is not an admin must be denied with 403."""
    monkeypatch.setattr(settings, "basic_auth_username", "alice")
    token = create_session_token("alice")
    # alice is the local-console user → still an admin (see is_user_admin); switch principal:
    bad_token = create_session_token("not-admin@example.com", kind="entra")
    from unittest.mock import patch

    with patch("app.services.user_directory_service.is_user_allowed_to_sign_in", return_value=True):
        response = client.get(
            "/api/admin/users",
            cookies={SESSION_COOKIE_NAME: bad_token},
        )
    # not-admin@example.com is not in the directory ⇒ is_user_admin = False ⇒ 403
    assert response.status_code == 403


# -- POST /api/admin/users -----------------------------------------------------


def test_add_user_persists_and_returns_row(
    client: TestClient, admin_session_cookie: str
) -> None:
    response = client.post(
        "/api/admin/users",
        json={"email": "Alice@Example.COM", "role": "user"},
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["email"] == "alice@example.com"
    assert user["role"] == "user"
    assert user["created_by"] == "admin"

    # GET should now contain the user
    listing = client.get(
        "/api/admin/users",
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    emails = [u["email"] for u in listing.json()["users"]]
    assert "alice@example.com" in emails


def test_add_user_returns_400_for_blank_email(
    client: TestClient, admin_session_cookie: str
) -> None:
    """upsert_directory_user raises ValueError for blank email — router must convert to 400."""
    response = client.post(
        "/api/admin/users",
        json={"email": "   ", "role": "user"},
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    # Pydantic rejects below min_length=3 first
    assert response.status_code in (400, 422)


def test_add_user_rejects_invalid_role_with_422(
    client: TestClient, admin_session_cookie: str
) -> None:
    """Literal['admin', 'user'] field — Pydantic rejects 'root'."""
    response = client.post(
        "/api/admin/users",
        json={"email": "bob@example.com", "role": "root"},
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 422


def test_add_user_converts_value_error_to_400(
    client: TestClient, admin_session_cookie: str, monkeypatch
) -> None:
    """If the service layer raises ValueError (e.g. internal validation), router → 400."""

    def boom(*_a, **_k):
        raise ValueError("custom rule violated")

    monkeypatch.setattr("app.api.routers.users_admin.upsert_directory_user", boom)
    response = client.post(
        "/api/admin/users",
        json={"email": "ok@example.com", "role": "user"},
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 400
    assert "custom rule violated" in response.json()["detail"]


# -- DELETE /api/admin/users/{email} -------------------------------------------


def test_delete_user_returns_404_when_missing(
    client: TestClient, admin_session_cookie: str
) -> None:
    response = client.delete(
        "/api/admin/users/ghost@example.com",
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 404


def test_delete_user_after_add(
    client: TestClient, admin_session_cookie: str
) -> None:
    client.post(
        "/api/admin/users",
        json={"email": "to-delete@example.com", "role": "user"},
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    response = client.delete(
        "/api/admin/users/to-delete@example.com",
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["deleted"] == "to-delete@example.com"


def test_delete_user_rejects_blank_email_with_400(
    client: TestClient, admin_session_cookie: str
) -> None:
    """A whitespace-only path parameter normalises to "" → 400 'Invalid email'."""
    response = client.delete(
        "/api/admin/users/%20%20",
        cookies={SESSION_COOKIE_NAME: admin_session_cookie},
    )
    assert response.status_code == 400
    assert "Invalid email" in response.json()["detail"]
