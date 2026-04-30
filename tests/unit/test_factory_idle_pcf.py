"""Unit tests for factory idle-time allocation on PCF reports."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from app.services.factory_consumption_service import collect_idle_cf_by_machine_for_work_order


def test_collect_idle_cf_formula_and_label() -> None:
    """share = wo_min / (total_time - total_idle_time); cf = share * idle_kwh * g/1000."""
    db = {
        "Hall_10": {
            "DMG70": {
                "electricity": {
                    "idle_consumption_total_kwh": 100.0,
                    "total_time": 180.0,
                    "total_idle_time": 80.0,
                    "machine_name": "DMG70",
                    "work_orders_duration": {"PO_40005": 40.0},
                }
            }
        }
    }
    # prod_min = 100, share = 0.4, allocated idle kWh = 40, gCO2=350 -> kg = 40 * 0.35 = 14
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(db, f)
        p = Path(f.name)
    try:
        out = collect_idle_cf_by_machine_for_work_order(p, "PO_40005", 350.0)
        assert len(out) == 1
        key = next(iter(out))
        assert key == "Idle_Time: DMG70 (Hall_10)"
        assert abs(out[key] - 14.0) < 1e-6
    finally:
        p.unlink()


def test_collect_idle_cf_skips_zero_production_window() -> None:
    db = {
        "B": {
            "M": {
                "electricity": {
                    "idle_consumption_total_kwh": 10.0,
                    "total_time": 60.0,
                    "total_idle_time": 60.0,
                    "machine_name": "X",
                    "work_orders_duration": {"WO1": 5.0},
                }
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(db, f)
        p = Path(f.name)
    try:
        out = collect_idle_cf_by_machine_for_work_order(p, "WO1", 350.0)
        assert out == {}
    finally:
        p.unlink()


@pytest.mark.parametrize("wo_key", ["PO_40005", " PO_40005 "])
def test_work_order_key_trim_match(wo_key: str) -> None:
    db = {
        "B": {
            "M": {
                "electricity": {
                    "idle_consumption_total_kwh": 10.0,
                    "total_time": 100.0,
                    "total_idle_time": 0.0,
                    "machine_name": "M1",
                    "work_orders_duration": {"PO_40005": 50.0},
                }
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(db, f)
        p = Path(f.name)
    try:
        out = collect_idle_cf_by_machine_for_work_order(p, wo_key, 1000.0)
        assert len(out) == 1
        assert next(iter(out.keys())) == "Idle_Time: M1 (B)"
        assert abs(next(iter(out.values())) - 5.0) < 1e-6  # 50/100 * 10 * 1.0
    finally:
        p.unlink()
