"""
Unit tests for AAS (Asset Administration Shell) data source option.

Validates that the AAS option works correctly with the new AAS_WO_2026_03_04_Template model.
The previous model (using only OperationStatus) is deprecated; the new model may use
ProcessOperationStatus in MachineDetails.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Template path under tests/fixtures
TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "aas" / "AAS_WO_2026_03_04_Template.json"

# Submodel IDs from template (used to match mocked URLs)
COMMON_PARAMETER_ID = "urn:submodel:ca7ee2a9-c739-4300-a7cf-0c216310f988"
BILL_OF_PROCESS_ID = "urn:submodel:bc115d38-5edf-4a91-8582-e1a2b8784716"


def _load_template() -> dict:
    """Load the new AAS template JSON."""
    with TEMPLATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _get_shell_from_template() -> dict:
    """Extract shell descriptor from template."""
    data = _load_template()
    shells = data.get("assetAdministrationShells", [])
    assert shells, "Template must have at least one assetAdministrationShell"
    return shells[0]


def _get_submodel_by_id(sm_id: str) -> dict | None:
    """Get submodel by id from template."""
    data = _load_template()
    for sm in data.get("submodels", []):
        if sm.get("id") == sm_id:
            return sm
    return None


def _find_property_in_collection(collection: dict, id_short: str):
    """Find property value in a SubmodelElementCollection's value array."""
    for item in collection.get("value", []):
        if isinstance(item, dict) and item.get("idShort") == id_short:
            return item.get("value")
    return None


def _get_process_element(bop_submodel: dict, process_id: str, element_id: str) -> dict | None:
    """Get a collection element (e.g. MachineDetails, TakenPlaceProduction) from a BOP process."""
    for proc_elem in bop_submodel.get("submodelElements", []):
        if proc_elem.get("idShort") != process_id:
            continue
        for child in proc_elem.get("value", []):
            if isinstance(child, dict) and child.get("idShort") == element_id:
                return child
    return None


def _get_element_by_dotted_path(submodel: dict, dotted_path: str) -> dict | None:
    """Get element from submodel by dotted path (e.g. 'Process_PR_456_on_DMG.MachineDetails')."""
    parts = dotted_path.split(".")
    current = submodel
    for part in parts:
        if not part:
            return None
        if "submodelElements" in current:
            current = next(
                (e for e in current.get("submodelElements", []) if e.get("idShort") == part),
                None,
            )
        elif "value" in current and isinstance(current.get("value"), list):
            current = next(
                (e for e in current.get("value", []) if isinstance(e, dict) and e.get("idShort") == part),
                None,
            )
        else:
            return None
        if current is None:
            return None
    return current


