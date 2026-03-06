"""Composition root for the PCF Calculation Hub.

This module is where adapters are wired into the ports declared in
:mod:`app.application.ports`. Both :mod:`app.api.deps` (HTTP requests)
and :mod:`app.core.lifespan` (background AAS poller) read from here so
the application has exactly one place that knows how concrete
implementations are selected.

Phase 1 keeps the surface deliberately small: each builder returns the
existing module-level helper so behaviour does not change. Later phases
substitute real ``Port``-typed objects without touching the call sites.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any


def build_material_pcf_fetcher() -> Callable[[list[Any]], dict[str, Any]]:
    """Return the callable that resolves material PCF for the MES flow.

    Phase 1: thin re-export of the existing behaviour at
    :func:`app.services.material_pcf.fetch_material_pcf_map`. Phase 3
    will route this through :mod:`app.services.sigreen_factory` so all
    SiGREEN client construction goes through a single site.
    """
    from app.services.material_pcf import fetch_material_pcf_map

    def _fetch(consumed_materials: list[Any]) -> dict[str, Any]:
        return fetch_material_pcf_map(consumed_materials, log_label="SiGREEN")

    return _fetch


def build_app_config_loader() -> Callable[[], dict[str, Any]]:
    """Return the function used to read the live app configuration.

    Phase 1: returns :func:`app.services.config_service.load_app_config`
    directly. Phase 5 replaces this with an :class:`AppConfigPort`
    instance that memoizes the read.
    """
    from app.services.config_service import load_app_config

    return load_app_config


def build_aas_pcf_processor() -> Callable[[], dict[str, Any]]:
    """Return the callable that runs one AAS PCF processing pass.

    Phase 1: returns :func:`app.services.aas_service.process_aas_shells_for_pcf`
    so the lifespan thread can call it through the container. Phase 5
    replaces this with an ``AasIngestionUseCase`` instance.
    """
    from app.services.aas_service import process_aas_shells_for_pcf

    return process_aas_shells_for_pcf


__all__ = [
    "build_material_pcf_fetcher",
    "build_app_config_loader",
    "build_aas_pcf_processor",
]
