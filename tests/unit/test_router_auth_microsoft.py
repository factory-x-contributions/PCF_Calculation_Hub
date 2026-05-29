# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Coverage for the Microsoft Entra ID branches of :mod:`app.api.routers.auth`.

These tests exercise every error/skip path of the OAuth callback because the
callback is the single most security-sensitive function in the app: any
regression that lets a bad state, a missing code, or a denied principal slip
through opens the configuration UI to anyone who can forge a redirect.

External seams (token exchange, id_token validation, allowlist lookup) are
mocked individually so the test asserts the *router contract*, not the OAuth
library's behaviour. The happy-path test verifies the four-step ordering:
state cookie present → token exchange OK → id_token valid → principal allowed
→ session cookie set & state cookie cleared.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app
from app.services.security_service import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    create_session_token,
    sign_oauth_state,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def ms_configured(monkeypatch) -> None:
    """Enable Microsoft sign-in for the duration of the test."""
    monkeypatch.setattr(settings, "microsoft_entra_tenant_id", "tenant-abc")
    monkeypatch.setattr(settings, "microsoft_entra_client_id", "client-xyz")
    monkeypatch.setattr(settings, "microsoft_entra_client_secret", "secret-123")
    monkeypatch.setattr(settings, "public_base_url", "https://app.example.com")


# -- /api/auth/session -----------------------------------------------------------


def test_session_returns_401_when_cookie_missing(client: TestClient) -> None:
    response = client.get("/api/auth/session")
    assert response.status_code == 401


def test_session_returns_401_when_token_invalid(client: TestClient) -> None:
    response = client.get(
        "/api/auth/session",
        cookies={SESSION_COOKIE_NAME: "garbage-token"},
    )
    assert response.status_code == 401


