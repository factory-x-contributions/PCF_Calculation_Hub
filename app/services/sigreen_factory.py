# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Single place to construct :class:`~app.integrations.sigreen.SiGREENInterface` clients from app config."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.services.config_service import DEFAULT_SIGREEN_BASE_URL, ensure_sigreen_factory_id, load_app_config

if TYPE_CHECKING:
    from app.integrations.sigreen import SiGREENInterface

logger = logging.getLogger("pcf_creator_app")


def _factory_name(cfg: dict) -> str:
    return (cfg.get("sigreen_factory_name") or "").strip() or "OPC"


def _base_url(cfg: dict) -> str:
    return (cfg.get("sigreen_base_url") or "").strip() or DEFAULT_SIGREEN_BASE_URL


def build_sigreen_for_emissions() -> "SiGREENInterface":
    """SiGREEN client for PCF emission submission — resolves factory_id when needed."""
    ensure_sigreen_factory_id()
    cfg = load_app_config()
    from app.integrations.sigreen import SiGREENInterface

    return SiGREENInterface(
        factory_name=_factory_name(cfg),
        factory_id=None,
        base_url=_base_url(cfg),
    )


def build_sigreen_for_material_lookup() -> "SiGREENInterface | None":
    """SiGREEN client for BOM material lookups; ``None`` when SiGREEN is disabled or init fails."""
    cfg = load_app_config()
    if cfg.get("pcf_tool") != "sigreen":
        return None
    try:
        from app.integrations.sigreen import SiGREENInterface
    except Exception as exc:
        logger.warning("SiGREEN interface unavailable for material PCF: %s", exc)
        return None

    try:
        return SiGREENInterface(factory_name=_factory_name(cfg), base_url=_base_url(cfg))
    except Exception as exc:
        logger.warning("SiGREEN interface unavailable for material PCF: %s", exc)
        return None


def build_sigreen_for_aas_pipeline() -> "SiGREENInterface | None":
    """SiGREEN client for AAS batch PCF; keeps cached ``factory_id`` from config when set."""
    ensure_sigreen_factory_id()
    cfg = load_app_config()
    from app.integrations.sigreen import SiGREENInterface

    factory_id = (cfg.get("sigreen_factory_id") or "").strip() or None
    sigi = SiGREENInterface(
        factory_name=_factory_name(cfg),
        factory_id=factory_id,
        base_url=_base_url(cfg),
    )
    if not sigi.factory_id:
        logger.warning(
            "SiGREEN factory_id not resolved for factory name %r. Product creation will fail. "
            "Save the SiGREEN config in the Config UI (with correct factory name) so factory_id is looked up and stored.",
            _factory_name(cfg),
        )
    return sigi

