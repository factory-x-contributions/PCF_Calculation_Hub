# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for :mod:`app.services.aas_service` — the AAS-side PCF orchestrator.

The service stitches together the AAS HTTP client, the SiGREEN HTTP client,
the carbon-intensity strategy, the idle-allocation strategy, and the work-order
JSON store. Each test mocks exactly the seam it is exercising; nothing in this
file talks to a live server.

Why this matters (FX TP2.10 §5.2.5 and §5.2.6):
* The pull-side pipeline must validate every shell, derive a stable product
  identifier from CommonParameter, route credentials through ``sigreen_factory``,
  and never let one bad shell abort the whole cycle.
* The helpers (status decoding, time-range derivation, BOM gathering) are the
  unit boundaries the spec calls out by name; pinning them makes the rest of
  the orchestrator changeable without breaking AAS demo runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services import aas_service


# -- pure helpers ----------------------------------------------------------------------


def test_string_list_to_float_handles_well_formed_list() -> None:
    assert aas_service._string_list_to_float("[1.0, 2.5, 3]") == [1.0, 2.5, 3.0]


@pytest.mark.parametrize("value", ["", "[]", "  ", None])
def test_string_list_to_float_returns_empty_for_blank(value) -> None:
    assert aas_service._string_list_to_float(value or "") == []


def test_aas_time_to_sigreen_format_normalises_z_suffix() -> None:
    out = aas_service._aas_time_to_sigreen_format("2026-03-04T15:48:36Z")
    assert out == "2026-03-04T15:48:36.000Z"


def test_aas_time_to_sigreen_format_returns_empty_for_blank() -> None:
    assert aas_service._aas_time_to_sigreen_format("") == ""


def test_date_offset_subtracts_one_day_by_default() -> None:
    assert aas_service._date_offset("2026-03-05T00:00:00Z").startswith("2026-03-04T")


def test_shell_id_to_product_identifier_extracts_wo_pattern() -> None:
    """Shell IDs like ``WO20260304121530xx`` must yield the WO + 14-digit suffix."""
    sid = "WO20260304121530-extra"
    assert aas_service._shell_id_to_product_identifier(sid) == "WO20260304121530"


def test_shell_id_to_product_identifier_falls_back_to_short_form() -> None:
    """A short shell id without WO falls back to a stable AAS- prefix."""
    assert aas_service._shell_id_to_product_identifier("abc") == "AAS-abc"


def test_shell_id_to_product_identifier_returns_unknown_for_blank() -> None:
    assert aas_service._shell_id_to_product_identifier("") == "AAS-unknown"


@pytest.mark.parametrize("item,expected", [
    ("WO-1", "WO-1"),
    ({"id": "WO-1"}, "WO-1"),
    ({"idShort": "WO-1"}, "WO-1"),
    ({}, ""),
    (123, ""),
])
def test_shell_id_from_normalises_inputs(item, expected) -> None:
    assert aas_service._shell_id_from(item) == expected


# -- processed-shells store -----------------------------------------------------------


def test_load_processed_shells_returns_empty_when_file_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(aas_service.settings, "database_path", str(tmp_path / "db.json"))
    assert aas_service._load_processed_shells() == set()


def test_mark_then_load_roundtrips(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(aas_service.settings, "database_path", str(tmp_path / "db.json"))
    aas_service._mark_shell_processed("WO-1")
    aas_service._mark_shell_processed("WO-2")
    assert aas_service._load_processed_shells() == {"WO-1", "WO-2"}


def test_load_processed_shells_recovers_from_corrupt_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(aas_service.settings, "database_path", str(tmp_path / "db.json"))
    path = aas_service._get_processed_shells_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert aas_service._load_processed_shells() == set()


# -- _get_aas_interface_from_config ---------------------------------------------------


def test_get_aas_interface_returns_none_when_no_base_url(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"aas_base_url": ""})
    assert aas_service._get_aas_interface_from_config() is None


