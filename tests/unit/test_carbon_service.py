"""Unit tests for ``app.services.carbon_service.calculate_energy_cf``.

The function is the only source of energy CF math in the app, so we cover:
electricity-only, compressed-air-only, mixed, no-data, and the emission-factor source.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models.consumption import ConsumedEnergy, ConsumptionData, Measurement, ResourceUsage
from app.services.carbon_service import COMPRESSED_AIR_KWH_PER_NM3, calculate_energy_cf


def _make_consumption(*energies: ConsumedEnergy) -> ConsumptionData:
    when = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ConsumptionData(
        workOrderName="WO_T",
        workOrderOperationName="OP",
        workUnit="WU",
        consumedEnergies=list(energies),
        actualStartTime=when,
        actualEndTime=when,
        timestamp=when,
    )


def _energy(energy_type: str, uom: str, *consumptions: float) -> ConsumedEnergy:
    return ConsumedEnergy(
        type=energy_type,
        uom=uom,
        resourceUsage=ResourceUsage(
            measurementType="DELTA",
            measurements=[
                Measurement(start=datetime(2026, 1, 1, tzinfo=timezone.utc), duration=15, consumption=c)
                for c in consumptions
            ],
        ),
    )


@pytest.fixture
def constant_emission_factor():
    """Pin the emission factor so tests don't depend on the on-disk app_config."""
    with patch("app.services.carbon_service.load_app_config") as mock:
        mock.return_value = {"carbon_intensity_constant_gco2": 350}
        yield 350.0


def test_no_energies_returns_empty(constant_emission_factor) -> None:
    breakdown, kwh, cf, gco2 = calculate_energy_cf(_make_consumption())
    assert breakdown == {}
    assert kwh == 0.0
    assert cf == 0.0
    assert gco2 == 0.0


def test_electricity_only(constant_emission_factor) -> None:
    breakdown, kwh, cf, _ = calculate_energy_cf(
        _make_consumption(_energy("Electricity", "kWh", 5.0, 5.0))
    )
    assert "Electricity" in breakdown
    assert breakdown["Electricity"]["total_consumption"] == pytest.approx(10.0)
    assert breakdown["Electricity"]["uom"] == "kWh"
    assert kwh == pytest.approx(10.0)
    assert cf == pytest.approx(10.0 * 350 / 1000)


def test_compressed_air_only(constant_emission_factor) -> None:
    breakdown, kwh, cf, _ = calculate_energy_cf(
        _make_consumption(_energy("CompressedAir", "M3", 10.0))
    )
    assert "CompressedAir" in breakdown
    assert breakdown["CompressedAir"]["uom"] == "M3"
    assert breakdown["CompressedAir"]["total_consumption"] == pytest.approx(10.0)  # original Nm³
    assert kwh == pytest.approx(10.0 * COMPRESSED_AIR_KWH_PER_NM3)
    assert cf == pytest.approx(10.0 * COMPRESSED_AIR_KWH_PER_NM3 * 350 / 1000)


def test_mixed_electricity_and_compressed_air(constant_emission_factor) -> None:
    breakdown, kwh, cf, _ = calculate_energy_cf(_make_consumption(
        _energy("Electricity", "kWh", 5.0),
        _energy("CompressedAir", "M3", 5.0),
    ))
    assert set(breakdown) == {"Electricity", "CompressedAir"}
    assert kwh == pytest.approx(5.0 + 5.0 * COMPRESSED_AIR_KWH_PER_NM3)
    assert cf == pytest.approx((5.0 + 5.0 * COMPRESSED_AIR_KWH_PER_NM3) * 350 / 1000)


def test_compressed_air_inferred_from_uom_alone(constant_emission_factor) -> None:
    """Empty energy.type plus M3 uom must still be classified as CompressedAir."""
    breakdown, _, cf, _ = calculate_energy_cf(_make_consumption(_energy("", "Nm3", 1.0)))
    assert "CompressedAir" in breakdown
    assert cf == pytest.approx(1.0 * COMPRESSED_AIR_KWH_PER_NM3 * 350 / 1000)


def test_co2g_coeff_avg_matches_factor(constant_emission_factor) -> None:
    _, _, _, gco2 = calculate_energy_cf(_make_consumption(_energy("Electricity", "kWh", 1.0, 2.0, 3.0)))
    assert gco2 == pytest.approx(350.0)
