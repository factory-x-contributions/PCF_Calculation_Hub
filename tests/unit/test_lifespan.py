# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for :mod:`app.core.lifespan` — the AAS polling thread wiring.

The legacy ``_aas_polling_loop`` had ``from app.services… import`` statements
inside ``while True:``; Phase 2 replaced that with a single call to
:func:`app.application.aas_polling.aas_polling_loop_forever` driven by the
container module. These tests guard the new wiring.
"""
from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from app.core import lifespan as lifespan_mod


def _wait_for(predicate, timeout: float = 1.0) -> bool:
    """Tiny busy-wait helper so tests do not flake on thread scheduling."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_start_aas_polling_thread_calls_loop_forever_with_injected_callables() -> None:
    """The thread target must be the injectable port, not the legacy inline loop."""
    captured: dict[str, Any] = {}

    def fake_loop_forever(**kwargs: Any) -> None:
        captured.update(kwargs)

    with patch.object(lifespan_mod, "aas_polling_loop_forever", side_effect=fake_loop_forever):
        thread = lifespan_mod._start_aas_polling_thread()
        thread.join(timeout=1.0)

    assert "load_app_config" in captured
    assert "process_aas_shells_for_pcf" in captured
    assert "sleep_fn" in captured
    assert "logger" in captured
    assert callable(captured["load_app_config"])
    assert callable(captured["process_aas_shells_for_pcf"])
    assert captured["sleep_fn"] is time.sleep
    assert captured["logger"] is lifespan_mod.logger


def test_start_aas_polling_thread_returns_daemon_thread() -> None:
    """Daemon=True is essential — tests must not deadlock if the loop stays running."""
    with patch.object(lifespan_mod, "aas_polling_loop_forever", return_value=None):
        thread = lifespan_mod._start_aas_polling_thread()

    assert isinstance(thread, threading.Thread)
    assert thread.daemon is True
    thread.join(timeout=1.0)


def test_no_inline_polling_loop_definition_remains() -> None:
    """Regression guard: the old ``_aas_polling_loop`` symbol must be gone after Phase 2."""
    assert not hasattr(lifespan_mod, "_aas_polling_loop"), (
        "lifespan must delegate to aas_polling_loop_forever from "
        "app.application.aas_polling, not re-implement the loop inline"
    )


@pytest.mark.asyncio
async def test_lifespan_warns_when_session_secret_is_default(monkeypatch, caplog) -> None:
    """A non-local environment with the placeholder secret must log a warning."""
    monkeypatch.setattr(lifespan_mod.settings, "environment", "production")
    monkeypatch.setattr(lifespan_mod.settings, "session_secret_key", "change-me-in-production")

    with patch.object(lifespan_mod, "_start_aas_polling_thread"):
        async with lifespan_mod.lifespan(None):  # type: ignore[arg-type]
            pass

    assert any("SESSION_SECRET_KEY is still the default placeholder" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_lifespan_local_environment_does_not_warn(monkeypatch, caplog) -> None:
    """Local environment must not log the warning (developer ergonomics)."""
    monkeypatch.setattr(lifespan_mod.settings, "environment", "local")
    monkeypatch.setattr(lifespan_mod.settings, "session_secret_key", "change-me-in-production")

    with patch.object(lifespan_mod, "_start_aas_polling_thread"):
        async with lifespan_mod.lifespan(None):  # type: ignore[arg-type]
            pass

    assert not any("SESSION_SECRET_KEY" in record.message for record in caplog.records)
