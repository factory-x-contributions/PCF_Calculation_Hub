"""Unit tests for :class:`app.integrations.oauth_token_cache.TokenCache`.

The cache is the single OAuth2 client-credentials implementation shared by
SiGREEN, AssetFox (AAS), and Green Grid Compass. Tests cover:

* The unauthenticated-fallback contract (empty creds → ``None``).
* Caching within the leeway window.
* Refresh after expiry.
* JSON and form-urlencoded body modes (the IdPs differ).
* Audience and scope passthrough via ``extra_body``.
* Explicit cache invalidation via :meth:`clear`.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.integrations.oauth_token_cache import TokenCache


def _ok_response(*, token: str = "tok", expires_in: int = 3600) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {"access_token": token, "expires_in": expires_in}
    response.raise_for_status = MagicMock()
    return response


def test_returns_none_when_credentials_are_empty() -> None:
    """Spec FX TP2.10 §5.2.4: empty credentials must signal unauthenticated mode, not raise."""
    post = MagicMock()
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "",
        client_secret_provider=lambda: "",
        http_post=post,
    )
    assert cache.get() is None
    post.assert_not_called()


def test_returns_none_when_only_one_credential_is_set() -> None:
    """A half-configured client (id without secret, or vice versa) is treated as unauthenticated."""
    post = MagicMock()
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "",
        http_post=post,
    )
    assert cache.get() is None
    post.assert_not_called()


def test_fetches_token_and_caches_within_leeway() -> None:
    post = MagicMock(return_value=_ok_response(token="abc", expires_in=3600))
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        clock=lambda: 1000.0,
        http_post=post,
    )
    assert cache.get() == "abc"
    assert cache.get() == "abc"
    post.assert_called_once()


def test_refreshes_after_expiry() -> None:
    """Past the cached expiry minus the 60-second leeway, a fresh token is fetched."""
    clock = MagicMock(side_effect=[1000.0, 5000.0, 5000.0])
    post = MagicMock(side_effect=[
        _ok_response(token="old", expires_in=900),
        _ok_response(token="new", expires_in=900),
    ])
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        clock=clock,
        http_post=post,
    )
    assert cache.get() == "old"  # primes
    assert cache.get() == "new"  # past leeway → refresh
    assert post.call_count == 2


def test_clear_invalidates_cache() -> None:
    """Explicit ``clear`` is what the Config UI calls when SiGREEN credentials change."""
    post = MagicMock(side_effect=[
        _ok_response(token="t1", expires_in=3600),
        _ok_response(token="t2", expires_in=3600),
    ])
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        clock=lambda: 100.0,
        http_post=post,
    )
    assert cache.get() == "t1"
    cache.clear()
    assert cache.get() == "t2"
    assert post.call_count == 2


def test_json_body_mode_sends_audience_in_json_body() -> None:
    """SiGREEN's Auth0 IdP wants a JSON body with the audience field."""
    post = MagicMock(return_value=_ok_response())
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        extra_body={"audience": "aud-x"},
        body_format="json",
        http_post=post,
    )
    cache.get()
    args, kwargs = post.call_args
    assert kwargs["json"]["audience"] == "aud-x"
    assert kwargs["json"]["grant_type"] == "client_credentials"
    assert kwargs["headers"]["Content-Type"] == "application/json"


def test_form_body_mode_sends_scope_in_urlencoded_body() -> None:
    """Siemens Energy / AssetFox IdPs use form-urlencoded; scope must travel in ``data``."""
    post = MagicMock(return_value=_ok_response())
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        extra_body={"scope": "esp"},
        body_format="form",
        http_post=post,
    )
    cache.get()
    args, kwargs = post.call_args
    assert kwargs["data"]["scope"] == "esp"
    assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_invalid_body_format_rejects_at_construction() -> None:
    with pytest.raises(ValueError):
        TokenCache(
            token_url="x",
            client_id_provider=lambda: "i",
            client_secret_provider=lambda: "s",
            body_format="xml",
        )


def test_missing_access_token_in_response_raises() -> None:
    """A 200 OK with no ``access_token`` is a real misconfiguration; surface it loudly."""
    post = MagicMock(return_value=MagicMock(
        json=MagicMock(return_value={"oops": True}),
        raise_for_status=MagicMock(),
    ))
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        http_post=post,
    )
    with pytest.raises(RuntimeError, match="access_token"):
        cache.get()


def test_credential_providers_are_evaluated_each_call() -> None:
    """Cred providers are callables so live config edits in the UI take effect on the next get()."""
    creds = {"id": "first", "secret": "first"}
    post = MagicMock(return_value=_ok_response())
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: creds["id"],
        client_secret_provider=lambda: creds["secret"],
        http_post=post,
    )
    cache.get()
    creds["id"] = ""
    creds["secret"] = ""
    assert cache.get() is None  # config was zeroed → unauthenticated mode kicks in


def test_token_url_provider_overrides_static_url() -> None:
    """Live token URL changes (e.g. from the Config UI) must apply on the next refresh."""
    urls = {"current": "https://example/token-a"}
    post = MagicMock(return_value=_ok_response())
    cache = TokenCache(
        token_url="https://example/fallback",
        token_url_provider=lambda: urls["current"],
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        http_post=post,
    )
    cache.get()
    assert post.call_args[0][0] == "https://example/token-a"
    urls["current"] = "https://example/token-b"
    cache.clear()
    cache.get()
    assert post.call_args[0][0] == "https://example/token-b"


def test_extra_body_provider_overrides_static_body() -> None:
    audiences = {"current": "aud-a"}
    post = MagicMock(return_value=_ok_response())
    cache = TokenCache(
        token_url="https://example/token",
        client_id_provider=lambda: "id",
        client_secret_provider=lambda: "secret",
        extra_body={"audience": "fallback"},
        extra_body_provider=lambda: {"audience": audiences["current"]},
        http_post=post,
    )
    cache.get()
    assert post.call_args[1]["json"]["audience"] == "aud-a"
    audiences["current"] = "aud-b"
    cache.clear()
    cache.get()
    assert post.call_args[1]["json"]["audience"] == "aud-b"