def test_get_aas_interface_picks_basyx_for_known_aas_type(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {
        "aas_base_url": "http://basyx:8081",
        "aas_type": "AAS (BaSyx)",
        "aas_asset_name": "WO-1",
    })
    iface = aas_service._get_aas_interface_from_config()
    assert iface is not None
    assert iface.aas_type == "AAS (BaSyx)"


def test_get_aas_interface_infers_assetfox_from_url_when_type_missing(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {
        "aas_base_url": "https://test.assetfox.apps.siemens.cloud/api/aas/v3",
        "aas_type": "",
        "aas_asset_name": "WO-1",
    })
    iface = aas_service._get_aas_interface_from_config()
    assert iface is not None
    assert iface.aas_type == "AAS (AssetFox)"


# -- _list_workorder_shells -----------------------------------------------------------


def test_list_workorder_shells_returns_string_ids() -> None:
    aasi = MagicMock()
    aasi.find_shells.return_value = {"result": ["WO-1", {"id": "WO-2"}, {"idShort": "WO-3"}]}
    assert aas_service._list_workorder_shells(aasi) == ["WO-1", "WO-2", "WO-3"]


def test_list_workorder_shells_returns_empty_on_unexpected_payload() -> None:
    aasi = MagicMock()
    aasi.find_shells.return_value = "garbage"
    assert aas_service._list_workorder_shells(aasi) == []


# -- _carbon_intensity_for ------------------------------------------------------------


def test_carbon_intensity_for_returns_constant_by_default() -> None:
    cfg = {"carbon_intensity_constant_gco2": 410}
    out = aas_service._carbon_intensity_for(cfg, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
    assert out == 410.0


def test_carbon_intensity_for_handles_unparseable_timestamps() -> None:
    """Bad timestamps must not crash the pipeline; the constant strategy returns the configured value."""
    cfg = {"carbon_intensity_constant_gco2": 350}
    out = aas_service._carbon_intensity_for(cfg, "garbage", "also garbage")
    assert out == 350.0


def test_carbon_intensity_for_dispatches_to_grid_compass_when_configured(monkeypatch) -> None:
    """When ``carbon_intensity_source=green_grid_compass`` the AAS pipeline must hit Grid Compass."""
    fake_grid = MagicMock()
    fake_grid.get_avg_carbon_coeff.return_value = 295.0
    cfg = {"carbon_intensity_source": "green_grid_compass"}
    with patch("app.integrations.grid.GridInterface", return_value=fake_grid):
        out = aas_service._carbon_intensity_for(cfg, "2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
    assert out == 295.0


# -- get_available_aas_shells ---------------------------------------------------------


def test_get_available_aas_shells_returns_error_when_data_source_not_aas(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "mes"})
    out = aas_service.get_available_aas_shells()
    assert out == {"shell_ids": [], "error": "Data source is not AAS"}


def test_get_available_aas_shells_returns_error_when_aas_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: None)
    out = aas_service.get_available_aas_shells()
    assert out["error"] == "AAS base URL not configured"


def test_get_available_aas_shells_filters_to_workorder_shells(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    fake = MagicMock()
    fake.find_shells.return_value = {"result": [
        "WO-1",
        {"id": "factory-shell"},
        {"id": "WO-2"},
    ]}
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake)
    out = aas_service.get_available_aas_shells()
    assert out["shell_ids"] == ["WO-1", "WO-2"]
    assert out["error"] is None


def test_get_available_aas_shells_captures_exception_message(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    fake = MagicMock()
    fake.find_shells.side_effect = RuntimeError("registry unreachable")
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake)
    out = aas_service.get_available_aas_shells()
    assert "registry unreachable" in (out["error"] or "")


# -- _get_common_parameter_operation_status -------------------------------------------


def _ok_resp(json_value: dict | list, status: int = 200, content: bytes = b'{"x":1}') -> MagicMock:
    resp = MagicMock(status_code=status, content=content)
    resp.json.return_value = json_value
    resp.raise_for_status = MagicMock()
    resp.text = ""
    return resp


