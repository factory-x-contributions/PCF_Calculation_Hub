"""Single OAuth2 client-credentials token cache used by every integration.

Before Phase 3 each integration (SiGREEN, AssetFox, Green Grid Compass) had
its own copy of "fetch token, cache it, refresh 1 minute before expiry".
The three copies drifted (e.g. only some accept ``scope``, some send the
body as JSON and some as ``application/x-www-form-urlencoded``).

This module collapses those into one :class:`TokenCache` whose only
moving parts are the three knobs that actually differ:

1. ``extra_body`` — additional fields the IdP requires (``audience`` for
   SiGREEN's Auth0 tenant, ``scope`` for Green Grid Compass, nothing for
   AssetFox).
2. ``body_format`` — ``"json"`` for Auth0, ``"form"`` (urlencoded) for the
   two Siemens IdPs.
3. ``client_id_provider`` / ``client_secret_provider`` — callables so the
   cache picks up live config changes without being re-instantiated.

Empty credentials are a first-class signal (spec FX TP2.10 §5.2.4): when
both ``client_id`` and ``client_secret`` are blank, :meth:`TokenCache.get`
returns ``None`` and the calling client must omit the Authorization
header. Authentication is **not** mandatory — the spec explicitly allows
unauthenticated submissions when credentials are intentionally omitted.

The ``clock`` and ``http_post`` parameters are the only injection seams
the tests need: a fake clock makes expiry deterministic and a fake
``http_post`` removes the requests dependency entirely.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import requests

logger = logging.getLogger("pcf_creator_app")

_DEFAULT_LEEWAY_SECONDS = 60
_MAX_CACHE_SECONDS = 14 * 60


class TokenCache:
    """Caches one OAuth2 client-credentials access token across calls.

    Thread-safe enough for the patterns we use (single producer per cache
    instance; a worst-case race results in two parallel token fetches and
    the second one wins — both tokens are valid). For a stricter guarantee
    a future revision can wrap :meth:`get` with a :class:`threading.Lock`.
    """

    def __init__(
        self,
        *,
        token_url: str = "",
        token_url_provider: Callable[[], str] | None = None,
        client_id_provider: Callable[[], str],
        client_secret_provider: Callable[[], str],
        extra_body: dict[str, str] | None = None,
        extra_body_provider: Callable[[], dict[str, str]] | None = None,
        body_format: str = "json",
        leeway_seconds: int = _DEFAULT_LEEWAY_SECONDS,
        clock: Callable[[], float] = time.time,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        if body_format not in ("json", "form"):
            raise ValueError(f"body_format must be 'json' or 'form', got {body_format!r}")
        if not token_url and not token_url_provider:
            raise ValueError("token_url or token_url_provider is required")
        self._token_url = token_url
        self._token_url_provider = token_url_provider
        self._client_id_provider = client_id_provider
        self._client_secret_provider = client_secret_provider
        self._extra_body = dict(extra_body or {})
        self._extra_body_provider = extra_body_provider
        self._body_format = body_format
        self._leeway_seconds = leeway_seconds
        self._clock = clock
        # Stored as None means "look up requests.post at call time" — this lets unittest.mock.patch
        # on ``app.integrations.oauth_token_cache.requests.post`` reach the cache without the test
        # having to reach into private attributes.
        self._http_post = http_post
        self._cached: tuple[str, float] | None = None

    def clear(self) -> None:
        """Drop any cached token. Call when credentials change."""
        self._cached = None

    def _resolve_token_url(self) -> str:
        if self._token_url_provider is not None:
            return (self._token_url_provider() or "").strip() or self._token_url
        return self._token_url

    def _resolve_extra_body(self) -> dict[str, str]:
        if self._extra_body_provider is not None:
            return dict(self._extra_body_provider())
        return dict(self._extra_body)

    def get(self) -> str | None:
        """Return a fresh access token, or ``None`` if no credentials are configured.

        Callers that receive ``None`` must omit the ``Authorization`` header
        from the outbound request (unauthenticated submission, per spec).
        """
        client_id = (self._client_id_provider() or "").strip()
        client_secret = (self._client_secret_provider() or "").strip()
        if not client_id or not client_secret:
            return None

        now = self._clock()
        if self._cached is not None:
            token, expires_at = self._cached
            if now < expires_at - self._leeway_seconds:
                return token

        return self._refresh(client_id=client_id, client_secret=client_secret, now=now)

    def _refresh(self, *, client_id: str, client_secret: str, now: float) -> str:
        body = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            **self._resolve_extra_body(),
        }
        post = self._http_post if self._http_post is not None else requests.post
        token_url = self._resolve_token_url()
        if self._body_format == "json":
            response = post(
                token_url,
                json=body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
        else:
            response = post(
                token_url,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
        response.raise_for_status()
        token_data = response.json()
        token = token_data.get("access_token")
        if not isinstance(token, str) or not token:
            raise RuntimeError(f"OAuth response missing access_token: {token_data!r}")
        expires_in = float(token_data.get("expires_in", 900))
        self._cached = (token, now + min(expires_in, _MAX_CACHE_SECONDS))
        return token


__all__ = ["TokenCache"]
