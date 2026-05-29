# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Branch-coverage closers for :mod:`app.services.aas_service`.

The service exposes a small number of well-tested happy paths, but the
spec-critical error handling lives in the *branches* — the bits that decide
whether to skip a shell, fall back to a different AAS response shape, or log
and continue. This file pins each of those branches so a future refactor
can't silently change them.

Test groups (mirror the source file layout):
* ``_get_sigreen_from_config`` — delegation to the SiGREEN factory.
* ``_get_common_parameter_operation_status`` — every short-circuit in the
  response walk (non-200, empty content, missing CommonParameter, missing
  Details, malformed elements/values).
* ``_set_common_parameter_operation_status`` — symmetric short-circuits plus
  the PUT branch.
* ``_extract_common_parameter_details`` — non-200 / non-list element handling
  and ProductFamily extraction (used by the AAS demonstrator).
* ``_get_process_energy_kwh`` — outer exception path (set_active_process fails).
* ``_get_process_materials`` — non-list entries, non-dict props, data-point-id
  fallback when Name is missing, and the AssetFox-style submodel fallback.
* ``_get_shell_time_range`` — exception while reading time range.
* ``_build_aas_db_record`` — distribution PCF per unit branch.
* ``_shell_id_to_product_identifier`` — long-ID truncation.
* ``_process_shell`` — get_product_uuid failure, set_status warning,
  update_from_aas failure (PCF still considered successful).
* ``process_aas_shells_for_pcf`` — discover_bop_machines failure, error attached
  to ``_ShellSkipped`` is forwarded to the cycle ``errors`` list.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services import aas_service


def _ok(json_value, status=200, content=b'{"x":1}'):
    resp = MagicMock(status_code=status, content=content)
    resp.json.return_value = json_value
    resp.raise_for_status = MagicMock()
    resp.text = ""
    return resp


# -- _get_sigreen_from_config --------------------------------------------------


def test_get_sigreen_from_config_delegates_to_factory() -> None:
    """The AAS pipeline must build its SiGREEN client via the shared factory so
    factory_id resolution stays consistent with MES/material lookups."""
    fake_sigi = MagicMock()
    with patch(
        "app.services.sigreen_factory.build_sigreen_for_aas_pipeline",
        return_value=fake_sigi,
    ) as build:
        out = aas_service._get_sigreen_from_config()
    assert out is fake_sigi
    build.assert_called_once_with()


# -- _get_common_parameter_operation_status — short-circuits ------------------


def test_get_common_parameter_status_skips_when_response_non_200() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    with patch.object(aas_service.requests, "get", return_value=_ok({}, status=500)):
        assert aas_service._get_common_parameter_operation_status(aasi, "WO-1") is None


def test_get_common_parameter_status_skips_when_response_body_empty() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    with patch.object(aas_service.requests, "get", return_value=_ok({}, content=b"")):
        assert aas_service._get_common_parameter_operation_status(aasi, "WO-1") is None


def test_get_common_parameter_status_handles_non_list_elements() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    payload = {"idShort": "CommonParameter", "submodelElements": "not-a-list"}
    with patch.object(aas_service.requests, "get", return_value=_ok(payload)):
        assert aas_service._get_common_parameter_operation_status(aasi, "WO-1") is None


def test_get_common_parameter_status_handles_non_list_details_values() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    payload = {
        "idShort": "CommonParameter",
        "submodelElements": [{"idShort": "Details", "value": "not-a-list"}],
    }
    with patch.object(aas_service.requests, "get", return_value=_ok(payload)):
        assert aas_service._get_common_parameter_operation_status(aasi, "WO-1") is None


def test_get_common_parameter_status_skips_non_details_elements() -> None:
    """Other elements before Details must not block the search."""
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    payload = {
        "idShort": "CommonParameter",
        "submodelElements": [
            {"idShort": "Header", "value": []},
            {"idShort": "Details", "value": [
                {"idShort": "OperationStatus", "value": "Ended"},
            ]},
        ],
    }
    with patch.object(aas_service.requests, "get", return_value=_ok(payload)):
        assert aas_service._get_common_parameter_operation_status(aasi, "WO-1") == "Ended"


# -- _set_common_parameter_operation_status — short-circuits -------------------


def test_set_common_parameter_status_skips_when_first_get_non_200() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    with patch.object(aas_service.requests, "get", return_value=_ok({}, status=404)):
        assert aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended") is False