def test_get_common_parameter_operation_status_returns_value_when_present() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    common = {
        "idShort": "CommonParameter",
        "submodelElements": [{
            "idShort": "Details",
            "value": [{"idShort": "OperationStatus", "value": "Ended"}],
        }],
    }
    with patch.object(aas_service.requests, "get", return_value=_ok_resp(common)):
        status = aas_service._get_common_parameter_operation_status(aasi, "WO-1")
    assert status == "Ended"


def test_get_common_parameter_operation_status_returns_none_when_not_common_parameter() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:other"]
    other = {"idShort": "Other"}
    with patch.object(aas_service.requests, "get", return_value=_ok_resp(other)):
        status = aas_service._get_common_parameter_operation_status(aasi, "WO-1")
    assert status is None


def test_get_common_parameter_operation_status_returns_none_on_exception() -> None:
    aasi = MagicMock()
    aasi.get_submodel_refs.side_effect = RuntimeError("boom")
    assert aas_service._get_common_parameter_operation_status(aasi, "WO-1") is None


# -- _set_common_parameter_operation_status -------------------------------------------


def test_set_common_parameter_operation_status_returns_true_on_put_success() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    sm_resp = _ok_resp({"idShort": "CommonParameter"})
    details_resp = _ok_resp({"value": [{"idShort": "OperationStatus", "value": "Init"}]})
    put_resp = MagicMock(status_code=204, content=b"")
    put_resp.raise_for_status = MagicMock()
    with patch.object(aas_service.requests, "get", side_effect=[sm_resp, details_resp]):
        with patch.object(aas_service.requests, "put", return_value=put_resp) as put:
            ok = aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended")
    assert ok is True
    put.assert_called_once()


def test_set_common_parameter_operation_status_returns_false_when_no_common_parameter() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:other"]
    with patch.object(aas_service.requests, "get", return_value=_ok_resp({"idShort": "Other"})):
        assert aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended") is False


def test_set_common_parameter_operation_status_returns_false_on_exception() -> None:
    aasi = MagicMock()
    aasi.get_submodel_refs.side_effect = RuntimeError("network down")
    assert aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended") is False


# -- _extract_common_parameter_details ------------------------------------------------


def test_extract_common_parameter_details_finds_all_fields() -> None:
    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:cp"]
    sm = {
        "submodelElements": [{
            "idShort": "Details",
            "value": [
                {"idShort": "ProductID", "value": "P-1"},
                {"idShort": "PcfComponentId", "value": "uuid-12345-67890"},
                {"idShort": "WorkOrder", "value": "WO_42"},
                {"idShort": "ProductFamily", "value": "Test"},
            ],
        }]
    }
    with patch.object(aas_service.requests, "get", return_value=_ok_resp(sm)):
        out = aas_service._extract_common_parameter_details(aasi, "WO-1")
    assert out == {
        "product_id": "P-1",
        "pcf_component_id": "uuid-12345-67890",
        "work_order": "WO_42",
        "product_family": "Test",
    }


def test_extract_common_parameter_details_swallows_exception() -> None:
    aasi = MagicMock()
    aasi.get_submodel_refs.side_effect = RuntimeError("boom")
    out = aas_service._extract_common_parameter_details(aasi, "WO-1")
    assert all(v is None for v in out.values())


# -- _get_product_uuid_from_shell -----------------------------------------------------


def test_get_product_uuid_uses_pcf_component_id_when_present(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_extract_common_parameter_details", lambda *_a: {
        "pcf_component_id": "uuid-aaaa-bbbb-cccc",
        "product_id": None, "work_order": None, "product_family": None,
    })
    aasi = MagicMock()
    sigi = MagicMock()
    uuid, ident, was_created = aas_service._get_product_uuid_from_shell(aasi, "WO-1", sigi)
    assert uuid == "uuid-aaaa-bbbb-cccc"
    assert ident is None
    assert was_created is None


