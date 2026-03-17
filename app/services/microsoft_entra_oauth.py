"""OAuth2 / OpenID Connect helpers for Microsoft Entra ID (v2 endpoint)."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient

from app.config.settings import settings

logger = logging.getLogger("pcf_creator_app")


def microsoft_oauth_is_configured() -> bool:
    return bool(
        (settings.microsoft_entra_tenant_id or "").strip()
        and (settings.microsoft_entra_client_id or "").strip()
        and (settings.microsoft_entra_client_secret or "").strip()
        and (settings.public_base_url or "").strip()
    )


def _tenant() -> str:
    return (settings.microsoft_entra_tenant_id or "").strip()


def authorization_url(*, redirect_uri: str, state: str) -> str:
    base = f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/authorize"
    q = {
        "client_id": settings.microsoft_entra_client_id.strip(),
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": state,
    }
    return f"{base}?{urlencode(q)}"


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    jwks_uri = f"https://login.microsoftonline.com/{_tenant()}/discovery/v2.0/keys"
    return PyJWKClient(jwks_uri)


def exchange_code_for_tokens(*, code: str, redirect_uri: str) -> dict[str, Any]:
    token_url = f"https://login.microsoftonline.com/{_tenant()}/oauth2/v2.0/token"
    data = {
        "client_id": settings.microsoft_entra_client_id.strip(),
        "client_secret": settings.microsoft_entra_client_secret.strip(),
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    if response.status_code != 200:
        logger.warning("Entra token exchange failed: %s %s", response.status_code, response.text[:500])
        raise ValueError("token_exchange_failed")
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError("invalid_token_response")
    return body


def validate_id_token(id_token: str) -> dict[str, Any]:
    """Verify signature, issuer, audience, expiry; return claims."""
    issuer = f"https://login.microsoftonline.com/{_tenant()}/v2.0"
    signing_key = _jwks_client().get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.microsoft_entra_client_id.strip(),
        issuer=issuer,
    )
    return claims


def principal_email_from_claims(claims: dict[str, Any]) -> str:
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").strip()
    return email.lower()
