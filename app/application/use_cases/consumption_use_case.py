"""``/consumptionData`` use case (MES push flow).

Encapsulates the orchestration that turns one ``ConsumptionData`` payload into
a persisted work-order record and the response body the router returns.
Collaborators are injected as plain callables so the unit tests can drive the
class with fakes without touching the JSON store or the SiGREEN network.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.application.ports import MaterialPcfFetcherPort
from app.models.consumption import ConsumptionData


class ConsumptionUseCase:
    """Persist one ``/consumptionData`` payload and return the API response body."""

    def __init__(
        self,
        *,
        calculate_energy_cf: Callable[..., Any],
        update_after_consumption: Callable[..., Any],
        fetch_material_pcf_map: MaterialPcfFetcherPort | None,
    ) -> None:
        self._calculate_energy_cf = calculate_energy_cf
        self._update_after_consumption = update_after_consumption
        self._fetch_material_pcf_map = fetch_material_pcf_map

    def execute(self, *, db_path: Path, data: ConsumptionData) -> dict[str, Any]:
        energy_breakdown, total_energy_kwh, total_cf_kg, co2g_coeff_avg = (
            self._calculate_energy_cf(data)
        )
        fetcher = self._fetch_material_pcf_map or (lambda _materials: {})
        material_pcf = fetcher(data.consumedMaterials or [])

        record = self._update_after_consumption(
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


__all__ = ["ConsumptionUseCase"]
