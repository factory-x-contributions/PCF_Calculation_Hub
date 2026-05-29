# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""App configuration store + SiGREEN credential helpers.

Configuration lives in ``app/data/app_config.json`` (mirrored to S3 in deployed stages).
SiGREEN factory_id is resolved on demand from the SiGREEN API and cached in this same file.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from urllib.parse import urlparse

import requests

from app.config.settings import settings
from app.storage import JsonStore

# Default SiGREEN base URL and credential-validation endpoints (UAT).
DEFAULT_SIGREEN_BASE_URL = "https://app-uat.sigreen-playground.siemens.cloud/api"
DEFAULT_SIGREEN_TOKEN_URL = "https://siemens-00340.eu.auth0.com/oauth/token/"
DEFAULT_SIGREEN_AUDIENCE = "https://app-uat.sigreen-playground.siemens.cloud/"
SIGREEN_TOKEN_URL = DEFAULT_SIGREEN_TOKEN_URL  # backwards-compatible alias
SIGREEN_AUDIENCE = DEFAULT_SIGREEN_AUDIENCE  # backwards-compatible alias

logger = logging.getLogger("pcf_creator_app")

DEFAULT_APP_CONFIG: dict[str, Any] = {
    "data_source": "",
    "pcf_tool": "",
    "sigreen_base_url": DEFAULT_SIGREEN_BASE_URL,
    "sigreen_token_url": DEFAULT_SIGREEN_TOKEN_URL,
    "sigreen_client_id": "",
    "sigreen_client_secret": "",
    "sigreen_factory_name": "OPC",
    "sigreen_factory_id": "",
    "sigreen_product_identifier_type": "Product ID",
    "aas_base_url": "",
    "aas_asset_name": "",
    "aas_client_id": "",
    "aas_client_secret": "",
    "aas_type": "AAS (AssetFox)",
    "aas_check_period_minutes": 0,
    "carbon_intensity_source": "constant",
    "carbon_intensity_constant_gco2": 350,
    "pcf_include_bom": True,
    "material_identifier_mapping": {},
}


def _store() -> JsonStore:
    return JsonStore(
        Path(settings.app_config_path),
        s3_bucket=settings.app_config_s3_bucket,
        s3_key=settings.app_config_s3_key,
        default=DEFAULT_APP_CONFIG,
    )


def load_app_config() -> dict[str, Any]:
    """Load merged config (defaults overlaid with persisted values)."""
    return _store().load()


def save_app_config(config: dict[str, Any]) -> None:
    """Persist config locally and (when configured) to S3."""
    _store().save(config)


def get_sigreen_credentials() -> tuple[str, str]:
    cfg = load_app_config()
    return (
        (cfg.get("sigreen_client_id") or "").strip(),
        (cfg.get("sigreen_client_secret") or "").strip(),
    )


def get_sigreen_token_url(cfg: dict[str, Any] | None = None) -> str:
    """Return the configured SiGREEN OAuth token URL, falling back to the UAT default."""
    data = cfg if cfg is not None else load_app_config()
    return (data.get("sigreen_token_url") or "").strip() or DEFAULT_SIGREEN_TOKEN_URL


def infer_sigreen_audience_from_base_url(base_url: str) -> str:
    """Derive the Auth0 audience from the SiGREEN REST base URL (origin + trailing slash)."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return DEFAULT_SIGREEN_AUDIENCE
    if url.endswith("/api"):
        url = url[: -len("/api")]
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return DEFAULT_SIGREEN_AUDIENCE
    return f"{parsed.scheme}://{parsed.netloc}/"


def get_sigreen_audience(cfg: dict[str, Any] | None = None) -> str:
    """Return the SiGREEN OAuth audience inferred from the configured REST base URL."""
    data = cfg if cfg is not None else load_app_config()
    base_url = (data.get("sigreen_base_url") or "").strip() or DEFAULT_SIGREEN_BASE_URL
    return infer_sigreen_audience_from_base_url(base_url)


def ensure_sigreen_factory_id() -> None:
    """Re-resolve sigreen_factory_id from the SiGREEN API and persist it. Idempotent."""
    cfg = load_app_config()
    if cfg.get("pcf_tool") != "sigreen":
        return
    factory_name = (cfg.get("sigreen_factory_name") or "").strip() or "OPC"
    try:
        from app.integrations.sigreen import SiGREENInterface

        base_url = (cfg.get("sigreen_base_url") or "").strip() or DEFAULT_SIGREEN_BASE_URL
        sigi = SiGREENInterface(factory_name=factory_name, factory_id=None, base_url=base_url)
    except Exception as exc:
        logger.warning("Could not look up SiGREEN factory_id for %r: %s", factory_name, exc)
        return

    if sigi.factory_id:
        if (cfg.get("sigreen_factory_id") or "").strip() != sigi.factory_id:
            cfg["sigreen_factory_id"] = sigi.factory_id
            save_app_config(cfg)
            logger.info("Resolved sigreen_factory_id for %r: %s", factory_name, sigi.factory_id)
    else:
        cfg["sigreen_factory_id"] = ""
        save_app_config(cfg)
        logger.warning(
            "SiGREEN: no factory found for name %r. Check spelling and available factories.",
            factory_name,
        )


def validate_sigreen_credentials(
    client_id: str,
    client_secret: str,
    *,
    token_url: str | None = None,
    audience: str | None = None,
    base_url: str | None = None,
) -> bool:
    """Try the SiGREEN OAuth token endpoint; return True iff a token comes back."""
    if not client_id or not client_secret:
        return False
    resolved_token_url = (token_url or "").strip() or get_sigreen_token_url()
    resolved_audience = (audience or "").strip()
    if not resolved_audience:
        if (base_url or "").strip():
            resolved_audience = infer_sigreen_audience_from_base_url(base_url)
        else:
            resolved_audience = get_sigreen_audience()
    try:
        response = requests.post(
            resolved_token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": resolved_audience,
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            return False
        return bool(response.json().get("access_token"))
    except Exception:
        return False
