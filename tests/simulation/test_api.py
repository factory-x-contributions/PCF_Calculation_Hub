# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app
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

pytestmark = pytest.mark.simulation

client = TestClient(app)


def _reset_database() -> None:
    """Clear both the work-order DB and the factory DB (idle CF rows pollute PCF if left in place)."""
    for path in (Path(settings.database_path), Path(settings.factory_database_path)):
        if path.exists():
            path.unlink()


def _get_stored_pcf(work_order: str) -> float | None:
    """Read productCarbonFootprint for a work order from the database."""
    db_path = Path(settings.database_path)
    if not db_path.exists():
        return None
    with db_path.open("r", encoding="utf-8") as f:
        db = json.load(f)
    record = db.get(work_order)
    if not record:
        return None
    pcf = record.get("pcf")
    if not pcf:
        return None
    return pcf.get("productCarbonFootprint")


def test_consumption_and_production_flow() -> None:
    """End-to-end test covering /consumptionData and /productionResults."""

    _reset_database()

    # Post consumption operations
    for payload in (op_1, op_2, op_3, op_4):
        response = client.post("/consumptionData", json=payload)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["workOrder"] == "PO_40003"
        assert "total_energy_consumption_kwh" in body
        assert "total_carbon_footprint_kg" in body

    # Final production results
    response = client.post("/productionResults", json=prod_result_1)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workOrderName"] == "PO_40003"
    assert body["productId"] == prod_result_1["productId"]
    assert "productUuid" in body


def test_consumption_overwrite_same_operation() -> None:
    """Repeated consumptionData for same workOrder+operation overwrites instead of adding.

    Posting op_1 multiple times must not accumulate total_consumption; the last call
    wins. So productCarbonFootprint after productionResults stays 113.4 (same as
    posting op_1 and op_2 once each).
    """
    _reset_database()

    # Post op_1 three times (same workOrderName + workOrderOperationName)
    for _ in range(3):
        response = client.post("/consumptionData", json=op_1)
        assert response.status_code == 201, response.text

    # Post op_2 once
    response = client.post("/consumptionData", json=op_2)
    assert response.status_code == 201, response.text

    # Finalize production
    response = client.post("/productionResults", json=prod_result_1)
    assert response.status_code == 201, response.text

    # PCF must be 113.4 (op_1 + op_2), not 3 * op_1 + op_2
    stored_pcf = _get_stored_pcf("PO_40003")
    assert stored_pcf is not None, "PCF should be stored after productionResults"
    assert abs(stored_pcf - 113.4) < 0.01, (
        f"productCarbonFootprint should be 113.4 (overwrite), got {stored_pcf}"
    )


def test_consumption_stores_material_pcf_from_sigreen() -> None:
    """When SiGREEN returns PCF per unit for materials, carbon_footprint_per_unit and carbon_footprint_kg are stored."""
    _reset_database()

    mock_pcf = {
        "Screw_M6": 0.42,
        "PneumaticConnection_Festo": 1.2,
        "PackagingBox_Size15": 0.85,
    }

    with patch(
        "app.api.routers.consumption._fetch_material_pcf_map",
        return_value=mock_pcf,
    ):
        response = client.post("/consumptionData", json=op_4)
        assert response.status_code == 201, response.text

    db_path = Path(settings.database_path)
    assert db_path.exists()
    with db_path.open("r", encoding="utf-8") as f:
        db = json.load(f)
    record = db.get("PO_40003")
    assert record is not None
    materials = record.get("materials", {})
    assert "Screw_M6" in materials
    screw = materials["Screw_M6"]
    assert screw["carbon_footprint_per_unit"] == 0.42
    assert screw["carbon_footprint_kg"] == 2 * 0.42  # quantity 2
    assert materials["PneumaticConnection_Festo"]["carbon_footprint_per_unit"] == 1.2
    assert materials["PneumaticConnection_Festo"]["carbon_footprint_kg"] == 1.2
    assert materials["PackagingBox_Size15"]["carbon_footprint_per_unit"] == 0.85
    assert materials["PackagingBox_Size15"]["carbon_footprint_kg"] == 0.85


def test_consumption_stores_material_pcf_stages_from_sigreen() -> None:
    """When SiGREEN returns production and distribution stages, both are persisted per material."""
    _reset_database()

    mock_pcf = {
        "Screw_M6": {"total": 0.42, "production": 0.35, "distribution": 0.07},
        "PneumaticConnection_Festo": {"total": 1.2, "production": 1.0, "distribution": 0.2},
        "PackagingBox_Size15": {"total": 0.85, "production": 0.7, "distribution": 0.15},
    }

    with patch("app.api.routers.consumption._fetch_material_pcf_map", return_value=mock_pcf):
        response = client.post("/consumptionData", json=op_4)
        assert response.status_code == 201, response.text

    with Path(settings.database_path).open("r", encoding="utf-8") as f:
        materials = json.load(f).get("PO_40003", {}).get("materials", {})

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


