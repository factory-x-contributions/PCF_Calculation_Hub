from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.models.general_consumption import GeneralConsumptionPayload
from app.storage import JsonStore

logger = logging.getLogger("pcf_creator_app")

# Nested: building_id -> machine_id -> energy_type -> metrics
FactoryDb = dict[str, Any]


def _factory_store(path: Path) -> JsonStore:
    return JsonStore(
        path,
        s3_bucket=settings.factory_database_s3_bucket,
        s3_key=settings.factory_database_s3_key,
    )


def _load_factory_db(path: Path) -> FactoryDb:
    return _factory_store(path).load()


def _save_factory_db(path: Path, data: FactoryDb) -> None:
    _factory_store(path).save(data)


def _coerce_publication_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _publication_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _node_total_time(node: dict[str, Any]) -> float:
    if "total_time" in node:
        return float(node["total_time"])
    return float(node.get("total_duration_minutes", 0.0))


def _node_total_idle_time(node: dict[str, Any]) -> float:
    if "total_idle_time" in node:
        return float(node["total_idle_time"])
    return float(node.get("total_idle_time_minutes", 0.0))


def _merge_work_orders_duration(
    node: dict[str, Any], incoming: dict[str, float] | None
) -> None:
    if not incoming:
        return
    raw = node.get("work_orders_duration")
    acc: dict[str, float] = dict(raw) if isinstance(raw, dict) else {}
    for k, v in incoming.items():
        acc[k] = float(acc.get(k, 0.0)) + float(v)
    node["work_orders_duration"] = acc


def delete_factory_building(db_path: Path, building_id: str) -> bool:
    """Remove one building branch from the factory database. Returns True if a row was deleted."""
    data = _load_factory_db(db_path)
    if building_id not in data:
        return False
    del data[building_id]
    _save_factory_db(db_path, data)
    return True


def merge_general_consumption(db_path: Path, payload: GeneralConsumptionPayload) -> FactoryDb:
    """Merge payload into hierarchy: building_id -> machine_id -> energy_type -> totals."""
    data = _load_factory_db(db_path)
    building = payload.building_id.strip()
    machine = payload.machine_id.strip()
    energy = payload.energy_type.strip().lower()

    if building not in data:
        data[building] = {}
    if machine not in data[building]:
        data[building][machine] = {}
    if energy not in data[building][machine]:
        data[building][machine][energy] = {
            "idle_consumption_total_kwh": 0.0,
            "prod_consumption_total_kwh": 0.0,
            "total_time": 0.0,
            "total_idle_time": 0.0,
            "work_orders_duration": {},
            "idle_consumption_rate": 0.0,
            "prod_consumption_rate": 0.0,
            "machine_name": payload.machine_name,
            "entry_count": 0,
        }

    node = data[building][machine][energy]
    node["idle_consumption_total_kwh"] = float(node.get("idle_consumption_total_kwh", 0.0)) + float(
        payload.idle_consumption_total
    )
    node["prod_consumption_total_kwh"] = float(node.get("prod_consumption_total_kwh", 0.0)) + float(
        payload.prod_consumption_total
    )
    node["total_time"] = _node_total_time(node) + float(payload.total_time)
    node["total_idle_time"] = _node_total_idle_time(node) + float(payload.total_idle_time)
    if "total_duration_minutes" in node:
        del node["total_duration_minutes"]
    if "total_idle_time_minutes" in node:
        del node["total_idle_time_minutes"]
    _merge_work_orders_duration(node, payload.work_orders_duration)
    node["machine_name"] = payload.machine_name
    node["entry_count"] = int(node.get("entry_count", 0)) + 1
    dur_h = float(node["total_time"]) / 60.0
    node["idle_consumption_rate"] = (
        float(node["idle_consumption_total_kwh"]) / dur_h if dur_h > 0 else 0.0
    )
    node["prod_consumption_rate"] = (
        float(node["prod_consumption_total_kwh"]) / dur_h if dur_h > 0 else 0.0
    )

    if payload.publication_datetime is not None:
        new_dt = _publication_utc(payload.publication_datetime)
        old_dt = _coerce_publication_dt(node.get("publication_datetime"))
        if old_dt is None or new_dt > _publication_utc(old_dt):
            node["publication_datetime"] = new_dt.isoformat().replace("+00:00", "Z")

    _save_factory_db(db_path, data)
    return data


