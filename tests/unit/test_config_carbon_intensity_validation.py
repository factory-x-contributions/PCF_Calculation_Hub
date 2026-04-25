"""Spec §5.2.2 evidence: the Config UI POST validates ``carbon_intensity_source``.

The API today accepts ``constant`` or ``green_grid_compass`` and silently coerces
anything else to ``constant``; that's the defensive validation enforced inline in
:func:`app.api.routers.config.post_config`. These tests pin the contract.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app


@pytest.fixture
def authenticated_client(monkeypatch, tmp_path):
    """A TestClient with the work-order/factory DBs redirected to a temp dir and a logged-in session."""
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "db.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(tmp_path / "factory.json"))
    monkeypatch.setattr(settings, "app_config_path", str(tmp_path / "app_config.json"))

    # write a baseline config so post_config's `current = load_app_config()` finds something
    (tmp_path / "app_config.json").write_text(
        '{"data_source": "mes", "pcf_tool": "sigreen", "carbon_intensity_source": "constant", "carbon_intensity_constant_gco2": 350}',
        encoding="utf-8",
    )

    client = TestClient(app)
    # log in via the same Basic Auth credentials used by the test session
    response = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200, response.text
    return client


def test_unknown_carbon_intensity_source_falls_back_to_constant(authenticated_client: TestClient) -> None:
    """Anything outside the {constant, green_grid_compass} set is coerced to ``constant``."""
    response = authenticated_client.post(
        "/api/config",
        json={"carbon_intensity_source": "satellite"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["config"]["carbon_intensity_source"] == "constant"


def test_green_grid_compass_source_is_accepted(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/config",
        json={"carbon_intensity_source": "green_grid_compass"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["carbon_intensity_source"] == "green_grid_compass"


def test_constant_source_is_accepted(authenticated_client: TestClient) -> None:
    response = authenticated_client.post(
        "/api/config",
        json={"carbon_intensity_source": "constant"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["carbon_intensity_source"] == "constant"


def test_carbon_intensity_constant_negative_clamped_to_zero(authenticated_client: TestClient) -> None:
    """The router validation clamps the constant to a non-negative value."""
    response = authenticated_client.post(
        "/api/config",
        json={"carbon_intensity_constant_gco2": -50},
    )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["carbon_intensity_constant_gco2"] == 0.0


def test_carbon_intensity_constant_unparseable_falls_back_to_default(authenticated_client: TestClient) -> None:
    """Non-numeric input is rejected by the router and replaced with the documented default of 350."""
    response = authenticated_client.post(
        "/api/config",
        json={"carbon_intensity_constant_gco2": "abc"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["config"]["carbon_intensity_constant_gco2"] == 350
