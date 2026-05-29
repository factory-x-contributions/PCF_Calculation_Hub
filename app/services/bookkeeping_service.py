# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, MutableMapping

from app.domain.work_order_energy import (
    energy_total_cf_kg as _domain_energy_total_cf_kg,
    energy_total_consumption as _domain_energy_total_consumption,
)
from app.models.consumption import ConsumptionData
from app.services.database_store_service import load_database, save_database


WorkOrderDb = Dict[str, Any]
Database = Dict[str, WorkOrderDb]


def _load_database(path: Path) -> Database:
    return load_database(path)


def _save_database(path: Path, data: Database) -> None:
    save_database(path, data)


def _ensure_work_order(db: Database, work_order: str) -> WorkOrderDb:
    record = db.get(work_order)
    if record is None:
        record = {"operations": {}, "materials": {}, "pcf": None}
        db[work_order] = record
    else:
        record.setdefault("operations", {})
        record.setdefault("materials", {})
        record.setdefault("pcf", None)
    return record


def update_after_consumption(
    *,
    db_path: Path,
    data: ConsumptionData,
    energy_breakdown: Dict[str, Dict[str, float]],
    total_energy_kwh: float,
    total_cf_kg: float,
    co2g_coeff_avg: float = 0.0,
    material_pcf_per_unit: Dict[str, float] | Dict[str, Dict[str, float]] | None = None,
) -> Dict[str, Any]:
    """Persist consumption data into the JSON database.

    The structure for each work order is:

    {
        "operations": {
            "<operationName>": {
                "energy": {
                    "Electricity": {
                        "total_consumption": <float>,
                        "uom": "kWh",
                        "carbon_intensity_gco2_per_kwh": <float>,
                        "carbon_footprint_kg": <float>
                    },
                    "CompressedAir": { ... }
                }
            }
        },
        "materials": { ... },
        "pcf": { ... }  # optional, filled at /productionResults
    }
    """

    db = _load_database(db_path)
    record = _ensure_work_order(db, data.workOrderName)

    operations: MutableMapping[str, Any] = record["operations"]
    op = operations.get(data.workOrderOperationName) or {}
    # Overwrite energy for this operation (same workOrderName + workOrderOperationName)
    # so repeated calls do not accumulate; they replace the previous consumption.
    energy_block: Dict[str, Any] = {}
    for etype, entry in energy_breakdown.items():
        energy_block[etype] = {
            "total_consumption": float(entry.get("total_consumption", 0)),
            "uom": entry.get("uom", "kWh"),
            "carbon_intensity_gco2_per_kwh": float(
                entry.get("carbon_intensity_gco2_per_kwh") or co2g_coeff_avg
            ),
            "carbon_footprint_kg": float(entry.get("carbon_footprint_kg", 0)),
        }

    op["energy"] = energy_block
    operations[data.workOrderOperationName] = op

    # Materials aggregation
    materials: MutableMapping[str, Any] = record["materials"]
    pcf_map = material_pcf_per_unit or {}
    for material in data.consumedMaterials or []:
        existing = materials.get(material.identifier) or {
            "total_quantity": 0.0,
            "uom": material.materialUom,
        }
        qty_delta = float(material.quantity)
        existing["total_quantity"] = float(existing["total_quantity"]) + qty_delta
        existing["uom"] = material.materialUom
        pcf_entry = pcf_map.get(material.identifier)
        if pcf_entry is not None:
            # Support dict {"total", "production", "distribution"} from SiGREEN
            if isinstance(pcf_entry, dict):
                total_pcf = float(pcf_entry.get("total", 0))
                prod_pcf = pcf_entry.get("production")
                dist_pcf = pcf_entry.get("distribution")
            else:
                total_pcf = float(pcf_entry)
                prod_pcf = dist_pcf = None
            existing["carbon_footprint_per_unit"] = total_pcf
            total_qty = float(existing["total_quantity"])
            existing["carbon_footprint_kg"] = total_qty * total_pcf
            if prod_pcf is not None:
                existing["carbon_footprint_production_per_unit"] = float(prod_pcf)
            if dist_pcf is not None:
                existing["carbon_footprint_distribution_per_unit"] = float(dist_pcf)
        materials[material.identifier] = existing

    _save_database(db_path, db)
    return record


def get_material_cf_for_work_order(db_path: Path, work_order_name: str) -> float:
    """Return total material carbon footprint (kg CO2e) for a work order from BOM/materials."""
    breakdown = get_materials_cf_breakdown(db_path, work_order_name)
    return sum(m.get("carbon_footprint_kg", 0.0) for m in breakdown.values())