def test_get_product_uuid_creates_via_get_or_create_when_id_missing(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_extract_common_parameter_details", lambda *_a: {
        "pcf_component_id": None, "product_id": "P-1", "work_order": None, "product_family": None,
    })
    aasi = MagicMock()
    sigi = MagicMock()
    with patch.object(aas_service, "get_or_create_product_uuid", return_value=("uuid-x", True)):
        uuid, ident, was_created = aas_service._get_product_uuid_from_shell(aasi, "WO-1", sigi)
    assert uuid == "uuid-x"
    assert ident == "P-1"
    assert was_created is True


def test_get_product_uuid_uses_default_when_no_sigi(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_extract_common_parameter_details", lambda *_a: {
        "pcf_component_id": None, "product_id": None, "work_order": None, "product_family": None,
    })
    aasi = MagicMock()
    uuid, ident, was_created = aas_service._get_product_uuid_from_shell(aasi, "WO-1", None)
    assert uuid == aas_service.DEFAULT_PRODUCT_UUID
    assert ident is None


# -- _get_process_energy_kwh / _get_process_materials ---------------------------------


def test_get_process_energy_kwh_returns_total_and_time_series() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_list_item_property.return_value = {"TotalConsumption": "12.5", "TimeSeriesConsumption": "[1.0, 2.5]"}
    aasi.get_process_property.side_effect = ["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]
    total, ts, t_start, t_end = aas_service._get_process_energy_kwh(aasi, "Process_X", "urn:bop", "WO-1")
    assert total == 12.5
    assert ts == [1.0, 2.5]
    assert t_start == "2026-01-01T00:00:00Z"
    assert t_end == "2026-01-01T01:00:00Z"


def test_get_process_energy_kwh_falls_back_to_sum_of_time_series_when_total_zero() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_list_item_property.return_value = {"TotalConsumption": None, "TimeSeriesConsumption": "[3, 4, 5]"}
    aasi.get_process_property.side_effect = [None, None]
    total, ts, _, _ = aas_service._get_process_energy_kwh(aasi, "Process_X", "urn:bop", "WO-1")
    assert total == 12.0
    assert ts == [3.0, 4.0, 5.0]


def test_get_process_energy_kwh_handles_exceptions_gracefully() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_list_item_property.side_effect = KeyError("missing")
    aasi.get_process_property.side_effect = StopIteration
    total, ts, t_start, t_end = aas_service._get_process_energy_kwh(aasi, "Process_X", "urn:bop", "WO-1")
    assert total == 0.0
    assert ts == []


def test_get_process_materials_returns_parsed_entries() -> None:
    aasi = MagicMock()
    elem = {"value": [{
        "value": [
            {"idShort": "Name", "value": "Bolt-M6"},
            {"idShort": "TotalConsumption", "value": "4"},
            {"idShort": "Unit", "value": "piece"},
        ]
    }]}
    aasi._get_element_by_path.return_value = elem
    out = aas_service._get_process_materials(aasi, "Process_X", "urn:bop", "WO-1")
    assert out == [{"name": "Bolt-M6", "quantity": 4.0, "unit": "piece"}]


def test_get_process_materials_skips_zero_quantity_entries() -> None:
    aasi = MagicMock()
    elem = {"value": [{
        "value": [
            {"idShort": "Name", "value": "X"},
            {"idShort": "TotalConsumption", "value": "0"},
        ]
    }]}
    aasi._get_element_by_path.return_value = elem
    assert aas_service._get_process_materials(aasi, "Process_X", "urn:bop", "WO-1") == []


def test_get_process_materials_falls_back_to_full_submodel_on_path_error() -> None:
    """Some AAS APIs reject the dotted path; the function must walk the full submodel."""
    aasi = MagicMock()
    aasi._get_element_by_path.side_effect = RuntimeError("path not supported")
    aasi.get_submodel_by_urn.return_value = {
        "submodelElements": [{
            "idShort": "Process_X",
            "value": [{
                "idShort": "MaterialConsumption",
                "value": [{
                    "value": [
                        {"idShort": "Name", "value": "Bracket"},
                        {"idShort": "Quantity", "value": "1"},
                        {"idShort": "Unit", "value": "piece"},
                    ]
                }],
            }],
        }]
    }
    out = aas_service._get_process_materials(aasi, "Process_X", "urn:bop", "WO-1")
    assert out == [{"name": "Bracket", "quantity": 1.0, "unit": "piece"}]


# -- _get_process_operation_status ----------------------------------------------------


def test_get_process_operation_status_returns_first_match() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_process_property.side_effect = [None, "Ended"]
    proc = {"process_idShort": "P", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}
    assert aas_service._get_process_operation_status(aasi, proc) == "Ended"


def test_get_process_operation_status_returns_none_when_all_lookups_fail() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_process_property.side_effect = KeyError("none")
    proc = {"process_idShort": "P", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}
    assert aas_service._get_process_operation_status(aasi, proc) is None


# -- _get_shell_time_range ------------------------------------------------------------


def test_get_shell_time_range_returns_min_start_and_max_end() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_process_property.side_effect = [
        "2026-03-05T15:00:00Z", "2026-03-05T16:00:00Z",  # process 1
        "2026-03-05T14:00:00Z", "2026-03-05T17:00:00Z",  # process 2 (wider)
    ]
    procs = [
        {"process_idShort": "A", "bop_submodel_id": "urn:b", "shell_id": "WO-1"},
        {"process_idShort": "B", "bop_submodel_id": "urn:b", "shell_id": "WO-1"},
    ]
    t_start, t_end = aas_service._get_shell_time_range(aasi, "WO-1", procs)
    assert t_start == "2026-03-05T14:00:00Z"
    assert t_end == "2026-03-05T17:00:00Z"


def test_get_shell_time_range_falls_back_to_default_dates() -> None:
    aasi = MagicMock()
    aasi.set_active_process = MagicMock()
    aasi.get_process_property.side_effect = [None, None]
    procs = [{"process_idShort": "A", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    t_start, t_end = aas_service._get_shell_time_range(aasi, "WO-1", procs)
    assert t_start.startswith("2026-")
    assert t_end.startswith("2026-")


# -- _aggregate_processes_data --------------------------------------------------------


def test_aggregate_processes_data_sums_energy_and_collects_materials(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_get_process_energy_kwh", lambda *_a: (10.0, [], None, None))
    monkeypatch.setattr(aas_service, "_get_process_materials", lambda *_a: [
        {"name": "Bolt", "quantity": 2.0, "unit": "piece"},
    ])
    aasi = MagicMock()
    procs = [
        {"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"},
        {"process_idShort": "P2", "bop_submodel_id": "urn:b", "shell_id": "WO-1"},
    ]
    bop, mats, kwhs, energy_pcf = aas_service._aggregate_processes_data(aasi, procs, gco2=350.0, shell_id="WO-1")
    # Each process contributes 10 kWh * 350 / 1000 = 3.5 kg
    assert bop == {"P1": pytest.approx(3.5), "P2": pytest.approx(3.5)}
    assert kwhs == {"P1": 10.0, "P2": 10.0}
    # Same material in both processes — quantities accumulate
    assert mats == {"Bolt": {"quantity": 4.0, "unit": "piece"}}
    assert energy_pcf == pytest.approx(7.0)


# -- _build_aas_db_record -------------------------------------------------------------


def test_build_aas_db_record_shapes_operations_and_materials() -> None:
    bop = {"P1": 3.5}
    kwhs = {"P1": 10.0}
    mats = {"Bolt": {"quantity": 4.0, "unit": "piece"}}
    breakdown = {"Bolt": {
        "carbon_footprint_per_unit": 0.05,
        "carbon_footprint_kg": 0.2,
        "carbon_footprint_production_per_unit": 0.04,
    }}
    ops, db_mats = aas_service._build_aas_db_record(bop, kwhs, mats, breakdown, gco2=350.0)
    assert ops["P1"]["energy"]["carbon_footprint_kg"] == 3.5
    assert db_mats["Bolt"]["carbon_footprint_per_unit"] == 0.05
    assert db_mats["Bolt"]["carbon_footprint_production_per_unit"] == 0.04


def test_build_aas_db_record_skips_optional_breakdown_fields() -> None:
    bop = {"P1": 1.0}
    kwhs = {"P1": 1.0}
    mats = {"Bolt": {"quantity": 1.0, "unit": "piece"}}
    ops, db_mats = aas_service._build_aas_db_record(bop, kwhs, mats, {}, gco2=300.0)
    assert "carbon_footprint_kg" not in db_mats["Bolt"]


# -- process_aas_shells_for_pcf -------------------------------------------------------


def test_process_aas_shells_for_pcf_returns_error_when_data_source_not_aas(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "mes"})
    out = aas_service.process_aas_shells_for_pcf()
    assert "Data source is not AAS" in out["errors"]


def test_process_aas_shells_for_pcf_returns_error_when_aas_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: None)
    out = aas_service.process_aas_shells_for_pcf()
    assert "AAS base URL not configured" in out["errors"]


def test_process_aas_shells_for_pcf_returns_error_when_sigreen_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: MagicMock())
    monkeypatch.setattr(aas_service, "_get_sigreen_from_config", lambda: None)
    out = aas_service.process_aas_shells_for_pcf()
    assert "SiGREEN not configured" in out["errors"]


def test_process_aas_shells_for_pcf_continues_after_per_shell_error(monkeypatch) -> None:
    """One bad shell must not abort the whole cycle — error list grows, processing continues."""
    fake_aasi = MagicMock(aas_type="AAS (BaSyx)")
    fake_aasi.discover_bop_machines.return_value = []
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake_aasi)
    monkeypatch.setattr(aas_service, "_get_sigreen_from_config", lambda: MagicMock())
    monkeypatch.setattr(aas_service, "_list_workorder_shells", lambda _aasi: ["WO-1", "WO-2"])

    def fake_process(shell_id, *_a, **_k):
        if shell_id == "WO-1":
            raise aas_service._ShellError("bad")
        raise aas_service._ShellSkipped()

    monkeypatch.setattr(aas_service, "_process_shell", fake_process)
    out = aas_service.process_aas_shells_for_pcf()
    assert out["processed"] == 0
    assert out["skipped"] == 1
    assert "bad" in out["errors"]


