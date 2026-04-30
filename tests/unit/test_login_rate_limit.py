"""Unit tests for in-process login rate limiting."""

from __future__ import annotations

import uuid

import pytest

import app.services.login_rate_limit as lrl


@pytest.fixture(autouse=True)
def _clear_rate_limit_state() -> None:
    """Avoid order-dependent failures when the full suite runs."""
    with lrl._LOCK:
        lrl._FAILED_ATTEMPTS.clear()
    yield
    with lrl._LOCK:
        lrl._FAILED_ATTEMPTS.clear()


def test_failed_login_exceeds_rate_limit_after_threshold() -> None:
    client = f"test-client-{uuid.uuid4().hex}"
    assert lrl.failed_login_exceeds_rate_limit(client) is False
    for _ in range(lrl._MAX_FAILURES - 1):
        assert lrl.failed_login_exceeds_rate_limit(client) is False
    assert lrl.failed_login_exceeds_rate_limit(client) is True


def test_distinct_clients_independent() -> None:
    a = f"a-{uuid.uuid4().hex}"
    b = f"b-{uuid.uuid4().hex}"
    for _ in range(lrl._MAX_FAILURES):
        lrl.failed_login_exceeds_rate_limit(a)
    assert lrl.failed_login_exceeds_rate_limit(b) is False