def test_session_returns_principal_and_admin_flag_for_valid_token(client: TestClient) -> None:
    """An admin local session returns its username plus ``is_admin=True``."""
    token = create_session_token("admin")
    response = client.get(
        "/api/auth/session",
        cookies={SESSION_COOKIE_NAME: token},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == "admin"
    assert body["is_admin"] is True


# -- /api/auth/login (password-disabled mode) -----------------------------------


def test_login_returns_403_when_password_disabled(client: TestClient, ms_configured, monkeypatch) -> None:
    """When Microsoft is configured AND legacy password login is disabled,
    POST /api/auth/login must refuse with 403."""
    monkeypatch.setattr(settings, "enable_legacy_password_login", False)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 403
    assert "Microsoft" in response.json()["detail"]


def test_login_returns_401_for_malformed_json_body(client: TestClient) -> None:
    """``_read_credentials`` must treat malformed JSON as empty creds → 401."""
    response = client.post(
        "/api/auth/login",
        content=b"{ not-json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401


def test_login_options_legacy_login_url_uses_root_when_no_stage(client: TestClient) -> None:
    """Without an APIGW stage, the Microsoft login URL must be absolute root."""
    response = client.get("/api/auth/options")
    assert response.status_code == 200
    body = response.json()
    assert body["microsoft"]["login_url"] == "/api/auth/microsoft/login"


# -- /api/auth/microsoft/login --------------------------------------------------


def test_microsoft_login_returns_503_when_unconfigured(client: TestClient) -> None:
    response = client.get("/api/auth/microsoft/login", follow_redirects=False)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_microsoft_login_redirects_to_microsoft_with_state_cookie(
    client: TestClient, ms_configured
) -> None:
    response = client.get("/api/auth/microsoft/login", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(
        "https://login.microsoftonline.com/tenant-abc/oauth2/v2.0/authorize?"
    )
    # The redirect must also drop a signed state cookie
    set_cookie = response.headers.get("set-cookie", "")
    assert OAUTH_STATE_COOKIE_NAME in set_cookie


# -- /api/auth/microsoft/callback ----------------------------------------------


def _login_url() -> str:
    return "/login?signin=error"


def test_callback_with_error_param_redirects_to_login(client: TestClient, ms_configured) -> None:
    response = client.get(
        "/api/auth/microsoft/callback?error=access_denied",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_with_missing_state_redirects(client: TestClient, ms_configured) -> None:
    response = client.get("/api/auth/microsoft/callback?code=abc", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_with_state_mismatch_redirects(client: TestClient, ms_configured) -> None:
    """State in the cookie must match the state query param — otherwise CSRF protection trips."""
    response = client.get(
        "/api/auth/microsoft/callback?code=abc&state=query-state",
        cookies={OAUTH_STATE_COOKIE_NAME: "different-state"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_with_unsigned_state_redirects(client: TestClient, ms_configured) -> None:
    """An attacker-supplied state that happens to match the cookie but is not signed by us must still fail verification."""
    response = client.get(
        "/api/auth/microsoft/callback?code=abc&state=forged",
        cookies={OAUTH_STATE_COOKIE_NAME: "forged"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_with_blank_code_redirects(client: TestClient, ms_configured) -> None:
    state = sign_oauth_state("nonce-1")
    response = client.get(
        f"/api/auth/microsoft/callback?code=&state={state}",
        cookies={OAUTH_STATE_COOKIE_NAME: state},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_token_exchange_failure_redirects(client: TestClient, ms_configured) -> None:
    state = sign_oauth_state("nonce-2")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        side_effect=ValueError("token_exchange_failed"),
    ):
        response = client.get(
            f"/api/auth/microsoft/callback?code=abcd&state={state}",
            cookies={OAUTH_STATE_COOKIE_NAME: state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_without_id_token_redirects(client: TestClient, ms_configured) -> None:
    state = sign_oauth_state("nonce-3")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        return_value={"access_token": "x"},
    ):
        response = client.get(
            f"/api/auth/microsoft/callback?code=abcd&state={state}",
            cookies={OAUTH_STATE_COOKIE_NAME: state},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_id_token_validation_failure_redirects(client: TestClient, ms_configured) -> None:
    state = sign_oauth_state("nonce-4")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        return_value={"id_token": "fake"},
    ):
        with patch(
            "app.api.routers.auth.validate_id_token",
            side_effect=RuntimeError("invalid signature"),
        ):
            response = client.get(
                f"/api/auth/microsoft/callback?code=abcd&state={state}",
                cookies={OAUTH_STATE_COOKIE_NAME: state},
                follow_redirects=False,
            )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_non_dict_claims_redirect(client: TestClient, ms_configured) -> None:
    """A pathological JWT library returning non-dict claims must be rejected."""
    state = sign_oauth_state("nonce-4b")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        return_value={"id_token": "fake"},
    ):
        with patch(
            "app.api.routers.auth.validate_id_token",
            return_value=["not", "a", "dict"],
        ):
            response = client.get(
                f"/api/auth/microsoft/callback?code=abcd&state={state}",
                cookies={OAUTH_STATE_COOKIE_NAME: state},
                follow_redirects=False,
            )
    assert response.status_code == 302
    assert response.headers["location"] == _login_url()


def test_callback_missing_email_claim_redirects_with_no_email(
    client: TestClient, ms_configured
) -> None:
    state = sign_oauth_state("nonce-5")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        return_value={"id_token": "fake"},
    ):
        with patch(
            "app.api.routers.auth.validate_id_token",
            return_value={"sub": "abc"},
        ):
            response = client.get(
                f"/api/auth/microsoft/callback?code=abcd&state={state}",
                cookies={OAUTH_STATE_COOKIE_NAME: state},
                follow_redirects=False,
            )
    assert response.status_code == 302
    assert response.headers["location"] == "/login?signin=no_email"


def test_callback_disallowed_email_redirects_with_not_invited(
    client: TestClient, ms_configured
) -> None:
    state = sign_oauth_state("nonce-6")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        return_value={"id_token": "fake"},
    ):
        with patch(
            "app.api.routers.auth.validate_id_token",
            return_value={"email": "stranger@example.com", "name": "Stranger"},
        ):
            with patch(
                "app.api.routers.auth.is_user_allowed_to_sign_in",
                return_value=False,
            ):
                response = client.get(
                    f"/api/auth/microsoft/callback?code=abcd&state={state}",
                    cookies={OAUTH_STATE_COOKIE_NAME: state},
                    follow_redirects=False,
                )
    assert response.status_code == 302
    assert response.headers["location"] == "/login?signin=not_invited"


def test_callback_happy_path_sets_session_cookie_and_redirects_to_config(
    client: TestClient, ms_configured, monkeypatch
) -> None:
    """Full happy path — token exchange, validation, allowlist, bootstrap, cookie."""
    bootstrap_calls: list[tuple[str, str]] = []

    def fake_bootstrap(email: str, *, display_name: str = "") -> None:
        bootstrap_calls.append((email, display_name))

    state = sign_oauth_state("nonce-7")
    with patch(
        "app.api.routers.auth.exchange_code_for_tokens",
        return_value={"id_token": "fake"},
    ):
        with patch(
            "app.api.routers.auth.validate_id_token",
            return_value={"email": "Allowed@Example.com", "name": "User Allowed"},
        ):
            with patch(
                "app.api.routers.auth.is_user_allowed_to_sign_in",
                return_value=True,
            ):
                monkeypatch.setattr(
                    "app.api.routers.auth.ensure_bootstrap_user_record",
                    fake_bootstrap,
                )
                response = client.get(
                    f"/api/auth/microsoft/callback?code=abcd&state={state}",
                    cookies={OAUTH_STATE_COOKIE_NAME: state},
                    follow_redirects=False,
                )

    assert response.status_code == 302
    assert response.headers["location"] == "/config"
    # Session cookie set, state cookie cleared
    cookie_header = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE_NAME in cookie_header
    # Bootstrap was invoked with the *normalized* email (lowercased)
    assert bootstrap_calls == [("allowed@example.com", "User Allowed")]
