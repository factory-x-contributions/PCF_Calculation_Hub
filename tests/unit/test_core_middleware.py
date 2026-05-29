# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`app.core.middleware` — security headers, 422 handler, stage-prefix.

Spec §5.2.4 mandates the three security headers (X-Content-Type-Options, X-Frame-Options,
Referrer-Policy). Spec §5.2.6 mandates the 422 envelope with structured ``errors`` plus a
bounded raw-body preview for diagnostics.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_security_headers_present_on_every_response(client: TestClient) -> None:
    response = client.get("/login")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_security_headers_present_on_404(client: TestClient) -> None:
    response = client.get("/this/does/not/exist")
    assert response.status_code == 404
    assert "X-Content-Type-Options" in response.headers


def test_validation_error_returns_422_with_structured_envelope(client: TestClient) -> None:
    """Schema-failed POST must return 422 with detail + errors[] + raw body preview."""
    response = client.post("/consumptionData", json={"workOrderName": "x"})  # missing required fields
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Request validation failed"
    assert isinstance(body["errors"], list) and len(body["errors"]) > 0
    assert "received_body_preview" in body


def test_validation_error_truncates_raw_body_preview(client: TestClient) -> None:
    """Spec §5.2.6: the preview is bounded to 4096 chars to avoid leaking large payloads in client responses."""
    huge_string = "x" * 20_000
    response = client.post("/consumptionData", json={"workOrderName": huge_string})
    assert response.status_code == 422
    preview = response.json().get("received_body_preview", "")
    assert len(preview) <= 4096
