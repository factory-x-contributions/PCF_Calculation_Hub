from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter

from app.api.deps import ConsumptionUseCaseDep, DatabasePathDep
from app.domain import MaterialPCFMap
from app.models.consumption import ConsumptionData
from app.services.material_pcf import fetch_material_pcf_map

logger = logging.getLogger("pcf_creator_app")

router = APIRouter()


def _fetch_material_pcf_map(consumed_materials: list) -> MaterialPCFMap:
    """SiGREEN material PCF lookup for MES flow.

    Kept as a thin module-level function so existing tests can patch it directly
    (``patch("app.api.routers.consumption._fetch_material_pcf_map", ...)``).
    The :func:`app.api.deps.get_material_pcf_fetcher` factory resolves this seam
    on every request, so the patch applies even though use-case construction
    moved into ``deps``.
    """
    return fetch_material_pcf_map(consumed_materials, log_label="SiGREEN")


@router.post("/consumptionData", status_code=201)
def consumption_data(
    data: ConsumptionData,
    use_case: ConsumptionUseCaseDep,
    db_path: DatabasePathDep,
) -> Dict[str, Any]:
    """Ingest consumption data and update the bookkeeping JSON database.

    Orchestration is delegated to :class:`app.application.use_cases.ConsumptionUseCase`
    so this router stays a thin HTTP adapter.
    """
    logger.info(
        "POST /consumptionData — workOrder=%s operation=%s",
        data.workOrderName, data.workOrderOperationName,
    )
    try:
        result = use_case.execute(db_path=db_path, data=data)
        logger.info(
            "Consumption processed — workOrder=%s energy=%.2f kWh cf=%.2f kg",
            data.workOrderName,
            result["total_energy_consumption_kwh"],
            result["total_carbon_footprint_kg"],
        )
        return result
    except Exception:
        logger.exception("Error processing consumption for workOrder=%s", data.workOrderName)
        raise
