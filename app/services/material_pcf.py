# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Single SiGREEN material-PCF lookup used by both MES and AAS flows.

Caller-friendly: pass identifiers (or objects with ``.identifier``); returns ``MaterialPCFMap``
keyed by the *original* identifier even when ``material_identifier_mapping`` redirected the lookup.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

from app.domain import MaterialPCF, MaterialPCFMap
from app.services.config_service import load_app_config
from app.services.sigreen_factory import build_sigreen_for_material_lookup

logger = logging.getLogger("pcf_creator_app")


def _identifier_of(item: Any) -> str:
    return str(getattr(item, "identifier", "") or (item if isinstance(item, str) else "")).strip()


def _identifier_mapping() -> dict[str, str]:
    mapping = load_app_config().get("material_identifier_mapping") or {}
    return mapping if isinstance(mapping, dict) else {}


def fetch_material_pcf_map(
    materials: Iterable[Any],
    *,
    sigi=None,
    log_label: str = "SiGREEN",
) -> MaterialPCFMap:
    """Look up SiGREEN PCF per unit for each material identifier.

    ``materials`` may be a list of strings or objects with an ``identifier`` attribute.
    When ``sigi`` is given, it is used directly; otherwise the canonical
    :func:`app.services.sigreen_factory.build_sigreen_for_material_lookup` is the
    only place that knows how to construct the SiGREEN client.
    """
    if not materials:
        return {}
    cfg = load_app_config()
    if cfg.get("pcf_tool") != "sigreen" or cfg.get("pcf_include_bom") is False:
        return {}

    sigi = sigi or build_sigreen_for_material_lookup()
    if sigi is None:
        return {}

    mapping = _identifier_mapping()
    result: MaterialPCFMap = {}
    for item in materials:
        ident = _identifier_of(item)
        if not ident:
            continue
        sigreen_id = mapping.get(ident, ident)
        try:
            pcf = sigi.get_material_pcf_per_unit_kg(sigreen_id)
        except Exception as exc:
            logger.warning(
                "[%s] PCF lookup failed for %r (lookup key: %r): %s",
                log_label, ident, sigreen_id, exc,
            )
            continue
        if pcf is None:
            logger.warning(
                "[%s] no PCF data for material %r (lookup key: %r). "
                "Add it to SiGREEN Components or configure material_identifier_mapping.",
                log_label, ident, sigreen_id,
            )
            continue
        result[ident] = pcf  # type: ignore[assignment]  # SiGREENInterface returns dict-like
        if sigreen_id != ident:
            logger.info(
                "[%s] material PCF: %r (mapped from %r) = %.4f kg CO2e/unit",
                log_label, sigreen_id, ident, pcf["total"],
            )
        else:
            logger.info(
                "[%s] material PCF: %r = %.4f kg CO2e/unit (prod=%.4f dist=%.4f)",
                log_label, ident, pcf["total"], pcf.get("production", 0), pcf.get("distribution", 0),
            )
    return result


def material_breakdown_for(
    aggregated_materials: dict[str, dict[str, Any]],
    pcf_map: MaterialPCFMap,
) -> tuple[dict[str, dict[str, Any]], float]:
    """Compute the per-material CF breakdown and BOM total used by the PCF builder.

    ``aggregated_materials`` is ``{identifier: {"quantity": float, "unit": str}}``.
    Returns ``(breakdown, bom_total_kg)``.
    """
    breakdown: dict[str, dict[str, Any]] = {}
    bom_total = 0.0
    for ident, info in aggregated_materials.items():
        pcf = pcf_map.get(ident)
        if pcf is None:
            continue
        per_unit = float(pcf.get("total", 0.0))
        qty = float(info.get("quantity", 0.0))
        cf = qty * per_unit
        bom_total += cf
        entry: dict[str, Any] = {
            "carbon_footprint_kg": cf,
            "total_quantity": qty,
            "uom": info.get("unit", "piece"),
            "carbon_footprint_per_unit": per_unit,
        }
        if pcf.get("production") is not None:
            entry["carbon_footprint_production_per_unit"] = float(pcf["production"])
        if pcf.get("distribution") is not None:
            entry["carbon_footprint_distribution_per_unit"] = float(pcf["distribution"])
        breakdown[ident] = entry
    return breakdown, bom_total
