"""Router-level tests for ``/consumptionData`` using FastAPI ``dependency_overrides``.

These complement the simulation-tier tests by exercising the router with a
*fake* :class:`ConsumptionUseCase`, so the unit suite alone covers HTTP-layer
concerns (status code, headers, response shape) without touching SiGREEN or the
JSON store.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_consumption_use_case, get_database_path
from app.main import app
from tests.fixtures import http_payloads


@pytest.fixture
def client_with_fake_use_case():
    use_case = MagicMock()
    use_case.execute.return_value = {
        "workOrder": http_payloads.op_1["workOrderName"],
        "operation": http_payloads.op_1["workOrderOperationName"],
        "total_energy_consumption_kwh": 50.0,
        "total_carbon_footprint_kg": 17.5,
        "materials_count": 1,
        "energy_types_count": 1,
        "database_record": {},
        "_api_version": "energy-split-v2",
    }

    app.dependency_overrides[get_consumption_use_case] = lambda: use_case
    app.dependency_overrides[get_database_path] = lambda: Path("/tmp/test.json")
    test_client = TestClient(app)
    try:
        yield test_client, use_case
    finally:
        app.dependency_overrides.pop(get_consumption_use_case, None)
        app.dependency_overrides.pop(get_database_path, None)


def test_router_returns_201_with_use_case_payload(client_with_fake_use_case) -> None:
    client, use_case = client_with_fake_use_case
    response = client.post("/consumptionData", json=http_payloads.op_1)
    assert response.status_code == 201
    body = response.json()
    assert body["workOrder"] == http_payloads.op_1["workOrderName"]
    assert body["_api_version"] == "energy-split-v2"
    use_case.execute.assert_called_once()


def test_router_propagates_use_case_exception_as_500(client_with_fake_use_case) -> None:
    """A non-``PCFError`` raised by the use case becomes a generic 500 (default FastAPI behaviour)."""
    client, use_case = client_with_fake_use_case
    use_case.execute.side_effect = RuntimeError("downstream blew up")
    response = client.post("/consumptionData", json=http_payloads.op_1)
    assert response.status_code == 500


def test_router_validates_request_body_with_422(client_with_fake_use_case) -> None:
    """Pydantic schema failures return 422 before the use case is called."""
    client, use_case = client_with_fake_use_case
    response = client.post("/consumptionData", json={"workOrderName": "x"})
    assert response.status_code == 422
    use_case.execute.assert_not_called()
