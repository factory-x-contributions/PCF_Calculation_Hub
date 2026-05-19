"""
AAS data source service: discover shells, validate BOP, calculate PCF, submit to SiGREEN.

When data_source is AAS, this service:
1. Finds available shells from the AAS registry
2. Skips shells that already have PCF calculated
3. For each shell: checks Bill_of_Process - all OperationStatus must be Ended or Aborted
4. Calculates consumption and carbon footprint
5. Creates PCF report and submits to SiGREEN

Product UUID: Uses PcfComponentId from AAS CommonParameter when available;
otherwise falls back to config or hardcoded default (user will define AAS mapping later).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from app.config.settings import settings
from app.integrations.aas import AASInterface, base64url_encode
from app.integrations.grid import enforce_time_resolution
from app.integrations.sigreen import SiGREENInterface
from app.services.bookkeeping_service import update_from_aas
from app.services.config_service import load_app_config
from app.services.factory_consumption_service import collect_idle_cf_by_machine_for_work_order
from app.services.pcf_builder import build_pcf_report
from app.services.pcf_service import get_or_create_product_uuid

logger = logging.getLogger("pcf_creator_app")

# Default product UUID when not available from AAS (user will define AAS mapping later)
DEFAULT_PRODUCT_UUID = "019b9d4d-569f-733e-b649-642c7ecabfc9"

# Allowed OperationStatus/ProcessOperationStatus values for processes ready for PCF calculation
# New AAS model (AAS_WO_2026_03_04_Template) uses ProcessOperationStatus; deprecated model uses OperationStatus
READY_STATUSES = ("Ended", "Aborted")
STATUS_PROPERTY_NAMES = ("OperationStatus", "ProcessOperationStatus")


def _get_processed_shells_path() -> Path:
    return Path(settings.database_path).parent / "aas_processed_shells.json"


def _load_processed_shells() -> set[str]:
    """Load set of shell IDs that have already had PCF calculated and submitted."""
    path = _get_processed_shells_path()
    if not path.exists():
        return set()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("shell_ids", []))
    except (json.JSONDecodeError, OSError):
        return set()


def _mark_shell_processed(shell_id: str) -> None:
    """Mark a shell as having had PCF calculated."""
    path = _get_processed_shells_path()
    processed = _load_processed_shells()
    processed.add(shell_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"shell_ids": list(processed)}, f, indent=2)


def _string_list_to_float(s: str) -> list[float]:
    """Parse '[1.0, 2.0, 3.0]' style string to list of floats."""
    s = (s or "").strip()
    if not s or s == "[]":
        return []
    return list(map(float, s.strip("[]").replace(",", " ").split()))


def _aas_time_to_sigreen_format(t: str) -> str:
    """Convert AAS datetime to SiGREEN format (YYYY-MM-DDTHH:MM:SS.000Z)."""
    if not t:
        return ""
    dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _date_offset(ts: str, days: int = 1) -> str:
    """Apply day offset to ISO timestamp (temporary for dev alignment with pcf-creator)."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _get_aas_interface_from_config() -> AASInterface | None:
    """Create AASInterface from app config. Returns None if AAS not configured."""
    cfg = load_app_config()
    base_url = (cfg.get("aas_base_url") or "").strip()
    if not base_url:
        return None
    aas_type = cfg.get("aas_type") or ""
    if aas_type not in ("AAS (BaSyx)", "AAS (AssetFox)"):
        aas_type = "AAS (AssetFox)" if "assetfox" in base_url.lower() else "AAS (BaSyx)"
    asset_name = (cfg.get("aas_asset_name") or "").strip()
    return AASInterface(
        asset_name=asset_name or "",  # Empty = shell-specific context when discovering work orders
        submodel_name="",
        base_url=base_url,
        client_id=cfg.get("aas_client_id") or "",
        client_secret=cfg.get("aas_client_secret") or "",
        aas_type=aas_type,
    )


