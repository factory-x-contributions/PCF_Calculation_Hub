"""Extractable AAS periodic polling loop for background execution and unit tests."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


def run_single_aas_poll_cycle(
    *,
    load_app_config: Callable[[], dict[str, Any]],
    process_aas_shells_for_pcf: Callable[[], dict[str, Any]],
    logger: logging.Logger,
) -> float:
    """Run one scheduler iteration; return seconds to sleep before the next iteration."""
    cfg = load_app_config()
    period_minutes = float(cfg.get("aas_check_period_minutes") or 0)
    if cfg.get("data_source") != "aas" or period_minutes <= 0:
        return 60.0

    aas_type = cfg.get("aas_type") or "AAS (AssetFox)"
    logger.info("[AAS period] Starting periodic check — %s (interval=%.1f min)", aas_type, period_minutes)
    result = process_aas_shells_for_pcf()
    if result.get("processed", 0) > 0 or result.get("errors"):
        logger.info(
            "AAS periodic check: processed=%s skipped=%s errors=%s",
            result.get("processed", 0),
            result.get("skipped", 0),
            len(result.get("errors", [])),
        )
    return period_minutes * 60


def aas_polling_loop_forever(
    *,
    load_app_config: Callable[[], dict[str, Any]],
    process_aas_shells_for_pcf: Callable[[], dict[str, Any]],
    sleep_fn: Callable[[float], None],
    logger: logging.Logger | None = None,
) -> None:
    """Infinite polling loop (daemon thread entrypoint)."""
    log = logger or logging.getLogger("pcf_creator_app")
    while True:
        try:
            delay = run_single_aas_poll_cycle(
                load_app_config=load_app_config,
                process_aas_shells_for_pcf=process_aas_shells_for_pcf,
                logger=log,
            )
            sleep_fn(delay)
        except Exception:
            log.exception("AAS polling loop error")
            sleep_fn(60.0)
