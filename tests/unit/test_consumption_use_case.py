"""Unit tests for :class:`app.application.use_cases.ConsumptionUseCase`.

Drives the use case with fake collaborators so the orchestration class is
exercised in isolation from the actual carbon math, JSON store, and SiGREEN
network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.application.use_cases.consumption_use_case import ConsumptionUseCase
from app.models.consumption import ConsumptionData
from tests.fixtures import http_payloads


def _payload() -> ConsumptionData:
    return ConsumptionData.model_validate(http_payloads.op_1)


def test_execute_invokes_each_collaborator_once() -> None:
    calls: dict[str, int] = {"calc": 0, "fetch": 0, "update": 0}

    def fake_calc(_data: ConsumptionData) -> tuple[dict, float, float, float]:
        calls["calc"] += 1
        return {"Electricity": {"total_consumption": 50.0, "carbon_footprint_kg": 17.5}}, 50.0, 17.5, 350.0

    def fake_fetch(materials: list) -> dict:
        calls["fetch"] += 1
        return {}

    def fake_update(**kwargs: Any) -> dict:
        calls["update"] += 1
        return {"operations": {}, "materials": {}, "pcf": None}

    use_case = ConsumptionUseCase(
        calculate_energy_cf=fake_calc,
        update_after_consumption=fake_update,
        fetch_material_pcf_map=fake_fetch,
    )
    result = use_case.execute(db_path=Path("/tmp/db.json"), data=_payload())

    assert calls == {"calc": 1, "fetch": 1, "update": 1}
    assert result["workOrder"] == http_payloads.op_1["workOrderName"]
    assert result["total_energy_consumption_kwh"] == 50.0
    assert result["total_carbon_footprint_kg"] == 17.5


def test_execute_passes_through_when_fetcher_is_none() -> None:
    """A None fetcher (e.g. SiGREEN disabled) must not be invoked; the use case treats it as empty."""
    use_case = ConsumptionUseCase(
        calculate_energy_cf=lambda _d: ({}, 0.0, 0.0, 0.0),
        update_after_consumption=lambda **kw: {"materials": {}},
        fetch_material_pcf_map=None,
    )

    result = use_case.execute(db_path=Path("/tmp/db.json"), data=_payload())

    assert result["materials_count"] >= 0  # no crash