def _get_sigreen_from_config() -> SiGREENInterface | None:
    """Return the canonical SiGREEN client for the AAS batch pipeline.

    Routed through :func:`app.services.sigreen_factory.build_sigreen_for_aas_pipeline`
    so all three SiGREEN constructions (MES emissions, material lookup, AAS batch)
    share one factory site. The factory itself emits the missing-factory_id warning.
    """
    from app.services.sigreen_factory import build_sigreen_for_aas_pipeline

    return build_sigreen_for_aas_pipeline()

def get_available_aas_shells() -> dict[str, Any]:
    """List available AAS shells. Returns {shell_ids: [...], error: str|null}."""
    result: dict[str, Any] = {"shell_ids": [], "error": None}
    cfg = load_app_config()
    if cfg.get("data_source") != "aas":
        result["error"] = "Data source is not AAS"
        return result
    aasi = _get_aas_interface_from_config()
    if not aasi:
        result["error"] = "AAS base URL not configured"
        return result
    try:
        shells_data = aasi.find_shells()
        shells = shells_data.get("result", shells_data)
        if not isinstance(shells, list):
            shells = []
        for item in shells:
            sid = item if isinstance(item, str) else (item.get("id") or item.get("idShort") or "")
            if sid and "WO" in sid:
                result["shell_ids"].append(sid)
    except Exception as e:
        result["error"] = str(e)
    return result


def _get_common_parameter_operation_status(aasi: AASInterface, shell_id: str) -> str | None:
    """
    Get OperationStatus from CommonParameter > Details for a shell.
    Returns None if not found or on error.
    """
    try:
        refs = aasi.get_submodel_refs(shell_id)
        shell_enc = base64url_encode(shell_id)
        for sm_ref in refs:
            sm_id = base64url_encode(sm_ref)
            url = f"{aasi.registry_base_url}/shells/{shell_enc}/submodels/{sm_id}"
            if aasi.aas_type == "AAS (BaSyx)":
                url = f"{aasi.registry_base_url}/submodels/{sm_id}"
            resp = requests.get(url, headers=aasi._headers(), timeout=10)
            if resp.status_code != 200 or not resp.content:
                continue
            sm = resp.json()
            if sm.get("idShort") != "CommonParameter":
                continue
            elems = sm.get("submodelElements", sm.get("value", []))
            if not isinstance(elems, list):
                continue
            for elem in elems:
                if elem.get("idShort") != "Details":
                    continue
                vals = elem.get("value", [])
                if not isinstance(vals, list):
                    continue
                for prop in vals:
                    if prop.get("idShort") == "OperationStatus":
                        return prop.get("value")
            break
    except Exception:
        pass
    return None


def _set_common_parameter_operation_status(
    aasi: AASInterface, shell_id: str, value: str
) -> bool:
    """
    Set OperationStatus in CommonParameter > Details for a shell.
    Returns True on success, False on failure.
    """
    try:
        refs = aasi.get_submodel_refs(shell_id)
        shell_enc = base64url_encode(shell_id)
        for sm_ref in refs:
            sm_id = base64url_encode(sm_ref)
            sm_url = f"{aasi.registry_base_url}/shells/{shell_enc}/submodels/{sm_id}"
            if aasi.aas_type == "AAS (BaSyx)":
                sm_url = f"{aasi.registry_base_url}/submodels/{sm_id}"
            sm_resp = requests.get(sm_url, headers=aasi._headers(), timeout=10)
            if sm_resp.status_code != 200 or not sm_resp.content:
                continue
            sm = sm_resp.json()
            if sm.get("idShort") != "CommonParameter":
                continue
            get_url = f"{aasi.registry_base_url}/shells/{shell_enc}/submodels/{sm_id}/submodel-elements/Details"
            if aasi.aas_type == "AAS (BaSyx)":
                get_url = f"{aasi.registry_base_url}/submodels/{sm_id}/submodel-elements/Details"
            resp = requests.get(get_url, headers=aasi._headers(), timeout=10)
            if resp.status_code != 200 or not resp.content:
                continue
            details = resp.json()
            vals = details.get("value", [])
            if not isinstance(vals, list):
                continue
            for prop in vals:
                if prop.get("idShort") == "OperationStatus":
                    prop["value"] = value
                    put_url = f"{aasi.registry_base_url}/shells/{shell_enc}/submodels/{sm_id}/submodel-elements/Details"
                    if aasi.aas_type == "AAS (BaSyx)":
                        put_url = f"{aasi.registry_base_url}/submodels/{sm_id}/submodel-elements/Details"
                    put_resp = requests.put(
                        put_url, headers=aasi._headers(), json=details, timeout=10
                    )
                    put_resp.raise_for_status()
                    return True
            break
    except Exception as e:
        logger.warning(
            "[AAS period] Shell %s: Failed to set CommonParameter OperationStatus: %s",
            shell_id, e,
        )
    return False