def test_process_aas_shells_for_pcf_collects_processed_outcomes(monkeypatch) -> None:
    fake_aasi = MagicMock(aas_type="AAS (BaSyx)")
    fake_aasi.discover_bop_machines.return_value = []
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake_aasi)
    monkeypatch.setattr(aas_service, "_get_sigreen_from_config", lambda: MagicMock())
    monkeypatch.setattr(aas_service, "_list_workorder_shells", lambda _aasi: ["WO-1"])
    monkeypatch.setattr(aas_service, "_process_shell", lambda *_a, **_k: {
        "shell_id": "WO-1", "work_order": "WO-1", "product_uuid": "u",
        "total_pcf_kg": 1.0, "energy_pcf_kg": 0.5, "bom_pcf_kg": 0.5, "materials_count": 1,
    })
    out = aas_service.process_aas_shells_for_pcf()
    assert out["processed"] == 1
    assert out["shells_processed"][0]["shell_id"] == "WO-1"


def test_process_aas_shells_for_pcf_handles_find_shells_failure(monkeypatch) -> None:
    fake_aasi = MagicMock(aas_type="AAS (BaSyx)")
    monkeypatch.setattr(aas_service, "load_app_config", lambda: {"data_source": "aas"})
    monkeypatch.setattr(aas_service, "_get_aas_interface_from_config", lambda: fake_aasi)
    monkeypatch.setattr(aas_service, "_get_sigreen_from_config", lambda: MagicMock())

    def boom(_aasi):
        raise RuntimeError("registry down")

    monkeypatch.setattr(aas_service, "_list_workorder_shells", boom)
    out = aas_service.process_aas_shells_for_pcf()
    assert any("registry down" in e for e in out["errors"])


