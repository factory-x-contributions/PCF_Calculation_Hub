from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter

from app.config.settings import settings
from app.models.general_consumption import GeneralConsumptionPayload
from app.services.factory_consumption_service import merge_general_consumption

logger = logging.getLogger("pcf_creator_app")

router = APIRouter()


def _factory_db_path() -> Path:
    return Path(settings.factory_database_path)


@router.post("/idle_consumptions", status_code=201)
def post_idle_consumptions(body: GeneralConsumptionPayload) -> Dict[str, Any]:
    """Accept general idle consumption data and persist under building → machine → energy_type."""
    payload_dict = body.model_dump(mode="json")
    logger.info(
        "POST /idle_consumptions — %s",
        json.dumps(payload_dict, ensure_ascii=False),
    )

    db_path = _factory_db_path()
    merge_general_consumption(db_path, body)

    return {
        "status": "accepted",
        "building_id": body.building_id,
        "machine_id": body.machine_id,
        "machine_name": body.machine_name,
        "energy_type": body.energy_type,
        "database_path": str(db_path),
    }
