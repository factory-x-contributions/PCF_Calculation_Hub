# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DatabasePathDep, ProductionUseCaseDep
from app.application.use_cases.production_use_case import MissingConsumptionForWorkOrderError
from app.models.production import ProductionResults

logger = logging.getLogger("pcf_creator_app")

router = APIRouter()


@router.post("/productionResults", status_code=201)
def production_results(
    data: ProductionResults,
    use_case: ProductionUseCaseDep,
    db_path: DatabasePathDep,
) -> Dict[str, Any]:
    """Finalize production, compute PCF, submit to SiGREEN, and persist to JSON.

    Orchestration is delegated to :class:`app.application.use_cases.ProductionUseCase`.
    The router only owns request parsing, the 400 translation when no prior consumption
    rows exist, and a generic 500 fallback. The global :class:`app.domain.errors.PCFError`
    handler covers everything else.
    """
    logger.info(
        "POST /productionResults — workOrder=%s productId=%s",
        data.workOrderName,
        data.productId,
    )

    try:
        return use_case.execute(db_path=db_path, data=data)
    except MissingConsumptionForWorkOrderError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No consumption data found for given workOrderName",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error processing production results for workOrder=%s", data.workOrderName)
        raise

