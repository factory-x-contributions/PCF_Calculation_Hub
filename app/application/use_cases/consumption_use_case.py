"""``/consumptionData`` use case (MES push flow).

Phase 5 lifts the orchestration out of the router into a class so the
collaborators are explicit and the call graph is easy to follow:

    Router (HTTP) → ConsumptionUseCase → process_consumption_submission

Today's implementation still delegates to the legacy
:func:`app.application.mes_workflow.process_consumption_submission` so the
behaviour and existing test patches stay valid; Phase 6 deletes that
intermediate function and folds its body into :meth:`ConsumptionUseCase.execute`.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.application.mes_workflow import process_consumption_submission
from app.application.ports import MaterialPcfFetcherPort
from app.models.consumption import ConsumptionData


class ConsumptionUseCase:
    """Persist one ``/consumptionData`` payload and return the API response body.

    Collaborators are injected as plain callables rather than ``ABC`` instances
    because that's how the legacy ``process_consumption_submission`` already
    accepted them — no behavioural change in this phase, just a class boundary.
    """

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
        return process_consumption_submission(
            db_path=db_path,
            data=data,
            calculate_energy_cf=self._calculate_energy_cf,
            update_after_consumption=self._update_after_consumption,
            fetch_material_pcf_map=self._fetch_material_pcf_map,
        )


__all__ = ["ConsumptionUseCase"]
