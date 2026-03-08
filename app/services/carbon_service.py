from __future__ import annotations

from app.domain import EnergyBreakdown, EnergyEntry
from app.models.consumption import ConsumptionData
from app.services.config_service import load_app_config

# kWh equivalent per Nm³ of compressed air (for CO2 calculation)
COMPRESSED_AIR_KWH_PER_NM3 = 0.12


def _get_emission_factor_gco2() -> float:
    """Get CO2 emission factor in gCO2/kWh from config or default."""
    cfg = load_app_config()
    return float(cfg.get("carbon_intensity_constant_gco2") or 350)


def carbon_intensity_gco2_per_kwh() -> float:
    """Configured grid carbon intensity (g CO₂ per kWh), same as used for work-order energy CF."""
    return _get_emission_factor_gco2()


def _normalize_energy_type_label(energy_type: str, uom: str) -> str:
    """Return a display label for the energy type (Electricity, CompressedAir, etc.)."""
    et = (energy_type or "").strip()
    u = (uom or "").strip().upper()
    if et:
        # Preserve original casing for display (e.g. Electricity, CompressedAir)
        return et if et[0].isupper() else et.capitalize()
    if u in ("M3", "M³", "NM3", "NM³"):
        return "CompressedAir"
    return "Electricity"


def calculate_energy_cf(
    data: ConsumptionData,
) -> tuple[EnergyBreakdown, float, float, float]:
    """Compute per-energy-type breakdown plus aggregate totals for a work-order operation.

    Electricity: CF = kWh × emission_factor (kgCO2/kWh).
    CompressedAir: CF = Nm³ × 0.12 (kWh/Nm³) × emission_factor (kgCO2/kWh) — same factor as electricity.

    Returns: ``(energy_breakdown, total_energy_kwh, total_cf_kg, co2g_coeff_avg)``.
    """
    energy_breakdown: EnergyBreakdown = {}
    total_energy_kwh = 0.0
    total_cf_kg = 0.0
    co2g_coeff: list[float] = []
    gco2 = _get_emission_factor_gco2()

    if not data.consumedEnergies:
        return {}, 0.0, 0.0, 0.0

    for energy in data.consumedEnergies:
        energy_type_raw = (energy.type or "").strip().lower()
        uom = (energy.uom or "kWh").strip().upper()
        if uom in ("M3", "M³", "NM3", "NM³"):
            uom_stored = "M3"
        else:
            uom_stored = "kWh"

        is_compressed_air = (
            energy_type_raw == "compressedair"
            or (energy_type_raw == "compressed air")
            or uom in ("M3", "M³", "NM3", "NM³")
        )

        label = _normalize_energy_type_label(energy.type or "", uom)

        for measurement in energy.resourceUsage.measurements:
            consumption = float(measurement.consumption)

            if is_compressed_air:
                kwh_equiv = consumption * COMPRESSED_AIR_KWH_PER_NM3
                cf_kg = kwh_equiv * gco2 / 1000.0
                total_consumption = consumption  # store original Nm³
            else:
                total_consumption = consumption
                cf_kg = consumption * gco2 / 1000.0
                kwh_equiv = consumption

            total_energy_kwh += kwh_equiv
            total_cf_kg += cf_kg
            co2g_coeff.append(gco2)

            entry = energy_breakdown.get(label)
            if entry is None:
                entry = EnergyEntry(
                    total_consumption=0.0,
                    uom=uom_stored,
                    carbon_footprint_kg=0.0,
                    carbon_intensity_gco2_per_kwh=gco2,
                )
                energy_breakdown[label] = entry
            entry["total_consumption"] += total_consumption
            entry["carbon_footprint_kg"] += cf_kg

    co2g_coeff_avg = sum(co2g_coeff) / len(co2g_coeff) if co2g_coeff else 0.0
    return energy_breakdown, total_energy_kwh, total_cf_kg, co2g_coeff_avg

