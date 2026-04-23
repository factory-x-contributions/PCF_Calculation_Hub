"""Unit tests for the work-order bookkeeping store: legacy-shape reads, idempotent writes, deletes."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.consumption import ConsumedMaterial, ConsumptionData
from app.services.bookkeeping_service import (
    delete_work_order,
    get_bop_for_work_order,
    get_materials_cf_breakdown,
    update_after_consumption,
    update_pcf_for_work_order,
)


def _consumption(work_order: str, operation: str, materials=None) -> ConsumptionData:
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ConsumptionData(
        workOrderName=work_order,
        workOrderOperationName=operation,
        workUnit="WU",
        consumedEnergies=[],
        consumedMaterials=materials or [],
        actualStartTime=when,
        actualEndTime=when,
        timestamp=when,
    )


def test_consumption_overwrites_same_operation(tmp_path: Path) -> None:
    """Repeated calls for same workOrder + operation must replace energy, not accumulate."""
    db = tmp_path / "db.json"
    breakdown = {"Electricity": {"total_consumption": 5.0, "uom": "kWh", "carbon_intensity_gco2_per_kwh": 350, "carbon_footprint_kg": 1.75}}
    for _ in range(3):
        update_after_consumption(
            db_path=db, data=_consumption("WO", "OP10"),
            energy_breakdown=breakdown, total_energy_kwh=5.0, total_cf_kg=1.75, co2g_coeff_avg=350,
        )
    record = json.loads(db.read_text())["WO"]
    assert record["operations"]["OP10"]["energy"]["Electricity"]["total_consumption"] == 5.0


def test_get_bop_reads_legacy_format(tmp_path: Path) -> None:
    """Legacy shape: ``BOP: {operation -> CF}`` (pre-energy-split-v2 records on disk)."""
    db = tmp_path / "db.json"
    db.write_text(json.dumps({"WO_legacy": {"BOP": {"OP10": 100.0, "OP20": 50.0}}}))
    assert get_bop_for_work_order(db, "WO_legacy") == {"OP10": 100.0, "OP20": 50.0}


def test_get_bop_reads_new_split_format(tmp_path: Path) -> None:
    """New shape: ``operations[op].energy[type].carbon_footprint_kg`` summed per operation."""
    db = tmp_path / "db.json"
    db.write_text(json.dumps({"WO": {"operations": {
        "OP10": {"energy": {
            "Electricity": {"carbon_footprint_kg": 5.0},
            "CompressedAir": {"carbon_footprint_kg": 1.0},
        }}
    }}}))
    assert get_bop_for_work_order(db, "WO") == {"OP10": 6.0}


def test_get_bop_for_missing_work_order_is_empty(tmp_path: Path) -> None:
    db = tmp_path / "db.json"
    db.write_text(json.dumps({}))
    assert get_bop_for_work_order(db, "missing") == {}


def test_materials_cf_breakdown_filters_zero_footprint(tmp_path: Path) -> None:
    db = tmp_path / "db.json"
    db.write_text(json.dumps({"WO": {"materials": {
        "M_with": {"carbon_footprint_kg": 1.0, "total_quantity": 2.0, "uom": "piece"},
        "M_without": {"total_quantity": 5.0, "uom": "kg"},  # no CF — must be skipped
    }}}))
    out = get_materials_cf_breakdown(db, "WO")
    assert "M_with" in out
    assert "M_without" not in out


def test_update_pcf_persists_report(tmp_path: Path) -> None:
    db = tmp_path / "db.json"
    update_pcf_for_work_order(db, "WO", {"productCarbonFootprint": 12.5}, product_name="Widget")
    record = json.loads(db.read_text())["WO"]
    assert record["pcf"]["productCarbonFootprint"] == 12.5
    assert record["product_name"] == "Widget"


def test_delete_work_order_removes_record(tmp_path: Path) -> None:
    db = tmp_path / "db.json"
    db.write_text(json.dumps({"WO_a": {}, "WO_b": {}}))
    assert delete_work_order(db, "WO_a") is True
    assert delete_work_order(db, "WO_a") is False  # already gone
    remaining = json.loads(db.read_text())
    assert list(remaining) == ["WO_b"]


def test_consumption_records_material_with_pcf_per_unit(tmp_path: Path) -> None:
    """Per-unit PCF expands to total CF = quantity × per_unit_pcf."""
    db = tmp_path / "db.json"
    materials = [ConsumedMaterial(identifier="A", materialName="A", quantity=4.0, materialUom="piece")]
    update_after_consumption(
        db_path=db,
        data=_consumption("WO", "OP10", materials=materials),
        energy_breakdown={}, total_energy_kwh=0.0, total_cf_kg=0.0, co2g_coeff_avg=0.0,
        material_pcf_per_unit={"A": {"total": 0.5, "production": 0.4, "distribution": 0.1}},
    )
    mat = json.loads(db.read_text())["WO"]["materials"]["A"]
    assert mat["carbon_footprint_per_unit"] == 0.5
    assert mat["carbon_footprint_kg"] == 2.0
    assert mat["carbon_footprint_production_per_unit"] == 0.4
    assert mat["carbon_footprint_distribution_per_unit"] == 0.1