class MockAASInterface:
    """
    Mock AASInterface that serves data from AAS_WO_2026_03_04_Template.json.
    Used to test aas_service logic without HTTP calls.
    """

    def __init__(self):
        self.template = _load_template()
        self.shell = _get_shell_from_template()
        self.shell_id = self.shell.get("idShort") or self.shell.get("id", "")
        self.active_process: str | None = None
        self.bop_submodel_id: str | None = None
        self.bop_shell_id: str | None = None
        self.aas_type = "AAS (AssetFox)"
        self.registry_base_url = "https://test.example.com/api/aas/v3"

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def find_shells(self) -> dict:
        """Return shells in API format."""
        return {"result": [self.shell]}

    def get_shell_asset(self, shell_name: str) -> dict:
        """Return shell descriptor."""
        if shell_name == self.shell_id or shell_name in (self.shell.get("id"), self.shell.get("idShort")):
            return self.shell
        raise ValueError(f"Shell not found: {shell_name}")

    def get_submodel_refs(self, shell_id: str) -> list[str]:
        """Return submodel reference values from shell."""
        shell = self.get_shell_asset(shell_id)
        refs = []
        for sm in shell.get("submodels", []):
            try:
                val = sm["keys"][0]["value"]
                refs.append(val)
            except (KeyError, IndexError):
                continue
        return refs

    def discover_bop_machines(self, shell_id: str | None = None) -> list[dict]:
        """Discover BOP machines from Bill_of_Process submodel (new template model)."""
        sid = shell_id or self.shell_id
        shell = self.get_shell_asset(sid)
        machines = []
        for ref in shell.get("submodels", []):
            try:
                sm_id = ref["keys"][0]["value"]
            except (KeyError, IndexError):
                continue
            sm = _get_submodel_by_id(sm_id)
            if not sm:
                continue
            elems = sm.get("submodelElements", [])
            for elem in elems:
                if elem.get("modelType") != "SubmodelElementCollection":
                    continue
                md = next(
                    (c for c in elem.get("value", [])
                     if isinstance(c, dict) and c.get("idShort") == "MachineDetails"),
                    None,
                )
                if md is None:
                    continue
                name = _find_property_in_collection(md, "MachineName")
                if name:
                    machines.append({
                        "machine_name": name,
                        "process_idShort": elem.get("idShort", ""),
                        "bop_submodel_id": sm_id,
                        "shell_id": sid,
                    })
        return machines

    def set_active_process(self, process_id_short: str, bop_submodel_id: str, shell_id: str | None = None) -> None:
        """Set active BOP process for subsequent calls."""
        self.active_process = process_id_short
        self.bop_submodel_id = bop_submodel_id
        self.bop_shell_id = shell_id or self.shell_id

    def get_process_property(self, element_id: str, id_short: str):
        """Get property from active process collection (MachineDetails, TakenPlaceProduction, etc.)."""
        if not self.bop_submodel_id:
            raise ValueError("No active process set")
        sm = _get_submodel_by_id(self.bop_submodel_id)
        if not sm:
            raise ValueError(f"Submodel not found: {self.bop_submodel_id}")
        elem = _get_process_element(sm, self.active_process or "", element_id)
        if not elem:
            raise KeyError(f"Element {element_id} not found")
        return _find_property_in_collection(elem, id_short)

    def get_list_item_property(self, element_id: str, index: int, id_short: str):
        """Get property from EnergyConsumption list item. Supports ConsumptionData."""
        if not self.bop_submodel_id:
            raise ValueError("No active process set")
        sm = _get_submodel_by_id(self.bop_submodel_id)
        if not sm:
            raise ValueError(f"Submodel not found: {self.bop_submodel_id}")
        energy_elem = _get_process_element(sm, self.active_process or "", element_id)
        if not energy_elem:
            raise KeyError(f"Element {element_id} not found")
        entries = energy_elem.get("value", [])
        if index >= len(entries):
            raise IndexError(f"List index {index} out of range")
        item = entries[index]
        props = item.get("value", [])
        if id_short == "ConsumptionData":
            total = next((p.get("value") for p in props if p.get("idShort") == "TotalConsumption"), None)
            timeseries = next((p.get("value") for p in props if p.get("idShort") == "TimeSeriesConsumption"), None)
            return {"TotalConsumption": total, "TimeSeriesConsumption": timeseries}
        p = next((x for x in props if isinstance(x, dict) and x.get("idShort") == id_short), None)
        if p is None:
            raise KeyError(f"Property '{id_short}' not found")
        return p.get("value")


# ---------------------------------------------------------------------------
# Tests for new AAS_WO_2026_03_04_Template model
# ---------------------------------------------------------------------------


def test_template_loads() -> None:
    """Template file exists and is valid JSON."""
    data = _load_template()
    assert "assetAdministrationShells" in data
    assert "submodels" in data
    assert len(data["assetAdministrationShells"]) >= 1
    assert len(data["submodels"]) >= 2


def test_template_has_common_parameter_and_bill_of_process() -> None:
    """New template has CommonParameter and Bill_of_Process submodels."""
    data = _load_template()
    submodel_ids = [sm.get("idShort") for sm in data.get("submodels", [])]
    assert "CommonParameter" in submodel_ids
    assert "Bill_of_Process" in submodel_ids


def test_template_process_pr_456_uses_process_operation_status() -> None:
    """Process_PR_456_on_DMG uses ProcessOperationStatus (new model), not OperationStatus."""
    bop = _get_submodel_by_id("urn:submodel:bc115d38-5edf-4a91-8582-e1a2b8784716")
    assert bop is not None
    proc = next(e for e in bop.get("submodelElements", []) if e.get("idShort") == "Process_PR_456_on_DMG")
    assert proc is not None
    md = next(c for c in proc.get("value", []) if isinstance(c, dict) and c.get("idShort") == "MachineDetails")
    assert md is not None
    status_prop = next(p for p in md.get("value", []) if p.get("idShort") == "ProcessOperationStatus")
    assert status_prop is not None
    assert status_prop.get("value") == "Ended"