def _work_order_minutes_from_node(wo: dict[str, Any], work_order_key: str) -> float | None:
    """Resolve minutes for this work order (exact key, then trimmed match)."""
    if not work_order_key or not isinstance(wo, dict):
        return None
    key = work_order_key.strip()
    if key in wo:
        try:
            return float(wo[key])
        except (TypeError, ValueError):
            return None
    for k, v in wo.items():
        if str(k).strip() == key:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    return None


def _idle_activity_label(
    building_id: str,
    machine_id: str,
    machine_name: str,
    used_labels: set[str],
) -> str:
    base = (machine_name or machine_id).strip() or str(machine_id)
    primary = f"Idle_Time: {base} ({building_id})"
    if primary not in used_labels:
        used_labels.add(primary)
        return primary
    secondary = f"Idle_Time: {base} ({building_id}/{machine_id})"
    if secondary not in used_labels:
        used_labels.add(secondary)
        return secondary
    i = 0
    while True:
        c = f"Idle_Time: {base} ({building_id}/{machine_id}) #{i}"
        if c not in used_labels:
            used_labels.add(c)
            return c
        i += 1


from app.application.pipelines.idle_allocation import (
    IdleAllocationStrategyPort,
    ProportionalShareIdleAllocation,
)

# Default proportional-share strategy. Tests can substitute this by reaching
# into the module attribute ``_IDLE_ALLOCATOR`` to verify alternative strategies,
# but production callers should not — the public surface is the function below.
_IDLE_ALLOCATOR: IdleAllocationStrategyPort = ProportionalShareIdleAllocation()


def collect_idle_cf_by_machine_for_work_order(
    db_path: Path,
    work_order_key: str,
    gco2_per_kwh: float,
) -> dict[str, float]:
    """Kg CO₂e per PCF emission line for factory idle energy attributed to this work order.

    For each machine / energy row that lists ``work_order_key`` in ``work_orders_duration``,
    allocates a share of ``idle_consumption_total_kwh`` using::

        wo_minutes / (total_time - total_idle_time) * idle_kWh * (gCO2/kWh / 1000)

    Rows for the same machine (possibly multiple energy types) are summed. Keys are
    ``typeOfActivity`` strings ``Idle_Time: <machine name> (<building_id>)``, with
    ``/<machine_id>`` appended if the same building has another machine with the same name.
    """
    data = _load_factory_db(db_path)
    if not data or not (work_order_key or "").strip():
        return {}

    # (building_id, machine_id) -> (display_name, cf_kg)
    acc: dict[tuple[str, str], tuple[str, float]] = {}

    for building_id, machines in data.items():
        if not isinstance(machines, dict):
            continue
        for machine_id, energies in machines.items():
            if not isinstance(energies, dict):
                continue
            for _energy_type, node in energies.items():
                if not isinstance(node, dict):
                    continue
                wo_min = _work_order_minutes_from_node(
                    node.get("work_orders_duration") or {}, work_order_key
                )
                if wo_min is None or wo_min <= 0:
                    continue
                tt = _node_total_time(node)
                ti = _node_total_idle_time(node)
                idle_kwh = float(node.get("idle_consumption_total_kwh", 0.0))
                allocated_kwh = _IDLE_ALLOCATOR.allocate_kwh(
                    work_order_minutes=wo_min,
                    total_time_minutes=tt,
                    total_idle_minutes=ti,
                    idle_kwh=idle_kwh,
                )
                if allocated_kwh <= 0:
                    continue
                cf_kg = allocated_kwh * (float(gco2_per_kwh) / 1000.0)
                mk = (str(building_id), str(machine_id))
                mname = str(node.get("machine_name") or machine_id).strip() or str(machine_id)
                prev = acc.get(mk)
                if prev is None:
                    acc[mk] = (mname, cf_kg)
                else:
                    acc[mk] = (prev[0], prev[1] + cf_kg)

    used: set[str] = set()
    out: dict[str, float] = {}
    for (bid, mid), (mname, cf) in sorted(acc.items()):
        if cf <= 0:
            continue
        label = _idle_activity_label(bid, mid, mname, used)
        out[label] = cf
    return out
