"""Unit tests for :mod:`app.application.mes_workflow` — the use-case shell.

The functions in this module accept all collaborators as parameters
so they can be exercised entirely with fakes. These tests pin the
contract that:

1. Consumption submissions call every collaborator with the expected arguments.
2. Production submissions raise :class:`MissingConsumptionForWorkOrderError`
   when no prior consumption rows exist (the router translates this into HTTP 400).
3. The ``pcf_include_bom`` flag short-circuits the BOM lookup as the spec requires.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.application.mes_workflow import (
    MissingConsumptionForWorkOrderError,
    process_consumption_submission,
    process_production_submission,
)
from app.models.consumption import ConsumptionData
from app.models.production import ProductionResults
from tests.fixtures import http_payloads


# -- consumption ------------------------------------------------------------------------


def _make_consumption_payload(*, materials: list[dict] | None = None) -> ConsumptionData:
    """Build a valid ConsumptionData using the canonical fixture as a template."""
    payload = dict(http_payloads.op_1)
    payload["workOrderName"] = "PO_TEST"
    payload["workOrderOperationName"] = "OP10"
    if materials is not None:
        payload["consumedMaterials"] = materials
    else:
        payload["consumedMaterials"] = []
    return ConsumptionData.model_validate(payload)


def test_process_consumption_calls_each_collaborator_once() -> None:
    """The use case must invoke calculate → fetch_pcf → update exactly once each."""
    calls: dict[str, int] = {"calc": 0, "fetch": 0, "update": 0}

    def fake_calculate(_data: ConsumptionData) -> tuple[dict, float, float, float]:
        calls["calc"] += 1
        return {"Electricity": {"total_consumption": 10.0, "carbon_footprint_kg": 3.5}}, 10.0, 3.5, 350.0

    def fake_fetch(materials: list) -> dict:
        calls["fetch"] += 1
        return {}

    def fake_update(**kwargs: Any) -> dict:
        calls["update"] += 1
        return {"operations": {}, "materials": {}, "pcf": None, "_received": kwargs}

    data = _make_consumption_payload()
    result = process_consumption_submission(
        db_path=Path("/tmp/db.json"),
        data=data,
        calculate_energy_cf=fake_calculate,
        update_after_consumption=fake_update,
        fetch_material_pcf_map=fake_fetch,
    )

    assert calls == {"calc": 1, "fetch": 1, "update": 1}
    assert result["workOrder"] == "PO_TEST"
    assert result["operation"] == "OP10"
    assert result["total_energy_consumption_kwh"] == 10.0
    assert result["total_carbon_footprint_kg"] == 3.5
    assert result["materials_count"] == 0
    assert result["energy_types_count"] == 1
    assert result["_api_version"] == "energy-split-v2"


def test_process_consumption_uses_empty_fetcher_when_none_provided() -> None:
    """A ``None`` material PCF fetcher must not crash; it implies BOM lookup is disabled."""
    data = _make_consumption_payload()

    result = process_consumption_submission(
        db_path=Path("/tmp/db.json"),
        data=data,
        calculate_energy_cf=lambda _d: ({}, 0.0, 0.0, 0.0),
        update_after_consumption=lambda **kw: {"materials": {}},
        fetch_material_pcf_map=None,
    )

    assert result["materials_count"] == 0


# -- production -------------------------------------------------------------------------


def _production_payload() -> ProductionResults:
    payload = dict(http_payloads.prod_result_1)
    payload["workOrderName"] = "PO_TEST"
    payload["productId"] = "X100"
    payload["productName"] = "Bracket"
    return ProductionResults.model_validate(payload)


def test_process_production_raises_when_no_consumption_rows_exist() -> None:
    """The 400 mapping in the router relies on this exception being raised by the use case."""
    with pytest.raises(MissingConsumptionForWorkOrderError) as exc_info:
        process_production_submission(
            db_path=Path("/tmp/db.json"),
            data=_production_payload(),
            load_app_config_fn=lambda: {},
            get_bop_for_work_order=lambda **_kw: {},  # empty -> trigger
            get_materials_cf_breakdown=lambda *_a, **_k: {},
            create_own_emission_cf_report=lambda **_kw: {},
            submit_factory_emissions=lambda **_kw: "uuid",
            update_pcf_for_work_order=lambda **_kw: None,
        )

    assert str(exc_info.value) == "PO_TEST"


def test_process_production_skips_bom_when_pcf_include_bom_disabled() -> None:
    """When ``pcf_include_bom`` is False the materials breakdown must not be fetched (spec §5.2.5)."""
    bom_called = {"count": 0}

    def fake_get_bom(*_a: Any, **_k: Any) -> dict:
        bom_called["count"] += 1
        return {"X": {"carbon_footprint_kg": 1.0}}

    captured: dict[str, Any] = {}

    def fake_create_report(*, bill_of_process, data, materials_breakdown):
        captured["materials_breakdown"] = materials_breakdown
        return {"productCarbonFootprint": 100.0}

    process_production_submission(
        db_path=Path("/tmp/db.json"),
        data=_production_payload(),
        load_app_config_fn=lambda: {"pcf_include_bom": False},
        get_bop_for_work_order=lambda **_kw: {"OP10": 100.0},
        get_materials_cf_breakdown=fake_get_bom,
        create_own_emission_cf_report=fake_create_report,
        submit_factory_emissions=lambda **_kw: "uuid",
        update_pcf_for_work_order=lambda **_kw: None,
    )

    assert bom_called["count"] == 0
    assert captured["materials_breakdown"] is None


def test_process_production_passes_materials_breakdown_when_bom_enabled() -> None:
    """The default (``pcf_include_bom`` True or absent) must include the BOM in the report builder."""
    captured: dict[str, Any] = {}

    def fake_create_report(*, bill_of_process, data, materials_breakdown):
        captured["materials_breakdown"] = materials_breakdown
        return {"productCarbonFootprint": 110.0}

    process_production_submission(
        db_path=Path("/tmp/db.json"),
        data=_production_payload(),
        load_app_config_fn=lambda: {},  # default — pcf_include_bom missing means True
        get_bop_for_work_order=lambda **_kw: {"OP10": 100.0},
        get_materials_cf_breakdown=lambda *_a, **_k: {"Bolt": {"carbon_footprint_kg": 10.0}},
        create_own_emission_cf_report=fake_create_report,
        submit_factory_emissions=lambda **_kw: "uuid",
        update_pcf_for_work_order=lambda **_kw: None,
    )

    assert captured["materials_breakdown"] == {"Bolt": {"carbon_footprint_kg": 10.0}}


def test_process_production_returns_payload_with_uuid() -> None:
    """The returned dict is the body the router echoes; pin the keys."""
    result = process_production_submission(
        db_path=Path("/tmp/db.json"),
        data=_production_payload(),
        load_app_config_fn=lambda: {"pcf_include_bom": False},
        get_bop_for_work_order=lambda **_kw: {"OP10": 50.0},
        get_materials_cf_breakdown=lambda *_a, **_k: {},
        create_own_emission_cf_report=lambda **_kw: {"productCarbonFootprint": 50.0},
        submit_factory_emissions=lambda **_kw: "uuid-123",
        update_pcf_for_work_order=lambda **_kw: None,
    )

    assert result["workOrderName"] == "PO_TEST"
    assert result["productId"] == "X100"
    assert result["productUuid"] == "uuid-123"
    assert result["producedQuantity"] == 1
    assert "timestamp" in result
