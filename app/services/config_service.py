"""App configuration store + SiGREEN credential helpers.

Configuration lives in ``app/data/app_config.json`` (mirrored to S3 in deployed stages).
SiGREEN factory_id is resolved on demand from the SiGREEN API and cached in this same file.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import requests

from app.config.settings import settings
from app.storage import JsonStore

# Default SiGREEN base URL and credential-validation endpoints (UAT).
DEFAULT_SIGREEN_BASE_URL = "https://app-uat.sigreen-playground.siemens.cloud/api"
SIGREEN_TOKEN_URL = "https://siemens-00340.eu.auth0.com/oauth/token/"
SIGREEN_AUDIENCE = "https://app-uat.sigreen-playground.siemens.cloud/"

logger = logging.getLogger("pcf_creator_app")

DEFAULT_APP_CONFIG: dict[str, Any] = {
    "data_source": "",
    "pcf_tool": "",
    "sigreen_base_url": DEFAULT_SIGREEN_BASE_URL,
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


def validate_sigreen_credentials(client_id: str, client_secret: str) -> bool:
    """Try the SiGREEN OAuth token endpoint; return True iff a token comes back."""
    if not client_id or not client_secret:
        return False
    try:
        response = requests.post(
            SIGREEN_TOKEN_URL,
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": SIGREEN_AUDIENCE,
            },
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code != 200:
            return False
        return bool(response.json().get("access_token"))
    except Exception:
        return False
