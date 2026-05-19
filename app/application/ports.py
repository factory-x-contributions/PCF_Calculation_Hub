"""Application-layer port protocols (typing-only seams for DI and tests).

Only ports that have at least one live consumer live here. Adding a new port
is cheap; keeping an unused one drags imports and confuses readers about which
seam is the real one.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class MaterialPcfFetcherPort(Protocol):
    """Maps consumed materials from a payload to material-level PCF data."""

    def __call__(self, consumed_materials: list[Any]) -> dict[str, Any]:
        ...


class CarbonIntensityProviderPort(Protocol):
    """Returns grid carbon intensity in g CO2 per kWh for a time window.

    Two implementations live in :mod:`app.application.pipelines.carbon_intensity`:

    * :class:`ConstantCarbonIntensity` — returns the configured constant
      regardless of window.
    * :class:`GreenGridCompassCarbonIntensity` — calls the Grid Compass API
      via :class:`app.integrations.grid.GridInterface` for a window.

    Used by the AAS pipeline only; the MES path keeps its current behaviour
    (per the architectural decision to leave MES asymmetric).
    """

    def gco2_per_kwh(
        self, at_window: tuple[datetime, datetime] | None = None
    ) -> float:
        ...


__all__ = [
    "MaterialPcfFetcherPort",
    "CarbonIntensityProviderPort",
]
