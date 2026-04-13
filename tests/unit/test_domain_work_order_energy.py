"""Unit tests for :mod:`app.domain.work_order_energy` — the canonical energy aggregators.

These were previously duplicated verbatim in
``app.services.bookkeeping_service`` (private ``_energy_total_*`` functions).
After Phase 1 consolidation the bookkeeping module re-exports them as
thin shims, so the tests here also indirectly cover that the shims still
return the same numbers.
"""
from __future__ import annotations

import pytest

from app.domain.work_order_energy import (
    energy_total_cf_kg,
    energy_total_consumption,
    operation_energy_cf_and_consumption,
)
from app.services import bookkeeping_service


# -- energy_total_cf_kg -----------------------------------------------------------------


def test_energy_total_cf_kg_empty_returns_zero() -> None:
    assert energy_total_cf_kg({}) == 0.0


def test_energy_total_cf_kg_split_by_type_sums_subblocks() -> None:
    energy = {
        "Electricity": {"carbon_footprint_kg": 100.0, "total_consumption": 200.0, "uom": "kWh"},
        "CompressedAir": {"carbon_footprint_kg": 0.21, "total_consumption": 5.0, "uom": "M3"},
    }
    assert energy_total_cf_kg(energy) == pytest.approx(100.21)


def test_energy_total_cf_kg_skips_non_dict_values_in_split_format() -> None:
    """A stray scalar in the new structure must not crash the aggregator (defensive against legacy mixes)."""
    energy = {
        "Electricity": {"carbon_footprint_kg": 7.0},
        "stray": 123,  # not a dict — should be silently ignored
    }
    assert energy_total_cf_kg(energy) == 7.0


def test_energy_total_cf_kg_legacy_flat_structure() -> None:
    legacy = {"carbon_footprint_kg": 39.7, "total_consumption": 113.4, "uom": "kWh"}
    assert energy_total_cf_kg(legacy) == 39.7


def test_energy_total_cf_kg_handles_none_carbon_footprint() -> None:
    """A missing or null ``carbon_footprint_kg`` must coerce to 0, not raise TypeError."""
    energy = {"Electricity": {"carbon_footprint_kg": None}, "CompressedAir": {}}
    assert energy_total_cf_kg(energy) == 0.0


# -- energy_total_consumption ------------------------------------------------------------


def test_energy_total_consumption_empty_returns_zero() -> None:
    assert energy_total_consumption({}) == 0.0


def test_energy_total_consumption_split_by_type_sums_subblocks() -> None:
    energy = {
        "Electricity": {"carbon_footprint_kg": 100.0, "total_consumption": 200.0, "uom": "kWh"},
        "CompressedAir": {"carbon_footprint_kg": 0.21, "total_consumption": 5.0, "uom": "M3"},
    }
    assert energy_total_consumption(energy) == 205.0


def test_energy_total_consumption_legacy_flat_structure() -> None:
    legacy = {"carbon_footprint_kg": 39.7, "total_consumption": 113.4, "uom": "kWh"}
    assert energy_total_consumption(legacy) == 113.4


# -- operation_energy_cf_and_consumption ------------------------------------------------


def test_operation_energy_legacy_numeric_bop_returns_cf_only() -> None:
    """Legacy BOP rows are bare floats; consumption is unknown so it stays at 0."""
    cf, cons = operation_energy_cf_and_consumption(111.65)
    assert cf == 111.65
    assert cons == 0.0


def test_operation_energy_structured_returns_both_totals() -> None:
    op = {
        "energy": {
            "Electricity": {"carbon_footprint_kg": 39.7, "total_consumption": 113.4},
        }
    }
    cf, cons = operation_energy_cf_and_consumption(op)
    assert cf == pytest.approx(39.7)
    assert cons == pytest.approx(113.4)


def test_operation_energy_unknown_shape_returns_zeros() -> None:
    """Anything that is not numeric or dict (e.g. a list, None) must not crash."""
    cf, cons = operation_energy_cf_and_consumption(None)  # type: ignore[arg-type]
    assert cf == 0.0
    assert cons == 0.0


# -- bookkeeping_service shims (Phase 1 re-export) --------------------------------------


def test_bookkeeping_shim_matches_domain_for_split_format() -> None:
    """The Phase 1 re-export must return identical numbers to the domain helper for every input shape."""
    energy = {
        "Electricity": {"carbon_footprint_kg": 100.0, "total_consumption": 200.0},
        "CompressedAir": {"carbon_footprint_kg": 0.21, "total_consumption": 5.0},
    }
    assert bookkeeping_service._energy_total_cf_kg(energy) == energy_total_cf_kg(energy)
    assert bookkeeping_service._energy_total_consumption(energy) == energy_total_consumption(energy)


def test_bookkeeping_shim_matches_domain_for_legacy_format() -> None:
    legacy = {"carbon_footprint_kg": 39.7, "total_consumption": 113.4, "uom": "kWh"}
    assert bookkeeping_service._energy_total_cf_kg(legacy) == energy_total_cf_kg(legacy)
    assert bookkeeping_service._energy_total_consumption(legacy) == energy_total_consumption(legacy)