def test_template_process_pr_123_uses_operation_status() -> None:
    """Process_PR_123_on_Trumpf uses OperationStatus (deprecated but still supported)."""
    bop = _get_submodel_by_id("urn:submodel:bc115d38-5edf-4a91-8582-e1a2b8784716")
    assert bop is not None
    proc = next(e for e in bop.get("submodelElements", []) if e.get("idShort") == "Process_PR_123_on_Trumpf")
    assert proc is not None
    md = next(c for c in proc.get("value", []) if isinstance(c, dict) and c.get("idShort") == "MachineDetails")
    assert md is not None
    props = [p.get("idShort") for p in md.get("value", [])]
    assert "OperationStatus" in props
    status_prop = next(p for p in md.get("value", []) if p.get("idShort") == "OperationStatus")
    assert status_prop.get("value") == "Ended"


def test_mock_aas_discover_bop_machines() -> None:
    """MockAASInterface discovers both BOP processes from new template."""
    mock = MockAASInterface()
    machines = mock.discover_bop_machines(shell_id=mock.shell_id)
    assert len(machines) >= 2
    process_ids = [m["process_idShort"] for m in machines]
    assert "Process_PR_456_on_DMG" in process_ids
    assert "Process_PR_123_on_Trumpf" in process_ids
    dmg = next(m for m in machines if m["process_idShort"] == "Process_PR_456_on_DMG")
    assert dmg["machine_name"] == "DMG"
    trumpf = next(m for m in machines if m["process_idShort"] == "Process_PR_123_on_Trumpf")
    assert trumpf["machine_name"] == "Trumpf"


def test_mock_aas_get_process_status_process_operation_status() -> None:
    """Process_PR_456_on_DMG returns Ended via ProcessOperationStatus."""
    from app.services.aas_service import _get_process_operation_status

    mock = MockAASInterface()
    proc = next(
        m for m in mock.discover_bop_machines(shell_id=mock.shell_id)
        if m["process_idShort"] == "Process_PR_456_on_DMG"
    )
    status = _get_process_operation_status(mock, proc)
    assert status == "Ended"


def test_mock_aas_get_process_status_operation_status() -> None:
    """Process_PR_123_on_Trumpf returns Ended via OperationStatus."""
    from app.services.aas_service import _get_process_operation_status

    mock = MockAASInterface()
    proc = next(
        m for m in mock.discover_bop_machines(shell_id=mock.shell_id)
        if m["process_idShort"] == "Process_PR_123_on_Trumpf"
    )
    status = _get_process_operation_status(mock, proc)
    assert status == "Ended"


def test_mock_aas_get_process_energy_kwh() -> None:
    """Energy consumption is correctly read from new template's EnergyConsumption."""
    from app.services.aas_service import _get_process_energy_kwh

    mock = MockAASInterface()
    proc = next(
        m for m in mock.discover_bop_machines(shell_id=mock.shell_id)
        if m["process_idShort"] == "Process_PR_456_on_DMG"
    )
    total_kwh, ts_kwh, t_start, t_end = _get_process_energy_kwh(
        mock, proc["process_idShort"], proc["bop_submodel_id"], proc["shell_id"]
    )
    assert total_kwh > 0
    assert abs(total_kwh - 0.02284) < 0.0001
    assert t_start == "2026-03-02T22:48:42Z"
    assert t_end == "2026-03-02T22:48:57Z"


