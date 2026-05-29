# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for carbon-intensity strategies (Phase 4 of the §5.2 refactor)."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.application.pipelines.carbon_intensity import (
    DEFAULT_CONSTANT_GCO2_PER_KWH,
    ConstantCarbonIntensity,
    GreenGridCompassCarbonIntensity,
    build_carbon_intensity_provider,
)


# -- ConstantCarbonIntensity ------------------------------------------------------------


def test_constant_returns_configured_value_regardless_of_window() -> None:
    provider = ConstantCarbonIntensity(value=400.0)
    assert provider.gco2_per_kwh() == 400.0
    assert provider.gco2_per_kwh(at_window=(datetime.now(timezone.utc), datetime.now(timezone.utc))) == 400.0


def test_constant_rejects_negative_value() -> None:
    with pytest.raises(ValueError):
        ConstantCarbonIntensity(value=-1.0)


# -- GreenGridCompassCarbonIntensity ----------------------------------------------------


def test_grid_compass_calls_grid_client_with_iso_window_and_zone() -> None:
    grid_client = MagicMock()
    grid_client.get_avg_carbon_coeff.return_value = 280.5

    provider = GreenGridCompassCarbonIntensity(grid_client=grid_client, zone="DE_LU")
    start = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    result = provider.gco2_per_kwh(at_window=(start, end))

    assert result == 280.5
    grid_client.get_avg_carbon_coeff.assert_called_once_with(
        start="2026-01-01T10:00:00Z",
        end="2026-01-01T12:00:00Z",
        zone="DE_LU",
    )


def test_grid_compass_returns_zero_when_api_responds_with_none() -> None:
    """No data for the window is treated as zero — pipeline must still produce a report."""
    grid_client = MagicMock()
    grid_client.get_avg_carbon_coeff.return_value = None
    provider = GreenGridCompassCarbonIntensity(grid_client=grid_client)
    assert provider.gco2_per_kwh(
        at_window=(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    ) == 0.0


def test_grid_compass_falls_back_to_zero_on_exception(caplog) -> None:
    """Network failure must not crash the AAS pipeline; it logs and returns 0.0."""
    grid_client = MagicMock()
    grid_client.get_avg_carbon_coeff.side_effect = RuntimeError("network down")
    provider = GreenGridCompassCarbonIntensity(grid_client=grid_client)

    result = provider.gco2_per_kwh(
        at_window=(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 2, tzinfo=timezone.utc))
    )
    assert result == 0.0
    assert any("Green Grid Compass query failed" in r.message for r in caplog.records)


def test_grid_compass_requires_window() -> None:
    grid_client = MagicMock()
    provider = GreenGridCompassCarbonIntensity(grid_client=grid_client)
    with pytest.raises(ValueError):
        provider.gco2_per_kwh(at_window=None)


# -- build_carbon_intensity_provider ----------------------------------------------------


def test_build_returns_constant_by_default() -> None:
    provider = build_carbon_intensity_provider({})
    assert isinstance(provider, ConstantCarbonIntensity)
    assert provider.gco2_per_kwh() == DEFAULT_CONSTANT_GCO2_PER_KWH


def test_build_returns_constant_with_configured_value() -> None:
    provider = build_carbon_intensity_provider({"carbon_intensity_constant_gco2": 410})
    assert provider.gco2_per_kwh() == 410.0


def test_build_returns_grid_compass_when_source_is_green_grid() -> None:
    fake_grid = MagicMock()
    provider = build_carbon_intensity_provider(
        {"carbon_intensity_source": "green_grid_compass"},
        grid_client_factory=lambda: fake_grid,
    )
    assert isinstance(provider, GreenGridCompassCarbonIntensity)


def test_build_falls_back_to_default_when_constant_unparseable() -> None:
    provider = build_carbon_intensity_provider({"carbon_intensity_constant_gco2": "not-a-number"})
    assert isinstance(provider, ConstantCarbonIntensity)
    assert provider.gco2_per_kwh() == DEFAULT_CONSTANT_GCO2_PER_KWH


def test_build_unknown_source_falls_back_to_constant() -> None:
    """Unknown ``carbon_intensity_source`` strings degrade to the constant strategy."""
    provider = build_carbon_intensity_provider(
        {"carbon_intensity_source": "satellite", "carbon_intensity_constant_gco2": 500}
    )
    assert isinstance(provider, ConstantCarbonIntensity)
    assert provider.gco2_per_kwh() == 500.0
