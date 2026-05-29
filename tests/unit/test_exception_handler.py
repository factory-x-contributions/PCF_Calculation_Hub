# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Tests for the global :class:`PCFError` handler installed in :mod:`app.main`.

Each ``PCFError`` subclass must map to the documented HTTP code with a stable JSON body
of the shape ``{"detail": "<message>"}``. The handler is wired in
:func:`app.main._install_pcf_error_handler`; we exercise it by registering one
synthetic endpoint at module-import time and pushing a different exception per test.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.domain.errors import (
    ConfigurationError,
    DomainValidationError,
    IntegrationError,
    PCFError,
    PipelineSkipped,
)
from app.main import app

# One shared route — registering the same path multiple times would only ever
# dispatch to the first registration, so we centralise the behaviour here and
# vary the raised exception per test through a module-level queue.
_PENDING: list[Exception] = []


@app.get("/__test__/raise")
def _raise_test_endpoint():
    if _PENDING:
        raise _PENDING.pop(0)
    return {"ok": True}


@pytest.fixture
def client():
    _PENDING.clear()
    yield TestClient(app)
    _PENDING.clear()


def test_domain_validation_error_maps_to_400(client: TestClient) -> None:
    _PENDING.append(DomainValidationError("invalid uom"))
    response = client.get("/__test__/raise")
    assert response.status_code == 400
    assert response.json() == {"detail": "invalid uom"}


def test_configuration_error_maps_to_503(client: TestClient) -> None:
    _PENDING.append(ConfigurationError("factory_id not resolved"))
    response = client.get("/__test__/raise")
    assert response.status_code == 503
    assert response.json()["detail"] == "factory_id not resolved"


def test_integration_error_maps_to_502(client: TestClient) -> None:
    _PENDING.append(IntegrationError("SiGREEN POST failed"))
    response = client.get("/__test__/raise")
    assert response.status_code == 502


def test_pipeline_skipped_returns_204(client: TestClient) -> None:
    """``PipelineSkipped`` is a control-flow signal — the handler returns 204 if it ever leaks."""
    _PENDING.append(PipelineSkipped("shell already processed"))
    response = client.get("/__test__/raise")
    assert response.status_code == 204


def test_pcf_error_root_maps_to_500(client: TestClient) -> None:
    """Raising ``PCFError`` directly is against the contract; handler degrades to 500."""
    _PENDING.append(PCFError("rogue raise"))
    response = client.get("/__test__/raise")
    assert response.status_code == 500
