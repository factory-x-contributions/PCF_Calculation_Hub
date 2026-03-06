"""Application lifespan: warn about default secrets, spawn AAS polling thread."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.application.aas_polling import aas_polling_loop_forever
from app.config.settings import settings
from app.core.container import build_aas_pcf_processor, build_app_config_loader

logger = logging.getLogger("pcf_creator_app")


def _start_aas_polling_thread() -> threading.Thread:
    """Spawn the AAS polling daemon thread.

    Wired through :mod:`app.application.aas_polling` (the injectable port) and
    :mod:`app.core.container` (the composition root). Imports are resolved once at
    module load — no ``from app.services… import`` hidden inside ``while True:``.
    """
    thread = threading.Thread(
        target=aas_polling_loop_forever,
        kwargs={
            "load_app_config": build_app_config_loader(),
            "process_aas_shells_for_pcf": build_aas_pcf_processor(),
            "sleep_fn": time.sleep,
            "logger": logger,
        },
        daemon=True,
    )
    thread.start()
    return thread


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Warn on missing prod secrets, then spawn the AAS poller for the lifetime of the process."""
    if (settings.environment or "").strip().lower() != "local" and settings.session_secret_key == "change-me-in-production":
        logger.warning("SESSION_SECRET_KEY is still the default placeholder; set a strong random value in production.")
    _start_aas_polling_thread()
    yield
