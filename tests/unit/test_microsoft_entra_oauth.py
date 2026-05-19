"""Unit tests for :mod:`app.services.microsoft_entra_oauth`.

The OAuth helper sits between FastAPI routes and the Microsoft v2 endpoint.
External calls (token exchange, JWKS discovery, RS256 verification) are
mocked at the seam — nothing in this module is allowed to touch the network
during unit tests, and we pin every branch that the auth router relies on
(``microsoft_oauth_is_configured`` gating, claims normalisation, signature
verification fallbacks).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import settings
from app.services import microsoft_entra_oauth as oauth


@pytest.fixture
def configured_oauth(monkeypatch) -> None:
    """Populate the four Entra settings the helpers require."""
    monkeypatch.setattr(settings, "microsoft_entra_tenant_id", "tenant-abc")
    monkeypatch.setattr(settings, "microsoft_entra_client_id", "client-xyz")
    monkeypatch.setattr(settings, "microsoft_entra_client_secret", "secret-123")
    monkeypatch.setattr(settings, "public_base_url", "https://app.example.com")


def test_microsoft_oauth_is_configured_true_when_all_set(configured_oauth) -> None:
    assert oauth.microsoft_oauth_is_configured() is True


@pytest.mark.parametrize("attr", [
    "microsoft_entra_tenant_id",
    "microsoft_entra_client_id",
    "microsoft_entra_client_secret",
    "public_base_url",
])
def test_microsoft_oauth_is_configured_false_when_any_blank(
    configured_oauth, monkeypatch, attr
) -> None:
    """Each of the four required settings is mandatory; missing any disables Microsoft sign-in."""
    monkeypatch.setattr(settings, attr, "   ")
    assert oauth.microsoft_oauth_is_configured() is False


def test_authorization_url_embeds_tenant_redirect_state(configured_oauth) -> None:
    url = oauth.authorization_url(
        redirect_uri="https://app.example.com/cb",
        state="state-token-1",
    )
    assert url.startswith(
        "https://login.microsoftonline.com/tenant-abc/oauth2/v2.0/authorize?"
    )
    # Query params must be URL-encoded but include all required values
    assert "client_id=client-xyz" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fcb" in url
    assert "state=state-token-1" in url
    assert "response_type=code" in url
    assert "scope=openid+profile+email" in url


def test_exchange_code_for_tokens_returns_body_on_200(configured_oauth) -> None:
    fake_response = MagicMock(status_code=200, text="")
    fake_response.json.return_value = {"id_token": "abc", "access_token": "xyz"}

    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value.post.return_value = fake_response
    fake_ctx.__exit__.return_value = False
    with patch.object(oauth.httpx, "Client", return_value=fake_ctx):
        out = oauth.exchange_code_for_tokens(code="abcd", redirect_uri="https://x")
    assert out == {"id_token": "abc", "access_token": "xyz"}


def test_exchange_code_for_tokens_raises_on_non_200(configured_oauth) -> None:
    fake_response = MagicMock(status_code=400, text="bad client")
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value.post.return_value = fake_response
    fake_ctx.__exit__.return_value = False
    with patch.object(oauth.httpx, "Client", return_value=fake_ctx):
        with pytest.raises(ValueError, match="token_exchange_failed"):
            oauth.exchange_code_for_tokens(code="abcd", redirect_uri="https://x")


def test_exchange_code_for_tokens_raises_on_non_dict_body(configured_oauth) -> None:
    fake_response = MagicMock(status_code=200, text="")
    fake_response.json.return_value = ["not", "a", "dict"]
    fake_ctx = MagicMock()
    fake_ctx.__enter__.return_value.post.return_value = fake_response
    fake_ctx.__exit__.return_value = False
    with patch.object(oauth.httpx, "Client", return_value=fake_ctx):
        with pytest.raises(ValueError, match="invalid_token_response"):
            oauth.exchange_code_for_tokens(code="abcd", redirect_uri="https://x")


def test_validate_id_token_uses_jwks_and_returns_decoded_claims(configured_oauth) -> None:
    """RS256 verification must use the discovered JWKS key and validate aud/iss/exp."""
    fake_jwks = MagicMock()
    signing_key = MagicMock()
    signing_key.key = "fake-pubkey"
    fake_jwks.get_signing_key_from_jwt.return_value = signing_key

    # Ensure a fresh client (lru_cache may have a stale tenant from earlier tests)
    oauth._jwks_client.cache_clear()
    with patch.object(oauth, "PyJWKClient", return_value=fake_jwks):
        with patch.object(oauth.jwt, "decode", return_value={"email": "u@x", "name": "U"}) as decode:
            claims = oauth.validate_id_token("fake.jwt.token")
    assert claims == {"email": "u@x", "name": "U"}
    decode.assert_called_once()
    kwargs = decode.call_args.kwargs
    assert kwargs["algorithms"] == ["RS256"]
    assert kwargs["audience"] == "client-xyz"
    assert kwargs["issuer"] == "https://login.microsoftonline.com/tenant-abc/v2.0"


def test_principal_email_from_claims_prefers_email_field() -> None:
    out = oauth.principal_email_from_claims({"email": "User@Example.com", "upn": "x"})
    assert out == "user@example.com"


def test_principal_email_from_claims_falls_back_to_preferred_username() -> None:
    out = oauth.principal_email_from_claims({"preferred_username": "User@Example.com"})
    assert out == "user@example.com"


def test_principal_email_from_claims_falls_back_to_upn() -> None:
    out = oauth.principal_email_from_claims({"upn": "User@example.com"})
    assert out == "user@example.com"


def test_principal_email_from_claims_returns_blank_when_no_identity_fields() -> None:
    """Service-principal-style tokens without email/UPN must not be accepted as a user."""
    assert oauth.principal_email_from_claims({"sub": "abc-123"}) == ""


def test_principal_email_from_claims_strips_whitespace() -> None:
    assert oauth.principal_email_from_claims({"email": "  user@x  "}) == "user@x"
