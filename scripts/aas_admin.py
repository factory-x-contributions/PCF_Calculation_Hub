"""Operator CLI for the configured AAS server.

Usage:
    python -m scripts.aas_admin <subcommand> [args]

Subcommands:
    discover                 List BOP processes the configured AAS exposes (per shell).
    common-status <shell_id> Print CommonParameter / Details / OperationStatus for one shell.
    check-shell <shell_id>   Verify all BOP processes for a shell are Ended/Aborted (PCF-ready).
    materials <shell_id>     List MaterialConsumption entries for each BOP process.

Replaces the older standalone scripts (``_query_aas_processes.py``, ``check_shell_complete.py``,
``check_shell_materials.py``, ``get_common_operation_status.py``).
"""
from __future__ import annotations

import sys

import requests

from app.integrations.aas import AASInterface, base64url_encode
from app.services.aas_service import (
    READY_STATUSES,
    _get_aas_interface_from_config,
    _get_process_materials,
    _get_process_operation_status,
)
from app.services.config_service import load_app_config


def _require_aas() -> AASInterface:
    cfg = load_app_config()
    if cfg.get("data_source") != "aas":
        sys.exit("ERROR: Data source is not AAS")
    aasi = _get_aas_interface_from_config()
    if not aasi:
        sys.exit("ERROR: AAS base URL not configured")
    return aasi


def _cmd_discover() -> None:
    cfg = load_app_config()
    print(f"AAS type: {cfg.get('aas_type')}")
    print(f"Base URL: {cfg.get('aas_base_url')}")
    aasi = _require_aas()
    machines = aasi.discover_bop_machines()
    print(f"Found {len(machines)} BOP process(es):")
    for m in machines:
        print(f"  - {m['process_idShort']}  (shell: {m.get('shell_id', '?')})")


def _cmd_common_status(shell_id: str) -> None:
    aasi = _require_aas()
    refs = aasi.get_submodel_refs(shell_id)
    for sm_ref in refs:
        sm_id = base64url_encode(sm_ref)
        url = (
            f"{aasi.registry_base_url}/shells/{base64url_encode(shell_id)}/submodels/{sm_id}"
            if aasi.aas_type != "AAS (BaSyx)"
            else f"{aasi.registry_base_url}/submodels/{sm_id}"
        )
        resp = requests.get(url, headers=aasi._headers(), timeout=10)
        if resp.status_code != 200 or not resp.content:
            continue
        sm = resp.json()
        if sm.get("idShort") != "CommonParameter":
            continue
        for elem in sm.get("submodelElements", sm.get("value", [])):
            if elem.get("idShort") != "Details":
                continue
            for prop in elem.get("value", []) or []:
                if prop.get("idShort") == "OperationStatus":
                    print(f"OperationStatus: {prop.get('value')}")
                    return
    sys.exit("OperationStatus: (not found)")


def _cmd_check_shell(shell_id: str) -> None:
    aasi = _require_aas()
    machines = aasi.discover_bop_machines()
    bop_processes = [m for m in machines if m.get("shell_id") == shell_id]
    if not bop_processes:
        sys.exit(f"ERROR: No BOP processes found for shell {shell_id}")
    print(f"Shell: {shell_id}")
    print(f"BOP processes: {len(bop_processes)}")
    all_ready = True
    for proc in bop_processes:
        status = _get_process_operation_status(aasi, proc)
        print(f"  - {proc['process_idShort']}: status={status}")
        if status not in READY_STATUSES:
            all_ready = False
    print(f"Complete (ready for PCF): {all_ready}")
    sys.exit(0 if all_ready else 1)


def _cmd_materials(shell_id: str) -> None:
    aasi = _require_aas()
    machines = aasi.discover_bop_machines()
    bop_processes = [m for m in machines if m.get("shell_id") == shell_id]
    if not bop_processes:
        sys.exit(f"No BOP processes found for shell {shell_id}")
    bop_submodel_id = bop_processes[0]["bop_submodel_id"]
    totals: dict[str, dict] = {}
    for proc in bop_processes:
        materials = _get_process_materials(aasi, proc["process_idShort"], bop_submodel_id, shell_id)
        print(f"Process {proc['process_idShort']}: {len(materials)} material(s)")
        for m in materials:
            print(f"  - {m['name']}: qty={m['quantity']} {m['unit']}")
            existing = totals.setdefault(m["name"], {"quantity": 0.0, "unit": m["unit"]})
            existing["quantity"] += m["quantity"]
    print(f"\nTotal unique materials: {len(totals)}")
    for name, info in totals.items():
        print(f"  {name}: {info['quantity']} {info['unit']}")


_COMMANDS = {
    "discover": (_cmd_discover, 0),
    "common-status": (_cmd_common_status, 1),
    "check-shell": (_cmd_check_shell, 1),
    "materials": (_cmd_materials, 1),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        print(__doc__)
        sys.exit(2 if len(sys.argv) >= 2 else 0)
    fn, expected_args = _COMMANDS[sys.argv[1]]
    args = sys.argv[2:]
    if len(args) != expected_args:
        sys.exit(f"ERROR: '{sys.argv[1]}' expects {expected_args} arg(s); got {len(args)}")
    fn(*args)


if __name__ == "__main__":
    main()
