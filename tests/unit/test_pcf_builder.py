"""Unit tests for ``app.services.pcf_builder.build_pcf_report`` — additivity + share math."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.pcf_builder import build_pcf_report


def _spy_sigi() -> MagicMock:
    """Return a SiGREEN-shaped mock that captures bills and assembles a minimal PCFReport."""
    sigi = MagicMock()
    sigi.create_process_bill.side_effect = lambda total, pcf_share, type_of_activity, comment: {
        "typeOfActivity": type_of_activity,
        "total": total,
        "shareOnTotal": pcf_share,
        "comment": comment,
    }
    sigi.create_PCF_report.side_effect = lambda bills, **kw: {
        "productCarbonFootprint": kw["Total_PCF"],
        "emissions": bills,
        "from": kw["t_start"],
        "to": kw["t_end"],
        "batch": {"batchNumber": kw.get("batch_number") or "Not provided", "quantity": kw["quantity"]},
    }
    return sigi


def test_total_is_sum_of_bop_bom_and_idle() -> None:
    sigi = _spy_sigi()
    report = build_pcf_report(
        sigi,
        bill_of_process={"OP10": 10.0, "OP20": 20.0},
        materials_breakdown={"M1": {"carbon_footprint_kg": 5.0}},
        idle_by_activity={"Idle_Time: DMG (Hall_1)": 4.0},
        work_order_name="WO_X",
        t_start="2026-01-01T00:00:00.000Z",
        t_end="2026-01-02T00:00:00.000Z",
        quantity=1,
        batch_number="B1",
    )
    assert report["productCarbonFootprint"] == pytest.approx(39.0)


def test_zero_cf_rows_are_skipped_for_bom_and_idle() -> None:
    sigi = _spy_sigi()
    report = build_pcf_report(
        sigi,
        bill_of_process={"OP10": 1.0},
        materials_breakdown={"M_zero": {"carbon_footprint_kg": 0.0}, "M_real": {"carbon_footprint_kg": 1.0}},
        idle_by_activity={"Idle_zero": 0.0, "Idle_real": 1.0},
        work_order_name="WO",
        t_start="t1",
        t_end="t2",
        quantity=1,
        batch_number=None,
    )
    activities = [b["typeOfActivity"] for b in report["emissions"]]
    assert "BOP: OP10" in activities
    assert "BOM: M_real" in activities
    assert "Idle_real" in activities
    assert "BOM: M_zero" not in activities
    assert "Idle_zero" not in activities


def test_share_percentages_sum_to_100() -> None:
    sigi = _spy_sigi()
    report = build_pcf_report(
        sigi,
        bill_of_process={"OP1": 1.0, "OP2": 3.0},
        materials_breakdown={"M": {"carbon_footprint_kg": 2.0}},
        idle_by_activity={"Idle": 4.0},
        work_order_name="WO",
        t_start="a",
        t_end="b",
        quantity=1,
        batch_number=None,
    )
    total_share = sum(b["shareOnTotal"] for b in report["emissions"])
    assert total_share == pytest.approx(100.0)


def test_no_data_produces_zero_total() -> None:
    sigi = _spy_sigi()
    report = build_pcf_report(
        sigi,
        bill_of_process={},
        materials_breakdown=None,
        idle_by_activity={},
        work_order_name="WO",
        t_start="a",
        t_end="b",
        quantity=1,
        batch_number=None,
    )
    assert report["productCarbonFootprint"] == 0.0
    assert report["emissions"] == []


def test_material_comment_includes_quantity_and_per_unit_pcf() -> None:
    sigi = _spy_sigi()
    report = build_pcf_report(
        sigi,
        bill_of_process={},
        materials_breakdown={"Screw_M6": {
            "carbon_footprint_kg": 0.84,
            "total_quantity": 2.0,
            "uom": "piece",
            "carbon_footprint_per_unit": 0.42,
        }},
        idle_by_activity={},
        work_order_name="WO",
        t_start="a",
        t_end="b",
        quantity=1,
        batch_number=None,
    )
    bom_bill = next(b for b in report["emissions"] if b["typeOfActivity"] == "BOM: Screw_M6")
    assert "Material: Screw_M6" in bom_bill["comment"]
    assert "quantity: 2.0 piece" in bom_bill["comment"]
    assert "PCF per unit: 0.4200" in bom_bill["comment"]
