# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for :class:`app.integrations.aas.AASInterface` — the AAS HTTP client.

Inspired by the IIH Aggregator Wizard testing pattern (TESTS.md §1):
all HTTP calls are intercepted with ``unittest.mock.patch`` so the suite
runs without a live BaSyx or AssetFox endpoint. Each test stubs a single
``requests.<verb>`` call with a structured JSON response and asserts the
URL, headers, and body the interface produces.

Why these tests matter (FX TP2.10 §5.2.5):
* AAS is the *pull* side of the spec; PCF Calculation Hub depends on a
  predictable HTTP surface against both BaSyx (no auth) and AssetFox
  (Bearer token via the shared :class:`TokenCache`).
* The dot-notation submodel paths (``CommonParameter.Details``,
  ``Bill_of_Process.Process_X.MachineDetails``) are spec-mandated and
  fragile — these tests pin them.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.integrations import aas as aas_mod
from app.integrations.aas import (
    AASInterface,
    PROPERTY_ALIASES,
    _normalize_energy_name,
    base64url_encode,
)


# -- module-level helpers ---------------------------------------------------------------


def test_base64url_encode_strips_padding() -> None:
    """BaSyx requires no trailing ``=`` padding on base64url identifiers."""
    assert base64url_encode("urn:abc") == "dXJuOmFiYw"


def test_normalize_energy_name_canonicalises_compressed_air_variants() -> None:
    for variant in ("Compressed Air", "compressed air", "compressedair"):
        assert _normalize_energy_name(variant) == "CompressedAir"


def test_normalize_energy_name_canonicalises_electricity() -> None:
    for variant in ("Electricity", "electricity", "ELECTRICITY"):
        assert _normalize_energy_name(variant) == "electricity"


def test_normalize_energy_name_returns_stripped_for_unknown() -> None:
    assert _normalize_energy_name("  Diesel  ") == "Diesel"


def test_normalize_energy_name_returns_input_for_falsy() -> None:
    assert _normalize_energy_name("") == ""
    assert _normalize_energy_name(None) is None  # type: ignore[arg-type]


def test_property_aliases_kept_minimal() -> None:
    """Single source of truth for OperationStatus aliasing — guards against duplication."""
    assert PROPERTY_ALIASES == {"OperationStatus": ["OperationStatus", "ProcessOperationStatus"]}


# -- AASInterface construction & headers -----------------------------------------------


@pytest.fixture
def basyx() -> AASInterface:
    """A BaSyx interface pointed at a placeholder — no auto-discovery triggered."""
    return AASInterface(
        asset_name="WO-1",
        submodel_name="urn:submodel:1",
        base_url="http://basyx.local:8081",
        aas_type="AAS (BaSyx)",
    )


@pytest.fixture
def assetfox() -> AASInterface:
    return AASInterface(
        asset_name="WO-1",
        submodel_name="urn:submodel:1",
        base_url="https://assetfox.local/api/aas/v3",
        aas_type="AAS (AssetFox)",
        client_id="cid",
        client_secret="csec",
    )


def test_basyx_headers_omit_authorization(basyx: AASInterface) -> None:
    headers = basyx._headers()
    assert headers == {"Content-Type": "application/json"}


def test_assetfox_headers_include_bearer(assetfox: AASInterface) -> None:
    """AssetFox authentication must produce a Bearer token in the header."""
    with patch.object(assetfox, "fetch_assetfox_token", return_value="abc"):
        headers = assetfox._headers()
    assert headers["Authorization"] == "Bearer abc"


def test_basyx_token_returns_none(basyx: AASInterface) -> None:
    """No token is needed for BaSyx — keep the early return so we don't burn requests."""
    assert basyx.fetch_assetfox_token() is None


def test_assetfox_token_uses_shared_token_cache(assetfox: AASInterface) -> None:
    """The cache instance must come from the shared TokenCache class — Phase 3 contract."""
    with patch("app.integrations.oauth_token_cache.requests.post") as post:
        post.return_value = MagicMock(
            json=MagicMock(return_value={"access_token": "tok", "expires_in": 900}),
            raise_for_status=MagicMock(),
        )
        token = assetfox.fetch_assetfox_token()
    assert token == "tok"
    # cache instance is now attached to the interface
    from app.integrations.oauth_token_cache import TokenCache

    assert isinstance(assetfox._assetfox_token_cache_obj, TokenCache)


