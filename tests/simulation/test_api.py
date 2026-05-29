# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""In-process API simulation: consumption + production flows without live SiGREEN."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from tests.fixtures.http_payloads import (
    op_1,
    op_2,
    op_3,
    op_4,
    op_compressed_air,
    prod_result_1,
    wo9_consumption,
    wo9_prod_result,
)
from tests.simulation.sigreen_mock import DEFAULT_PRODUCT_UUID, patch_sigreen

pytestmark = pytest.mark.simulation

PO_40003 = "PO_40003"
EXPECTED_BOP_CF_KG = 113.4  # op_1 (111.65) + op_2 (1.75) after overwrite semantics


@pytest.fixture(autouse=True)
def _offline_material_pcf_lookup() -> None:
    """Avoid live SiGREEN calls during /consumptionData (overridden per test when needed)."""
    with patch("app.api.routers.consumption._fetch_material_pcf_map", return_value={}):
        yield


def _db_path() -> Path:
    return Path(settings.database_path)


def _load_work_order_record(work_order: str) -> dict[str, Any]:
    with _db_path().open(encoding="utf-8") as f:
        return json.load(f).get(work_order, {})


def _post_consumption(client: TestClient, *payloads: dict[str, Any]) -> None:
    for payload in payloads:
        response = client.post("/consumptionData", json=payload)
        assert response.status_code == 201, response.text