# -- _process_shell -------------------------------------------------------------------


def test_process_shell_skips_when_shell_id_lacks_wo() -> None:
    with pytest.raises(aas_service._ShellSkipped):
        aas_service._process_shell(
            "factory-shell", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=[],
        )


def test_process_shell_skips_when_already_ended(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: "Ended")
    with pytest.raises(aas_service._ShellSkipped):
        aas_service._process_shell(
            "WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=[],
        )


def test_process_shell_skips_when_no_bop_processes(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    with pytest.raises(aas_service._ShellSkipped):
        aas_service._process_shell(
            "WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=[],
        )


def test_process_shell_skips_when_status_unreadable(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: None)
    machines = [{"process_idShort": "P", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    with pytest.raises(aas_service._ShellSkipped) as info:
        aas_service._process_shell(
            "WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=machines,
        )
    assert "could not read" in str(info.value)


def test_process_shell_skips_when_status_not_ready(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: "Running")
    machines = [{"process_idShort": "P", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    with pytest.raises(aas_service._ShellSkipped):
        aas_service._process_shell(
            "WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=machines,
        )


def test_process_shell_raises_shell_error_when_no_consumption(monkeypatch) -> None:
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: "Ended")
    monkeypatch.setattr(aas_service, "_get_shell_time_range", lambda *_a: ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
    monkeypatch.setattr(aas_service, "_carbon_intensity_for", lambda *_a: 350.0)
    monkeypatch.setattr(aas_service, "_aggregate_processes_data", lambda *_a, **_k: ({}, {}, {}, 0.0))
    machines = [{"process_idShort": "P", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    with pytest.raises(aas_service._ShellError, match="no consumption data"):
        aas_service._process_shell(
            "WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=machines,
        )


def test_process_shell_happy_path_returns_summary(monkeypatch, tmp_path) -> None:
    """Drive every collaborator with small fakes and verify the returned summary."""
    monkeypatch.setattr(aas_service.settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(aas_service.settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: "Ended")
    monkeypatch.setattr(aas_service, "_get_shell_time_range", lambda *_a: ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
    monkeypatch.setattr(aas_service, "_carbon_intensity_for", lambda *_a: 350.0)
    monkeypatch.setattr(aas_service, "_aggregate_processes_data", lambda *_a, **_k: (
        {"P1": 10.0}, {"Bolt": {"quantity": 1.0, "unit": "piece"}}, {"P1": 30.0}, 10.0,
    ))
    monkeypatch.setattr(aas_service, "_extract_common_parameter_details", lambda *_a: {
        "product_id": "P-1", "pcf_component_id": None, "work_order": "WO-1", "product_family": None,
    })
    monkeypatch.setattr(aas_service, "collect_idle_cf_by_machine_for_work_order", lambda *_a, **_k: {})
    monkeypatch.setattr(
        aas_service, "build_pcf_report",
        lambda *_a, **_k: {"productCarbonFootprint": 11.5, "emissions": [{"typeOfActivity": "P1", "total": 10.0}]},
    )
    monkeypatch.setattr(aas_service, "_get_product_uuid_from_shell", lambda *_a: ("uuid-x", "P-1", False))
    monkeypatch.setattr(aas_service, "_set_common_parameter_operation_status", lambda *_a: True)

    sigi = MagicMock()
    machines = [{"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    out = aas_service._process_shell("WO-1", aasi=MagicMock(), sigi=sigi, cfg={}, all_machines=machines)

    assert out["shell_id"] == "WO-1"
    assert out["work_order"] == "WO-1"
    assert out["product_uuid"] == "uuid-x"
    assert out["total_pcf_kg"] == 11.5
    sigi.send_factory_emissions.assert_called_once()