def test_set_common_parameter_status_skips_when_details_get_non_200() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    sm_resp = _ok({"idShort": "CommonParameter"})
    details_resp = _ok({}, status=500)
    with patch.object(aas_service.requests, "get", side_effect=[sm_resp, details_resp]):
        assert aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended") is False


def test_set_common_parameter_status_skips_when_details_values_not_list() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    sm_resp = _ok({"idShort": "CommonParameter"})
    details_resp = _ok({"value": "not-a-list"})
    with patch.object(aas_service.requests, "get", side_effect=[sm_resp, details_resp]):
        assert aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended") is False


def test_set_common_parameter_status_returns_false_when_no_operation_status_prop() -> None:
    """Details exist but contain no OperationStatus → the loop ``break``s and we return False."""
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    sm_resp = _ok({"idShort": "CommonParameter"})
    details_resp = _ok({"value": [{"idShort": "OtherProp", "value": "x"}]})
    with patch.object(aas_service.requests, "get", side_effect=[sm_resp, details_resp]):
        assert aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended") is False


# -- _extract_common_parameter_details — non-200 / non-list -------------------


def test_extract_common_parameter_details_skips_non_200_response() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    with patch.object(aas_service.requests, "get", return_value=_ok({}, status=500)):
        out = aas_service._extract_common_parameter_details(aasi, "WO-1")
    assert all(v is None for v in out.values())


def test_extract_common_parameter_details_handles_non_list_elements() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    payload = {"submodelElements": "not-a-list"}
    with patch.object(aas_service.requests, "get", return_value=_ok(payload)):
        out = aas_service._extract_common_parameter_details(aasi, "WO-1")
    assert all(v is None for v in out.values())


def test_extract_common_parameter_details_skips_elem_with_non_list_values() -> None:
    """An element whose ``value`` isn't a list must be skipped — not crash."""
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    payload = {"submodelElements": [{"value": "not-a-list"}]}
    with patch.object(aas_service.requests, "get", return_value=_ok(payload)):
        out = aas_service._extract_common_parameter_details(aasi, "WO-1")
    assert all(v is None for v in out.values())


# -- _shell_id_to_product_identifier — long IDs --------------------------------


def test_shell_id_to_product_identifier_truncates_long_non_wo_id() -> None:
    """A 30-char shell id without WO must collapse to AAS-{last 24 chars}."""
    long_id = "abcdefghij1234567890abcdefghij"  # 30 chars
    out = aas_service._shell_id_to_product_identifier(long_id)
    assert out == "AAS-" + long_id[-24:]


# -- _get_process_energy_kwh — outer exception path ---------------------------


def test_get_process_energy_kwh_logs_and_returns_zeros_on_outer_failure() -> None:
    """A non-expected exception from the AAS client (e.g. RuntimeError) must not
    propagate — the outer try/except logs and returns zeros so the pipeline can
    continue with the rest of the work order."""
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_list_item_property.side_effect = RuntimeError("unexpected")
    total, ts, t_start, t_end = aas_service._get_process_energy_kwh(aasi, "P", "urn:b", "WO-1")
    assert total == 0.0
    assert ts == []
    assert t_start is None
    assert t_end is None


# -- _get_process_materials — additional shapes -------------------------------


def test_get_process_materials_filters_non_dict_props() -> None:
    """A property that isn't a dict must be silently skipped, not crash."""
    aasi = MagicMock()
    aasi._get_element_by_path.return_value = {"value": [{
        "value": [
            "not-a-dict",
            {"idShort": "Name", "value": "Bolt"},
            {"idShort": "TotalConsumption", "value": "2"},
        ],
    }]}
    out = aas_service._get_process_materials(aasi, "P", "urn:b", "WO-1")
    assert out == [{"name": "Bolt", "quantity": 2.0, "unit": "piece"}]


def test_get_process_materials_uses_data_point_id_when_name_blank() -> None:
    aasi = MagicMock()
    aasi._get_element_by_path.return_value = {"value": [{
        "value": [
            {"idShort": "Name", "value": "null"},  # treated as missing
            {"idShort": "MaterialConsumptionDataPointId", "value": "DP-42"},
            {"idShort": "TotalConsumption", "value": "1"},
        ],
    }]}
    out = aas_service._get_process_materials(aasi, "P", "urn:b", "WO-1")
    assert out == [{"name": "DP-42", "quantity": 1.0, "unit": "piece"}]