def test_consumption_skips_material_pcf_when_pcf_include_bom_disabled() -> None:
    """When pcf_include_bom is False, material PCF is not fetched and materials have no carbon_footprint."""
    _reset_database()

    with patch("app.services.material_pcf.load_app_config") as mock_load:
        mock_load.return_value = {
            "pcf_tool": "sigreen",
            "pcf_include_bom": False,
            "sigreen_factory_name": "OPC",
            "sigreen_base_url": "",
            "material_identifier_mapping": {},
        }
        response = client.post("/consumptionData", json=op_4)
        assert response.status_code == 201, response.text

    db_path = Path(settings.database_path)
    with db_path.open("r", encoding="utf-8") as f:
        db = json.load(f)
    materials = db.get("PO_40003", {}).get("materials", {})
    assert "Screw_M6" in materials
    assert "carbon_footprint_kg" not in materials["Screw_M6"]
    assert "carbon_footprint_per_unit" not in materials["Screw_M6"]


def test_consumption_material_identifier_mapping() -> None:
    """When material_identifier_mapping is configured, MES codes are looked up via SiGREEN identifiers."""
    _reset_database()

    # op_4 uses Screw_M6, PneumaticConnection_Festo, PackagingBox_Size15.
    # Simulate MES sending different codes - map them to SiGREEN ids.
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

    def mock_fetch(materials):
        # Simulate mapping: C_736895 -> PackagingBox_Size15, C_007578 -> Screw_M6
        result = {}
        for m in materials:
            ident = getattr(m, "identifier", str(m))
            sigreen_id = {"C_736895": "PackagingBox_Size15", "C_007578": "Screw_M6"}.get(ident, ident)
            if sigreen_id in mock_pcf:
                result[ident] = mock_pcf[sigreen_id]
        return result

    with patch("app.api.routers.consumption._fetch_material_pcf_map", side_effect=mock_fetch):
        response = client.post("/consumptionData", json=mes_payload)
        assert response.status_code == 201, response.text

    db_path = Path(settings.database_path)
    with db_path.open("r", encoding="utf-8") as f:
        db = json.load(f)
    materials = db.get("PO_40003", {}).get("materials", {})
    assert materials["C_736895"]["carbon_footprint_per_unit"] == 0.85
    assert materials["C_736895"]["carbon_footprint_kg"] == 0.85
    assert materials["C_007578"]["carbon_footprint_per_unit"] == 0.42
    assert materials["C_007578"]["carbon_footprint_kg"] == 0.84  # 2 * 0.42


def test_production_results_wo0009_engine_block() -> None:
    """Full /consumptionData + /productionResults flow for WO-0009 EngineBlock.

    Mocks SiGREEN so the test is self-contained (no external API calls).
    Validates:
      - 201 response with expected fields
      - PCF stored in database with correct structure
      - BOM material PCF included in total when pcf_include_bom is True
    """
    _reset_database()

    mock_material_pcf = {
        "Screw_M6": {"total": 0.054166666700000005, "production": 0.05, "distribution": 0.0041666667},
    }

    with patch("app.api.routers.consumption._fetch_material_pcf_map", return_value=mock_material_pcf):
        resp = client.post("/consumptionData", json=wo9_consumption)
        assert resp.status_code == 201, resp.text

    fake_uuid = "0198c1dc-94d1-73d7-bc80-b84a10b639d8"

    with patch("app.services.pcf_service._get_sigreen") as mock_sg:
        mock_sigi = mock_sg.return_value
        mock_sigi.factory_id = "01989e05-9adf-7bb2-83eb-4f5090fed02a"
        mock_sigi.factory_name = "OPC"
        mock_sigi.create_process_bill.side_effect = lambda total, pcf_share, type_of_activity, comment: {
            "typeOfActivity": type_of_activity,
            "total": total,
            "primaryDataShare": 75.8,
            "shareOnTotal": pcf_share,
            "emissionUnit": "kgCO2e/piece",
            "comment": comment,
            "fossil": 500.8,
            "biogenic": 0,
            "dLuc": 0,
            "landUse": 0,
            "aircraft": 0,
        }
        mock_sigi.create_PCF_report.side_effect = lambda bop, **kw: {
            "revision": "1",
            "factoryId": mock_sigi.factory_id,
            "factory": "OPC",
            "from": kw.get("t_start", ""),
            "to": kw.get("t_end", ""),
            "batch": {
                "batchNumber": kw.get("batch_number", ""),
                "quantity": kw.get("quantity", 1),
                "assessmentYear": 2026,
                "dataSource": "PCF Creator APP V-1.0",
                "comment": "First batch of the year",
            },
            "productCarbonFootprint": kw.get("Total_PCF", 0),
            "emissions": bop,
            "comment": "Emission data from DMG Mori",
            "sourceSystem": "API",
        }
        mock_sigi.get_product_uuid.return_value = fake_uuid
        mock_sigi.send_factory_emissions.return_value = None

        resp = client.post("/productionResults", json=wo9_prod_result)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["workOrderName"] == "WO-0009"
    assert body["productId"] == "EngineBlock"
    assert body["productUuid"] == fake_uuid
    assert body["producedQuantity"] == 1

    db_path = Path(settings.database_path)
    with db_path.open("r", encoding="utf-8") as f:
        db = json.load(f)
    record = db.get("WO-0009")
    assert record is not None

    # PCF report stored
    pcf = record.get("pcf")
    assert pcf is not None
    assert pcf["factoryId"] == "01989e05-9adf-7bb2-83eb-4f5090fed02a"
    assert pcf["productCarbonFootprint"] > 0
    assert pcf["batch"]["batchNumber"] == "WO-0009"
    assert pcf["from"] == "2026-03-05T15:48:36.000Z"
    assert pcf["to"] == "2026-03-05T15:52:19.000Z"

    emission_types = [e["typeOfActivity"] for e in pcf["emissions"]]
    assert any(t.startswith("BOP:") for t in emission_types)
    assert "BOM: Screw_M6" in emission_types

    # Product name persisted
    assert record.get("product_name") == "EngineBlock"

    # Materials still present with PCF data
    materials = record.get("materials", {})
    assert "Screw_M6" in materials
    assert materials["Screw_M6"]["carbon_footprint_per_unit"] > 0


