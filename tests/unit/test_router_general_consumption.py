"""Router tests for ``POST /idle_consumptions``."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    factory_path = tmp_path / "factory_db.json"
    monkeypatch.setattr(settings, "factory_database_path", str(factory_path))
    return TestClient(app)


def test_post_idle_consumptions_201_and_persists(client: TestClient) -> None:
    body = {
        "total_time": 60.0,
        "total_idle_time": 30.0,
        "machine_id": "M1",
        "energy_type": "Electricity",
        "machine_name": "Mill-A",
        "building_id": "B1",
        "idle_consumption_total": 5.0,
    }
    response = client.post("/idle_consumptions", json=body)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "accepted"
    assert data["building_id"] == "B1"
    assert data["machine_id"] == "M1"
    assert data["energy_type"] == "Electricity"
    db_path = Path(settings.factory_database_path)
    assert db_path.exists()
    stored = json.loads(db_path.read_text(encoding="utf-8"))
    assert "B1" in stored


def test_post_idle_consumptions_building_level_201(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    factory_path = tmp_path / "factory_db.json"
    monkeypatch.setattr(settings, "factory_database_path", str(factory_path))
    client = TestClient(app)
    body = {
        "total_time": 1380.5853,
        "total_idle_time": 1380.5853,
        "building_name": "G21_Hall",
        "energy_type": "electricity",
        "building_id": "G21_Hall",
        "idle_consumption_total": 12.37044,
        "idle_consumption_rate": 0.53762,
        "publication_datetime": "2026-05-16T14:08:56.100Z",
    }
    response = client.post("/idle_consumptions", json=body)
    assert response.status_code == 201
    data = response.json()
    assert data["machine_id"] == "building_idle"
    assert data["machine_name"] == "G21_Hall"
    stored = json.loads(Path(settings.factory_database_path).read_text(encoding="utf-8"))
    node = stored["G21_Hall"]["building_idle"]["electricity"]
    assert node["aggregate_scope"] == "building"
    assert node["idle_consumption_total_kwh"] == pytest.approx(12.37044)
