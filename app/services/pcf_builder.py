"""Single PCF report builder shared by MES (/productionResults) and AAS (poll) flows.

The previous code had this logic in two places (``pcf_service.create_own_emission_cf_report``
and inline in ``aas_service.process_aas_shells_for_pcf``). They computed the same totals,
emitted the same bill rows in the same order, and used the same comment templates — they
just disagreed on a few labels and timestamp helpers.

This module is the single source of truth: BOP energy bills + BOM material bills + factory
idle bills, summed into a typed PCF report.
"""
from __future__ import annotations

from typing import Any

from app.domain import PCFReport


def _share_pct(cf: float, total: float) -> float:
    return (cf / total) * 100 if total else 0.0


def build_pcf_report(
    sigi,
    *,
    bill_of_process: dict[str, float],
    materials_breakdown: dict[str, dict[str, Any]] | None,
    idle_by_activity: dict[str, float],
    work_order_name: str,
    t_start: str,
    t_end: str,
    quantity: float | int,
    batch_number: str | None,
) -> PCFReport:
    """Build a complete PCF report (BOP + BOM + Idle) and return SiGREEN's PCFReport dict.

    All three inputs are pre-computed in kg CO2e:
      * ``bill_of_process``: mapping ``process_idShort -> CF``.
      * ``materials_breakdown``: ``{material_id: {carbon_footprint_kg, total_quantity, uom, ...}}``
        as produced by ``material_pcf.material_breakdown_for``.
      * ``idle_by_activity``: ``{typeOfActivity_label -> CF}`` from ``factory_consumption_service``.
    """
    materials_breakdown = materials_breakdown or {}
    idle_by_activity = idle_by_activity or {}

    total_pcf = sum(bill_of_process.values())
    total_pcf += sum(m.get("carbon_footprint_kg", 0.0) for m in materials_breakdown.values())
    total_pcf += sum(idle_by_activity.values())

    bop_payload: list = []

    # 1. Process / "BOP" energy bills
    for process_id, cf in bill_of_process.items():
        bop_payload.append(sigi.create_process_bill(
            total=cf,
            pcf_share=_share_pct(cf, total_pcf),
            type_of_activity=f"BOP: {process_id}",
            comment="Own Energy consumption",
        ))

    # 2. BOM material bills (skip rows with no CF)
    for mat_id, mat_data in materials_breakdown.items():
        cf = float(mat_data.get("carbon_footprint_kg") or 0.0)
        if cf <= 0:
            continue
        bop_payload.append(sigi.create_process_bill(
            total=cf,
            pcf_share=_share_pct(cf, total_pcf),
            type_of_activity=f"BOM: {mat_id}",
            comment=_material_comment(mat_id, mat_data),
        ))

    # 3. Factory idle bills
    for type_of_activity, cf in idle_by_activity.items():
        if cf <= 0:
            continue
        bop_payload.append(sigi.create_process_bill(
            total=cf,
            pcf_share=_share_pct(cf, total_pcf),
            type_of_activity=type_of_activity,
            comment=f"Idle energy share for work order {work_order_name} (factory data)",
        ))

    return sigi.create_PCF_report(
        bop_payload,
        Total_PCF=total_pcf,
        quantity=quantity,
        t_start=t_start,
        t_end=t_end,
        batch_number=batch_number,
    )


def _material_comment(mat_id: str, mat_data: dict[str, Any]) -> str:
    parts = [f"Material: {mat_id}"]
    qty = mat_data.get("total_quantity")
    uom = mat_data.get("uom") or "piece"
    if qty is not None:
        parts.append(f"quantity: {qty} {uom}")
    per_unit = mat_data.get("carbon_footprint_per_unit")
    if per_unit is not None:
        parts.append(f"PCF per unit: {float(per_unit):.4f} kg CO2e (from SiGREEN)")
    return "; ".join(parts)
