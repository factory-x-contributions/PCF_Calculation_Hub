# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Overview dashboard aggregates over the work-order JSON database."""
from __future__ import annotations

from typing import Any

from app.domain.work_order_energy import operation_energy_cf_and_consumption


def build_overview_stats(database: dict[str, Any]) -> dict[str, Any]:
    """Build the JSON payload for `/api/overview_stats` from an in-memory DB snapshot."""
    work_order_count = len(database)
    total_operations = 0
    total_materials = 0
    total_energy_kwh = 0.0
    total_cf_kg = 0.0
    pcf_count = 0
    latest_pcf_wo: str | None = None
    latest_pcf_value: float | None = None
    work_orders: list[dict[str, Any]] = []

    for wo_name, record in database.items():
        ops = record.get("operations") or record.get("BOP") or {}
        mats = record.get("materials") or record.get("BOM") or {}
        total_operations += len(ops)
        total_materials += len(mats)

        wo_energy = 0.0
        wo_cf = 0.0
        if isinstance(ops, dict):
            for op_data in ops.values():
                cf, cons = operation_energy_cf_and_consumption(op_data)  # type: ignore[arg-type]
                wo_cf += cf
                wo_energy += cons

        total_energy_kwh += wo_energy
        total_cf_kg += wo_cf

        pcf = record.get("pcf") or record.get("PCF")
        pcf_val: float | None = None
        if isinstance(pcf, dict):
            raw = pcf.get("productCarbonFootprint")
            if raw is not None:
                pcf_val = float(raw)
                pcf_count += 1
                latest_pcf_wo = wo_name
                latest_pcf_value = pcf_val

        work_orders.append({
            "name": wo_name,
            "operations": len(ops),
            "materials": len(mats),
            "energy_kwh": round(wo_energy, 2),
            "carbon_footprint_kg": round(wo_cf, 2),
            "pcf": round(float(pcf_val), 2) if pcf_val is not None else None,
        })

    products: list[dict[str, Any]] = []
    for wo_name, record in database.items():
        pcf = record.get("pcf") or record.get("PCF")
        if not isinstance(pcf, dict) or pcf.get("productCarbonFootprint") is None:
            continue
        ops = record.get("operations") or record.get("BOP") or {}
        mats = record.get("materials") or record.get("BOM") or {}
        batch = pcf.get("batch") or {}
        emissions = pcf.get("emissions") or []
        products.append({
            "work_order": wo_name,
            "product_name": record.get("product_name", ""),
            "factory": pcf.get("factory", ""),
            "pcf_value": round(float(pcf["productCarbonFootprint"]), 2),
            "batch_number": batch.get("batchNumber", ""),
            "quantity": batch.get("quantity"),
            "processes": len(emissions),
            "materials": len(mats),
            "emission_unit": emissions[0].get("emissionUnit", "kgCO2e/piece") if emissions else "",
            "primary_data_share": emissions[0].get("primaryDataShare") if emissions else None,
        })

    return {
        "work_order_count": work_order_count,
        "total_operations": total_operations,
        "total_materials": total_materials,
        "total_energy_kwh": round(total_energy_kwh, 2),
        "total_carbon_footprint_kg": round(total_cf_kg, 2),
        "pcf_count": pcf_count,
        "latest_pcf_work_order": latest_pcf_wo,
        "latest_pcf_value": latest_pcf_value,
        "work_orders": work_orders,
        "products": products,
    }