def get_materials_cf_breakdown(
    db_path: Path, work_order_name: str
) -> Dict[str, Dict[str, Any]]:
    """Return per-material carbon footprint breakdown for a work order.

    Returns Dict[material_id, {carbon_footprint_kg, total_quantity, uom, carbon_footprint_per_unit?}].
    Only includes materials with carbon_footprint_kg > 0.
    """
    db = _load_database(db_path)
    record = db.get(work_order_name)
    if not record:
        return {}
    materials = record.get("materials") or record.get("BOM") or {}
    result: Dict[str, Dict[str, Any]] = {}
    for mat_id, mat_data in (materials.items() if isinstance(materials, dict) else []):
        if not isinstance(mat_data, dict):
            continue
        cf_kg = float(mat_data.get("carbon_footprint_kg") or 0.0)
        if cf_kg <= 0:
            continue
        result[str(mat_id)] = {
            "carbon_footprint_kg": cf_kg,
            "total_quantity": float(mat_data.get("total_quantity") or 0.0),
            "uom": (mat_data.get("uom") or "piece"),
            "carbon_footprint_per_unit": mat_data.get("carbon_footprint_per_unit"),
        }
    return result


def _energy_total_cf_kg(energy: Dict[str, Any]) -> float:
    """Backwards-compatible re-export of :func:`app.domain.work_order_energy.energy_total_cf_kg`.

    Existing callers (e.g. :mod:`app.api.routers.config`) import this private name;
    keeping the shim avoids a churn-only change while the canonical implementation
    lives in the domain module. Phase 6 deletes both the shim and any remaining callers.
    """
    return _domain_energy_total_cf_kg(energy)


def _energy_total_consumption(energy: Dict[str, Any]) -> float:
    """Backwards-compatible re-export of :func:`app.domain.work_order_energy.energy_total_consumption`."""
    return _domain_energy_total_consumption(energy)


def get_bop_for_work_order(db_path: Path, work_order_name: str) -> Dict[str, float]:
    """Return a Bills of Processes mapping from operation name to CF in kg.

    Supports both the new structured format and the legacy format:

    Legacy:
        {
            "BOP": {
                "OP10-Fraesen": 111.65,
                ...
            },
            ...
        }

    New (split by energy type):
        {
            "operations": {
                "OP10-Fraesen": {
                    "energy": {
                        "Electricity": { "carbon_footprint_kg": 111.65 },
                        "CompressedAir": { "carbon_footprint_kg": 0.21 }
                    }
                }
            }
        }
    """

    db = _load_database(db_path)
    record = db.get(work_order_name)
    if not record:
        return {}

    bop: Dict[str, float] = {}

    # Legacy structure
    legacy_bop = record.get("BOP")
    if isinstance(legacy_bop, dict):
        for op_name, cf in legacy_bop.items():
            bop[op_name] = float(cf)
        if bop:
            return bop

    # New structured format
    operations = record.get("operations", {})
    for op_name, op_data in operations.items():
        energy = op_data.get("energy") or {}
        bop[op_name] = _energy_total_cf_kg(energy)
    return bop


def update_pcf_for_work_order(
    db_path: Path,
    work_order_name: str,
    pcf_report: Dict[str, Any],
    product_name: str = "",
) -> None:
    """Persist the final PCF report and product name into the JSON database for a work order."""

    db = _load_database(db_path)
    record = _ensure_work_order(db, work_order_name)
    record["pcf"] = pcf_report
    if product_name:
        record["product_name"] = product_name
    _save_database(db_path, db)


def update_from_aas(
    db_path: Path,
    work_order_name: str,
    *,
    operations: Dict[str, Dict[str, Any]],
    materials: Dict[str, Dict[str, Any]],
    pcf_report: Dict[str, Any],
    product_name: str = "",
) -> Dict[str, Any]:
    """Persist a complete AAS work order record (operations, materials, PCF) in one step.

    Called after the AAS service calculates PCF and submits to SiGREEN.
    Uses the same database structure as the MES flow so Work Order Records
    display AAS and MES data uniformly.
    """
    db = _load_database(db_path)
    record = _ensure_work_order(db, work_order_name)
    record["operations"] = operations
    record["materials"] = materials
    record["pcf"] = pcf_report
    if product_name:
        record["product_name"] = product_name
    record["data_source"] = "aas"
    _save_database(db_path, db)
    return record


def delete_work_order(db_path: Path, work_order_name: str) -> bool:
    """Remove a work order record from the database. Returns True if deleted, False if not found."""
    db = _load_database(db_path)
    if work_order_name not in db:
        return False
    del db[work_order_name]
    _save_database(db_path, db)
    return True