def test_basyx_base_url_keeps_registry_url(basyx: AASInterface) -> None:
    assert basyx.base_url == basyx.registry_base_url == "http://basyx.local:8081"


def test_assetfox_base_url_includes_shell_segment() -> None:
    af = AASInterface(
        asset_name="WO-1",
        submodel_name="urn:submodel:1",
        base_url="https://x/api/aas/v3",
        aas_type="AAS (AssetFox)",
    )
    assert af.registry_base_url == "https://x/api/aas/v3"
    assert "/shells/" in af.base_url


def test_default_base_url_for_basyx_when_none_given() -> None:
    iface = AASInterface(
        asset_name="WO-1", submodel_name="urn:s", base_url=None, aas_type="AAS (BaSyx)"
    )
    assert iface.base_url == "http://localhost:8081"


def test_default_base_url_for_assetfox_when_none_given() -> None:
    iface = AASInterface(
        asset_name="WO-1", submodel_name="urn:s", base_url=None, aas_type="AAS (AssetFox)"
    )
    assert iface.registry_base_url == "https://test.assetfox.apps.siemens.cloud/api/aas/v3"


def test_unknown_aas_type_falls_back_to_assetfox() -> None:
    iface = AASInterface(
        asset_name="WO-1", submodel_name="urn:s", base_url="http://x", aas_type="other"
    )
    assert iface.aas_type == "AAS (AssetFox)"


# -- find_shells / get_shell_asset / get_submodel_refs ---------------------------------


