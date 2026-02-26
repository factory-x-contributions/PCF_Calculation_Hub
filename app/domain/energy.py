"""Typed shapes for energy consumption breakdown.

Stored on disk as JSON, so we use ``TypedDict`` to add static typing without changing the
runtime representation. ``EnergyBreakdown`` is a mapping ``label -> EnergyEntry`` where label
is e.g. ``"Electricity"`` or ``"CompressedAir"``.
"""
from __future__ import annotations

from typing import TypedDict


class EnergyEntry(TypedDict):
    total_consumption: float
    uom: str  # "kWh" or "M3"
    carbon_intensity_gco2_per_kwh: float
    carbon_footprint_kg: float


EnergyBreakdown = dict[str, EnergyEntry]
