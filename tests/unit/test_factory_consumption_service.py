"""Targeted tests for :mod:`app.services.factory_consumption_service`.

These exercise the public surface (``collect_idle_cf_by_machine_for_work_order``,
``delete_factory_building``, label disambiguation) without touching the JSON store —
the underlying ``_load_factory_db`` is monkey-patched per test.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import factory_consumption_service as fcs


@pytest.fixture
def factory_db():
    return {
        "B1": {
            "M1": {
                "Electricity": {
                    "machine_name": "Mill-A",
                    "work_orders_duration": {"PO_X": 30.0},
                    "total_time": 100.0,
                    "total_idle_time": 40.0,
                    "idle_consumption_total_kwh": 20.0,
                }
            },
            "M2": {
                "Electricity": {
                    "machine_name": "Mill-A",  # same display name → disambiguator kicks in
                    "work_orders_duration": {"PO_X": 60.0},
                    "total_time": 100.0,
                    "total_idle_time": 40.0,
                    "idle_consumption_total_kwh": 10.0,
                }
            },
        }
    }


def test_collect_idle_cf_attributes_share_to_work_order(monkeypatch, factory_db) -> None:
    monkeypatch.setattr(fcs, "_load_factory_db", lambda *_a, **_k: factory_db)
    out = fcs.collect_idle_cf_by_machine_for_work_order(
        db_path=Path("dummy"), work_order_key="PO_X", gco2_per_kwh=400.0
    )
    # Two machines with the same name → two distinct labels
    assert len(out) == 2
    # Total CF: ((30/60)*20 + (60/60)*10) * 400 / 1000 = (10 + 10) * 0.4 = 8.0 kg
    assert sum(out.values()) == pytest.approx(8.0)


def test_collect_idle_cf_returns_empty_when_no_db(monkeypatch) -> None:
    monkeypatch.setattr(fcs, "_load_factory_db", lambda *_a, **_k: {})
    out = fcs.collect_idle_cf_by_machine_for_work_order(
        db_path=Path("dummy"), work_order_key="PO_X", gco2_per_kwh=350.0
    )
    assert out == {}


def test_collect_idle_cf_returns_empty_when_work_order_key_blank(monkeypatch, factory_db) -> None:
    monkeypatch.setattr(fcs, "_load_factory_db", lambda *_a, **_k: factory_db)
    out = fcs.collect_idle_cf_by_machine_for_work_order(
        db_path=Path("dummy"), work_order_key="", gco2_per_kwh=350.0
    )
    assert out == {}


def test_collect_idle_cf_skips_rows_without_matching_work_order(monkeypatch) -> None:
    """Machines that did not run this WO must not contribute to its idle bucket."""
    db = {
        "B1": {
            "M1": {
                "Electricity": {
                    "machine_name": "Mill",
                    "work_orders_duration": {"PO_OTHER": 30.0},
                    "total_time": 100.0,
                    "total_idle_time": 40.0,
                    "idle_consumption_total_kwh": 20.0,
                }
            }
        }
    }
    monkeypatch.setattr(fcs, "_load_factory_db", lambda *_a, **_k: db)
    out = fcs.collect_idle_cf_by_machine_for_work_order(
        db_path=Path("dummy"), work_order_key="PO_X", gco2_per_kwh=350.0
    )
    assert out == {}


def test_delete_factory_building_removes_top_level_key(tmp_path) -> None:
    factory_path = tmp_path / "factory.json"
    factory_path.write_text(json.dumps({"B1": {}, "B2": {}}), encoding="utf-8")
    deleted = fcs.delete_factory_building(factory_path, "B1")
    assert deleted is True
    remaining = json.loads(factory_path.read_text(encoding="utf-8"))
    assert "B1" not in remaining
    assert "B2" in remaining


def test_delete_factory_building_returns_false_when_missing(tmp_path) -> None:
    factory_path = tmp_path / "factory.json"
    factory_path.write_text(json.dumps({"B1": {}}), encoding="utf-8")
    assert fcs.delete_factory_building(factory_path, "B-NOPE") is False
