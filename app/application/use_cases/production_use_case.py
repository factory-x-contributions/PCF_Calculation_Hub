"""``/productionResults`` use case (MES push flow).

Wraps :func:`app.application.mes_workflow.process_production_submission` for the
same reason its sibling :class:`ConsumptionUseCase` does — to give the router a
typed, dependency-injectable entry point. ``MissingConsumptionForWorkOrderError``
escapes through the use case unchanged so the router's existing 400 mapping
keeps working until the global :class:`PCFError` handler is wired up.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.application.mes_workflow import process_production_submission
from app.models.production import ProductionResults


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
        return process_production_submission(
            db_path=db_path,
            data=data,
            load_app_config_fn=self._load_app_config,
            get_bop_for_work_order=self._get_bop_for_work_order,
            get_materials_cf_breakdown=self._get_materials_cf_breakdown,
            create_own_emission_cf_report=self._create_own_emission_cf_report,
            submit_factory_emissions=self._submit_factory_emissions,
            update_pcf_for_work_order=self._update_pcf_for_work_order,
        )


__all__ = ["ProductionUseCase"]
