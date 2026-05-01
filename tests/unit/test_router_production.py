"""Router-level tests for ``/productionResults`` using ``dependency_overrides``."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_database_path, get_production_use_case
from app.application.mes_workflow import MissingConsumptionForWorkOrderError
from app.main import app
from tests.fixtures import http_payloads


@pytest.fixture
def client_with_fake_use_case():
    use_case = MagicMock()
    use_case.execute.return_value = {
        "workOrderName": http_payloads.prod_result_1["workOrderName"],
        "productId": http_payloads.prod_result_1["productId"],
        "productUuid": "uuid-test-1",
        "producedQuantity": 1,
        "timestamp": http_payloads.prod_result_1["timestamp"],
    }

    app.dependency_overrides[get_production_use_case] = lambda: use_case
    app.dependency_overrides[get_database_path] = lambda: Path("/tmp/test.json")
    test_client = TestClient(app)
    try:
        yield test_client, use_case
    finally:
        app.dependency_overrides.pop(get_production_use_case, None)
        app.dependency_overrides.pop(get_database_path, None)


def test_router_returns_201_on_success(client_with_fake_use_case) -> None:
    client, _ = client_with_fake_use_case
    response = client.post("/productionResults", json=http_payloads.prod_result_1)
    assert response.status_code == 201
    body = response.json()
    assert body["productUuid"] == "uuid-test-1"


def test_router_returns_400_when_no_consumption(client_with_fake_use_case) -> None:
    """``MissingConsumptionForWorkOrderError`` must surface as HTTP 400 with the spec-mandated detail."""
    client, use_case = client_with_fake_use_case
    use_case.execute.side_effect = MissingConsumptionForWorkOrderError("PO_X")
    response = client.post("/productionResults", json=http_payloads.prod_result_1)
    assert response.status_code == 400
    assert response.json()["detail"] == "No consumption data found for given workOrderName"


def test_router_propagates_other_exceptions_as_500(client_with_fake_use_case) -> None:
    client, use_case = client_with_fake_use_case
    use_case.execute.side_effect = RuntimeError("downstream went boom")
    response = client.post("/productionResults", json=http_payloads.prod_result_1)
    assert response.status_code == 500


def test_router_reraises_http_exception_from_use_case(client_with_fake_use_case) -> None:
    """``HTTPException`` from the use case must pass through without becoming a generic 500."""
    client, use_case = client_with_fake_use_case
    use_case.execute.side_effect = HTTPException(status_code=409, detail="conflict")
    response = client.post("/productionResults", json=http_payloads.prod_result_1)
    assert response.status_code == 409
    assert response.json()["detail"] == "conflict"
