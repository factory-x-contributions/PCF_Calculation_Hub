"""Router-level tests for the rest of :mod:`app.api.routers.config`.

These complement :mod:`tests.unit.test_config_carbon_intensity_validation`
(which covers the POST schema) by exercising the GET endpoints, the
session-protected pages, and the admin DELETE handlers.

Pattern is identical across tests:
1. monkeypatch the four ``settings`` paths to ``tmp_path``.
2. log in via ``/api/auth/login`` so the session cookie is attached.
3. call the endpoint and assert response shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app


@pytest.fixture
def authenticated_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))
    (tmp_path / "app_config.json").write_text(
        json.dumps({"data_source": "mes", "pcf_tool": "sigreen"}), encoding="utf-8"
    )
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200, response.text
    return client


# -- protected pages (HTML or redirect) -----------------------------------------------


def test_config_page_when_authenticated(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/config")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_work_order_records_page(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/work_order_records")
    assert response.status_code == 200


def test_factory_energy_distribution_page(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/factory_energy_distribution")
    assert response.status_code == 200


def test_unauthenticated_config_page_redirects_to_login(monkeypatch, tmp_path) -> None:
    """Without a session cookie the protected page must redirect to /login."""
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))
    client = TestClient(app)
    response = client.get("/config", follow_redirects=False)
    assert response.status_code in (302, 303, 307)


# -- /api/factory_energy_distribution -------------------------------------------------


def test_factory_energy_distribution_returns_db(authenticated_client: TestClient, tmp_path: Path) -> None:
    factory_path = Path(settings.factory_database_path)
    factory_path.write_text(json.dumps({"B1": {"M1": {}}}), encoding="utf-8")
    response = authenticated_client.get("/api/factory_energy_distribution")
    assert response.status_code == 200
    assert response.json() == {"B1": {"M1": {}}}


def test_delete_factory_building_returns_200_when_present(authenticated_client: TestClient) -> None:
    factory_path = Path(settings.factory_database_path)
    factory_path.write_text(json.dumps({"B1": {}, "B2": {}}), encoding="utf-8")
    response = authenticated_client.delete("/api/factory_energy_distribution/B1")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "deleted": "B1"}
    remaining = json.loads(factory_path.read_text(encoding="utf-8"))
    assert "B1" not in remaining


def test_delete_factory_building_returns_404_when_missing(authenticated_client: TestClient) -> None:
    factory_path = Path(settings.factory_database_path)
    factory_path.write_text(json.dumps({"B1": {}}), encoding="utf-8")
    response = authenticated_client.delete("/api/factory_energy_distribution/Nope")
    assert response.status_code == 404


# -- /api/data_explorer ---------------------------------------------------------------


def test_data_explorer_returns_full_db(authenticated_client: TestClient) -> None:
    db_path = Path(settings.database_path)
    db_path.write_text(json.dumps({"PO_1": {"operations": {}, "materials": {}, "pcf": None}}), encoding="utf-8")
    response = authenticated_client.get("/api/data_explorer")
    assert response.status_code == 200
    assert "PO_1" in response.json()


def test_delete_work_order_returns_200_on_success(authenticated_client: TestClient) -> None:
    db_path = Path(settings.database_path)
    db_path.write_text(json.dumps({"PO_X": {"operations": {}}, "PO_Y": {"operations": {}}}), encoding="utf-8")
    response = authenticated_client.delete("/api/data_explorer/PO_X")
    assert response.status_code == 200
    remaining = json.loads(db_path.read_text(encoding="utf-8"))
    assert "PO_X" not in remaining


def test_delete_work_order_returns_404_when_missing(authenticated_client: TestClient) -> None:
    db_path = Path(settings.database_path)
    db_path.write_text(json.dumps({"PO_X": {"operations": {}}}), encoding="utf-8")
    response = authenticated_client.delete("/api/data_explorer/PO_Y")
    assert response.status_code == 404


# -- /api/logs ------------------------------------------------------------------------


def test_logs_returns_recent_entries(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/logs?after=0")
    assert response.status_code == 200
    body = response.json()
    assert "entries" in body and isinstance(body["entries"], list)


# -- /api/aas/shells -----------------------------------------------------------------


def test_aas_shells_returns_error_when_data_source_not_aas(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/aas/shells")
    assert response.status_code == 200
    body = response.json()
    assert body["error"] == "Data source is not AAS"


def test_aas_process_shells_returns_error_when_data_source_not_aas(authenticated_client: TestClient) -> None:
    response = authenticated_client.post("/api/aas/process_shells")
    assert response.status_code == 200
    body = response.json()
    assert "Data source is not AAS" in body.get("errors", [])


# -- GET /api/config ------------------------------------------------------------------


def test_get_config_returns_current_state(authenticated_client: TestClient) -> None:
    response = authenticated_client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["data_source"] == "mes"


def test_get_config_includes_aas_status_when_data_source_is_aas(
    authenticated_client: TestClient, monkeypatch
) -> None:
    """When data_source=aas the config endpoint must report aas_status (even if AAS isn't reachable)."""
    # Flip data_source to AAS via the /api/config POST so both reads see it.
    response = authenticated_client.post(
        "/api/config",
        json={"data_source": "aas", "aas_base_url": "http://basyx.local:8081", "aas_type": "AAS (BaSyx)"},
    )
    assert response.status_code == 200, response.text

    response = authenticated_client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert "aas_status" in body


def test_get_config_reports_aas_unreachable_status_when_factory_raises(
    authenticated_client: TestClient, monkeypatch
) -> None:
    """A crash in ``_get_aas_interface_from_config`` must surface as a placeholder aas_status,
    not 500 — the config UI then shows '?' so the operator knows there's a misconfiguration."""
    authenticated_client.post("/api/config", json={"data_source": "aas"})
    monkeypatch.setattr(
        "app.api.routers.config._get_aas_interface_from_config",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    response = authenticated_client.get("/api/config")
    assert response.status_code == 200
    aas_status = response.json().get("aas_status", {})
    assert aas_status == {"aas_type": "?", "aas_base_url": "?", "asset_name": "?"}


def test_get_config_reports_empty_aas_status_when_aas_unconfigured(
    authenticated_client: TestClient, monkeypatch
) -> None:
    """When data_source=aas but no base URL is configured, the placeholder must report empty strings."""
    authenticated_client.post("/api/config", json={"data_source": "aas"})
    monkeypatch.setattr(
        "app.api.routers.config._get_aas_interface_from_config",
        lambda: None,
    )
    response = authenticated_client.get("/api/config")
    assert response.status_code == 200
    assert response.json()["aas_status"] == {"aas_type": "", "aas_base_url": "", "asset_name": ""}


# -- GET /api/overview_stats ---------------------------------------------------------


def test_overview_stats_returns_aggregated_metrics(authenticated_client: TestClient) -> None:
    """The overview endpoint must aggregate from the JSON DB and respond with a stats dict."""
    db_path = Path(settings.database_path)
    db_path.write_text(
        json.dumps({
            "PO_1": {
                "operations": {"OP10": {"energy": {"Electricity": {"carbon_footprint_kg": 12.5, "total_consumption": 25.0, "uom": "kWh"}}}},
                "materials": {},
                "pcf": {"productCarbonFootprint": 12.5},
            }
        }),
        encoding="utf-8",
    )
    response = authenticated_client.get("/api/overview_stats")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)


# -- POST /api/config — additional input-validation branches -------------------


def test_post_config_treats_non_json_body_as_empty_dict(
    authenticated_client: TestClient,
) -> None:
    """A malformed JSON body must not raise — the route logs and treats the body as empty."""
    response = authenticated_client.post(
        "/api/config",
        content=b"{ not-json",
        headers={"content-type": "application/json"},
    )
    # Empty body dict ⇒ no validation triggered ⇒ 200 with current config.
    assert response.status_code == 200


def test_post_config_skips_empty_sigreen_client_secret(
    authenticated_client: TestClient, monkeypatch
) -> None:
    """An empty ``sigreen_client_secret`` field in the body must be ignored (continue), so
    the previously-saved secret stays in place — operators can edit other fields without
    re-entering credentials each time."""
    # Pre-seed credentials directly so the next POST doesn't trigger validation.
    app_config_path = Path(settings.app_config_path)
    seed = json.loads(app_config_path.read_text(encoding="utf-8"))
    seed.update({"sigreen_client_id": "old", "sigreen_client_secret": "old-secret"})
    app_config_path.write_text(json.dumps(seed), encoding="utf-8")

    response = authenticated_client.post(
        "/api/config",
        json={"sigreen_client_secret": "", "carbon_intensity_constant_gco2": 425},
    )
    assert response.status_code == 200
    body = response.json()["config"]
    assert body.get("sigreen_client_secret") == "old-secret"


def test_post_config_falls_back_to_assetfox_for_unknown_aas_type(
    authenticated_client: TestClient,
) -> None:
    """Unknown ``aas_type`` value must coerce to a safe default ('AAS (AssetFox)')."""
    response = authenticated_client.post(
        "/api/config", json={"aas_type": "AAS (Bogus)"}
    )
    assert response.status_code == 200
    assert response.json()["config"]["aas_type"] == "AAS (AssetFox)"


def test_post_config_clamps_aas_check_period_minutes(
    authenticated_client: TestClient,
) -> None:
    """``aas_check_period_minutes`` is clamped to [0, 1440]."""
    response = authenticated_client.post(
        "/api/config", json={"aas_check_period_minutes": 99999}
    )
    assert response.status_code == 200
    assert response.json()["config"]["aas_check_period_minutes"] == 1440.0


def test_post_config_falls_back_to_zero_on_unparseable_aas_check_period(
    authenticated_client: TestClient,
) -> None:
    """Garbage value for ``aas_check_period_minutes`` must default to 0, not 500."""
    response = authenticated_client.post(
        "/api/config", json={"aas_check_period_minutes": "soonish"}
    )
    assert response.status_code == 200
    assert response.json()["config"]["aas_check_period_minutes"] == 0


def test_post_config_strips_sigreen_product_identifier_type(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/config", json={"sigreen_product_identifier_type": "  Material ID  "}
    )
    assert response.status_code == 200
    assert response.json()["config"]["sigreen_product_identifier_type"] == "Material ID"


def test_post_config_pcf_include_bom_coerces_to_bool(
    authenticated_client: TestClient,
) -> None:
    response = authenticated_client.post(
        "/api/config", json={"pcf_include_bom": "yes"}
    )
    assert response.status_code == 200
    assert response.json()["config"]["pcf_include_bom"] is True


