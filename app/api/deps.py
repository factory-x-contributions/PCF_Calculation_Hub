# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""FastAPI dependency factories for composition roots (override in tests via ``dependency_overrides``)."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends

from app.application.ports import MaterialPcfFetcherPort
from app.application.use_cases.consumption_use_case import ConsumptionUseCase
from app.application.use_cases.production_use_case import ProductionUseCase
from app.config.settings import settings
from app.services.config_service import load_app_config


def get_database_path() -> Path:
    """Work-order JSON database path (respects test monkeypatches on ``settings``)."""
    return Path(settings.database_path)


DatabasePathDep = Annotated[Path, Depends(get_database_path)]


def get_material_pcf_fetcher() -> MaterialPcfFetcherPort:
    """Default SiGREEN-backed material PCF resolver for ``/consumptionData``.

    Resolved through the seam at :func:`app.api.routers.consumption._fetch_material_pcf_map`
    (rather than directly from :mod:`app.services.material_pcf`) so existing simulation
    tests that patch the router-level seam continue to work after the Phase 5 wiring.
    """
    from app.api.routers.consumption import _fetch_material_pcf_map

    return _fetch_material_pcf_map


MaterialPcfFetcherDep = Annotated[MaterialPcfFetcherPort, Depends(get_material_pcf_fetcher)]


def get_app_config() -> dict[str, Any]:
    """Snapshot of the runtime app configuration for one request."""
    return load_app_config()


AppConfigDep = Annotated[dict[str, Any], Depends(get_app_config)]


def get_consumption_use_case(
    fetch_material_pcf_map: MaterialPcfFetcherDep,
) -> ConsumptionUseCase:
    """Build the use case for one ``/consumptionData`` request.

    Reads the pure-domain calc and the bookkeeping persistence from their
    canonical modules; the only DI seam exposed to tests is the SiGREEN-backed
    material fetcher, which can be overridden via ``app.dependency_overrides``
    *or* the legacy module-level ``patch`` on
    ``app.api.routers.consumption._fetch_material_pcf_map``.
    """
    from app.services.bookkeeping_service import update_after_consumption
    from app.services.carbon_service import calculate_energy_cf

    return ConsumptionUseCase(
        calculate_energy_cf=calculate_energy_cf,
        update_after_consumption=update_after_consumption,
        fetch_material_pcf_map=fetch_material_pcf_map,
    )


def get_production_use_case() -> ProductionUseCase:
    """Build the use case for one ``/productionResults`` request."""
    from app.services.bookkeeping_service import (
        get_bop_for_work_order,
        get_materials_cf_breakdown,
        update_pcf_for_work_order,
    )
    from app.services.config_service import load_app_config
    from app.services.pcf_service import create_own_emission_cf_report, submit_factory_emissions

    return ProductionUseCase(
        load_app_config=load_app_config,
        get_bop_for_work_order=get_bop_for_work_order,
        get_materials_cf_breakdown=get_materials_cf_breakdown,
        create_own_emission_cf_report=create_own_emission_cf_report,
        submit_factory_emissions=submit_factory_emissions,
        update_pcf_for_work_order=update_pcf_for_work_order,
    )


ConsumptionUseCaseDep = Annotated[ConsumptionUseCase, Depends(get_consumption_use_case)]
ProductionUseCaseDep = Annotated[ProductionUseCase, Depends(get_production_use_case)]
