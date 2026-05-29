# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for :class:`app.application.pipelines.idle_allocation.ProportionalShareIdleAllocation`.

The strategy is the canonical formula described in spec §5.2.5
(MES-scenario "Idle Time Consumption" Step 4): a work order's share of idle
energy equals its production-time fraction of the reporting period.
"""
from __future__ import annotations

import pytest

from app.application.pipelines.idle_allocation import ProportionalShareIdleAllocation


@pytest.fixture
def allocator() -> ProportionalShareIdleAllocation:
    return ProportionalShareIdleAllocation()


def test_proportional_share_simple_case(allocator: ProportionalShareIdleAllocation) -> None:
    # WO ran for 30 min; total elapsed 100 min minus 40 min idle = 60 min production.
    # Share = 30/60 = 0.5; 0.5 * 20 kWh = 10 kWh.
    result = allocator.allocate_kwh(
        work_order_minutes=30.0,
        total_time_minutes=100.0,
        total_idle_minutes=40.0,
        idle_kwh=20.0,
    )
    assert result == pytest.approx(10.0)


def test_proportional_share_zero_work_order_minutes(allocator: ProportionalShareIdleAllocation) -> None:
    """A work order that did not run at all gets nothing."""
    result = allocator.allocate_kwh(
        work_order_minutes=0.0,
        total_time_minutes=100.0,
        total_idle_minutes=40.0,
        idle_kwh=20.0,
    )
    assert result == 0.0


def test_proportional_share_zero_idle_kwh(allocator: ProportionalShareIdleAllocation) -> None:
    """No idle energy in the bucket means nothing to allocate."""
    result = allocator.allocate_kwh(
        work_order_minutes=30.0,
        total_time_minutes=100.0,
        total_idle_minutes=40.0,
        idle_kwh=0.0,
    )
    assert result == 0.0


def test_proportional_share_zero_production_time(allocator: ProportionalShareIdleAllocation) -> None:
    """When the machine was idle the entire period the formula's denominator is zero — return 0 not crash."""
    result = allocator.allocate_kwh(
        work_order_minutes=30.0,
        total_time_minutes=100.0,
        total_idle_minutes=100.0,  # entire window was idle
        idle_kwh=20.0,
    )
    assert result == 0.0


def test_proportional_share_negative_production_time(allocator: ProportionalShareIdleAllocation) -> None:
    """Defensive: malformed rows where idle > total must not produce a negative share."""
    result = allocator.allocate_kwh(
        work_order_minutes=30.0,
        total_time_minutes=50.0,
        total_idle_minutes=100.0,
        idle_kwh=20.0,
    )
    assert result == 0.0


def test_proportional_share_full_window(allocator: ProportionalShareIdleAllocation) -> None:
    """A WO that consumed all production minutes claims the entire idle bucket."""
    result = allocator.allocate_kwh(
        work_order_minutes=60.0,
        total_time_minutes=100.0,
        total_idle_minutes=40.0,
        idle_kwh=20.0,
    )
    assert result == pytest.approx(20.0)


def test_factory_consumption_service_uses_strategy(monkeypatch) -> None:
    """The adapter delegates allocation to the module-level strategy.

    Replacing ``_IDLE_ALLOCATOR`` with a stub proves the strategy is the seam,
    not a hard-coded inline formula.
    """
    from app.services import factory_consumption_service as fcs

    captured: dict = {}

    class StubAllocator:
        def allocate_kwh(self, **kwargs):
            captured.update(kwargs)
            return 7.0  # constant — proves the wiring carries the value through

    monkeypatch.setattr(fcs, "_IDLE_ALLOCATOR", StubAllocator())
    monkeypatch.setattr(fcs, "_load_factory_db", lambda *_: {
        "B1": {
            "M1": {
                "Electricity": {
                    "machine_name": "Mill",
                    "work_orders_duration": {"PO_X": 10.0},
                    "total_time": 60.0,
                    "total_idle_time": 20.0,
                    "idle_consumption_total_kwh": 5.0,
                }
            }
        }
    })
    out = fcs.collect_idle_cf_by_machine_for_work_order(
        db_path="dummy",  # type: ignore[arg-type]
        work_order_key="PO_X",
        gco2_per_kwh=300.0,
    )

    # 7.0 kWh allocated by stub * 300 g/kWh / 1000 = 2.1 kg
    label = next(iter(out))
    assert out[label] == pytest.approx(2.1)
    assert captured["work_order_minutes"] == pytest.approx(10.0)
    assert captured["idle_kwh"] == pytest.approx(5.0)
