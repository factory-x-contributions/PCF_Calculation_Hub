# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for in-process login rate limiting."""

from __future__ import annotations

import time
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


def test_old_attempts_outside_window_are_pruned() -> None:
    """Attempts older than ``_WINDOW_SEC`` must be discarded — preventing permanent lockout
    after a slow drip of failures spread across hours."""
    client = f"prune-{uuid.uuid4().hex}"
    now = time.monotonic()
    # Timestamps must be relative to *current* monotonic time. Hard-coded 0/1/2 only look
    # "ancient" when monotonic() > _WINDOW_SEC (e.g. long-lived local dev machines); on a
    # fresh CI runner monotonic() can be < 60s, making cutoff negative so nothing is pruned.
    stale = [now - lrl._WINDOW_SEC - 30.0, now - lrl._WINDOW_SEC - 10.0, now - lrl._WINDOW_SEC - 1.0]
    with lrl._LOCK:
        lrl._FAILED_ATTEMPTS[client] = stale
    assert lrl.failed_login_exceeds_rate_limit(client) is False
    with lrl._LOCK:
        bucket = lrl._FAILED_ATTEMPTS[client]
    assert len(bucket) == 1
    assert bucket[0] == pytest.approx(now, abs=1.0)
