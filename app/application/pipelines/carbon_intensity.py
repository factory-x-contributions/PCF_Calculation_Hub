# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Carbon intensity providers — concrete implementations of :class:`CarbonIntensityProviderPort`.

Spec FX TP2.10 §5.2.2 lists the user choice "constant value vs. dynamic Green Grid Compass"
as a configuration option. Phase 4 makes that choice a first-class strategy:

* :class:`ConstantCarbonIntensity` — returns the configured constant g CO2 / kWh
  regardless of window. Used as the safe default when no API credentials are present.
* :class:`GreenGridCompassCarbonIntensity` — calls Green Grid Compass via
  :class:`app.integrations.grid.GridInterface` for the requested time window.

These are wired in the AAS pipeline only (per the architectural decision to keep the
MES path on its existing constant lookup). They're exposed here so future use cases
(or a parity refactor of the MES path) can pick them up without re-introducing the
inline dispatch that lived in ``aas_service._carbon_intensity_for``.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.application.ports import CarbonIntensityProviderPort

logger = logging.getLogger("pcf_creator_app")

DEFAULT_CONSTANT_GCO2_PER_KWH = 350.0


class ConstantCarbonIntensity:
    """Always returns the same value, regardless of the requested window."""

    def __init__(self, value: float = DEFAULT_CONSTANT_GCO2_PER_KWH) -> None:
        if value < 0:
            raise ValueError(f"carbon intensity must be non-negative, got {value}")
        self._value = float(value)

    def gco2_per_kwh(
        self, at_window: tuple[datetime, datetime] | None = None
    ) -> float:
        return self._value


class GreenGridCompassCarbonIntensity:
    """Pulls a window-averaged carbon intensity from Green Grid Compass.

    Falls back to ``0.0`` when the API returns no data — the spec treats Grid
    Compass as advisory; a zero value lets the AAS pipeline still produce a
    PCF report (with the energy contribution muted) rather than failing.
    """

    def __init__(
        self,
        *,
        grid_client: Any,
        zone: str = "DE_LU",
    ) -> None:
        self._grid_client = grid_client
        self._zone = zone

    def gco2_per_kwh(
        self, at_window: tuple[datetime, datetime] | None = None
    ) -> float:
        if at_window is None:
            raise ValueError(
                "GreenGridCompassCarbonIntensity requires a time window; "
                "supply at_window=(start, end) when calling gco2_per_kwh()"
            )
        start, end = at_window
        try:
            avg = self._grid_client.get_avg_carbon_coeff(
                start=_to_iso_z(start), end=_to_iso_z(end), zone=self._zone
            )
        except Exception as exc:
            logger.warning("Green Grid Compass query failed (%s); falling back to 0.0", exc)
            return 0.0
        return float(avg) if avg is not None else 0.0


def _to_iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 with a trailing Z (the format Grid Compass expects)."""
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def build_carbon_intensity_provider(
    config: dict[str, Any],
    *,
    grid_client_factory: Callable[[], Any] | None = None,
) -> CarbonIntensityProviderPort:
    """Pick a carbon-intensity provider based on the runtime config.

    ``config["carbon_intensity_source"]`` selects the strategy. Anything other than
    ``"green_grid_compass"`` falls back to the constant — matching today's
    ``aas_service._carbon_intensity_for`` semantics so the refactor is value-neutral
    when the config is unchanged.

    ``grid_client_factory`` is the seam tests use to inject a fake Grid client.
    """
    source = (config.get("carbon_intensity_source") or "").strip().lower()
    if source == "green_grid_compass":
        if grid_client_factory is None:
            from app.integrations.grid import GridInterface

            grid_client = GridInterface()
        else:
            grid_client = grid_client_factory()
        return GreenGridCompassCarbonIntensity(grid_client=grid_client)
    constant = config.get("carbon_intensity_constant_gco2")
    try:
        value = float(constant) if constant is not None else DEFAULT_CONSTANT_GCO2_PER_KWH
    except (TypeError, ValueError):
        value = DEFAULT_CONSTANT_GCO2_PER_KWH
    return ConstantCarbonIntensity(value=value)


__all__ = [
    "ConstantCarbonIntensity",
    "GreenGridCompassCarbonIntensity",
    "build_carbon_intensity_provider",
    "DEFAULT_CONSTANT_GCO2_PER_KWH",
]
