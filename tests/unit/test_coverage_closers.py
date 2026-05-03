"""Targeted tests that close the last per-module coverage gaps.

Each test below pairs with an *exact* uncovered line range from the most
recent ``pytest --cov-report=term-missing`` run. The intent is to express
the contract of those branches (almost all error-handling paths) so the
test plan stays self-documenting after coverage hits the >91% gate.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import settings
from app.services import sigreen_factory
from app.storage.json_store import JsonStore


# -- sigreen_factory error branches (lines 43-45, 49-51) ------------------------------


def test_build_sigreen_for_material_lookup_handles_import_error(monkeypatch, caplog) -> None:
    """If ``from app.integrations.sigreen import SiGREENInterface`` raises, the factory returns None."""
    monkeypatch.setattr(sigreen_factory, "load_app_config", lambda: {"pcf_tool": "sigreen"})

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "app.integrations.sigreen":
            raise ImportError("module gone")
        return real_import(name, *a, **k)

    with patch("builtins.__import__", side_effect=fake_import):
        out = sigreen_factory.build_sigreen_for_material_lookup()

    assert out is None
    assert any("SiGREEN interface unavailable" in r.message for r in caplog.records)


def test_build_sigreen_for_material_lookup_handles_constructor_error(monkeypatch, caplog) -> None:
    """An exception inside ``SiGREENInterface.__init__`` must surface as None, not propagate."""
    monkeypatch.setattr(sigreen_factory, "load_app_config", lambda: {"pcf_tool": "sigreen"})
    with patch("app.integrations.sigreen.SiGREENInterface", side_effect=RuntimeError("ctor blew up")):
        out = sigreen_factory.build_sigreen_for_material_lookup()
    assert out is None
    assert any("ctor blew up" in r.message for r in caplog.records)


# -- json_store error and retry branches ---------------------------------------------


def test_json_store_logs_when_local_write_fails(tmp_path, caplog) -> None:
    """OSError while writing local file must be logged but not propagate."""
    store = JsonStore(tmp_path / "store.json")

    # Patch ``Path.open`` since JsonStore writes via ``self.path.open(...)``.
    with patch("pathlib.Path.open", side_effect=OSError("disk full")):
        store.save({"x": 1})  # must not raise

    assert any("Failed to write" in r.message for r in caplog.records)


def test_json_store_read_s3_retries_on_transient_error(tmp_path, caplog) -> None:
    """A transient S3 error retried twice then logged on the third attempt."""
    fake_client = MagicMock()
    fake_client.get_object.side_effect = RuntimeError("transient")
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        with patch("app.storage.json_store.time.sleep"):
            store = JsonStore(tmp_path / "store.json", s3_bucket="b", s3_key="k")
            out = store.load()
    assert out == {}  # falls back to local default
    assert fake_client.get_object.call_count == 3
    assert any("Failed to read s3" in r.message for r in caplog.records)


# -- middleware unhandled-error path -------------------------------------------------


def test_middleware_global_handler_returns_500_on_unhandled_exception() -> None:
    """The ``_global_errors`` middleware must catch unhandled exceptions and return JSON 500."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.core.middleware import install_middleware

    app = FastAPI()
    install_middleware(app)

    @app.get("/__test__/boom")
    def _boom():
        raise RuntimeError("unhandled")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/__test__/boom")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}