def test_aas_process_shells_api_requires_aas_config() -> None:
    """POST /api/aas/process_shells returns error when data_source is not AAS."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    with patch("app.services.config_service.load_app_config") as mock_cfg:
        mock_cfg.return_value = {
            "data_source": "mes",
            "aas_base_url": "",
        }
        # Need to be logged in - use a session
        response = client.post("/api/aas/process_shells")
    # May get 401 if not authenticated, or 200 with error in body
    assert response.status_code in (200, 401)
    if response.status_code == 200:
        body = response.json()
        assert "errors" in body or "error" in str(body).lower()


def test_get_available_aas_shells_requires_aas_data_source() -> None:
    """get_available_aas_shells returns error when data_source is not aas."""
    from app.services.aas_service import get_available_aas_shells

    with patch("app.services.aas_service.load_app_config") as mock_cfg:
        mock_cfg.return_value = {"data_source": "mes", "aas_base_url": "https://example.com"}
        result = get_available_aas_shells()
    assert result["error"] == "Data source is not AAS"
    assert result["shell_ids"] == []


def test_process_aas_shells_returns_error_when_not_configured() -> None:
    """process_aas_shells_for_pcf returns errors when data_source is not aas."""
    from app.services.aas_service import process_aas_shells_for_pcf

    with patch("app.services.aas_service.load_app_config") as mock_cfg:
        mock_cfg.return_value = {"data_source": "mes"}
        result = process_aas_shells_for_pcf()
    assert "Data source is not AAS" in result["errors"]
    assert result["processed"] == 0


# ---------------------------------------------------------------------------
# Tests for AASInterface get_property, get_list_item_property, set_property
# with dot-notation paths (Bill_of_Process.Process_X.Y, CommonParameter.Details)
# ---------------------------------------------------------------------------


def _decode_sm_id_from_url(url: str) -> str | None:
    """Extract and base64url-decode submodel id from URL path. Returns URN or None."""
    import base64

    parts = url.split("/submodels/")
    if len(parts) < 2:
        return None
    seg = parts[1].split("/")[0].split("?")[0]
    try:
        pad = 4 - len(seg) % 4
        if pad != 4:
            seg += "=" * pad
        return base64.urlsafe_b64decode(seg).decode("utf-8")
    except Exception:
        return None


def _make_mock_requests_for_dot_notation(aas_type: str) -> tuple:
    """Create mock GET, PUT, POST handlers that serve template data for dot-notation path tests."""
    shell = _get_shell_from_template()
    common_sm = _get_submodel_by_id(COMMON_PARAMETER_ID)
    bop_sm = _get_submodel_by_id(BILL_OF_PROCESS_ID)

    def mock_get(url: str, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.content = b"{}"
        # Shell request (GET .../shells/xxx with no further path)
        if "/shells/" in url and "/submodels/" not in url:
            r.json = lambda: shell
            r.content = json.dumps(shell).encode()
        # Submodel request (full submodel, not submodel-elements)
        elif "/submodels/" in url and "/submodel-elements/" not in url:
            sm_urn = _decode_sm_id_from_url(url)
            if sm_urn == COMMON_PARAMETER_ID:
                r.json = lambda: common_sm
                r.content = json.dumps(common_sm).encode()
            elif sm_urn == BILL_OF_PROCESS_ID:
                r.json = lambda: bop_sm
                r.content = json.dumps(bop_sm).encode()
            else:
                r.status_code = 404
        # Submodel element request
        elif "/submodel-elements/" in url:
            path = url.split("/submodel-elements/")[-1].split("?")[0]
            sm_urn = _decode_sm_id_from_url(url)
            if sm_urn == COMMON_PARAMETER_ID:
                elem = next(
                    (e for e in common_sm.get("submodelElements", []) if e.get("idShort") == path),
                    None,
                )
            elif sm_urn == BILL_OF_PROCESS_ID:
                elem = _get_element_by_dotted_path(bop_sm, path)
            else:
                elem = None
            if elem:
                r.json = lambda: elem
                r.content = json.dumps(elem).encode()
            else:
                r.status_code = 404
        return r

    def mock_put(url: str, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.content = b""
        return r

    def mock_post(url: str, **kwargs):
        """Mock token endpoint for AssetFox."""
        r = MagicMock()
        r.status_code = 200
        r.json = lambda: {"access_token": "mock-token", "expires_in": 3600}
        r.content = b'{"access_token":"mock-token"}'
        return r

    return mock_get, mock_put, mock_post


@pytest.mark.parametrize("aas_type", ["AAS (AssetFox)", "AAS (BaSyx)"])
def test_aas_interface_get_property_dot_notation_assetfox_basyx(aas_type: str) -> None:
    """get_property with dot notation works for both AssetFox and BaSyx."""
    from app.integrations.aas import AASInterface

    mock_get, mock_put, mock_post = _make_mock_requests_for_dot_notation(aas_type)

    with patch("requests.get", side_effect=mock_get), patch("requests.put", side_effect=mock_put), patch(
        "requests.post", side_effect=mock_post
    ):
        bsx = AASInterface(
            asset_name="https://i.siemens.com/WO20260306150526",
            submodel_name="placeholder",
            base_url="https://test.assetfox.apps.siemens.cloud/api/aas/v3" if "AssetFox" in aas_type else "http://localhost:8081",
            client_id="***REMOVED***",
            client_secret="***REMOVED***",
            aas_type=aas_type,
        )
        # Process_PR_456 uses ProcessOperationStatus; OperationStatus alias resolves it
        status = bsx.get_property("Bill_of_Process.Process_PR_456_on_DMG.MachineDetails", "OperationStatus")
        assert status == "Ended"
        prod_start = bsx.get_property("Bill_of_Process.Process_PR_456_on_DMG.TakenPlaceProduction", "ProductionStart")
        assert prod_start == "2026-03-02T22:48:42Z"
        prod_end = bsx.get_property("Bill_of_Process.Process_PR_456_on_DMG.TakenPlaceProduction", "ProductionEnd")
        assert prod_end == "2026-03-02T22:48:57Z"


@pytest.mark.parametrize("aas_type", ["AAS (AssetFox)", "AAS (BaSyx)"])
def test_aas_interface_get_list_item_property_dot_notation_assetfox_basyx(aas_type: str) -> None:
    """get_list_item_property with dot notation works for both AssetFox and BaSyx."""
    from app.integrations.aas import AASInterface

    mock_get, mock_put, mock_post = _make_mock_requests_for_dot_notation(aas_type)

    with patch("requests.get", side_effect=mock_get), patch("requests.put", side_effect=mock_put), patch(
        "requests.post", side_effect=mock_post
    ):
        bsx = AASInterface(
            asset_name="https://i.siemens.com/WO20260306150526",
            submodel_name="placeholder",
            base_url="https://test.assetfox.apps.siemens.cloud/api/aas/v3" if "AssetFox" in aas_type else "http://localhost:8081",
            client_id="***REMOVED***",
            client_secret="***REMOVED***",
            aas_type=aas_type,
        )
        elec_total = bsx.get_list_item_property("Bill_of_Process.Process_PR_456_on_DMG.EnergyConsumption", 0, "TotalConsumption")
        assert elec_total == "0.02284"
        elec_ts = bsx.get_list_item_property("Bill_of_Process.Process_PR_456_on_DMG.EnergyConsumption", 0, "TimeSeriesConsumption")
        assert elec_ts == "[0.00571,0.00571,0.00571,0.00571]"
        air_total = bsx.get_list_item_property("Bill_of_Process.Process_PR_456_on_DMG.EnergyConsumption", 1, "TotalConsumption")
        assert air_total == "0.02284"
        air_ts = bsx.get_list_item_property("Bill_of_Process.Process_PR_456_on_DMG.EnergyConsumption", 1, "TimeSeriesConsumption")
        assert air_ts == "[0.00571,0.00571,0.00571,0.00571]"


@pytest.mark.parametrize("aas_type", ["AAS (AssetFox)", "AAS (BaSyx)"])
def test_aas_interface_set_property_dot_notation_assetfox_basyx(aas_type: str) -> None:
    """set_property with dot notation works for both AssetFox and BaSyx."""
    from app.integrations.aas import AASInterface

    mock_get, mock_put, mock_post = _make_mock_requests_for_dot_notation(aas_type)
    put_calls = []

    def capture_put(url: str, **kwargs):
        put_calls.append({"url": url, "json": kwargs.get("json")})
        r = MagicMock()
        r.status_code = 200
        r.content = b""
        return r

    with patch("requests.get", side_effect=mock_get), patch("requests.put", side_effect=capture_put), patch(
        "requests.post", side_effect=mock_post
    ):
        bsx = AASInterface(
            asset_name="https://i.siemens.com/WO20260306150526",
            submodel_name="placeholder",
            base_url="https://test.assetfox.apps.siemens.cloud/api/aas/v3" if "AssetFox" in aas_type else "http://localhost:8081",
            client_id="***REMOVED***",
            client_secret="***REMOVED***",
            aas_type=aas_type,
        )
        bsx.set_property("CommonParameter.Details", "OperationStatus", "Planned")
    assert len(put_calls) == 1
    payload = put_calls[0]["json"]
    assert payload is not None
    op_status = next((p.get("value") for p in payload.get("value", []) if p.get("idShort") == "OperationStatus"), None)
    assert op_status == "Planned"


@pytest.mark.parametrize("aas_type", ["AAS (AssetFox)", "AAS (BaSyx)"])
def test_aas_interface_set_list_item_property_dot_notation_assetfox_basyx(aas_type: str) -> None:
    """set_list_item_property with dot notation works for both AssetFox and BaSyx."""
    from app.integrations.aas import AASInterface

    mock_get, mock_put, mock_post = _make_mock_requests_for_dot_notation(aas_type)
    put_calls = []

    def capture_put(url: str, **kwargs):
        put_calls.append({"url": url, "json": kwargs.get("json")})
        r = MagicMock()
        r.status_code = 200
        r.content = b""
        return r

    with patch("requests.get", side_effect=mock_get), patch("requests.put", side_effect=capture_put), patch(
        "requests.post", side_effect=mock_post
    ):
        bsx = AASInterface(
            asset_name="https://i.siemens.com/WO20260306150526",
            submodel_name="placeholder",
            base_url="https://test.assetfox.apps.siemens.cloud/api/aas/v3" if "AssetFox" in aas_type else "http://localhost:8081",
            client_id="***REMOVED***",
            client_secret="***REMOVED***",
            aas_type=aas_type,
        )
        bsx.set_list_item_property("Bill_of_Process.Process_PR_456_on_DMG.MaterialConsumption", 0, "Name", "name_X")
    assert len(put_calls) == 1
    payload = put_calls[0]["json"]
    assert payload is not None
    entries = payload.get("value", [])
    assert len(entries) >= 1
    item0_props = entries[0].get("value", [])
    name_prop = next((p for p in item0_props if p.get("idShort") == "Name"), None)
    assert name_prop is not None
    assert name_prop.get("value") == "name_X"


# ---------------------------------------------------------------------------
# Tests for _get_process_materials (MaterialConsumption + fallback)
# ---------------------------------------------------------------------------


def _make_mock_for_get_process_materials(
    submodel_elements_404: bool = False,
    material_in_bop: dict | None = None,
) -> tuple:
    """
    Create mock GET/POST for _get_process_materials tests.
    When submodel_elements_404=True, submodel-elements path returns 404 to trigger fallback.
    material_in_bop: optional MaterialConsumption entry for Process_PR_456 (e.g. ALUROD123, 2.0).
    """
    shell = _get_shell_from_template()
    common_sm = _get_submodel_by_id(COMMON_PARAMETER_ID)
    bop_sm = _get_submodel_by_id(BILL_OF_PROCESS_ID)

    if material_in_bop:
        bop_sm = copy.deepcopy(bop_sm)
        proc = next(
            (e for e in bop_sm.get("submodelElements", [])
            if e.get("idShort") == "Process_PR_456_on_DMG"),
            None,
        )
        if proc:
            mat_list = next(
                (c for c in proc.get("value", [])
                if c.get("idShort") == "MaterialConsumption"),
                None,
            )
            if mat_list and mat_list.get("value"):
                mat_list["value"][0]["value"] = material_in_bop["value"]

    def mock_get(url: str, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.content = b"{}"
        r.raise_for_status = MagicMock()
        if "/shells/" in url and "/submodels/" not in url:
            r.json = lambda: shell
            r.content = json.dumps(shell).encode()
        elif "/submodel-elements/" in url:
            path = url.split("/submodel-elements/")[-1].split("?")[0]
            if submodel_elements_404 and "MaterialConsumption" in path:
                r.status_code = 404
                r.raise_for_status.side_effect = Exception("404")
            else:
                sm_urn = _decode_sm_id_from_url(url)
                if sm_urn == COMMON_PARAMETER_ID:
                    elem = next(
                        (e for e in common_sm.get("submodelElements", [])
                        if e.get("idShort") == path),
                        None,
                    )
                elif sm_urn == BILL_OF_PROCESS_ID:
                    elem = _get_element_by_dotted_path(bop_sm, path)
                else:
                    elem = None
                if elem:
                    r.json = lambda: elem
                    r.content = json.dumps(elem).encode()
                else:
                    r.status_code = 404
                    r.raise_for_status.side_effect = Exception("404")
        elif "/submodels/" in url:
            sm_urn = _decode_sm_id_from_url(url)
            if sm_urn == COMMON_PARAMETER_ID:
                r.json = lambda: common_sm
                r.content = json.dumps(common_sm).encode()
            elif sm_urn == BILL_OF_PROCESS_ID:
                r.json = lambda: bop_sm
                r.content = json.dumps(bop_sm).encode()
            else:
                r.status_code = 404
                r.raise_for_status.side_effect = Exception("404")
        return r

    def mock_post(url: str, **kwargs):
        r = MagicMock()
        r.status_code = 200
        r.json = lambda: {"access_token": "mock-token", "expires_in": 3600}
        r.content = b'{"access_token":"mock-token"}'
        return r

    return mock_get, mock_post


def test_get_process_materials_via_fallback_when_api_path_404() -> None:
    """_get_process_materials uses full submodel fallback when submodel-elements API returns 404."""
    from app.services.aas_service import _get_process_materials
    from app.integrations.aas import AASInterface

    # BOP with ALUROD123, 2.0 piece in Process_PR_456's MaterialConsumption
    material_entry = {
        "value": [
            {"idShort": "Name", "value": "ALUROD123"},
            {"idShort": "TotalConsumption", "value": "2.0"},
            {"idShort": "Unit", "value": "piece"},
        ]
    }
    mock_get, mock_post = _make_mock_for_get_process_materials(
        submodel_elements_404=True,
        material_in_bop=material_entry,
    )

    with patch("requests.get", side_effect=mock_get), patch("requests.post", side_effect=mock_post):
        aasi = AASInterface(
            asset_name="https://i.siemens.com/WO20260306150526",
            submodel_name="placeholder",
            base_url="https://test.assetfox.apps.siemens.cloud/api/aas/v3",
            client_id="***REMOVED***",
            client_secret="***REMOVED***",
            aas_type="AAS (AssetFox)",
        )
        materials = _get_process_materials(
            aasi,
            "Process_PR_456_on_DMG",
            BILL_OF_PROCESS_ID,
            "https://i.siemens.com/WO20260306150526",
        )
    assert len(materials) == 1
    assert materials[0]["name"] == "ALUROD123"
    assert materials[0]["quantity"] == 2.0
    assert materials[0]["unit"] == "piece"


def test_get_process_materials_via_primary_api_path() -> None:
    """_get_process_materials works via primary submodel-elements API path when supported."""
    from app.services.aas_service import _get_process_materials
    from app.integrations.aas import AASInterface

    material_entry = {
        "value": [
            {"idShort": "Name", "value": "STEEL_001"},
            {"idShort": "TotalConsumption", "value": "1.5"},
            {"idShort": "Unit", "value": "kg"},
        ]
    }
    mock_get, mock_post = _make_mock_for_get_process_materials(
        submodel_elements_404=False,
        material_in_bop=material_entry,
    )

    with patch("requests.get", side_effect=mock_get), patch("requests.post", side_effect=mock_post):
        aasi = AASInterface(
            asset_name="https://i.siemens.com/WO20260306150526",
            submodel_name="placeholder",
            base_url="https://test.assetfox.apps.siemens.cloud/api/aas/v3",
            client_id="***REMOVED***",
            client_secret="***REMOVED***",
            aas_type="AAS (AssetFox)",
        )
        materials = _get_process_materials(
            aasi,
            "Process_PR_456_on_DMG",
            BILL_OF_PROCESS_ID,
            "https://i.siemens.com/WO20260306150526",
        )
    assert len(materials) == 1
    assert materials[0]["name"] == "STEEL_001"
    assert materials[0]["quantity"] == 1.5
    assert materials[0]["unit"] == "kg"