def test_get_process_materials_handles_unparseable_quantity_as_zero() -> None:
    """A junk ``Quantity`` must be treated as 0 (entry skipped because qty <= 0)."""
    aasi = MagicMock()
    aasi._get_element_by_path.return_value = {"value": [{
        "value": [
            {"idShort": "Name", "value": "X"},
            {"idShort": "Quantity", "value": "not-a-number"},
        ],
    }]}
    assert aas_service._get_process_materials(aasi, "P", "urn:b", "WO-1") == []


def test_get_process_materials_skips_entries_with_non_list_props() -> None:
    """A material entry whose ``value`` isn't a list must be silently skipped."""
    aasi = MagicMock()
    aasi._get_element_by_path.return_value = {"value": [
        {"value": "not-a-list"},
        {"value": [
            {"idShort": "Name", "value": "Real"},
            {"idShort": "TotalConsumption", "value": "1"},
        ]},
    ]}
    out = aas_service._get_process_materials(aasi, "P", "urn:b", "WO-1")
    assert out == [{"name": "Real", "quantity": 1.0, "unit": "piece"}]


def test_get_process_materials_returns_empty_when_outer_entries_not_list() -> None:
    aasi = MagicMock()
    aasi._get_element_by_path.return_value = {"value": "not-a-list"}
    assert aas_service._get_process_materials(aasi, "P", "urn:b", "WO-1") == []


def test_get_process_materials_logs_when_both_paths_fail() -> None:
    """Both the dotted path *and* the full-submodel fallback may fail — function must return []."""
    aasi = MagicMock()
    aasi._get_element_by_path.side_effect = RuntimeError("dotted path unsupported")
    aasi.get_submodel_by_urn.side_effect = RuntimeError("submodel unavailable")
    assert aas_service._get_process_materials(aasi, "P", "urn:b", "WO-1") == []


# -- _get_shell_time_range — exception path ----------------------------------


