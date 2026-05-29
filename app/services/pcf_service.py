# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""SiGREEN orchestration for the MES /productionResults flow.

Delegates the report shape to ``pcf_builder.build_pcf_report`` (shared with the AAS path)
and the per-product UUID resolution to ``get_or_create_product_uuid`` (shared with AAS too).
SiGREEN client construction goes through :mod:`app.services.sigreen_factory` so all
three pipelines (MES, material lookup, AAS) share one factory site.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests as _requests

from app.config.settings import settings
from app.domain import PCFReport
from app.models.production import ProductionResults
from app.services.carbon_service import carbon_intensity_gco2_per_kwh
from app.services.factory_consumption_service import collect_idle_cf_by_machine_for_work_order
from app.services.pcf_builder import build_pcf_report
from app.services.sigreen_factory import build_sigreen_for_emissions
from app.integrations.sigreen import SiGREENInterface

logger = logging.getLogger("pcf_creator_app")


def _get_sigreen() -> SiGREENInterface:
    """Return the canonical SiGREEN client for emission submission (re-resolves factory_id)."""
    return build_sigreen_for_emissions()


def _format_iso_z(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_own_emission_cf_report(
    bill_of_process: dict[str, float],
    data: ProductionResults,
    materials_breakdown: dict[str, dict[str, Any]] | None = None,
) -> PCFReport:
    """Build a PCF report (BOP + BOM + Idle) for ``data.workOrderName`` and return SiGREEN's dict shape."""
    sigi = _get_sigreen()
    idle_by_activity = collect_idle_cf_by_machine_for_work_order(
        Path(settings.factory_database_path),
        data.workOrderName,
        carbon_intensity_gco2_per_kwh(),
    )
    return build_pcf_report(
        sigi,
        bill_of_process=bill_of_process,
        materials_breakdown=materials_breakdown,
        idle_by_activity=idle_by_activity,
        work_order_name=data.workOrderName,
        t_start=_format_iso_z(data.actualStartTime),
        t_end=_format_iso_z(data.actualEndTime),
        quantity=data.producedQuantity,
        batch_number=data.producedMtus[0] if data.producedMtus else None,
    )


def get_or_create_product_uuid(sigi: SiGREENInterface, product_id: str) -> tuple[str, bool]:
    """Resolve a SiGREEN product UUID by ``product_id``. Creates the product if it doesn't exist.

    SiGREEN sometimes returns 500 on a successful create (race / duplicate); we re-lookup
    after each failure so a live row is reported as ``(uuid, was_created=False)`` rather than
    surfacing a misleading error.
    """
    try:
        uuid = sigi.get_product_uuid(product_id=product_id)
    except _requests.HTTPError as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code != 404:
            raise RuntimeError(f"SiGREEN get_product_uuid failed for product_id={product_id!r}") from exc
        logger.info("SiGREEN: product %r not found (404), will create", product_id)
        uuid = None
    except Exception as exc:
        raise RuntimeError(f"SiGREEN get_product_uuid failed for product_id={product_id!r}") from exc

    if uuid is not None:
        return uuid, False

    if not sigi.factory_id:
        raise RuntimeError(
            "SiGREEN factory_id not configured. The SiGREEN API requires a factory when creating products. "
            "In the Config UI, set the correct factory name (e.g. OPC, Germany) and save. "
            "The factory must exist in your SiGREEN tenant."
        )

    logger.info("SiGREEN: product %r not found, creating (factory_id=%s)", product_id, sigi.factory_id)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            uuid = sigi.create_product(name=product_id, prod_id=product_id, prod_family="End-to-End-Test")
            return uuid, True
        except Exception as exc:
            last_error = exc
            logger.warning(
                "SiGREEN create_product attempt %d/3 failed for %r: %s",
                attempt + 1, product_id, exc,
            )
            time.sleep(1.0 * (attempt + 1))
            try:
                uuid = sigi.get_product_uuid(product_id=product_id)
                if uuid is not None:
                    logger.info(
                        "SiGREEN: product %r found on re-lookup after failed create (uuid=%s)",
                        product_id, uuid,
                    )
                    return uuid, False
            except Exception:
                pass

    raise RuntimeError(
        f"SiGREEN create_product failed for product_id={product_id!r} after 3 attempts: {last_error}"
    ) from last_error


def submit_factory_emissions(product_id: str, pcf_report: PCFReport) -> str:
    """Upload the PCF report to SiGREEN for ``product_id``; return the SiGREEN product UUID used."""
    sigi = _get_sigreen()
    uuid, _ = get_or_create_product_uuid(sigi, product_id)
    sigi.send_factory_emissions(product_uuid=uuid, PCF_report=pcf_report)
    return uuid