def _extract_common_parameter_details(
    aasi: AASInterface, shell_id: str
) -> dict[str, str | None]:
    """
    Extract key fields from CommonParameter submodel Details.

    Returns dict with keys: product_id, pcf_component_id, work_order, product_family.
    """
    result: dict[str, str | None] = {
        "product_id": None,
        "pcf_component_id": None,
        "work_order": None,
        "product_family": None,
    }
    try:
        refs = aasi.get_submodel_refs(shell_id)
        for sm_ref in refs:
            sm_id = base64url_encode(sm_ref)
            url = f"{aasi.registry_base_url}/shells/{base64url_encode(shell_id)}/submodels/{sm_id}"
            if aasi.aas_type == "AAS (BaSyx)":
                url = f"{aasi.registry_base_url}/submodels/{sm_id}"
            resp = requests.get(url, headers=aasi._headers(), timeout=10)
            if resp.status_code != 200 or not resp.content:
                continue
            sm = resp.json()
            elems = sm.get("submodelElements", sm.get("value", []))
            if not isinstance(elems, list):
                continue
            for elem in elems:
                vals = elem.get("value", [])
                if not isinstance(vals, list):
                    continue
                for prop in vals:
                    ps = prop.get("idShort")
                    v = prop.get("value")
                    if ps == "ProductID" and v and isinstance(v, str) and v.strip():
                        result["product_id"] = v.strip()
                    elif ps in ("PcfComponentId", "PCFComponentID") and v and isinstance(v, str) and len(v) > 10:
                        result["pcf_component_id"] = v
                    elif ps == "WorkOrder" and v and isinstance(v, str) and v.strip():
                        result["work_order"] = v.strip()
                    elif ps == "ProductFamily" and v and isinstance(v, str) and v.strip():
                        result["product_family"] = v.strip()
    except Exception:
        pass
    return result


def _shell_id_to_product_identifier(shell_id: str) -> str:
    """Derive a SiGREEN product identifier from shell ID when WorkOrder/ProductID is missing."""
    s = (shell_id or "").strip()
    if "WO" in s:
        m = re.search(r"WO\d{14}", s)
        if m:
            return m.group(0)
    return f"AAS-{s[-24:]}" if len(s) >= 24 else f"AAS-{s or 'unknown'}"


def _get_product_uuid_from_shell(
    aasi: AASInterface, shell_id: str, sigi: SiGREENInterface | None = None
) -> tuple[str, str | None, bool | None]:
    """
    Resolve product UUID from AAS shell for SiGREEN submission.

    When PCFComponentID is present in CommonParameter/Details, use it directly (SiGREEN product UUID).
    Otherwise: get-or-create via ProductID, WorkOrder, or shell-derived identifier.
    Returns (uuid, product_id_used, was_created).
    """
    details = _extract_common_parameter_details(aasi, shell_id)
    pcf_component_id = (details["pcf_component_id"] or "").strip()
    product_id = (details["product_id"] or "").strip()
    work_order = (details["work_order"] or "").strip()

    if pcf_component_id and len(pcf_component_id) > 10:
        return pcf_component_id, None, None

    if sigi:
        identifier = product_id or work_order or _shell_id_to_product_identifier(shell_id)
        uuid, was_created = get_or_create_product_uuid(sigi, identifier)
        return uuid, identifier, was_created

    return DEFAULT_PRODUCT_UUID, None, None


