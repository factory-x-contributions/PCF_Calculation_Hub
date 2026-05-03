"""
Integration tests against a running app (default: https://localhost:8443).

Set LIVE_BASE_URL to override (e.g. http://localhost:8443 for HTTP-on-8443 without TLS).

Requires the server to be running; tests are skipped if the connection fails.
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIVE_BASE_URL = (os.environ.get("LIVE_BASE_URL") or "https://localhost:8443").rstrip("/")


def _session() -> requests.Session:
    s = requests.Session()
    s.verify = False
    return s


@pytest.fixture(scope="module")
def live_available() -> bool:
    try:
        r = _session().get(f"{LIVE_BASE_URL}/openapi.json", timeout=3)
        return r.status_code == 200
    except OSError:
        return False


@pytest.mark.integration
def test_live_openapi_json(live_available: bool) -> None:
    if not live_available:
        pytest.skip(f"Server not reachable at {LIVE_BASE_URL}")
    r = _session().get(f"{LIVE_BASE_URL}/openapi.json", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert "openapi" in data or "swagger" in data or "paths" in data


@pytest.mark.integration
def test_live_general_consumptions(live_available: bool) -> None:
    if not live_available:
        pytest.skip(f"Server not reachable at {LIVE_BASE_URL}")
    payload = {
        "total_time": 180,
        "total_idle_time": 80,
        "machine_id": f"DMG70-test-{uuid.uuid4().hex[:8]}",
        "energy_type": "electricity",
        "machine_name": "DMG70",
        "building_id": "hall_10",
        "idle_consumption_total": 3000,
        "prod_consumption_total": 6000,
        "publication_datetime": "2026-03-26T14:30:00.000Z",
        "work_orders_duration": {"PO_40005": 40, "PO_40010": 60},
    }
    r = _session().post(
        f"{LIVE_BASE_URL}/general_consumptions",
        json=payload,
        timeout=10,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body.get("status") == "accepted"
    assert body.get("building_id") == "hall_10"
