"""Unit tests for session token roundtrip + cookie kwarg shapes."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.config.settings import settings
from app.services.security_service import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    client_ip_for_rate_limit,
    create_session_token,
    require_session,
    session_cookie_delete_kwargs,
    session_cookie_set_kwargs,
    verify_basic_auth,
    verify_session_token,
)


def test_token_roundtrip_returns_username() -> None:
    token = create_session_token("admin")
    assert verify_session_token(token) == "admin"


def test_entra_session_roundtrip_when_allowed() -> None:
    token = create_session_token("pat@example.com", kind="entra")
    with patch("app.services.user_directory_service.is_user_allowed_to_sign_in", return_value=True):
        assert verify_session_token(token) == "pat@example.com"


def test_entra_session_rejected_when_not_allowed() -> None:
    token = create_session_token("unknown@example.com", kind="entra")
    with patch("app.services.user_directory_service.is_user_allowed_to_sign_in", return_value=False):
        assert verify_session_token(token) is None


def test_garbled_token_returns_none() -> None:
    assert verify_session_token("not-a-real-token") is None
    assert verify_session_token("") is None


def test_token_expires_after_max_age() -> None:
    """Mock time to pretend the token is older than SESSION_MAX_AGE_SECONDS."""
    token = create_session_token("admin")
    with patch("app.services.security_service.URLSafeTimedSerializer") as mock_serializer:
        instance = mock_serializer.return_value
        from itsdangerous import SignatureExpired
        instance.loads.side_effect = SignatureExpired("expired", date_signed=None)
        assert verify_session_token(token) is None


def test_cookie_set_kwargs_shape() -> None:
    kw = session_cookie_set_kwargs()
    assert kw["httponly"] is True
    assert kw["samesite"] == "lax"
    assert kw["max_age"] == SESSION_MAX_AGE_SECONDS
    assert kw["path"] == "/"
    assert "secure" in kw


def test_cookie_delete_kwargs_match_set_kwargs() -> None:
    """The delete kwargs must match set_kwargs on path/secure/httponly/samesite, otherwise browsers
    refuse to evict the cookie."""
    set_kw = session_cookie_set_kwargs()
    del_kw = session_cookie_delete_kwargs()
    for key in ("path", "secure", "httponly", "samesite"):
        assert del_kw[key] == set_kw[key], f"mismatch on {key}"


def test_session_cookie_name_is_stable() -> None:
    """Renaming the cookie name silently logs every user out — guard against accidental change."""
    assert SESSION_COOKIE_NAME == "pcf_session"


def test_verify_session_token_rejects_other_username() -> None:
    token = create_session_token("otheruser")
    with patch("app.services.security_service._effective_username", return_value="admin"):
        assert verify_session_token(token) is None


def test_verify_basic_auth_accepts_matching_credentials() -> None:
    creds = MagicMock()
    creds.username = "admin"
    creds.password = "admin"
    with patch("app.services.security_service._effective_username", return_value="admin"):
        with patch("app.services.security_service._effective_password", return_value="admin"):
            assert verify_basic_auth(creds) is True


def test_verify_basic_auth_rejects_bad_password() -> None:
    creds = MagicMock()
    creds.username = "admin"
    creds.password = "wrong"
    with patch("app.services.security_service._effective_username", return_value="admin"):
        with patch("app.services.security_service._effective_password", return_value="admin"):
            with pytest.raises(HTTPException) as exc:
                verify_basic_auth(creds)
    assert exc.value.status_code == 401


def test_require_session_missing_cookie() -> None:
    req = MagicMock()
    req.cookies.get.return_value = None
    with pytest.raises(HTTPException) as exc:
        require_session(req)
    assert exc.value.status_code == 401


def test_require_session_invalid_token() -> None:
    req = MagicMock()
    req.cookies.get.return_value = "x"
    with patch("app.services.security_service.verify_session_token", return_value=None):
        with pytest.raises(HTTPException) as exc:
            require_session(req)
    assert exc.value.status_code == 401


def test_require_session_returns_username() -> None:
    req = MagicMock()
    req.cookies.get.return_value = "tok"
    with patch("app.services.security_service.verify_session_token", return_value="admin"):
        assert require_session(req) == "admin"


def test_client_ip_prefers_forwarded_when_trusted() -> None:
    req = MagicMock()
    req.headers.get.return_value = "203.0.113.1, 10.0.0.1"
    with patch.object(settings, "trust_forwarded_headers", True):
        assert client_ip_for_rate_limit(req) == "203.0.113.1"


def test_client_ip_socket_host_when_not_trusted() -> None:
    req = MagicMock()
    req.headers.get.return_value = ""
    req.client.host = "127.0.0.1"
    with patch.object(settings, "trust_forwarded_headers", False):
        assert client_ip_for_rate_limit(req) == "127.0.0.1"


def test_client_ip_unknown_when_no_client() -> None:
    req = MagicMock()
    req.client = None
    with patch.object(settings, "trust_forwarded_headers", False):
        assert client_ip_for_rate_limit(req) == "unknown"


# -- verify_session_token: token payload variants ------------------------------------------


def _sign(payload: str) -> str:
    """Sign an arbitrary string with the live session serializer."""
    from app.services.security_service import _get_serializer

    return _get_serializer().dumps(payload)


def test_verify_session_token_rejects_malformed_json_with_brace_prefix() -> None:
    """When the payload looks like JSON (starts with ``{``) but isn't valid JSON, the function returns None."""
    token = _sign("{ not-json")
    from app.services.security_service import verify_session_token

    assert verify_session_token(token) is None


def test_verify_session_token_rejects_wrong_version() -> None:
    import json
    token = _sign(json.dumps({"v": 1, "kind": "local", "principal": "admin"}))
    from app.services.security_service import verify_session_token

    assert verify_session_token(token) is None


def test_verify_session_token_rejects_unknown_kind() -> None:
    import json
    token = _sign(json.dumps({"v": 2, "kind": "service", "principal": "admin"}))
    from app.services.security_service import verify_session_token

    assert verify_session_token(token) is None


def test_verify_session_token_rejects_blank_principal() -> None:
    import json
    token = _sign(json.dumps({"v": 2, "kind": "local", "principal": "   "}))
    from app.services.security_service import verify_session_token

    assert verify_session_token(token) is None


# -- legacy username|timestamp path ----------------------------------------------------------


def test_verify_session_token_accepts_legacy_username_pipe_timestamp() -> None:
    """v1 tokens used a ``username|timestamp`` string format — must keep working until rotated."""
    token = _sign("admin|1700000000")
    from app.services.security_service import verify_session_token

    with patch("app.services.security_service._effective_username", return_value="admin"):
        assert verify_session_token(token) == "admin"


def test_verify_session_token_rejects_legacy_format_with_wrong_user() -> None:
    token = _sign("attacker|1700000000")
    from app.services.security_service import verify_session_token

    with patch("app.services.security_service._effective_username", return_value="admin"):
        assert verify_session_token(token) is None


# -- require_admin_session --------------------------------------------------------------


def test_require_admin_session_rejects_non_admin_with_403() -> None:
    """A valid session whose principal is not an admin must raise HTTP 403."""
    from fastapi import HTTPException

    from app.services.security_service import require_admin_session

    req = MagicMock()
    req.cookies.get.return_value = "tok"
    with patch("app.services.security_service.verify_session_token", return_value="alice@example.com"):
        with patch("app.services.user_directory_service.is_user_admin", return_value=False):
            with pytest.raises(HTTPException) as exc:
                require_admin_session(req)
    assert exc.value.status_code == 403


def test_require_admin_session_returns_principal_for_admin() -> None:
    from app.services.security_service import require_admin_session

    req = MagicMock()
    req.cookies.get.return_value = "tok"
    with patch("app.services.security_service.verify_session_token", return_value="admin"):
        with patch("app.services.user_directory_service.is_user_admin", return_value=True):
            assert require_admin_session(req) == "admin"