def test_middleware_strips_stage_prefix_in_non_local_environment(monkeypatch) -> None:
    """When ``ENVIRONMENT=dev`` the middleware must strip ``/dev/`` from incoming paths."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.config.settings import settings as core_settings
    from app.core.middleware import install_middleware

    monkeypatch.setattr(core_settings, "environment", "dev")
    app = FastAPI()
    install_middleware(app)

    @app.get("/api/ping")
    def _ping():
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/dev/api/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


# -- aas.py discover_bop_machines configured-asset fallback (lines 608-686) ---------


def test_discover_bop_machines_fallback_uses_configured_asset(monkeypatch) -> None:
    """When the main shell loop yields nothing, the function must fall back to the configured asset."""
    from app.integrations import aas as aas_mod

    iface = aas_mod.AASInterface(
        asset_name="WO-1", submodel_name="urn:s",
        base_url="http://x", aas_type="AAS (BaSyx)",
    )
    iface.find_shells = MagicMock(return_value={"result": []})
    iface.get_shell_asset = MagicMock(return_value={
        "id": "WO-1",
        "submodels": [{"keys": [{"value": "urn:bop"}]}],
    })

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
    fake_resp = MagicMock(status_code=200, content=b"{")
    fake_resp.json.return_value = submodel
    fake_resp.raise_for_status = MagicMock()
    with patch.object(aas_mod.requests, "get", return_value=fake_resp):
        machines = iface.discover_bop_machines()

    assert any(m["machine_name"] == "DMG" for m in machines)


# -- aas_service _set_common_parameter_operation_status mid-loop success (line 230) --


def test_set_common_parameter_operation_status_iterates_until_match() -> None:
    """When the first submodel isn't CommonParameter, the function must keep trying."""
    from app.services import aas_service

    aasi = MagicMock(aas_type="AAS (BaSyx)", registry_base_url="http://x")
    aasi._headers.return_value = {}
    aasi.get_submodel_refs.return_value = ["urn:other", "urn:cp"]

    other_resp = MagicMock(status_code=200, content=b"{")
    other_resp.json.return_value = {"idShort": "Other"}
    cp_resp = MagicMock(status_code=200, content=b"{")
    cp_resp.json.return_value = {"idShort": "CommonParameter"}
    details_resp = MagicMock(status_code=200, content=b"{")
    details_resp.json.return_value = {"value": [{"idShort": "OperationStatus", "value": "Init"}]}
    put_resp = MagicMock(status_code=204, content=b"")
    put_resp.raise_for_status = MagicMock()

    with patch.object(aas_service.requests, "get", side_effect=[other_resp, cp_resp, details_resp]):
        with patch.object(aas_service.requests, "put", return_value=put_resp):
            ok = aas_service._set_common_parameter_operation_status(aasi, "WO-1", "Ended")
    assert ok is True


# -- config router POST /api/config: sigreen credentials changed -----------------------


def test_post_config_validates_sigreen_credentials_when_changed(monkeypatch, tmp_path) -> None:
    """Changing client_id/secret must trigger validate_sigreen_credentials, with 400 on failure."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))
    (tmp_path / "app_config.json").write_text(
        json.dumps({"data_source": "mes", "sigreen_client_id": "old"}), encoding="utf-8"
    )

    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    with patch("app.api.routers.config.validate_sigreen_credentials", return_value=False):
        response = client.post(
            "/api/config", json={"sigreen_client_id": "new-id", "sigreen_client_secret": "new-secret"}
        )

    assert response.status_code == 400
    assert "credentials are not correct" in response.json()["detail"]


def test_post_config_rejects_missing_sigreen_credential_pair(monkeypatch, tmp_path) -> None:
    """Changing only one of client_id/secret without the other (in config) returns 400."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))
    (tmp_path / "app_config.json").write_text(
        json.dumps({"data_source": "mes"}), encoding="utf-8"
    )

    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    response = client.post("/api/config", json={"sigreen_client_id": "alone"})
    assert response.status_code == 400
    assert "required" in response.json()["detail"].lower()


