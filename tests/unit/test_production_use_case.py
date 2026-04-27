"""Unit tests for :class:`app.application.use_cases.ProductionUseCase`."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.application.mes_workflow import MissingConsumptionForWorkOrderError
from app.application.use_cases.production_use_case import ProductionUseCase
from app.models.production import ProductionResults
from tests.fixtures import http_payloads


def _payload() -> ProductionResults:
    return ProductionResults.model_validate(http_payloads.prod_result_1)


_DEFAULT = object()  # sentinel — distinguishes "user passed an empty dict" from "user didn't override"


def _make_use_case(
    *,
    bop: Any = _DEFAULT,
    cfg: dict[str, Any] | None = None,
    mats: dict[str, dict[str, Any]] | None = None,
    submitted_uuid: str = "uuid-123",
) -> ProductionUseCase:
    bop_value: dict[str, float] = {"OP10": 50.0} if bop is _DEFAULT else bop  # type: ignore[assignment]
    return ProductionUseCase(
        load_app_config=lambda: cfg or {},
        get_bop_for_work_order=lambda **_kw: bop_value,
        get_materials_cf_breakdown=lambda *_a, **_k: mats or {},
        create_own_emission_cf_report=lambda **_kw: {"productCarbonFootprint": 50.0},
        submit_factory_emissions=lambda **_kw: submitted_uuid,
        update_pcf_for_work_order=lambda **_kw: None,
    )


def test_execute_happy_path_returns_uuid() -> None:
    result = _make_use_case().execute(db_path=Path("/tmp/db.json"), data=_payload())

    assert result["productUuid"] == "uuid-123"
    assert result["workOrderName"] == http_payloads.prod_result_1["workOrderName"]


def test_execute_raises_when_no_consumption_recorded() -> None:
    use_case = _make_use_case(bop={})  # empty BOP triggers the error

    with pytest.raises(MissingConsumptionForWorkOrderError):
        use_case.execute(db_path=Path("/tmp/db.json"), data=_payload())


def test_execute_skips_bom_when_pcf_include_bom_disabled() -> None:
    """The use case must propagate the ``pcf_include_bom`` flag from config to the BOM lookup."""
    bom_calls = {"count": 0}

    def fake_get_bom(*_a: Any, **_k: Any) -> dict:
        bom_calls["count"] += 1
        return {"X": {"carbon_footprint_kg": 1.0}}

    captured: dict[str, Any] = {}

    def fake_create(*, bill_of_process, data, materials_breakdown):
        captured["materials_breakdown"] = materials_breakdown
        return {"productCarbonFootprint": 50.0}

    use_case = ProductionUseCase(
        load_app_config=lambda: {"pcf_include_bom": False},
        get_bop_for_work_order=lambda **_kw: {"OP10": 50.0},
        get_materials_cf_breakdown=fake_get_bom,
        create_own_emission_cf_report=fake_create,
        submit_factory_emissions=lambda **_kw: "uuid",
        update_pcf_for_work_order=lambda **_kw: None,
    )
    use_case.execute(db_path=Path("/tmp/db.json"), data=_payload())

    assert bom_calls["count"] == 0
    assert captured["materials_breakdown"] is None
