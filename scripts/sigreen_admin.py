# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Operator CLI for the configured SiGREEN tenant.

Usage:
    python -m scripts.sigreen_admin <subcommand> [args]

Subcommands:
    factories [name1 name2 ...]   Resolve factory IDs by name (default: Germany, OPC).
    component <identifier>        Look up a component and report its per-unit PCF.
    components                    List up to 50 component identifiers in the tenant.
    product <uuid>                Look up a product by UUID and print details.
    verify-consumption-api        Smoke-test /consumptionData against the in-process app.

Replaces the older standalone scripts (``lookup_sigreen_factories.py``,
``lookup_sigreen_component.py``, ``lookup_product_by_uuid.py``, ``verify_consumption_api.py``).
"""
from __future__ import annotations

import json
import sys

from app.services.config_service import (
    DEFAULT_SIGREEN_BASE_URL,
    ensure_sigreen_factory_id,
    load_app_config,
)
from app.integrations.sigreen import SiGREENInterface


def _make_sigi() -> SiGREENInterface:
    cfg = load_app_config()
    factory_name = (cfg.get("sigreen_factory_name") or "").strip() or "OPC"
    base_url = (cfg.get("sigreen_base_url") or "").strip() or DEFAULT_SIGREEN_BASE_URL
    return SiGREENInterface(factory_name=factory_name, base_url=base_url)


def _cmd_factories(*names: str) -> None:
    targets = list(names) or ["Germany", "OPC"]
    sigi = _make_sigi()
    items = sigi.get_factories().get("items", [])
    print(f"Found {len(items)} factor(ies):\n")
    for name in targets:
        fid = next((it["id"] for it in items if it.get("factory") == name), None)
        print(f"  {name}: {fid or '(not found)'}")
    print("\nAll factories:")
    for it in items:
        print(f"  {it.get('factory')}: {it.get('id')}")


def _cmd_component(identifier: str) -> None:
    sigi = _make_sigi()
    print(f"Using SiGREEN base: {sigi.base_url}, factory: {sigi.factory_name}\n")
    comp = sigi.get_component_by_identifier(identifier)
    if comp:
        print(f"Component FOUND: id={comp.get('id')}, name={comp.get('name', 'N/A')}")
        print(f"  Identifiers: {comp.get('identifiers', [])}")
    else:
        print("Component NOT FOUND")
    print()
    pcf = sigi.get_material_pcf_per_unit_kg(identifier)
    if pcf:
        print("Carbon footprint (kg CO2e per unit):")
        print(f"  Total:        {pcf['total']:.6f}")
        print(f"  Production:   {pcf.get('production', 0):.6f}")
        print(f"  Distribution: {pcf.get('distribution', 0):.6f}")
    else:
        print("No PCF data available for this component.")


def _cmd_components() -> None:
    sigi = _make_sigi()
    items = sigi.get_components().get("items", [])
    print(f"SiGREEN has {len(items)} component(s). Identifiers (Product ID):")
    for it in items[:50]:
        ids = it.get("identifiers", [])
        vals = [i.get("value") for i in ids if i.get("idType") == "Product ID" or not ids] or [
            i.get("value") for i in ids
        ]
        print(f"  {it.get('name', 'N/A')}: {vals or ['(no value)']}")
    if len(items) > 50:
        print(f"  ... and {len(items) - 50} more")


def _cmd_product(uuid: str) -> None:
    ensure_sigreen_factory_id()
    sigi = _make_sigi()
    items = sigi.get_products().get("items", [])
    match = next((it for it in items if str(it.get("id", "")).strip() == uuid), None)
    if not match:
        print(f"No product found with UUID {uuid}\nTotal products in SiGREEN: {len(items)}\nExisting product UUIDs:")
        for it in items:
            print(f"  {it.get('id')}: {it.get('name', '(no name)')}")
        sys.exit(1)
    print(json.dumps(match, indent=2))
    print("\n--- Summary ---")
    print(f"Product name: {match.get('name', '(none)')}")
    print(f"UUID: {match.get('id', '(none)')}")
    for ident in match.get("identifiers", []):
        print(f"  - {ident.get('idType', '?')}: {ident.get('value', '?')}")


def _cmd_verify_consumption_api() -> None:
    """Smoke-test /consumptionData against the in-process FastAPI app (energy-split-v2 format)."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    payload = {
        "workOrderName": "PO_VERIFY",
        "workOrderOperationName": "OP20-Laesern",
        "workUnit": "Trumpf-WorkUnit-1",
        "consumedEnergies": [
            {"type": "Electricity", "uom": "kWh", "resourceUsage": {"measurementType": "DELTA",
                "measurements": [{"start": "2025-06-16T16:59:00Z", "duration": 1, "consumption": 5}]}},
            {"type": "CompressedAir", "uom": "M3", "resourceUsage": {"measurementType": "DELTA",
                "measurements": [{"start": "2025-06-16T16:59:00Z", "duration": 1, "consumption": 5}]}},
        ],
        "actualStartTime": "2025-06-16T16:59:00Z",
        "actualEndTime": "2025-06-16T17:00:00Z",
        "timestamp": "2025-06-16T17:01:00Z",
    }
    body = client.post("/consumptionData", json=payload).json()
    energy = body.get("database_record", {}).get("operations", {}).get("OP20-Laesern", {}).get("energy", {})

    issues: list[str] = []
    if body.get("_api_version") != "energy-split-v2":
        issues.append("_api_version is not 'energy-split-v2' (old code is running)")
    if "Electricity" not in energy or "CompressedAir" not in energy:
        issues.append(f"energy missing Electricity/CompressedAir keys: {list(energy.keys())}")
    if abs(body.get("total_energy_consumption_kwh", 0) - 5.6) > 0.01:
        issues.append(f"expected total_energy_consumption_kwh ≈ 5.6, got {body.get('total_energy_consumption_kwh')}")
    if abs(body.get("total_carbon_footprint_kg", 0) - 1.96) > 0.01:
        issues.append(f"expected total_carbon_footprint_kg ≈ 1.96, got {body.get('total_carbon_footprint_kg')}")

    if issues:
        for msg in issues:
            print(f"FAIL: {msg}")
        print("\nResponse snippet:")
        print(json.dumps({
            "energy": energy,
            "total_energy_consumption_kwh": body.get("total_energy_consumption_kwh"),
            "total_carbon_footprint_kg": body.get("total_carbon_footprint_kg"),
            "_api_version": body.get("_api_version"),
        }, indent=2))
        sys.exit(1)
    print("OK: Consumption API is using the correct split-by-type format")


_COMMANDS = {
    "factories": (_cmd_factories, None),  # variadic
    "component": (_cmd_component, 1),
    "components": (_cmd_components, 0),
    "product": (_cmd_product, 1),
    "verify-consumption-api": (_cmd_verify_consumption_api, 0),
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _COMMANDS:
        print(__doc__)
        sys.exit(2 if len(sys.argv) >= 2 else 0)
    fn, expected_args = _COMMANDS[sys.argv[1]]
    args = sys.argv[2:]
    if expected_args is not None and len(args) != expected_args:
        sys.exit(f"ERROR: '{sys.argv[1]}' expects {expected_args} arg(s); got {len(args)}")
    fn(*args)


if __name__ == "__main__":
    main()
