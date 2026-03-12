"""Application-layer port protocols (typing-only seams for DI and tests).

These ``Protocol`` classes are the contracts the application layer
(use cases, pipelines) depends on. Concrete implementations live in
:mod:`app.services` (persistence adapters), :mod:`app.integrations`
(external clients), and :mod:`app.application.pipelines` (strategies).

Keeping the contracts here means use cases never import an adapter
module — they take a port instance via ``Depends`` (HTTP) or via the
composition root in :mod:`app.core.container` (background threads).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


class MaterialPcfFetcherPort(Protocol):
    """Maps consumed materials from a payload to material-level PCF data."""

    def __call__(self, consumed_materials: list[Any]) -> dict[str, Any]:
        ...


class PcfReportSubmitterPort(Protocol):
    """Submits a PCF report to the configured PCF management tool (e.g. SiGREEN).

    Implementations resolve the product UUID for ``product_id`` (creating
    the product when missing) and post the report. They should raise
    :class:`app.domain.errors.IntegrationError` on transport / auth /
    parsing failures and :class:`app.domain.errors.ConfigurationError`
    when required credentials or factory binding are missing.
    """

    def get_or_create_product_uuid(self, product_id: str) -> str:
        ...

    def submit(self, product_uuid: str, pcf_report: dict[str, Any]) -> None:
        ...


class BookkeepingRepositoryPort(Protocol):
    """Persistence abstraction over the work-order JSON database.

    Hides the on-disk JSON / S3-mirror layout behind a method surface
    that callers in the application layer can satisfy with a fake.
    The real implementation today is :mod:`app.services.bookkeeping_service`
    backed by :class:`app.storage.json_store.JsonStore`.
    """

    def update_after_consumption(
        self,
        *,
        db_path: Path,
        data: Any,
        energy_breakdown: dict[str, Any],
        total_energy_kwh: float,
        total_cf_kg: float,
        co2g_coeff_avg: float,
        material_pcf_per_unit: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ...

    def get_bop_for_work_order(
        self, *, db_path: Path, work_order_name: str
    ) -> dict[str, float]:
        ...

    def get_materials_cf_breakdown(
        self, db_path: Path, work_order_name: str
    ) -> dict[str, dict[str, Any]]:
        ...

    def update_pcf_for_work_order(
        self,
        *,
        db_path: Path,
        work_order_name: str,
        pcf_report: dict[str, Any],
        product_name: str = "",
    ) -> None:
        ...


class AppConfigPort(Protocol):
    """Memoizing read/write access to the runtime app configuration.

    Replaces direct ``load_app_config()`` calls scattered through the
    services. ``get`` is expected to be idempotent within one request /
    one polling iteration; ``clear_cache`` is called when the config
    has just been written and downstream callers must read fresh values.
    """

    def get(self) -> dict[str, Any]:
        ...

    def save(self, config: dict[str, Any]) -> None:
        ...

    def clear_cache(self) -> None:
        ...


class CarbonIntensityProviderPort(Protocol):
    """Returns grid carbon intensity in g CO2 per kWh for a time window.

    Two implementations are planned (Phase 4):

    * ``ConstantCarbonIntensity`` — returns the configured constant
      regardless of window.
    * ``GreenGridCompassCarbonIntensity`` — calls the Grid Compass API
      via :class:`app.integrations.grid.GridInterface` for a window.

    Used by the AAS pipeline only; the MES path keeps its current
    behaviour (per the architectural decision to leave MES asymmetric).
    """

    def gco2_per_kwh(
        self, at_window: tuple[datetime, datetime] | None = None
    ) -> float:
        ...


__all__ = [
    "MaterialPcfFetcherPort",
    "PcfReportSubmitterPort",
    "BookkeepingRepositoryPort",
    "AppConfigPort",
    "CarbonIntensityProviderPort",
]