def _get_process_energy_kwh(
    aasi: AASInterface,
    process_id_short: str,
    bop_submodel_id: str,
    shell_id: str,
) -> tuple[float, list[float], str | None, str | None]:
    """
    Get energy consumption for a process using get_list_item_property on EnergyConsumption.
    Returns (total_kwh, time_series_kwh_list, t_start, t_end).
    """
    aasi.set_active_process(process_id_short, bop_submodel_id, shell_id)
    total_kwh = 0.0
    ts_kwh: list[float] = []
    t_start: str | None = None
    t_end: str | None = None

    try:
        # Use get_list_item_property for EnergyConsumption (e.g. EnergyConsumption, 0, ConsumptionData)
        try:
            data = aasi.get_list_item_property("EnergyConsumption", 0, "ConsumptionData")
            total_val = data.get("TotalConsumption")
            ts_val = data.get("TimeSeriesConsumption")
            if total_val is not None:
                total_kwh = float(total_val) if total_val else 0.0
            if ts_val:
                ts_kwh = _string_list_to_float(str(ts_val))
                if ts_kwh and total_kwh == 0:
                    total_kwh = sum(ts_kwh)
        except (KeyError, IndexError, ValueError, StopIteration):
            pass

        # Try TakenPlaceProduction for time range
        try:
            t_start = aasi.get_process_property("TakenPlaceProduction", "ProductionStart")
            t_end = aasi.get_process_property("TakenPlaceProduction", "ProductionEnd")
        except (StopIteration, KeyError, ValueError):
            pass
    except Exception as e:
        logger.warning("Could not read energy for process %s: %s", process_id_short, e)

    return total_kwh, ts_kwh, t_start, t_end


def _get_process_materials(
    aasi: AASInterface,
    process_id_short: str,
    bop_submodel_id: str,
    shell_id: str,
) -> list[dict[str, Any]]:
    """Read MaterialConsumption list from a BOP process.

    Uses same path as get_list_item_property: Bill_of_Process.Process_XXX.MaterialConsumption.
    Supports Name/MaterialConsumptionDataPointId, TotalConsumption/Quantity, Unit.
    Returns list of dicts: [{"name": str, "quantity": float, "unit": str}, ...]
    """
    materials: list[dict[str, Any]] = []

    def _parse_material_list(elem: dict) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        entries = elem.get("value", elem.get("submodelElements", []))
        if not isinstance(entries, list):
            return result
        for entry in entries:
            props = entry.get("value", entry.get("submodelElements", []))
            if not isinstance(props, list):
                continue
            name = None
            data_point_id = None
            total_consumption = 0.0
            unit = "piece"
            for p in props:
                if not isinstance(p, dict):
                    continue
                ps = p.get("idShort", "")
                val = p.get("value")
                if ps == "Name":
                    name = val
                elif ps == "MaterialConsumptionDataPointId":
                    data_point_id = val
                elif ps in ("TotalConsumption", "Quantity"):
                    try:
                        total_consumption = float(val) if val else 0.0
                    except (TypeError, ValueError):
                        total_consumption = 0.0
                elif ps == "Unit":
                    unit = str(val).strip() if val else "piece"
            if total_consumption <= 0:
                continue
            ident = None
            if name and str(name).lower() not in ("null", ""):
                ident = str(name).strip()
            elif data_point_id and str(data_point_id).strip():
                ident = str(data_point_id).strip()
            if ident:
                result.append({"name": ident, "quantity": total_consumption, "unit": unit})
        return result

    # Use same path as get_list_item_property: Bill_of_Process.Process_XXX.MaterialConsumption
    element_path = f"Bill_of_Process.{process_id_short}.MaterialConsumption"
    try:
        elem = aasi._get_element_by_path(element_path, shell_id)
        materials = _parse_material_list(elem)
    except Exception as e:
        logger.debug("MaterialConsumption API path %s: %s — trying full submodel fallback", element_path, e)
        # Fallback: some AAS APIs (e.g. AssetFox) don't support dotted submodel-elements path
        try:
            bop_sm = aasi.get_submodel_by_urn(shell_id, bop_submodel_id)
            proc = next(
                (e for e in bop_sm.get("submodelElements", bop_sm.get("value", []))
                if isinstance(e, dict) and e.get("idShort") == process_id_short),
                None,
            )
            mat_elem = (
                next(
                    (c for c in (proc or {}).get("value", [])
                    if isinstance(c, dict) and c.get("idShort") == "MaterialConsumption"),
                    None,
                )
                if proc
                else None
            )
            if mat_elem:
                materials = _parse_material_list(mat_elem)
            else:
                logger.debug("MaterialConsumption not found in BOP submodel for process %s", process_id_short)
        except Exception as fallback_e:
            logger.info(
                "MaterialConsumption for %s: API path failed (%s), fallback also failed (%s)",
                process_id_short, e, fallback_e,
            )
    return materials


