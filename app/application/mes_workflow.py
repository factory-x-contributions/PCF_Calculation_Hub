"""MES-oriented orchestration.

This module binds domain models with persistence and external services without HTTP concerns.
Keeping this layer explicit (injectable collaborators) simplifies unit testing and matches
PCF Calculation Hub responsibilities: ingestion, calculation, and bookkeeping toward SiGREEN.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias

from app.models.consumption import ConsumptionData
from app.models.production import ProductionResults

MaterialPcfFetcher: TypeAlias = Callable[..., dict[str, Any]]

logger = logging.getLogger("pcf_creator_app")


class MissingConsumptionForWorkOrderError(ValueError):
    """Raised when production is finalized without prior consumption rows for that work order."""


def process_consumption_submission(
    *,
    db_path: Path,
    data: ConsumptionData,
    calculate_energy_cf: Callable[..., Any],
    update_after_consumption: Callable[..., Any],
    fetch_material_pcf_map: MaterialPcfFetcher | None,
) -> dict[str, Any]:
    """Persist one ``/consumptionData`` payload and return API body fields."""

    energy_breakdown, total_energy_kwh, total_cf_kg, co2g_coeff_avg = calculate_energy_cf(data)
    fetcher = fetch_material_pcf_map or (lambda materials: {})
    material_pcf = fetcher(data.consumedMaterials or [])

    record = update_after_consumption(
        db_path=db_path,
        data=data,
        energy_breakdown=energy_breakdown,
        total_energy_kwh=total_energy_kwh,
        total_cf_kg=total_cf_kg,
        co2g_coeff_avg=co2g_coeff_avg,
        material_pcf_per_unit=material_pcf,
    )

    return {
        "workOrder": data.workOrderName,
        "operation": data.workOrderOperationName,
        "total_energy_consumption_kwh": total_energy_kwh,
        "total_carbon_footprint_kg": total_cf_kg,
        "materials_count": len(data.consumedMaterials or []),
        "energy_types_count": len(data.consumedEnergies or []),
        "database_record": record,
        "_api_version": "energy-split-v2",
    }


def process_production_submission(
    *,
    db_path: Path,
    data: ProductionResults,
    load_app_config_fn: Callable[[], dict[str, Any]],
    get_bop_for_work_order: Callable[..., dict[str, float]],
    get_materials_cf_breakdown: Callable[..., dict[str, dict[str, Any]]],
    create_own_emission_cf_report: Callable[..., Any],
    submit_factory_emissions: Callable[..., str],
    update_pcf_for_work_order: Callable[..., Any],
) -> dict[str, Any]:
    """Run one ``/productionResults`` lifecycle: assemble PCF, submit, persist."""

    bop = get_bop_for_work_order(db_path=db_path, work_order_name=data.workOrderName)
    if not bop:
        logger.warning("No consumption data found for workOrder=%s", data.workOrderName)
        raise MissingConsumptionForWorkOrderError(data.workOrderName)

    cfg = load_app_config_fn()
    materials_breakdown = None
    if cfg.get("pcf_include_bom", True):
        materials_breakdown = get_materials_cf_breakdown(db_path, data.workOrderName)
        if not materials_breakdown:
            materials_breakdown = None

    pcf_report = create_own_emission_cf_report(
        bill_of_process=bop,
        data=data,
        materials_breakdown=materials_breakdown,
    )
    logger.info("PCF report created for workOrder=%s", data.workOrderName)

    product_uuid = submit_factory_emissions(product_id=data.productId, pcf_report=pcf_report)
    logger.info(
        "Factory emissions submitted — workOrder=%s productUuid=%s",
        data.workOrderName,
        product_uuid,
    )

    update_pcf_for_work_order(
        db_path=db_path,
        work_order_name=data.workOrderName,
        pcf_report=pcf_report,
        product_name=data.productName,
    )

    return {
        "workOrderName": data.workOrderName,
        "productId": data.productId,
        "productUuid": product_uuid,
        "producedQuantity": data.producedQuantity,
        "timestamp": data.timestamp,
    }
