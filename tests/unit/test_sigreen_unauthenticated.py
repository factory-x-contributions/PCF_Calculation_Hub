# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Spec FX TP2.10 §5.2.4 evidence: SiGREEN must support unauthenticated submission.

The spec says:

> In scenarios where client credentials are intentionally omitted, the
> application gracefully falls back to unauthenticated submissions to support
> optionally relaxed local hub configurations.

Phase 3 made :func:`app.integrations.sigreen.fetch_token` return ``None`` when
credentials are blank, and :func:`app.integrations.sigreen._auth_headers` omit
the Authorization header in that case.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.integrations import sigreen


@pytest.fixture(autouse=True)
def _clear_token_cache_between_tests() -> None:
    """Without this, a token cached by an earlier test leaks into the next one."""
    sigreen.clear_sigreen_token_cache()
    yield
    sigreen.clear_sigreen_token_cache()


def test_fetch_token_returns_none_when_credentials_blank() -> None:
    with patch("app.integrations.sigreen._sigreen_client_id", return_value=""):
        with patch("app.integrations.sigreen._sigreen_client_secret", return_value=""):
            assert sigreen.fetch_token() is None


def test_auth_headers_omit_authorization_when_unauthenticated() -> None:
    with patch("app.integrations.sigreen._sigreen_client_id", return_value=""):
        with patch("app.integrations.sigreen._sigreen_client_secret", return_value=""):
            headers = sigreen._auth_headers()

    assert "Authorization" not in headers
    assert headers["Content-Type"] == "application/json"


def test_auth_headers_include_bearer_when_credentials_present() -> None:
    """When credentials exist, the Bearer header is built from the cached token."""
    with patch("app.integrations.sigreen.fetch_token", return_value="real-token"):
        headers = sigreen._auth_headers()

    assert headers["Authorization"] == "Bearer real-token"
    assert headers["Content-Type"] == "application/json"


def test_clear_sigreen_token_cache_resets_module_cache() -> None:
    """The public clear function must invalidate the underlying TokenCache."""
    sigreen._SIGREEN_TOKEN_CACHE._cached = ("stale", 9_999_999_999.0)  # type: ignore[attr-defined]
    sigreen.clear_sigreen_token_cache()
    assert sigreen._SIGREEN_TOKEN_CACHE._cached is None  # type: ignore[attr-defined]
