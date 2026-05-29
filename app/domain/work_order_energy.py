# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Pure helpers for reading energy totals from persisted work-order operation records."""
from __future__ import annotations

from typing import Any


def energy_total_cf_kg(energy: dict[str, Any]) -> float:
    """Sum carbon_footprint_kg from an operation energy block (split-by-type or legacy)."""
    if not energy:
        return 0.0
    if any(isinstance(v, dict) for v in energy.values()):
        return sum(
            float(e.get("carbon_footprint_kg") or 0.0)
            for e in energy.values()
            if isinstance(e, dict)
        )
    return float(energy.get("carbon_footprint_kg") or 0.0)


def energy_total_consumption(energy: dict[str, Any]) -> float:
    """Sum energy consumption units from an operation energy block (split-by-type or legacy)."""
    if not energy:
        return 0.0
    if any(isinstance(v, dict) for v in energy.values()):
        return sum(
            float(e.get("total_consumption") or 0.0)
            for e in energy.values()
            if isinstance(e, dict)
        )
    return float(energy.get("total_consumption") or 0.0)


def operation_energy_cf_and_consumption(
    operation_value: dict[str, Any] | float,
) -> tuple[float, float]:
    """Return (carbon kg, consumption total) for one operation stored under ``operations``.

    Supports structured ``{"energy": {...}}`` rows and legacy numeric BOP floats.
    """
    if isinstance(operation_value, (int, float)):
        return float(operation_value), 0.0
    if isinstance(operation_value, dict):
        energy = operation_value.get("energy") or {}
        return energy_total_cf_kg(energy), energy_total_consumption(energy)
    return 0.0, 0.0
