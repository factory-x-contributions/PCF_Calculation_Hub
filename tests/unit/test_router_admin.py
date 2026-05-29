# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Router tests for ``/data_base_view`` (admin pretty-printer)."""
from __future__ import annotations

import json
from base64 import b64encode

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app


@pytest.fixture
def client_with_seeded_db(monkeypatch, tmp_path):
    db_path = tmp_path / "db.json"
    db_path.write_text(json.dumps({"PO_T1": {"operations": {}, "materials": {}}}), encoding="utf-8")
    monkeypatch.setattr(settings, "database_path", str(db_path))
    return TestClient(app)


def _basic_auth_header() -> dict:
    token = b64encode(b"admin:admin").decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_data_base_view_requires_basic_auth(client_with_seeded_db: TestClient) -> None:
    """No credentials → 401 Unauthorized with WWW-Authenticate."""
    response = client_with_seeded_db.get("/data_base_view")
    assert response.status_code == 401
    assert "www-authenticate" in {h.lower() for h in response.headers}


def test_data_base_view_returns_html_with_pretty_json(client_with_seeded_db: TestClient) -> None:
    response = client_with_seeded_db.get("/data_base_view", headers=_basic_auth_header())
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "PO_T1" in response.text
    assert "<pre>" in response.text


def test_data_base_view_rejects_wrong_password(client_with_seeded_db: TestClient) -> None:
    bad = b64encode(b"admin:bad").decode("ascii")
    response = client_with_seeded_db.get(
        "/data_base_view", headers={"Authorization": f"Basic {bad}"}
    )
    assert response.status_code == 401