def test_post_config_rejects_non_object_body(monkeypatch, tmp_path) -> None:
    """A JSON array (or non-object) body must return 400 — ``post_config`` expects an object."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))
    (tmp_path / "app_config.json").write_text("{}", encoding="utf-8")

    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    response = client.post("/api/config", json=[1, 2, 3])
    assert response.status_code == 400


# -- pcf_service.get_or_create_product_uuid HTTPError without response (lines 79-80) --


def test_get_or_create_product_uuid_handles_httperror_without_response() -> None:
    """An HTTPError with response=None must surface as RuntimeError, not crash with AttributeError."""
    import requests

    from app.services import pcf_service

    sigi = MagicMock(factory_id="f1")
    err = requests.HTTPError("no response object")
    err.response = None
    sigi.get_product_uuid.side_effect = err

    with pytest.raises(RuntimeError, match="get_product_uuid failed"):
        pcf_service.get_or_create_product_uuid(sigi, "P1")


def test_get_or_create_product_uuid_exhausts_retries_and_raises() -> None:
    """Three create attempts all fail, re-lookup keeps returning None — must surface RuntimeError."""
    import requests

    from app.services import pcf_service

    sigi = MagicMock(factory_id="f1")
    sigi.get_product_uuid.return_value = None
    sigi.create_product.side_effect = RuntimeError("create blew up")

    with patch("app.services.pcf_service.time.sleep"):
        with pytest.raises(RuntimeError, match="create_product failed"):
            pcf_service.get_or_create_product_uuid(sigi, "P1")


# -- aas_service _process_shell SiGREEN submission failure (lines 740-746) -----------


def test_process_shell_wraps_sigreen_submission_error(monkeypatch, tmp_path) -> None:
    """When ``send_factory_emissions`` raises, ``_process_shell`` re-raises as ``_ShellError``."""
    from app.services import aas_service

    monkeypatch.setattr(aas_service.settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(aas_service.settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: "Ended")
    monkeypatch.setattr(
        aas_service, "_get_shell_time_range",
        lambda *_a: ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
    )
    monkeypatch.setattr(aas_service, "_carbon_intensity_for", lambda *_a: 350.0)
    monkeypatch.setattr(
        aas_service, "_aggregate_processes_data",
        lambda *_a, **_k: ({"P1": 5.0}, {}, {"P1": 14.0}, 5.0),
    )
    monkeypatch.setattr(aas_service, "_extract_common_parameter_details", lambda *_a: {
        "product_id": "P-1", "pcf_component_id": None, "work_order": "WO-1", "product_family": None,
    })
    monkeypatch.setattr(aas_service, "collect_idle_cf_by_machine_for_work_order", lambda *_a, **_k: {})
    monkeypatch.setattr(
        aas_service, "build_pcf_report",
        lambda *_a, **_k: {"productCarbonFootprint": 5.0, "emissions": []},
    )
    monkeypatch.setattr(aas_service, "_get_product_uuid_from_shell", lambda *_a: ("uuid-x", "P-1", False))

    sigi = MagicMock()
    sigi.send_factory_emissions.side_effect = RuntimeError("502 from SiGREEN")
    machines = [{"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]

    with pytest.raises(aas_service._ShellError, match="SiGREEN submit failed"):
        aas_service._process_shell("WO-1", aasi=MagicMock(), sigi=sigi, cfg={}, all_machines=machines)


# -- aas_service _process_shell carbon-intensity lookup failure (lines 691-692) -------


def test_process_shell_wraps_carbon_intensity_failure(monkeypatch) -> None:
    """A Grid Compass blowup must surface as a ``_ShellError`` with the original cause attached."""
    from app.services import aas_service

    monkeypatch.setattr(aas_service, "_get_common_parameter_operation_status", lambda *_a: None)
    monkeypatch.setattr(aas_service, "_get_process_operation_status", lambda *_a: "Ended")
    monkeypatch.setattr(
        aas_service, "_get_shell_time_range",
        lambda *_a: ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
    )

    def boom(*_a, **_k):
        raise RuntimeError("Grid down")

    monkeypatch.setattr(aas_service, "_carbon_intensity_for", boom)
    machines = [{"process_idShort": "P1", "bop_submodel_id": "urn:b", "shell_id": "WO-1"}]
    with pytest.raises(aas_service._ShellError, match="Green Grid Compass"):
        aas_service._process_shell(
            "WO-1", aasi=MagicMock(), sigi=MagicMock(), cfg={}, all_machines=machines,
        )


# -- config router POST flow that triggers ensure_sigreen_factory_id + cache clear ---


def test_post_config_clears_token_cache_when_credentials_change(monkeypatch, tmp_path) -> None:
    """Saving new sigreen credentials must call ``clear_sigreen_token_cache`` after persisting."""
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))
    (tmp_path / "app_config.json").write_text(
        json.dumps({
            "data_source": "mes",
            "pcf_tool": "sigreen",
            "sigreen_client_id": "old",
            "sigreen_client_secret": "old",
        }),
        encoding="utf-8",
    )

    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "admin"})

    cleared = {"count": 0}

    def fake_clear() -> None:
        cleared["count"] += 1

    with patch("app.api.routers.config.validate_sigreen_credentials", return_value=True):
        with patch("app.integrations.sigreen.clear_sigreen_token_cache", side_effect=fake_clear):
            with patch("app.api.routers.config.ensure_sigreen_factory_id"):
                response = client.post(
                    "/api/config",
                    json={
                        "sigreen_client_id": "new",
                        "sigreen_client_secret": "new",
                        "sigreen_factory_name": "OPC2",
                    },
                )

    assert response.status_code == 200
    assert cleared["count"] >= 1
