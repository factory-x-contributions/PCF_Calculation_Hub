"""Unit tests for :class:`app.integrations.sigreen.SiGREENInterface` — the SiGREEN HTTP client.

Mirrors the structure of :mod:`tests.unit.test_aas_interface`: every outbound
``requests`` call is intercepted, success and failure paths are pinned, and
the spec-mandated unauthenticated fallback (§5.2.4) is exercised end-to-end.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.integrations import sigreen as sigreen_mod
from app.integrations.sigreen import (
    SiGREENInterface,
    _auth_headers,
    base64_encode,
    save_dict_to_json,
)


def _resp(json_value=None, status: int = 200, ok: bool = True, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = ok
    response.text = text
    response.json.return_value = json_value if json_value is not None else {}
    response.raise_for_status = MagicMock()
    return response


@pytest.fixture
def sigi() -> SiGREENInterface:
    """A SiGREENInterface bypassing the auto factory_id lookup so tests can drive it directly."""
    return SiGREENInterface(factory_name="OPC", factory_id="factory-uuid", base_url="https://sigreen/api")


@pytest.fixture(autouse=True)
def _stub_credentials(monkeypatch):
    """Pin ``fetch_token`` to a deterministic stub so the suite never reaches Auth0.

    Most tests don't care which header is sent — they assert URLs, params, and
    response handling. By stubbing ``fetch_token`` here we keep the credential
    contract well-defined for every test in this file. The dedicated
    unauthenticated-fallback assertions live in ``test_sigreen_unauthenticated.py``.
    """
    monkeypatch.setattr(sigreen_mod, "fetch_token", lambda: "stubbed-token")
    sigreen_mod.clear_sigreen_token_cache()
    yield
    sigreen_mod.clear_sigreen_token_cache()


# -- module-level helpers ---------------------------------------------------------------


def test_base64_encode_simple_string() -> None:
    assert base64_encode("hello") == "aGVsbG8="


def test_save_dict_to_json_roundtrip(tmp_path) -> None:
    p = tmp_path / "out.json"
    save_dict_to_json({"a": 1, "b": [1, 2]}, p)
    assert p.read_text(encoding="utf-8").strip().startswith("{")


def test_load_sigreen_product_identifier_type_default(monkeypatch) -> None:
    """Falls back to 'Product ID' when config lookup fails."""
    monkeypatch.setattr(
        "app.services.config_service.load_app_config",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert sigreen_mod._load_sigreen_product_identifier_type() == "Product ID"


def test_load_sigreen_product_identifier_type_from_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.config_service.load_app_config",
        lambda: {"sigreen_product_identifier_type": "Material No."},
    )
    assert sigreen_mod._load_sigreen_product_identifier_type() == "Material No."


# -- _auth_headers contract from sigreen module -----------------------------------------


def test_auth_headers_with_credentials_attaches_bearer() -> None:
    with patch("app.integrations.sigreen.fetch_token", return_value="real-token"):
        headers = _auth_headers()
    assert headers["Authorization"] == "Bearer real-token"


# -- construction -----------------------------------------------------------------------


def test_construction_with_explicit_factory_id_skips_lookup() -> None:
    """Passing ``factory_id`` skips the auto-lookup that hits ``/factories``."""
    with patch.object(sigreen_mod.requests, "get") as get:
        SiGREENInterface(factory_name="X", factory_id="abc", base_url="https://x")
    get.assert_not_called()


def test_construction_falls_back_to_default_base_url() -> None:
    with patch.object(SiGREENInterface, "get_factory_id", return_value=None):
        sigi = SiGREENInterface(factory_name="X", base_url="")
    assert sigi.base_url == sigreen_mod.DEFAULT_SIGREEN_BASE_URL


def test_construction_strips_base_url() -> None:
    sigi = SiGREENInterface(factory_name="X", factory_id="x", base_url="  https://api  ")
    assert sigi.base_url == "https://api"


# -- get_factories / get_factory_id -----------------------------------------------------


def test_get_factories_returns_payload(sigi: SiGREENInterface) -> None:
    payload = {"items": [{"id": "f1", "factory": "OPC"}]}
    with patch.object(sigreen_mod.requests, "get", return_value=_resp(payload)):
        out = sigi.get_factories()
    assert out == payload


def test_get_factory_id_finds_match_case_insensitive(sigi: SiGREENInterface) -> None:
    payload = {"items": [
        {"id": "wrong", "factory": "Other"},
        {"id": "right", "name": "  opc  "},
    ]}
    with patch.object(sigi, "get_factories", return_value=payload):
        assert sigi.get_factory_id("OPC") == "right"


def test_get_factory_id_returns_none_when_no_match(sigi: SiGREENInterface) -> None:
    with patch.object(sigi, "get_factories", return_value={"items": []}):
        assert sigi.get_factory_id("Missing") is None


def test_get_factory_id_returns_none_when_input_blank(sigi: SiGREENInterface) -> None:
    assert sigi.get_factory_id("") is None
    assert sigi.get_factory_id("   ") is None


# -- get_products / get_product_uuid ----------------------------------------------------


def test_get_products_returns_payload(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": []})):
        assert sigi.get_products() == {"items": []}


def test_get_product_uuid_returns_first_match(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": [{"id": "uuid-x"}]})):
        assert sigi.get_product_uuid(product_id="P1") == "uuid-x"


def test_get_product_uuid_falls_back_to_full_list(sigi: SiGREENInterface) -> None:
    """When idValue lookup returns no items, the client must scan all products and match by identifier or name."""
    first = _resp({"items": []})
    second = _resp({"items": [
        {"id": "uuid-y", "identifiers": [{"value": "P-OTHER"}], "name": "Other"},
        {"id": "uuid-z", "identifiers": [{"value": "P1"}], "name": "Product One"},
    ]})
    with patch.object(sigreen_mod.requests, "get", side_effect=[first, second]):
        assert sigi.get_product_uuid(product_id="P1") == "uuid-z"


def test_get_product_uuid_returns_none_when_not_found(sigi: SiGREENInterface) -> None:
    first = _resp({"items": []})
    second = _resp({"items": [{"id": "uuid-y", "identifiers": [{"value": "Other"}], "name": "X"}]})
    with patch.object(sigreen_mod.requests, "get", side_effect=[first, second]):
        assert sigi.get_product_uuid(product_id="P1") is None


# -- send_factory_emissions ------------------------------------------------------------


def test_send_factory_emissions_calls_post_with_payload(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "post", return_value=_resp({})) as post:
        sigi.send_factory_emissions(product_uuid="P-uuid", PCF_report={"x": 1})
    post.assert_called_once()
    args, kwargs = post.call_args
    assert args[0].endswith("/products/P-uuid/factoryEmissions")
    assert kwargs["json"] == {"x": 1}


def test_send_factory_emissions_raises_on_non_2xx(sigi: SiGREENInterface) -> None:
    bad = _resp({"detail": "rejected"}, status=400, ok=False, text='{"detail": "rejected"}')
    with patch.object(sigreen_mod.requests, "post", return_value=bad):
        with pytest.raises(requests.HTTPError, match="SiGREEN 400"):
            sigi.send_factory_emissions(product_uuid="P", PCF_report={})


def test_send_factory_emissions_handles_empty_error_body(sigi: SiGREENInterface) -> None:
    bad = MagicMock()
    bad.ok = False
    bad.status_code = 502
    bad.text = ""
    bad.json.side_effect = ValueError("no body")
    with patch.object(sigreen_mod.requests, "post", return_value=bad):
        with pytest.raises(requests.HTTPError, match="empty body"):
            sigi.send_factory_emissions(product_uuid="P", PCF_report={})


# -- get_components / get_component_by_identifier --------------------------------------


def test_get_components_passes_id_value_and_type(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": []})) as get:
        sigi.get_components(id_value="X", id_type="Material No.")
    assert get.call_args.kwargs["params"] == {"idValue": "X", "idType": "Material No."}


def test_get_components_omits_params_when_none(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": []})) as get:
        sigi.get_components()
    assert get.call_args.kwargs["params"] is None


def test_get_component_by_identifier_returns_first_match(sigi: SiGREENInterface, monkeypatch) -> None:
    monkeypatch.setattr(sigreen_mod, "_load_sigreen_product_identifier_type", lambda: "Product ID")
    payload = {"items": [{"id": "comp-1", "identifiers": [{"value": "X-1"}]}]}
    with patch.object(sigi, "get_components", return_value=payload):
        out = sigi.get_component_by_identifier("X-1")
    assert out["id"] == "comp-1"


def test_get_component_by_identifier_tries_alternates(sigi: SiGREENInterface, monkeypatch) -> None:
    """If the configured id_type returns nothing, the client must try Material No. / Article Number."""
    monkeypatch.setattr(sigreen_mod, "_load_sigreen_product_identifier_type", lambda: "Product ID")
    calls = []

    def fake_get_components(id_value=None, id_type=None):
        calls.append(id_type)
        if id_type == "Material No.":
            return {"items": [{"id": "comp-2", "identifiers": [{"value": "X"}]}]}
        return {"items": []}

    with patch.object(sigi, "get_components", side_effect=fake_get_components):
        out = sigi.get_component_by_identifier("X")
    assert out["id"] == "comp-2"
    assert "Product ID" in calls and "Material No." in calls


def test_get_component_by_identifier_uses_full_list_fallback(sigi: SiGREENInterface, monkeypatch) -> None:
    monkeypatch.setattr(sigreen_mod, "_load_sigreen_product_identifier_type", lambda: "Product ID")

    def fake_get_components(id_value=None, id_type=None):
        if id_type is None:
            return {"items": [{"id": "comp-fb", "identifiers": [{"value": "X"}]}]}
        return {"items": []}

    with patch.object(sigi, "get_components", side_effect=fake_get_components):
        out = sigi.get_component_by_identifier("X")
    assert out["id"] == "comp-fb"


def test_get_component_by_identifier_returns_none_when_not_found(sigi: SiGREENInterface, monkeypatch) -> None:
    monkeypatch.setattr(sigreen_mod, "_load_sigreen_product_identifier_type", lambda: "Product ID")
    with patch.object(sigi, "get_components", return_value={"items": []}):
        assert sigi.get_component_by_identifier("X") is None


# -- secondary data endpoints ----------------------------------------------------------


def test_get_component_secondary_data_returns_payload(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": []})):
        assert sigi.get_component_secondary_data("comp-1") == {"items": []}


def test_get_component_pcf_data_returns_payload(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": []})):
        assert sigi.get_component_pcf_data() == {"items": []}


# -- _pcf_from_production_and_distribution / _pcf_stages_from_item ----------------------


def test_pcf_from_production_and_distribution_sums_stages(sigi: SiGREENInterface) -> None:
    item = {
        "productionStage": {"pcfIncludingBiogenic": 1.5},
        "distributionStage": {"pcfIncludingBiogenic": 0.5},
    }
    assert sigi._pcf_from_production_and_distribution(item) == 2.0


def test_pcf_from_production_and_distribution_uses_excluding_when_including_missing(sigi: SiGREENInterface) -> None:
    item = {
        "productionStage": {"pcfExcludingBiogenic": 1.0},
        "distributionStage": {"pcfExcludingBiogenic": 0.4},
    }
    assert sigi._pcf_from_production_and_distribution(item) == pytest.approx(1.4)


def test_pcf_from_production_and_distribution_returns_none_on_unparseable(sigi: SiGREENInterface) -> None:
    item = {
        "productionStage": {"pcfIncludingBiogenic": "not-a-number"},
        "distributionStage": {},
    }
    assert sigi._pcf_from_production_and_distribution(item) is None


def test_pcf_stages_from_item_returns_tuple(sigi: SiGREENInterface) -> None:
    item = {
        "productionStage": {"pcfIncludingBiogenic": 1.0},
        "distributionStage": {"pcfIncludingBiogenic": 0.5},
    }
    assert sigi._pcf_stages_from_item(item) == (1.0, 0.5)


def test_pcf_stages_from_item_returns_none_on_unparseable(sigi: SiGREENInterface) -> None:
    item = {"productionStage": {"pcfIncludingBiogenic": "x"}}
    assert sigi._pcf_stages_from_item(item) is None


# -- get_material_pcf_per_unit_kg ------------------------------------------------------


def test_get_material_pcf_per_unit_kg_uses_secondary_data(sigi: SiGREENInterface) -> None:
    component = {"id": "comp-1"}
    secondary = {"items": [{
        "productionStage": {"pcfIncludingBiogenic": 3.0},
        "distributionStage": {"pcfIncludingBiogenic": 0.0},
        "quantity": 2,
    }]}
    with patch.object(sigi, "get_component_by_identifier", return_value=component):
        with patch.object(sigi, "get_component_secondary_data", return_value=secondary):
            out = sigi.get_material_pcf_per_unit_kg("X-1")
    assert out == {"total": 1.5, "production": 1.5, "distribution": 0.0}


def test_get_material_pcf_per_unit_kg_falls_back_to_pcf_data(sigi: SiGREENInterface) -> None:
    component = {"id": "comp-1"}
    pcf_data = {"items": [{
        "componentId": "comp-1",
        "productionStage": {"pcfIncludingBiogenic": 1.0},
        "distributionStage": {"pcfIncludingBiogenic": 0.5},
        "quantity": 1,
    }]}
    with patch.object(sigi, "get_component_by_identifier", return_value=component):
        with patch.object(sigi, "get_component_secondary_data", return_value={"items": []}):
            with patch.object(sigi, "get_component_pcf_data", return_value=pcf_data):
                out = sigi.get_material_pcf_per_unit_kg("X-1")
    assert out["total"] == pytest.approx(1.5)


def test_get_material_pcf_per_unit_kg_pcfdata_top_level_value(sigi: SiGREENInterface) -> None:
    component = {"id": "comp-1"}
    pcf_data = {"items": [{
        "componentId": "comp-1",
        "pcfIncludingBiogenic": 4.2,
    }]}
    with patch.object(sigi, "get_component_by_identifier", return_value=component):
        with patch.object(sigi, "get_component_secondary_data", return_value={"items": []}):
            with patch.object(sigi, "get_component_pcf_data", return_value=pcf_data):
                out = sigi.get_material_pcf_per_unit_kg("X-1")
    assert out == {"total": 4.2, "production": 4.2, "distribution": 0.0}


def test_get_material_pcf_per_unit_kg_returns_none_when_component_missing(sigi: SiGREENInterface) -> None:
    with patch.object(sigi, "get_component_by_identifier", return_value=None):
        assert sigi.get_material_pcf_per_unit_kg("X") is None


def test_get_material_pcf_per_unit_kg_returns_none_when_secondary_data_fails(sigi: SiGREENInterface) -> None:
    """A network failure on the secondary-data endpoint must surface as None, not a crash."""
    with patch.object(sigi, "get_component_by_identifier", return_value={"id": "c"}):
        with patch.object(sigi, "get_component_secondary_data", side_effect=RuntimeError("boom")):
            assert sigi.get_material_pcf_per_unit_kg("X") is None


def test_get_material_pcf_per_unit_kg_picks_best_secondary_item(sigi: SiGREENInterface) -> None:
    """When SiGREEN returns multiple secondary-data rows, pick the one with the highest total."""
    component = {"id": "comp-1"}
    secondary = {"items": [
        {"productionStage": {"pcfIncludingBiogenic": 1.0}, "distributionStage": {}, "quantity": 1},
        {"productionStage": {"pcfIncludingBiogenic": 5.0}, "distributionStage": {"pcfIncludingBiogenic": 1.0}, "quantity": 1},
    ]}
    with patch.object(sigi, "get_component_by_identifier", return_value=component):
        with patch.object(sigi, "get_component_secondary_data", return_value=secondary):
            out = sigi.get_material_pcf_per_unit_kg("X")
    assert out["total"] == 6.0


# -- create_process_bill / create_PCF_report -------------------------------------------


def test_create_process_bill_returns_canonical_shape(sigi: SiGREENInterface) -> None:
    bill = sigi.create_process_bill(total=10.0, pcf_share=50.0, type_of_activity="OP10", comment="ok")
    assert bill["typeOfActivity"] == "OP10"
    assert bill["total"] == 10.0
    assert bill["shareOnTotal"] == 50.0
    assert bill["comment"] == "ok"


def test_create_process_bill_default_comment(sigi: SiGREENInterface) -> None:
    bill = sigi.create_process_bill(total=1, pcf_share=2, type_of_activity="X")
    assert bill["comment"] == "Estimated values"


def test_create_pcf_report_includes_factory_and_emissions(sigi: SiGREENInterface) -> None:
    bop = [{"typeOfActivity": "OP10"}]
    out = sigi.create_PCF_report(
        BOP=bop, Total_PCF=42.0, quantity=1,
        t_start="2026-01-01T00:00:00Z", t_end="2026-01-02T00:00:00Z", batch_number="B-1",
    )
    assert out["factoryId"] == "factory-uuid"
    assert out["emissions"] == bop
    assert out["batch"]["batchNumber"] == "B-1"
    assert out["productCarbonFootprint"] == 42.0


def test_create_pcf_report_default_batch_number(sigi: SiGREENInterface) -> None:
    out = sigi.create_PCF_report(BOP=[], Total_PCF=1.0, quantity=1, t_start="a", t_end="b")
    assert out["batch"]["batchNumber"] == "Not provided"


# -- create_product --------------------------------------------------------------------


def test_create_product_returns_id_from_response(sigi: SiGREENInterface, monkeypatch) -> None:
    monkeypatch.setattr(sigreen_mod, "_load_sigreen_product_identifier_type", lambda: "Product ID")
    with patch.object(sigreen_mod.requests, "post", return_value=_resp({"id": "uuid-new"})):
        uuid = sigi.create_product(name="X", prod_id="X-1", prod_family="Test")
    assert uuid == "uuid-new"


def test_create_product_raises_when_id_missing(sigi: SiGREENInterface, monkeypatch) -> None:
    monkeypatch.setattr(sigreen_mod, "_load_sigreen_product_identifier_type", lambda: "Product ID")
    with patch.object(sigreen_mod.requests, "post", return_value=_resp({})):
        with pytest.raises(ValueError, match="missing 'id'"):
            sigi.create_product(name="X", prod_id="X-1", prod_family="Test")


# -- BOM endpoints ---------------------------------------------------------------------


def test_get_prod_bom_versions_passes_product_id(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"items": []})) as get:
        sigi.get_prod_bom_versions("uuid-a")
    assert get.call_args.kwargs["params"] == {"productId": "uuid-a"}


def test_get_product_bom_passes_uuid_and_bom_id(sigi: SiGREENInterface) -> None:
    with patch.object(sigreen_mod.requests, "get", return_value=_resp({"x": 1})) as get:
        sigi.get_product_bom("uuid-a", "bom-1")
    assert "uuid-a" in get.call_args[0][0]
    assert "bom-1" in get.call_args[0][0]


def test_get_prod_last_bom_version_returns_last(sigi: SiGREENInterface) -> None:
    payload = {"items": [{"version": "v1", "id": "id-1"}, {"version": "v2", "id": "id-2"}]}
    with patch.object(sigi, "get_prod_bom_versions", return_value=payload):
        version, vid = sigi.get_prod_last_bom_version("uuid-a")
    assert version == "v2"
    assert vid == "id-2"


def test_create_bom_version_uses_existing_versions_listing(sigi: SiGREENInterface) -> None:
    with patch.object(sigi, "get_prod_bom_versions", return_value={"items": []}):
        with patch.object(sigreen_mod.requests, "post", return_value=_resp({"id": "bom-new"})):
            new_id = sigi.create_bom_version(uuid="uuid-a")
    assert new_id == "bom-new"


# -- handle_response -------------------------------------------------------------------


def test_handle_response_returns_json_when_ok(sigi: SiGREENInterface) -> None:
    out = sigi.handle_response(_resp({"x": 1}))
    assert out == {"x": 1}


def test_handle_response_raises_with_json_detail(sigi: SiGREENInterface) -> None:
    bad = _resp({"detail": "no"}, status=400, ok=False, text='{"detail": "no"}')
    with pytest.raises(requests.HTTPError, match="400 Error"):
        sigi.handle_response(bad)


def test_handle_response_raises_with_text_when_not_json(sigi: SiGREENInterface) -> None:
    bad = MagicMock()
    bad.ok = False
    bad.status_code = 500
    bad.text = "<html>oops</html>"
    bad.json.side_effect = ValueError("not json")
    with pytest.raises(requests.HTTPError, match="500 Error"):
        sigi.handle_response(bad)
