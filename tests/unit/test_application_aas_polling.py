"""Tests for :func:`app.application.aas_polling.run_single_aas_poll_cycle`.

The legacy ``_aas_polling_loop`` in :mod:`app.core.lifespan` was replaced in Phase 2 with
this injectable port. The function returns the number of seconds to sleep before the
next iteration so tests can drive the scheduler without spawning threads.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

from app.application.aas_polling import (
    aas_polling_loop_forever,
    run_single_aas_poll_cycle,
)


def test_returns_60s_when_data_source_is_not_aas() -> None:
    delay = run_single_aas_poll_cycle(
        load_app_config=lambda: {"data_source": "mes", "aas_check_period_minutes": 15},
        process_aas_shells_for_pcf=MagicMock(),
        logger=logging.getLogger("test"),
    )
    assert delay == 60.0


def test_returns_60s_when_period_is_zero() -> None:
    delay = run_single_aas_poll_cycle(
        load_app_config=lambda: {"data_source": "aas", "aas_check_period_minutes": 0},
        process_aas_shells_for_pcf=MagicMock(),
        logger=logging.getLogger("test"),
    )
    assert delay == 60.0


def test_runs_processor_when_aas_configured() -> None:
    processor = MagicMock(return_value={"processed": 0, "skipped": 0, "errors": []})
    delay = run_single_aas_poll_cycle(
        load_app_config=lambda: {
            "data_source": "aas",
            "aas_check_period_minutes": 15,
            "aas_type": "AAS (BaSyx)",
        },
        process_aas_shells_for_pcf=processor,
        logger=logging.getLogger("test"),
    )
    processor.assert_called_once()
    assert delay == 15 * 60


def test_logs_summary_when_processor_did_work(caplog) -> None:
    """Errors or processed shells must surface in the log so operators see periodic activity."""
    processor = MagicMock(return_value={"processed": 2, "skipped": 1, "errors": ["x"]})
    with caplog.at_level(logging.INFO, logger="test"):
        run_single_aas_poll_cycle(
            load_app_config=lambda: {"data_source": "aas", "aas_check_period_minutes": 5},
            process_aas_shells_for_pcf=processor,
            logger=logging.getLogger("test"),
        )
    assert any("processed=2" in record.message for record in caplog.records)


def test_loop_forever_swallows_processor_exceptions() -> None:
    """A crash in the processor must not kill the daemon thread; the loop logs and retries."""
    sleeps: list[float] = []
    iterations = {"n": 0}

    def cycle_then_stop(delay: float) -> None:
        sleeps.append(delay)
        iterations["n"] += 1
        if iterations["n"] >= 2:
            raise SystemExit  # break out of the otherwise-infinite loop

    def boom_load_config() -> dict:
        raise RuntimeError("config read blew up")

    try:
        aas_polling_loop_forever(
            load_app_config=boom_load_config,
            process_aas_shells_for_pcf=lambda: {},
            sleep_fn=cycle_then_stop,
            logger=logging.getLogger("test"),
        )
    except SystemExit:
        pass

    # Both iterations should have hit the 60s "error" sleep.
    assert sleeps == [60.0, 60.0]