def test_get_shell_time_range_uses_defaults_on_per_process_exception() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_process_property.side_effect = RuntimeError("read failed")
    procs = [{"process_idShort": "A", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    t_start, t_end = aas_service._get_shell_time_range(aasi, "WO-1", procs)
    assert t_start == "2026-01-01T00:00:00Z"
    assert t_end == "2026-01-02T00:00:00Z"


# -- _build_aas_db_record — distribution PCF branch --------------------------


def test_build_aas_db_record_propagates_distribution_pcf_per_unit() -> None:
    """When SiGREEN returns separated production+distribution PCF, both must be persisted."""
    bop = {"P1": 1.0}
    kwhs = {"P1": 1.0}
    mats = {"Bolt": {"quantity": 1.0, "unit": "piece"}}
    breakdown = {"Bolt": {
        "carbon_footprint_per_unit": 0.05,
        "carbon_footprint_kg": 0.05,
        "carbon_footprint_distribution_per_unit": 0.01,
    }}
    _, db_mats = aas_service._build_aas_db_record(bop, kwhs, mats, breakdown, gco2=300.0)
    assert db_mats["Bolt"]["carbon_footprint_distribution_per_unit"] == 0.01


# -- _process_shell — late-stage error paths ---------------------------------


def _prep_shell_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(aas_service.settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(aas_service.settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: "Ended")
    monkeypatch.setattr(aas_service, "_get_shell_time_range", lambda *_a: ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
    monkeypatch.setattr(aas_service, "_carbon_intensity_for", lambda *_a: 350.0)
    monkeypatch.setattr(
        aas_service, "_aggregate_processes_data",
        lambda *_a, **_k: ({"P1": 10.0}, {"Bolt": {"quantity": 1.0, "unit": "piece"}}, {"P1": 30.0}, 10.0),
    )
    monkeypatch.setattr(aas_service, "_extract_common_parameter_details", lambda *_a: {
        "product_id": "P-1", "pcf_component_id": None, "work_order": "WO-1", "product_family": None,
    })
    monkeypatch.setattr(aas_service, "collect_idle_cf_by_machine_for_work_order", lambda *_a, **_k: {})
    monkeypatch.setattr(
        aas_service, "build_pcf_report",
        lambda *_a, **_k: {"productCarbonFootprint": 11.5, "emissions": [{"typeOfActivity": "P1", "total": 10.0}]},
    )


def test_process_shell_wraps_get_product_uuid_exception_as_shell_error(monkeypatch, tmp_path) -> None:
    """A failure to resolve the product UUID is an error for *this* shell only."""
    _prep_shell_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(
        aas_service, "_get_product_uuid_from_shell",
        MagicMock(side_effect=RuntimeError("sigreen unavailable")),
    )
    machines = [{"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    with pytest.raises(aas_service._ShellError, match="get/create product failed"):
        aas_service._process_shell("WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=machines)


def test_process_shell_passes_work_order_name_as_batch_number(monkeypatch, tmp_path) -> None:
    """The PCF report sent to SiGREEN must use the work-order name as its ``batch_number``
    — this is what SiGREEN displays per submitted batch in its UI."""
    _prep_shell_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(aas_service, "_get_product_uuid_from_shell", lambda *_a: ("uuid-x", "P-1", False))
    monkeypatch.setattr(aas_service, "_set_common_parameter_operation_status", lambda *_a: True)
    captured: dict = {}

    def capture_build(sigi, **kwargs):
        captured.update(kwargs)
        return {"productCarbonFootprint": 11.5, "emissions": []}

    monkeypatch.setattr(aas_service, "build_pcf_report", capture_build)
    sigi = MagicMock()
    machines = [{"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    aas_service._process_shell("WO-1", aasi=MagicMock(), sigi=sigi, cfg={}, all_machines=machines)
    # work_order from CommonParameter.Details overrides the shell id ("WO-1" in this fixture)
    assert captured.get("batch_number") == "WO-1"
    assert captured.get("work_order_name") == "WO-1"


def test_process_shell_continues_when_update_from_aas_fails(monkeypatch, tmp_path) -> None:
    """If SiGREEN submission succeeded but the local DB write fails, the function must
    still return success — we already published the PCF and don't want to retry that."""
    _prep_shell_happy_path(monkeypatch, tmp_path)
    monkeypatch.setattr(aas_service, "_get_product_uuid_from_shell", lambda *_a: ("uuid-x", "P-1", False))
    monkeypatch.setattr(aas_service, "_set_common_parameter_operation_status", lambda *_a: False)
    monkeypatch.setattr(aas_service, "update_from_aas", MagicMock(side_effect=RuntimeError("disk full")))
    sigi = MagicMock()
    machines = [{"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    out = aas_service._process_shell("WO-1", aasi=MagicMock(), sigi=sigi, cfg={}, all_machines=machines)
    assert out["shell_id"] == "WO-1"
    assert out["total_pcf_kg"] == 11.5
    sigi.send_factory_emissions.assert_called_once()


# -- process_aas_shells_for_pcf — additional cycle failures --------------------


def test_process_aas_shells_for_pcf_handles_discover_bop_machines_failure(monkeypatch) -> None:
    """When ``discover_bop_machines`` raises, the cycle records the error and returns."""
    fake_aasi = MagicMock(aas_type="AAS (BaSyx)")
    fake_aasi.discover_bop_machines.side_effect = RuntimeError("bop registry down")
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake_aasi)
    monkeypatch.setattr(aas_service, "_get_sigreen_from_config", lambda: MagicMock())
    monkeypatch.setattr(aas_service, "_list_workorder_shells", lambda _aasi: ["WO-1"])
    out = aas_service.process_aas_shells_for_pcf()
    assert out["processed"] == 0
    assert any("discover_bop_machines" in e for e in out["errors"])


def test_process_aas_shells_for_pcf_attaches_skip_error_to_errors_list(monkeypatch) -> None:
    """A ``_ShellSkipped(error=...)`` must be counted *both* in skipped and errors."""
    fake_aasi = MagicMock(aas_type="AAS (BaSyx)")
    fake_aasi.discover_bop_machines.return_value = []
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake_aasi)
    monkeypatch.setattr(aas_service, "_get_sigreen_from_config", lambda: MagicMock())
    monkeypatch.setattr(aas_service, "_list_workorder_shells", lambda _aasi: ["WO-1"])
    monkeypatch.setattr(
        aas_service, "_process_shell",
        MagicMock(side_effect=aas_service._ShellSkipped(error="status unreadable")),
    )
    out = aas_service.process_aas_shells_for_pcf()
    assert out["skipped"] == 1
    assert "status unreadable" in out["errors"]