def _ok(json_value: dict | list | None = None, status: int = 200, content: bytes | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = (b"{}" if content is None else content)
    resp.text = (resp.content.decode() if isinstance(resp.content, (bytes, bytearray)) else "")
    resp.json.return_value = json_value if json_value is not None else {}
    resp.raise_for_status = MagicMock()
    return resp


def test_find_shells_basyx_uses_registry_shells_path(basyx: AASInterface) -> None:
    with patch.object(aas_mod.requests, "get", return_value=_ok({"result": ["WO-1"]})) as get:
        out = basyx.find_shells()
    assert out == {"result": ["WO-1"]}
    get.assert_called_once()
    assert get.call_args[0][0].endswith("/shells")


def test_find_shells_assetfox_uses_lookup_shells_path(assetfox: AASInterface) -> None:
    with patch.object(assetfox, "fetch_assetfox_token", return_value="tok"):
        with patch.object(aas_mod.requests, "get", return_value=_ok({"result": []})) as get:
            assetfox.find_shells()
    assert get.call_args[0][0].endswith("/lookup/shells")


def test_get_shell_asset_returns_shell_dict(basyx: AASInterface) -> None:
    with patch.object(aas_mod.requests, "get", return_value=_ok({"id": "WO-1", "submodels": []})):
        out = basyx.get_shell_asset("WO-1")
    assert out["id"] == "WO-1"


def test_get_submodel_refs_extracts_keys(basyx: AASInterface) -> None:
    shell = {"submodels": [
        {"keys": [{"value": "urn:sm:1"}]},
        {"keys": [{"value": "urn:sm:2"}]},
    ]}
    with patch.object(basyx, "get_shell_asset", return_value=shell):
        refs = basyx.get_submodel_refs()
    assert refs == ["urn:sm:1", "urn:sm:2"]


def test_get_submodel_refs_skips_keyless_entries(basyx: AASInterface) -> None:
    shell = {"submodels": [
        {"keys": [{"value": "urn:sm:1"}]},
        {"keys": []},  # malformed → skip
    ]}
    with patch.object(basyx, "get_shell_asset", return_value=shell):
        refs = basyx.get_submodel_refs()
    assert refs == ["urn:sm:1"]


# -- get_asset_submodel / submodel-element fetches -------------------------------------


def test_get_asset_submodel_returns_json(basyx: AASInterface) -> None:
    with patch.object(aas_mod.requests, "get", return_value=_ok({"submodelElements": []})):
        sm = basyx.get_asset_submodel()
    assert sm == {"submodelElements": []}


def test_get_asset_submodel_assetfox_falls_back_to_registry_on_404(assetfox: AASInterface) -> None:
    """AssetFox shell-scoped URL can return 404; the client must retry against the registry."""
    responses = [
        _ok(status=404, json_value={}, content=b""),
        _ok({"submodelElements": [{"idShort": "X"}]}),
    ]
    with patch.object(assetfox, "fetch_assetfox_token", return_value="tok"):
        with patch.object(aas_mod.requests, "get", side_effect=responses) as get:
            sm = assetfox.get_asset_submodel()
    assert sm["submodelElements"][0]["idShort"] == "X"
    assert get.call_count == 2


def test_get_submodel_top_level_elements_returns_idShorts(basyx: AASInterface) -> None:
    with patch.object(basyx, "get_asset_submodel", return_value={
        "submodelElements": [{"idShort": "A"}, {"idShort": "B"}, {}]
    }):
        out = basyx.get_submodel_top_level_elements()
    assert out == ["A", "B"]


def test_get_asset_submodel_element_raises_on_empty_body(basyx: AASInterface) -> None:
    resp = _ok(status=200, content=b"")
    resp.json.return_value = {}
    with patch.object(aas_mod.requests, "get", return_value=resp):
        with pytest.raises(ValueError, match="Empty response"):
            basyx.get_asset_submodel_element("X")


# -- _find_item_by_id_short and PROPERTY_ALIASES ---------------------------------------


def test_find_item_by_id_short_uses_aliases(basyx: AASInterface) -> None:
    """OperationStatus must also match ProcessOperationStatus per AAS_WO model evolution."""
    items = [{"idShort": "ProcessOperationStatus", "value": "Ended"}]
    found = basyx._find_item_by_id_short(items, "OperationStatus")
    assert found["value"] == "Ended"


def test_find_item_by_id_short_raises_when_missing(basyx: AASInterface) -> None:
    with pytest.raises(KeyError, match="Property 'X' not found"):
        basyx._find_item_by_id_short([{"idShort": "Y"}], "X")


# -- get_property / get_list_item_property dot-notation paths --------------------------


def test_get_property_via_top_level_element(basyx: AASInterface) -> None:
    with patch.object(basyx, "_get_element_by_path", return_value={"value": [
        {"idShort": "OperationStatus", "value": "Ended"}
    ]}):
        assert basyx.get_property("MachineDetails", "OperationStatus") == "Ended"


def test_get_property_with_dot_notation_calls_submodel_lookup(basyx: AASInterface) -> None:
    """Dot notation 'CommonParameter.Details' must resolve the submodel by idShort."""
    sm_lookup_resp = _ok({"idShort": "CommonParameter"})
    elem_resp = _ok({"value": [{"idShort": "WorkOrder", "value": "WO-1"}]})
    refs_shell = {"submodels": [{"keys": [{"value": "urn:cp"}]}]}
    with patch.object(basyx, "get_shell_asset", return_value=refs_shell):
        with patch.object(aas_mod.requests, "get", side_effect=[sm_lookup_resp, elem_resp]):
            value = basyx.get_property("CommonParameter.Details", "WorkOrder")
    assert value == "WO-1"


def test_get_list_item_property_returns_consumption_data_dict(basyx: AASInterface) -> None:
    elem = {"value": [
        {"value": [
            {"idShort": "TotalConsumption", "value": "12.5"},
            {"idShort": "TimeSeriesConsumption", "value": "[1,2]"},
        ]}
    ]}
    with patch.object(basyx, "_get_element_by_path", return_value=elem):
        out = basyx.get_list_item_property("EnergyConsumption", 0, "ConsumptionData")
    assert out == {"TotalConsumption": "12.5", "TimeSeriesConsumption": "[1,2]"}


def test_get_list_item_property_raises_on_index_out_of_range(basyx: AASInterface) -> None:
    with patch.object(basyx, "_get_element_by_path", return_value={"value": []}):
        with pytest.raises(IndexError):
            basyx.get_list_item_property("EnergyConsumption", 0, "TotalConsumption")


def test_get_list_item_property_raises_on_missing_id_short(basyx: AASInterface) -> None:
    with patch.object(basyx, "_get_element_by_path", return_value={"value": [
        {"value": [{"idShort": "Other"}]}
    ]}):
        with pytest.raises(KeyError):
            basyx.get_list_item_property("EnergyConsumption", 0, "TotalConsumption")


# -- set_property / set_list_item_property ---------------------------------------------


def test_set_property_top_level_calls_send_request(basyx: AASInterface) -> None:
    asset = {"value": [{"idShort": "OperationStatus", "value": "Init"}]}
    with patch.object(basyx, "_get_element_by_path", return_value=asset):
        with patch.object(basyx, "send_request") as sr:
            basyx.set_property("MachineDetails", "OperationStatus", "Ended")
    sr.assert_called_once()
    assert asset["value"][0]["value"] == "Ended"


def test_set_property_dot_notation_does_put(basyx: AASInterface) -> None:
    """Dot-notation set_property must do a direct PUT against the resolved submodel URL."""
    asset = {"value": [{"idShort": "WorkOrder", "value": "old"}]}
    refs_shell = {"submodels": [{"keys": [{"value": "urn:cp"}]}]}
    sm_lookup_resp = _ok({"idShort": "CommonParameter"})
    with patch.object(basyx, "_get_element_by_path", return_value=asset):
        with patch.object(basyx, "get_shell_asset", return_value=refs_shell):
            with patch.object(aas_mod.requests, "get", return_value=sm_lookup_resp):
                with patch.object(aas_mod.requests, "put") as put:
                    put.return_value = _ok({})
                    basyx.set_property("CommonParameter.Details", "WorkOrder", "WO-9")
    put.assert_called_once()
    assert asset["value"][0]["value"] == "WO-9"


def test_set_list_item_property_sets_consumption_data(basyx: AASInterface) -> None:
    elem = {"value": [{"value": [
        {"idShort": "TotalConsumption", "value": "0"},
        {"idShort": "TimeSeriesConsumption", "value": "[]"},
    ]}]}
    with patch.object(basyx, "_get_element_by_path", return_value=elem):
        with patch.object(basyx, "send_request") as sr:
            basyx.set_list_item_property(
                "EnergyConsumption", 0, "ConsumptionData",
                {"TotalConsumption": "42", "TimeSeriesConsumption": "[1,2]"},
            )
    sr.assert_called_once()
    props = elem["value"][0]["value"]
    assert props[0]["value"] == "42"
    assert props[1]["value"] == "[1,2]"


def test_set_list_item_property_raises_when_not_dict_for_consumption_data(basyx: AASInterface) -> None:
    with patch.object(basyx, "_get_element_by_path", return_value={"value": [{"value": []}]}):
        with pytest.raises(TypeError):
            basyx.set_list_item_property("EnergyConsumption", 0, "ConsumptionData", value="not a dict")


def test_set_list_item_property_raises_on_index_out_of_range(basyx: AASInterface) -> None:
    with patch.object(basyx, "_get_element_by_path", return_value={"value": []}):
        with pytest.raises(IndexError):
            basyx.set_list_item_property("EnergyConsumption", 0, "TotalConsumption", "x")


def test_set_list_item_property_raises_on_missing_property(basyx: AASInterface) -> None:
    with patch.object(basyx, "_get_element_by_path", return_value={"value": [{"value": []}]}):
        with pytest.raises(KeyError):
            basyx.set_list_item_property("EnergyConsumption", 0, "TotalConsumption", "x")


# -- send_request -----------------------------------------------------------------------


def test_send_request_returns_none_on_204(basyx: AASInterface) -> None:
    resp = _ok(status=204, content=b"")
    with patch.object(aas_mod.requests, "put", return_value=resp):
        out = basyx.send_request(basyx.asset_id, basyx.submodel_id, "X", body_msg={"x": 1})
    assert out is None


def test_send_request_returns_json_when_body_present(basyx: AASInterface) -> None:
    resp = _ok({"ok": True}, content=b'{"ok": true}')
    with patch.object(aas_mod.requests, "put", return_value=resp):
        out = basyx.send_request(basyx.asset_id, basyx.submodel_id, "X", body_msg={"x": 1})
    assert out == {"ok": True}


# -- discover_bop_machines --------------------------------------------------------------


def test_discover_bop_machines_returns_machine_with_process(basyx: AASInterface) -> None:
    """A BOP shell with a Process_X containing MachineDetails must surface a machine row."""
    shells = {"result": [{
        "id": "WO-DMG",
        "submodels": [{"keys": [{"value": "urn:bop:1"}]}],
    }]}
    submodel = {
        "submodelElements": [{
            "idShort": "Process_PR_456_on_DMG",
            "modelType": "SubmodelElementCollection",
            "value": [{
                "idShort": "MachineDetails",
                "value": [{"idShort": "MachineName", "value": "DMG"}],
            }],
        }]
    }
    with patch.object(basyx, "find_shells", return_value=shells):
        with patch.object(aas_mod.requests, "get", return_value=_ok(submodel, content=b"{")):
            machines = basyx.discover_bop_machines()
    assert len(machines) == 1
    assert machines[0]["machine_name"] == "DMG"
    assert machines[0]["process_idShort"] == "Process_PR_456_on_DMG"


def test_discover_bop_machines_skips_non_workorder_shells(basyx: AASInterface) -> None:
    """Shells without ``WO`` in the id must not trigger submodel reads on the main loop.

    A second GET fires only as part of the configured-asset fallback at the end
    of the function — that's expected; we just need to confirm no machines come
    back since the only shell was filtered out.
    """
    shells = {"result": [{"id": "factory-shell", "submodels": [{"keys": [{"value": "urn:x"}]}]}]}
    with patch.object(basyx, "find_shells", return_value=shells):
        # Configured asset fallback also does a GET; let it return an empty shell so we end with [].
        with patch.object(basyx, "get_shell_asset", return_value={"submodels": []}):
            machines = basyx.discover_bop_machines()
    assert machines == []


def test_discover_bop_machines_handles_empty_shell_list(basyx: AASInterface) -> None:
    with patch.object(basyx, "find_shells", return_value={"result": []}):
        assert basyx.discover_bop_machines() == []


# -- set_active_process / _bop_element_url ---------------------------------------------


def test_set_active_process_basyx_uses_registry_url(basyx: AASInterface) -> None:
    basyx.set_active_process("Process_X", "urn:bop", shell_id="WO-1")
    url = basyx._bop_element_url("Energy")
    assert "/submodels/" in url
    assert "/Process_X.Energy" in url


def test_set_active_process_assetfox_falls_back_to_asset_name(assetfox: AASInterface) -> None:
    """When no shell_id is given for AssetFox, the configured asset_name must be used."""
    assetfox.set_active_process("Process_X", "urn:bop", shell_id=None)
    assert assetfox.bop_shell_id is not None  # falls back to asset_name


def test_set_active_process_with_empty_process_keeps_top_level_path(basyx: AASInterface) -> None:
    """Direct-mode (no Process_X wrapper): URL omits the dot prefix."""
    basyx.set_active_process("", "urn:bop", shell_id="WO-1")
    url = basyx._bop_element_url("MachineDetails")
    assert "/MachineDetails" in url
    assert ".MachineDetails" not in url


# -- get_process_property / set_process_property ---------------------------------------


def test_get_process_property_returns_idShort_value(basyx: AASInterface) -> None:
    basyx.set_active_process("Process_X", "urn:bop")
    asset = {"value": [{"idShort": "Status", "value": "Running"}]}
    with patch.object(aas_mod.requests, "get", return_value=_ok(asset)):
        assert basyx.get_process_property("MachineDetails", "Status") == "Running"


def test_set_process_property_does_get_then_put(basyx: AASInterface) -> None:
    basyx.set_active_process("Process_X", "urn:bop")
    asset = {"value": [{"idShort": "Status", "value": "Idle"}]}
    with patch.object(aas_mod.requests, "get", return_value=_ok(asset)) as get:
        with patch.object(aas_mod.requests, "put", return_value=_ok({})) as put:
            basyx.set_process_property("MachineDetails", "Status", "Ended")
    assert asset["value"][0]["value"] == "Ended"
    get.assert_called_once()
    put.assert_called_once()


# -- update_energy_consumption ----------------------------------------------------------


def test_update_energy_consumption_writes_existing_entries(basyx: AASInterface) -> None:
    """Existing ``electricity`` entry: update TotalConsumption + TimeSeriesConsumption in place."""
    basyx.set_active_process("Process_X", "urn:bop")
    energy_list = {"value": [{
        "value": [
            {"idShort": "Name", "value": "electricity"},
            {"idShort": "TotalConsumption", "value": "0"},
            {"idShort": "TimeSeriesConsumption", "value": "[]"},
            {"idShort": "Unit", "value": "kWh"},
            {"idShort": "EnergyConsumptionDataPointId", "value": ""},
        ]
    }]}
    with patch.object(aas_mod.requests, "get", return_value=_ok(energy_list)):
        with patch.object(aas_mod.requests, "put", return_value=_ok({})) as put:
            basyx.update_energy_consumption([
                {"name": "electricity", "total_consumption": "12.5",
                 "time_series_str": "[1,2,3]", "data_point_id": "dp-1"},
            ])
    put.assert_called_once()
    props = energy_list["value"][0]["value"]
    name_to_value = {p["idShort"]: p["value"] for p in props}
    assert name_to_value["TotalConsumption"] == "12.5"
    assert name_to_value["TimeSeriesConsumption"] == "[1,2,3]"
    assert name_to_value["EnergyConsumptionDataPointId"] == "dp-1"


def test_update_energy_consumption_appends_new_entry_for_compressed_air(basyx: AASInterface) -> None:
    """When CompressedAir isn't yet in the list, the client must append a fully-formed entry."""
    basyx.set_active_process("Process_X", "urn:bop")
    energy_list = {"value": [{
        "value": [
            {"idShort": "Name", "value": "electricity"},
            {"idShort": "TotalConsumption", "value": "0"},
            {"idShort": "TimeSeriesConsumption", "value": "[]"},
            {"idShort": "Unit", "value": "kWh"},
            {"idShort": "EnergyConsumptionDataPointId", "value": ""},
        ]
    }]}
    with patch.object(aas_mod.requests, "get", return_value=_ok(energy_list)):
        with patch.object(aas_mod.requests, "put", return_value=_ok({})):
            basyx.update_energy_consumption([
                {"name": "CompressedAir", "total_consumption": "5",
                 "time_series_str": "[1]", "data_point_id": "dp-air"},
            ])
    assert len(energy_list["value"]) == 2
    new_entry = energy_list["value"][1]
    name = next(p["value"] for p in new_entry["value"] if p["idShort"] == "Name")
    unit = next(p["value"] for p in new_entry["value"] if p["idShort"] == "Unit")
    assert name == "CompressedAir"
    assert unit == "M3"


def test_update_energy_consumption_inserts_data_point_id_when_missing(basyx: AASInterface) -> None:
    """Older AAS payloads omit EnergyConsumptionDataPointId; the client must insert it after Unit."""
    basyx.set_active_process("Process_X", "urn:bop")
    energy_list = {"value": [{
        "value": [
            {"idShort": "Name", "value": "electricity"},
            {"idShort": "TotalConsumption", "value": "0"},
            {"idShort": "TimeSeriesConsumption", "value": "[]"},
            {"idShort": "Unit", "value": "kWh"},
        ]
    }]}
    with patch.object(aas_mod.requests, "get", return_value=_ok(energy_list)):
        with patch.object(aas_mod.requests, "put", return_value=_ok({})):
            basyx.update_energy_consumption([
                {"name": "electricity", "total_consumption": "5",
                 "time_series_str": "[1]", "data_point_id": "dp-9"},
            ])
    id_shorts = [p["idShort"] for p in energy_list["value"][0]["value"]]
    assert "EnergyConsumptionDataPointId" in id_shorts


# -- get_smc_prop / get_smc_ref / set_smc_prop / set_reference -------------------------


def test_get_smc_prop_returns_value(basyx: AASInterface) -> None:
    asset = {"value": [{"idShort": "Status", "value": "Running"}]}
    with patch.object(basyx, "get_asset_submodel_element", return_value=asset):
        assert basyx.get_smc_prop("X", "Status") == "Running"


def test_get_smc_ref_extracts_first_key(basyx: AASInterface) -> None:
    asset = {"value": [{"idShort": "Ref", "value": {"keys": [{"value": "urn:thing"}]}}]}
    with patch.object(basyx, "get_asset_submodel_element", return_value=asset):
        assert basyx.get_smc_ref("X", "Ref") == "urn:thing"


def test_set_smc_prop_invokes_send_request(basyx: AASInterface) -> None:
    asset = {"value": [{"idShort": "Status", "value": "Old"}]}
    with patch.object(basyx, "get_asset_submodel_element", return_value=asset):
        with patch.object(basyx, "send_request") as sr:
            basyx.set_smc_prop("X", "Status", "New")
    sr.assert_called_once()
    assert asset["value"][0]["value"] == "New"


def test_set_reference_overwrites_first_key(basyx: AASInterface) -> None:
    asset = {"value": [{"idShort": "Ref", "value": {"keys": [{"value": "urn:old"}]}}]}
    with patch.object(basyx, "get_asset_submodel_element", return_value=asset):
        with patch.object(basyx, "send_request"):
            basyx.set_reference("X", "Ref", "urn:new")
    assert asset["value"][0]["value"]["keys"][0]["value"] == "urn:new"


# -- get_submodel_by_urn ---------------------------------------------------------------


def test_get_submodel_by_urn_basyx_path(basyx: AASInterface) -> None:
    with patch.object(aas_mod.requests, "get", return_value=_ok({"idShort": "BOP"})) as get:
        out = basyx.get_submodel_by_urn("WO-1", "urn:bop")
    assert out["idShort"] == "BOP"
    assert "/submodels/" in get.call_args[0][0]


def test_get_submodel_by_urn_assetfox_path_includes_shell(assetfox: AASInterface) -> None:
    with patch.object(assetfox, "fetch_assetfox_token", return_value="tok"):
        with patch.object(aas_mod.requests, "get", return_value=_ok({"idShort": "BOP"})) as get:
            assetfox.get_submodel_by_urn("WO-1", "urn:bop")
    assert "/shells/" in get.call_args[0][0]


def test_get_submodel_by_urn_raises_on_empty_body(basyx: AASInterface) -> None:
    resp = _ok(status=200, content=b"")
    with patch.object(aas_mod.requests, "get", return_value=resp):
        with pytest.raises(ValueError, match="Empty response"):
            basyx.get_submodel_by_urn("WO-1", "urn:bop")


# -- _get_submodel_ref_by_id_short -----------------------------------------------------


def test_get_submodel_ref_by_id_short_returns_match(basyx: AASInterface) -> None:
    with patch.object(basyx, "get_submodel_refs", return_value=["urn:cp", "urn:bop"]):
        responses = [_ok({"idShort": "Other"}), _ok({"idShort": "CommonParameter"})]
        with patch.object(aas_mod.requests, "get", side_effect=responses):
            ref = basyx._get_submodel_ref_by_id_short("WO-1", "CommonParameter")
    assert ref == "urn:bop"


def test_get_submodel_ref_by_id_short_raises_when_no_match(basyx: AASInterface) -> None:
    with patch.object(basyx, "get_submodel_refs", return_value=["urn:cp"]):
        with patch.object(aas_mod.requests, "get", return_value=_ok({"idShort": "Other"})):
            with pytest.raises(ValueError, match="not found"):
                basyx._get_submodel_ref_by_id_short("WO-1", "BOP")


# -- for_asset classmethod -------------------------------------------------------------


def test_for_asset_picks_submodel_at_index(basyx: AASInterface) -> None:
    """``for_asset(submodel_index=1)`` must select the second submodel from the shell."""
    with patch.object(AASInterface, "get_submodel_refs", return_value=["urn:a", "urn:b"]):
        iface = AASInterface.for_asset("WO-1", "http://x:8081", aas_type="AAS (BaSyx)", submodel_index=1)
    assert iface.submodel_name == "urn:b"


def test_for_asset_raises_when_no_submodels(basyx: AASInterface) -> None:
    with patch.object(AASInterface, "get_submodel_refs", return_value=[]):
        with pytest.raises(ValueError, match="No submodels"):
            AASInterface.for_asset("WO-1", "http://x:8081", aas_type="AAS (BaSyx)")


# -- _resolve_submodel_with_machine_details --------------------------------------------


def test_resolve_submodel_picks_one_with_machine_details() -> None:
    """Construction must auto-pick the submodel containing MachineDetails when names mismatch."""
    target_submodel = {
        "submodelElements": [
            {"idShort": "Other"},
            {"idShort": "MachineDetails"},
        ]
    }
    other_submodel = {"submodelElements": [{"idShort": "X"}]}
    with patch.object(AASInterface, "get_submodel_refs", return_value=["urn:other", "urn:bop"]):
        responses = [_ok(other_submodel, content=b'{"x":1}'), _ok(target_submodel, content=b'{"x":1}')]
        with patch.object(aas_mod.requests, "get", side_effect=responses):
            iface = AASInterface(
                asset_name="WO-1", submodel_name="WO-1",
                base_url="http://x:8081", aas_type="AAS (BaSyx)",
            )
    assert iface.submodel_name == "urn:bop"