def _get_process_operation_status(
    aasi: AASInterface, proc: dict
) -> str | None:
    """
    Get process operation status from MachineDetails.
    Supports both OperationStatus (deprecated) and ProcessOperationStatus (new AAS_WO_2026_03_04_Template model).
    """
    aasi.set_active_process(
        proc["process_idShort"],
        proc["bop_submodel_id"],
        proc["shell_id"],
    )
    for prop_name in STATUS_PROPERTY_NAMES:
        try:
            status = aasi.get_process_property("MachineDetails", prop_name)
            if status is not None and str(status).strip():
                return str(status).strip()
        except (StopIteration, KeyError, ValueError, IndexError):
            continue
    return None


def _get_shell_time_range(aasi: AASInterface, shell_id: str, processes: list[dict]) -> tuple[str, str]:
    """Get earliest ProductionStart and latest ProductionEnd across all BOP processes."""
    starts: list[str] = []
    ends: list[str] = []
    for proc in processes:
        aasi.set_active_process(
            proc["process_idShort"],
            proc["bop_submodel_id"],
            proc["shell_id"],
        )
        try:
            t_start = aasi.get_process_property("TakenPlaceProduction", "ProductionStart")
            t_end = aasi.get_process_property("TakenPlaceProduction", "ProductionEnd")
            if t_start:
                starts.append(t_start)
            if t_end:
                ends.append(t_end)
        except Exception:
            continue
    t_start = min(starts) if starts else ""
    t_end = max(ends) if ends else ""
    return t_start or "2026-01-01T00:00:00Z", t_end or "2026-01-02T00:00:00Z"


class _ShellSkipped(Exception):
    """Raised inside the per-shell pipeline when a shell should be skipped (no error)."""

    def __init__(self, error: str | None = None) -> None:
        super().__init__(error or "")
        self.error = error


