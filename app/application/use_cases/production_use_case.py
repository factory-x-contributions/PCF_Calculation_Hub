# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""``/productionResults`` use case (MES push flow).

Encapsulates the orchestration that finalizes one ``ProductionResults`` payload:
fetch the persisted BOP for the work order, optionally fold in the material
breakdown, build the PCF report, submit it to SiGREEN, and persist the response.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.models.production import ProductionResults

logger = logging.getLogger("pcf_creator_app")


class MissingConsumptionForWorkOrderError(ValueError):
    """Raised when production is finalized without prior consumption rows for that work order.

    The HTTP layer (``app.api.routers.production``) translates this into a 400 with
    the spec-mandated detail message.
    """


class ProductionUseCase:
    """Finalize production: build PCF, submit to SiGREEN, persist."""

    def __init__(
        self,
        *,
        load_app_config: Callable[[], dict[str, Any]],
        get_bop_for_work_order: Callable[..., dict[str, float]],
        get_materials_cf_breakdown: Callable[..., dict[str, dict[str, Any]]],
        create_own_emission_cf_report: Callable[..., Any],
        submit_factory_emissions: Callable[..., str],
        update_pcf_for_work_order: Callable[..., Any],
    ) -> None:
        self._load_app_config = load_app_config
        self._get_bop_for_work_order = get_bop_for_work_order
        self._get_materials_cf_breakdown = get_materials_cf_breakdown
        self._create_own_emission_cf_report = create_own_emission_cf_report
        self._submit_factory_emissions = submit_factory_emissions
        self._update_pcf_for_work_order = update_pcf_for_work_order

    def execute(self, *, db_path: Path, data: ProductionResults) -> dict[str, Any]:
        bop = self._get_bop_for_work_order(db_path=db_path, work_order_name=data.workOrderName)
        if not bop:
            logger.warning("No consumption data found for workOrder=%s", data.workOrderName)
            raise MissingConsumptionForWorkOrderError(data.workOrderName)

        cfg = self._load_app_config()
        materials_breakdown = None
        if cfg.get("pcf_include_bom", True):
            materials_breakdown = self._get_materials_cf_breakdown(db_path, data.workOrderName)
            if not materials_breakdown:
                materials_breakdown = None

        pcf_report = self._create_own_emission_cf_report(
            bill_of_process=bop,
            data=data,
            materials_breakdown=materials_breakdown,
        )
        logger.info("PCF report created for workOrder=%s", data.workOrderName)

        product_uuid = self._submit_factory_emissions(
            product_id=data.productId, pcf_report=pcf_report
        )
        logger.info(
            "Factory emissions submitted — workOrder=%s productUuid=%s",
            data.workOrderName,
            product_uuid,
        )

        self._update_pcf_for_work_order(
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


__all__ = [
    "MissingConsumptionForWorkOrderError",
    "ProductionUseCase",
]