def test_consumption_compressed_air_carbon_footprint() -> None:
    """CompressedAir consumption uses CO2 = Nm³ × 0.12 (kWh/Nm³) × emission_factor (same as electricity)."""
    _reset_database()

    # Ensure deterministic emission factor (350 gCO2/kWh)
    with patch("app.services.carbon_service.load_app_config") as mock_load:
        mock_load.return_value = {"carbon_intensity_constant_gco2": 350}

        response = client.post("/consumptionData", json=op_compressed_air)
        assert response.status_code == 201, response.text

    body = response.json()
    assert body["workOrder"] == "PO_8886"
    assert body["operation"] == "OP20-Laesern"

    # Electricity: 5 kWh × 350/1000 = 1.75 kg CO2e
    # CompressedAir: 5 Nm³ × 0.12 kWh/Nm³ × 350/1000 = 0.21 kg CO2e
    # Total: 1.96 kg CO2e
    expected_cf = 5 * 350 / 1000 + 5 * 0.12 * 350 / 1000
    assert abs(body["total_carbon_footprint_kg"] - expected_cf) < 0.001, (
        f"Expected total_carbon_footprint_kg ≈ {expected_cf}, got {body['total_carbon_footprint_kg']}"
    )
    assert body["total_carbon_footprint_kg"] == pytest.approx(1.96, rel=1e-3)

    # Total energy: 5 kWh (elec) + 5×0.12 = 5.6 kWh equivalent
    expected_kwh = 5.0 + 5 * 0.12
    assert body["total_energy_consumption_kwh"] == pytest.approx(expected_kwh, rel=1e-6)

    assert body["energy_types_count"] == 2  # Electricity + CompressedAir

    # Database stores energy split by type (not combined)
    db_path = Path(settings.database_path)
    with db_path.open("r", encoding="utf-8") as f:
        db = json.load(f)
    op_energy = db.get("PO_8886", {}).get("operations", {}).get("OP20-Laesern", {}).get(
        "energy", {}
    )
    assert "Electricity" in op_energy, "Electricity should be stored as separate key"
    assert "CompressedAir" in op_energy, "CompressedAir should be stored as separate key"
    assert op_energy["Electricity"]["total_consumption"] == pytest.approx(5.0)
    assert op_energy["Electricity"]["carbon_footprint_kg"] == pytest.approx(1.75, rel=1e-3)
    assert op_energy["CompressedAir"]["total_consumption"] == pytest.approx(5.0)
    assert op_energy["CompressedAir"]["uom"] == "M3"
    assert op_energy["CompressedAir"]["carbon_footprint_kg"] == pytest.approx(0.21, rel=1e-3)


def test_production_results_no_consumption_returns_400() -> None:
    """POST /productionResults without prior consumption data returns 400."""
    _reset_database()
    payload = {**wo9_prod_result, "workOrderName": "WO-NONEXISTENT"}
    resp = client.post("/productionResults", json=payload)
    assert resp.status_code == 400
    assert "No consumption data" in resp.json()["detail"]