class _ShellError(Exception):
    """Raised inside the per-shell pipeline when a shell hit an error and processing must stop for it."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _shell_id_from(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("id") or item.get("idShort") or "")
    return ""


def _list_workorder_shells(aasi: AASInterface) -> list[str]:
    """Return shell IDs from ``aasi.find_shells()`` (no filtering — caller decides what's a WO)."""
    raw = aasi.find_shells()
    items = raw.get("result", raw) if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    return [sid for sid in (_shell_id_from(it) for it in items) if sid]


def _carbon_intensity_for(cfg: dict[str, Any], t_start: str, t_end: str) -> float:
    """Resolve grid CO2 intensity in g/kWh for the AAS pipeline.

    Phase 4 routed this through :class:`app.application.ports.CarbonIntensityProviderPort`
    so the constant-vs-Green-Grid-Compass switch is a first-class strategy. The
    function signature is preserved for the existing call site, but behaviour now
    matches whatever strategy the config selects.
    """
    from datetime import datetime, timezone

    from app.application.pipelines.carbon_intensity import build_carbon_intensity_provider

    provider = build_carbon_intensity_provider(cfg)
    try:
        start = datetime.fromisoformat(t_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(t_end.replace("Z", "+00:00"))
        window: tuple[datetime, datetime] | None = (start, end)
    except (ValueError, AttributeError):
        window = (datetime.now(timezone.utc), datetime.now(timezone.utc))
    return provider.gco2_per_kwh(at_window=window)


def _aggregate_processes_data(
    aasi: AASInterface, processes: list[dict], gco2: float, shell_id: str,
) -> tuple[dict[str, float], dict[str, dict[str, Any]], dict[str, float], float]:
    """For each BOP process: read total kWh + materials, accumulate.

    Returns ``(bop_of_product, all_materials, total_kwh_per_process, energy_pcf_kg)``.
    """
    bop_of_product: dict[str, float] = {}
    total_kwh_per_process: dict[str, float] = {}
    all_materials: dict[str, dict[str, Any]] = {}
    energy_pcf = 0.0
    for proc in processes:
        pid = proc["process_idShort"]
        total_kwh, _, _, _ = _get_process_energy_kwh(
            aasi, pid, proc["bop_submodel_id"], proc["shell_id"],
        )
        total_kwh_per_process[pid] = float(total_kwh)
        cf = float(total_kwh) * gco2 * 0.001 if total_kwh > 0 and gco2 else 0.0
        bop_of_product[pid] = cf
        energy_pcf += cf
        logger.info("[AAS period] Shell %s: process %s — %.2f kWh, %.2f kg CO2e", shell_id, pid, total_kwh, cf)

        for mat in _get_process_materials(aasi, pid, proc["bop_submodel_id"], proc["shell_id"]):
            existing = all_materials.get(mat["name"])
            if existing is None:
                all_materials[mat["name"]] = {"quantity": mat["quantity"], "unit": mat["unit"]}
            else:
                existing["quantity"] += mat["quantity"]
    return bop_of_product, all_materials, total_kwh_per_process, energy_pcf


def _build_aas_db_record(
    bop_of_product: dict[str, float],
    total_kwh_per_process: dict[str, float],
    materials: dict[str, dict[str, Any]],
    materials_breakdown: dict[str, dict[str, Any]],
    gco2: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Shape the ``operations`` and ``materials`` blocks for the work-order DB."""
    db_operations = {
        pid: {
            "energy": {
                "energy_type": "Electricity",
                "total_consumption": total_kwh_per_process.get(pid, 0.0),
                "uom": "kWh",
                "carbon_intensity_gco2_per_kwh": float(gco2),
                "carbon_footprint_kg": float(cf),
            }
        }
        for pid, cf in bop_of_product.items()
    }

    db_materials: dict[str, dict[str, Any]] = {}
    for mat_id, info in materials.items():
        entry: dict[str, Any] = {"total_quantity": info["quantity"], "uom": info["unit"]}
        bd = materials_breakdown.get(mat_id)
        if bd:
            for k in ("carbon_footprint_per_unit", "carbon_footprint_kg"):
                if k in bd:
                    entry[k] = bd[k]
            for k in ("carbon_footprint_production_per_unit", "carbon_footprint_distribution_per_unit"):
                if bd.get(k) is not None:
                    entry[k] = bd[k]
        db_materials[mat_id] = entry
    return db_operations, db_materials


def _process_shell(
    shell_id: str,
    aasi: AASInterface,
    sigi: SiGREENInterface,
    cfg: dict[str, Any],
    all_machines: list[dict],
) -> dict[str, Any]:
    """Run the full PCF pipeline for one shell. Raises ``_ShellSkipped``/``_ShellError`` on early exit."""
    if "WO" not in shell_id:
        logger.info("[AAS period] Shell %s: skipping (shell ID must contain 'WO')", shell_id)
        raise _ShellSkipped()
    if _get_common_parameter_operation_status(aasi, shell_id) == "Ended":
        logger.info("[AAS period] Shell %s: skipping (CommonParameter OperationStatus already Ended)", shell_id)
        raise _ShellSkipped()

    processes = [m for m in all_machines if m.get("shell_id") == shell_id]
    if not processes:
        logger.info("[AAS period] Shell %s: skipping (no BOP processes)", shell_id)
        raise _ShellSkipped()

    # Step 3: every process must be Ended/Aborted
    for proc in processes:
        pid = proc["process_idShort"]
        status = _get_process_operation_status(aasi, proc)
        if status is None:
            raise _ShellSkipped(
                f"Shell {shell_id}: could not read OperationStatus/ProcessOperationStatus for process {pid}"
            )
        if status not in READY_STATUSES:
            logger.info(
                "[AAS period] Shell %s: process %s status=%s (not Ended/Aborted) — skipping shell",
                shell_id, pid, status,
            )
            raise _ShellSkipped()
    logger.info("[AAS period] Shell %s: All processes Ended/Aborted — proceeding", shell_id)

    # Step 4: production time range (with legacy 1-day offset for pcf-creator alignment)
    t_start, t_end = _get_shell_time_range(aasi, shell_id, processes)
    t_start = _date_offset(t_start)
    t_end = _date_offset(t_end)
    t_start, t_end = enforce_time_resolution(t_start, t_end, 60, format="%Y-%m-%dT%H:%M:%SZ")

    # Step 5: grid CO2 intensity
    try:
        gco2 = _carbon_intensity_for(cfg, t_start, t_end)
    except Exception as exc:
        raise _ShellError(f"Shell {shell_id}: Green Grid Compass lookup failed: {exc}") from exc
    logger.info("[AAS period] Shell %s: CO2 coefficient %.1f g/kWh", shell_id, gco2)

    # Step 6: per-process energy + materials
    bop_of_product, all_materials, total_kwh_per_process, energy_pcf = _aggregate_processes_data(
        aasi, processes, gco2, shell_id,
    )
    if energy_pcf <= 0:
        raise _ShellError(f"Shell {shell_id}: no consumption data for PCF")

    # Step 6b: BOM material PCF
    materials_breakdown: dict[str, dict[str, Any]] = {}
    if cfg.get("pcf_include_bom", True) and all_materials:
        from app.services.material_pcf import fetch_material_pcf_map, material_breakdown_for

        pcf_map = fetch_material_pcf_map(list(all_materials.keys()), sigi=sigi, log_label="AAS BOM")
        materials_breakdown, _ = material_breakdown_for(all_materials, pcf_map)

    # Step 7+8: build PCF report (delegates to pcf_builder for the SiGREEN dict shape)
    common_details = _extract_common_parameter_details(aasi, shell_id)
    work_order_name = common_details["work_order"] or shell_id
    idle_by_activity = collect_idle_cf_by_machine_for_work_order(
        Path(settings.factory_database_path), work_order_name, gco2,
    )
    pcf_report = build_pcf_report(
        sigi,
        bill_of_process=bop_of_product,
        materials_breakdown=materials_breakdown,
        idle_by_activity=idle_by_activity,
        work_order_name=work_order_name,
        t_start=_aas_time_to_sigreen_format(t_start),
        t_end=_aas_time_to_sigreen_format(t_end),
        quantity=1,
        batch_number=work_order_name,
    )
    total_pcf = float(pcf_report.get("productCarbonFootprint") or 0.0)

    # Step 9: resolve product UUID
    try:
        product_uuid, product_id_used, was_created = _get_product_uuid_from_shell(aasi, shell_id, sigi)
    except Exception as exc:
        logger.exception("_get_product_uuid_from_shell failed for shell %s", shell_id)
        raise _ShellError(f"Shell {shell_id}: get/create product failed: {exc}") from exc

    # Step 10: submit
    try:
        sigi.send_factory_emissions(product_uuid=product_uuid, PCF_report=pcf_report)
        _mark_shell_processed(shell_id)
    except Exception as exc:
        logger.exception("SiGREEN send_factory_emissions failed for shell %s — %s", shell_id, exc)
        logger.info(
            "[AAS period] Shell %s: PCF report that failed to submit: %s",
            shell_id, json.dumps(pcf_report, indent=2),
        )
        raise _ShellError(f"Shell {shell_id}: SiGREEN submit failed: {exc}") from exc

    if _set_common_parameter_operation_status(aasi, shell_id, "Ended"):
        logger.info("[AAS period] Shell %s: Set CommonParameter OperationStatus to Ended", shell_id)
    else:
        logger.warning("[AAS period] Shell %s: Could not set CommonParameter OperationStatus", shell_id)

    # Step 11: persist work order record (same shape as MES flow)
    db_operations, db_materials = _build_aas_db_record(
        bop_of_product, total_kwh_per_process, all_materials, materials_breakdown, gco2,
    )
    try:
        update_from_aas(
            Path(settings.database_path),
            work_order_name,
            operations=db_operations,
            materials=db_materials,
            pcf_report=pcf_report,
            product_name=common_details.get("product_id") or "",
        )
    except Exception as exc:
        logger.warning(
            "[AAS period] Shell %s: Failed to save work order record: %s (PCF already submitted to SiGREEN)",
            shell_id, exc,
        )

    bom_pcf = sum(m.get("carbon_footprint_kg", 0.0) for m in materials_breakdown.values())
    return {
        "shell_id": shell_id,
        "work_order": work_order_name,
        "product_uuid": product_uuid,
        "total_pcf_kg": round(total_pcf, 2),
        "energy_pcf_kg": round(energy_pcf, 4),
        "bom_pcf_kg": round(bom_pcf, 4),
        "materials_count": len(materials_breakdown),
    }


def process_aas_shells_for_pcf() -> dict[str, Any]:
    """Discover AAS shells, validate BOP, calculate PCF, submit to SiGREEN, persist to DB.

    Returns a summary dict ``{processed, skipped, errors, shells_processed}``. Errors are
    accumulated per-shell so one bad shell never aborts the whole cycle.
    """
    result: dict[str, Any] = {"processed": 0, "skipped": 0, "errors": [], "shells_processed": []}

    cfg = load_app_config()
    if cfg.get("data_source") != "aas":
        result["errors"].append("Data source is not AAS")
        return result

    aasi = _get_aas_interface_from_config()
    if aasi is None:
        result["errors"].append("AAS base URL not configured")
        return result
    logger.info("[AAS period] AAS type: %s", aasi.aas_type)

    sigi = _get_sigreen_from_config()
    if sigi is None:
        result["errors"].append("SiGREEN not configured")
        return result

    try:
        shell_ids = _list_workorder_shells(aasi)
    except Exception as exc:
        logger.exception("AAS find_shells failed")
        result["errors"].append(f"Failed to find AAS shells: {exc}")
        return result
    logger.info("[AAS period] Found %d shells from %s", len(shell_ids), aasi.aas_type)

    try:
        all_machines = aasi.discover_bop_machines()
    except Exception as exc:
        logger.exception("AAS discover_bop_machines failed")
        result["errors"].append(f"discover_bop_machines failed: {exc}")
        return result

    for shell_id in shell_ids:
        try:
            outcome = _process_shell(shell_id, aasi, sigi, cfg, all_machines)
        except _ShellSkipped as skipped:
            result["skipped"] += 1
            if skipped.error:
                result["errors"].append(skipped.error)
            continue
        except _ShellError as failed:
            result["errors"].append(failed.message)
            continue
        result["processed"] += 1
        result["shells_processed"].append(outcome)
        logger.info(
            "[AAS period] Shell %s: PCF %.2f kg submitted to SiGREEN for product %s",
            shell_id, outcome["total_pcf_kg"], outcome["product_uuid"],
        )

    logger.info(
        "[AAS period] Cycle complete: processed=%d skipped=%d errors=%d",
        result["processed"], result["skipped"], len(result["errors"]),
    )
    return result
