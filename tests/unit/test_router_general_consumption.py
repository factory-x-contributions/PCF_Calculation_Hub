"""Router tests for ``POST /general_consumptions``."""
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


def test_post_general_consumptions_201_and_persists(client: TestClient) -> None:
    body = {
        "total_time": 60.0,
        "total_idle_time": 30.0,
        "machine_id": "M1",
        "energy_type": "Electricity",
        "machine_name": "Mill-A",
        "building_id": "B1",
        "idle_consumption_total": 5.0,
    }
    response = client.post("/general_consumptions", json=body)
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
