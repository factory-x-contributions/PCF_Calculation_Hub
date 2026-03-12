"""Idle-time allocation strategies for the AAS pipeline.

The §5.2 spec describes idle consumption as a factory-wide bucket that is
distributed across work orders that ran during the reporting period. The
default formula has lived in
:func:`app.services.factory_consumption_service.collect_idle_cf_by_machine_for_work_order`
since the project's start; Phase 4 lifts it behind a Protocol so future
strategies (e.g. equal-share, time-weighted) can plug in without touching
call sites.

Only the AAS pipeline applies idle allocation — the MES path is left
untouched per the architectural decision to keep MES asymmetric.
"""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("pcf_creator_app")


class IdleAllocationStrategyPort(Protocol):
    """Computes the kWh share allocated to a work order from a machine's idle bucket.

    Implementations receive raw scalars rather than DB rows so they stay pure
    and easy to unit-test. The :func:`collect_idle_cf_by_machine_for_work_order`
    adapter handles row iteration, label disambiguation, and CF conversion.
    """

    def allocate_kwh(
        self,
        *,
        work_order_minutes: float,
        total_time_minutes: float,
        total_idle_minutes: float,
        idle_kwh: float,
    ) -> float:
        ...


class ProportionalShareIdleAllocation:
    """The original formula extracted verbatim from the factory consumption service.

    ``share = wo_min / (total_time - total_idle_time)``;
    ``allocated = share * idle_kWh``.

    Returns ``0.0`` when the production-time denominator is non-positive
    (legacy guard kept to match the existing branch-coverage of the
    :mod:`app.services.factory_consumption_service` tests).
    """

    def allocate_kwh(
        self,
        *,
        work_order_minutes: float,
        total_time_minutes: float,
        total_idle_minutes: float,
        idle_kwh: float,
    ) -> float:
        if work_order_minutes <= 0 or idle_kwh <= 0:
            return 0.0
        production_minutes = total_time_minutes - total_idle_minutes
        if production_minutes <= 0:
            return 0.0
        share = work_order_minutes / production_minutes
        return share * idle_kwh


__all__ = [
    "IdleAllocationStrategyPort",
    "ProportionalShareIdleAllocation",
]