def _finalize_production(
    client: TestClient,
    payload: dict[str, Any],
    *,
    mock_sigreen: MagicMock | None = None,
) -> dict[str, Any]:
    """POST /productionResults; use ``mock_sigreen`` fixture or an explicit offline patch."""
    if mock_sigreen is None:
        with patch_sigreen():
            response = client.post("/productionResults", json=payload)
    else:
        response = client.post("/productionResults", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_consumption_and_production_flow(
    client: TestClient,
    reset_database: None,
    mock_sigreen: MagicMock,
) -> None:
    """End-to-end /consumptionData then /productionResults for PO_40003."""
    _post_consumption(client, op_1, op_2, op_3, op_4)

    body = _finalize_production(client, prod_result_1, mock_sigreen=mock_sigreen)

    assert body["workOrderName"] == PO_40003
    assert body["productId"] == prod_result_1["productId"]
    assert body["productUuid"] == DEFAULT_PRODUCT_UUID


def test_consumption_overwrite_same_operation(
    client: TestClient,
    reset_database: None,
    mock_sigreen: MagicMock,
    get_stored_pcf,
) -> None:
    """Repeated consumption for the same operation overwrites; PCF stays op_1 + op_2."""
    for _ in range(3):
        response = client.post("/consumptionData", json=op_1)
        assert response.status_code == 201, response.text

    response = client.post("/consumptionData", json=op_2)
    assert response.status_code == 201, response.text

    _finalize_production(client, prod_result_1, mock_sigreen=mock_sigreen)

    stored_pcf = get_stored_pcf(PO_40003)
    assert stored_pcf is not None
    assert stored_pcf == pytest.approx(EXPECTED_BOP_CF_KG, abs=0.01)


def test_consumption_stores_material_pcf_from_sigreen(
    client: TestClient,
    reset_database: None,
) -> None:
    """SiGREEN material PCF per unit is persisted on consumption rows."""
    mock_pcf = {
        "Screw_M6": 0.42,
        "PneumaticConnection_Festo": 1.2,
        "PackagingBox_Size15": 0.85,
    }

    with patch(
        "app.api.routers.consumption._fetch_material_pcf_map",
        return_value=mock_pcf,
    ):
        _post_consumption(client, op_4)

    materials = _load_work_order_record(PO_40003).get("materials", {})
    screw = materials["Screw_M6"]
    assert screw["carbon_footprint_per_unit"] == 0.42
    assert screw["carbon_footprint_kg"] == pytest.approx(2 * 0.42)
    assert materials["PneumaticConnection_Festo"]["carbon_footprint_per_unit"] == 1.2
    assert materials["PackagingBox_Size15"]["carbon_footprint_kg"] == 0.85


def test_consumption_stores_material_pcf_stages_from_sigreen(
    client: TestClient,
    reset_database: None,
) -> None:
    """Production and distribution stage PCF values are stored per material."""
    mock_pcf = {
        "Screw_M6": {"total": 0.42, "production": 0.35, "distribution": 0.07},
        "PneumaticConnection_Festo": {"total": 1.2, "production": 1.0, "distribution": 0.2},
        "PackagingBox_Size15": {"total": 0.85, "production": 0.7, "distribution": 0.15},
    }

    with patch("app.api.routers.consumption._fetch_material_pcf_map", return_value=mock_pcf):
        _post_consumption(client, op_4)

    materials = _load_work_order_record(PO_40003).get("materials", {})
    screw = materials["Screw_M6"]
    assert screw["carbon_footprint_per_unit"] == 0.42
    assert screw["carbon_footprint_production_per_unit"] == 0.35
    assert screw["carbon_footprint_distribution_per_unit"] == 0.07

    festo = materials["PneumaticConnection_Festo"]
    assert festo["carbon_footprint_production_per_unit"] == 1.0
    assert festo["carbon_footprint_distribution_per_unit"] == 0.2

    box = materials["PackagingBox_Size15"]
    assert box["carbon_footprint_production_per_unit"] == 0.7
    assert box["carbon_footprint_distribution_per_unit"] == 0.15


def test_consumption_skips_material_pcf_when_pcf_include_bom_disabled(
    client: TestClient,
    reset_database: None,
) -> None:
    """When pcf_include_bom is False, material carbon fields are not populated."""
    with patch("app.services.material_pcf.load_app_config") as mock_load:
        mock_load.return_value = {
            "pcf_tool": "sigreen",
            "pcf_include_bom": False,
            "sigreen_factory_name": "OPC",
            "sigreen_base_url": "",
            "material_identifier_mapping": {},
        }
        _post_consumption(client, op_4)

    materials = _load_work_order_record(PO_40003).get("materials", {})
    assert "Screw_M6" in materials
    assert "carbon_footprint_kg" not in materials["Screw_M6"]
    assert "carbon_footprint_per_unit" not in materials["Screw_M6"]


def test_consumption_material_identifier_mapping(
    client: TestClient,
    reset_database: None,
) -> None:
    """MES material codes are resolved through material_identifier_mapping."""
    mes_payload = {
        **op_4,
        "consumedMaterials": [
            {"identifier": "C_736895", "materialName": "Box", "quantity": 1, "materialUom": "piece"},
            {"identifier": "C_007578", "materialName": "Screw", "quantity": 2, "materialUom": "piece"},
        ],
    }
    mock_pcf = {
        "PackagingBox_Size15": {"total": 0.85, "production": 0.7, "distribution": 0.15},
        "Screw_M6": {"total": 0.42, "production": 0.35, "distribution": 0.07},
    }

    def mock_fetch(materials: list[Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        mapping = {"C_736895": "PackagingBox_Size15", "C_007578": "Screw_M6"}
        for m in materials:
            ident = getattr(m, "identifier", str(m))
            sigreen_id = mapping.get(ident, ident)
            if sigreen_id in mock_pcf:
                result[ident] = mock_pcf[sigreen_id]
        return result

    with patch("app.api.routers.consumption._fetch_material_pcf_map", side_effect=mock_fetch):
        _post_consumption(client, mes_payload)

    materials = _load_work_order_record(PO_40003).get("materials", {})
    assert materials["C_736895"]["carbon_footprint_per_unit"] == 0.85
    assert materials["C_736895"]["carbon_footprint_kg"] == 0.85
    assert materials["C_007578"]["carbon_footprint_per_unit"] == 0.42
    assert materials["C_007578"]["carbon_footprint_kg"] == pytest.approx(0.84)


def test_production_results_wo0009_engine_block(
    client: TestClient,
    reset_database: None,
    mock_sigreen: MagicMock,
) -> None:
    """WO-0009 flow: consumption, production finalize, PCF + BOM persisted."""
    mock_material_pcf = {
        "Screw_M6": {
            "total": 0.054166666700000005,
            "production": 0.05,
            "distribution": 0.0041666667,
        },
    }

    with patch(
        "app.api.routers.consumption._fetch_material_pcf_map",
        return_value=mock_material_pcf,
    ):
        _post_consumption(client, wo9_consumption)

    body = _finalize_production(client, wo9_prod_result, mock_sigreen=mock_sigreen)

    assert body["workOrderName"] == "WO-0009"
    assert body["productId"] == "EngineBlock"
    assert body["productUuid"] == DEFAULT_PRODUCT_UUID
    assert body["producedQuantity"] == 1

    record = _load_work_order_record("WO-0009")
    pcf = record["pcf"]
    assert pcf["factoryId"] == mock_sigreen.factory_id
    assert pcf["productCarbonFootprint"] > 0
    assert pcf["batch"]["batchNumber"] == "WO-0009"
    assert pcf["from"] == "2026-03-05T15:48:36.000Z"
    assert pcf["to"] == "2026-03-05T15:52:19.000Z"

    emission_types = [e["typeOfActivity"] for e in pcf["emissions"]]
    assert any(t.startswith("BOP:") for t in emission_types)
    assert "BOM: Screw_M6" in emission_types
    assert record.get("product_name") == "EngineBlock"

    materials = record.get("materials", {})
    assert materials["Screw_M6"]["carbon_footprint_per_unit"] > 0


def test_consumption_compressed_air_carbon_footprint(
    client: TestClient,
    reset_database: None,
) -> None:
    """CompressedAir uses Nm³ × 0.12 kWh/Nm³ × emission factor (same as electricity)."""
    with patch("app.services.carbon_service.load_app_config") as mock_load:
        mock_load.return_value = {"carbon_intensity_constant_gco2": 350}
        response = client.post("/consumptionData", json=op_compressed_air)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workOrder"] == "PO_8886"
    assert body["operation"] == "OP20-Laesern"

    expected_cf = 5 * 350 / 1000 + 5 * 0.12 * 350 / 1000
    assert body["total_carbon_footprint_kg"] == pytest.approx(expected_cf, rel=1e-3)
    assert body["total_energy_consumption_kwh"] == pytest.approx(5.0 + 5 * 0.12, rel=1e-6)
    assert body["energy_types_count"] == 2

    op_energy = (
        _load_work_order_record("PO_8886")
        .get("operations", {})
        .get("OP20-Laesern", {})
        .get("energy", {})
    )
    assert op_energy["Electricity"]["total_consumption"] == pytest.approx(5.0)
    assert op_energy["Electricity"]["carbon_footprint_kg"] == pytest.approx(1.75, rel=1e-3)
    assert op_energy["CompressedAir"]["total_consumption"] == pytest.approx(5.0)
    assert op_energy["CompressedAir"]["uom"] == "M3"
    assert op_energy["CompressedAir"]["carbon_footprint_kg"] == pytest.approx(0.21, rel=1e-3)


def test_production_results_no_consumption_returns_400(
    client: TestClient,
    reset_database: None,
) -> None:
    """POST /productionResults without prior consumption returns 400."""
    payload = {**wo9_prod_result, "workOrderName": "WO-NONEXISTENT"}
    response = client.post("/productionResults", json=payload)
    assert response.status_code == 400
    assert "No consumption data" in response.json()["detail"]
