# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Self-contained SiGREEN doubles for simulation-tier HTTP tests."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

PATCH_TARGET = "app.services.pcf_service._get_sigreen"

DEFAULT_FACTORY_ID = "01989e05-9adf-7bb2-83eb-4f5090fed02a"
DEFAULT_FACTORY_NAME = "OPC"
DEFAULT_PRODUCT_UUID = "0198c1dc-94d1-73d7-bc80-b84a10b639d8"


def _bill_stub(
    total: float,
    pcf_share: float,
    type_of_activity: str,
    comment: str,
) -> dict[str, Any]:
    return {
        "typeOfActivity": type_of_activity,
        "total": total,
        "primaryDataShare": 75.8,
        "shareOnTotal": pcf_share,
        "emissionUnit": "kgCO2e/piece",
        "comment": comment,
        "fossil": total,
        "biogenic": 0,
        "dLuc": 0,
        "landUse": 0,
        "aircraft": 0,
    }


def _pcf_report_stub(bop: list[Any], *, sigi: MagicMock, **kw: Any) -> dict[str, Any]:
    return {
        "revision": "1",
        "factoryId": sigi.factory_id,
        "factory": sigi.factory_name,
        "from": kw.get("t_start", ""),
        "to": kw.get("t_end", ""),
        "batch": {
            "batchNumber": kw.get("batch_number", ""),
            "quantity": kw.get("quantity", 1),
            "assessmentYear": 2026,
            "dataSource": "PCF Creator APP V-1.0",
            "comment": "Simulation test batch",
        },
        "productCarbonFootprint": kw.get("Total_PCF", 0),
        "emissions": bop,
        "comment": "Simulation test",
        "sourceSystem": "API",
    }


def configure_mock_sigreen(
    mock_get: MagicMock,
    *,
    factory_id: str = DEFAULT_FACTORY_ID,
    factory_name: str = DEFAULT_FACTORY_NAME,
    product_uuid: str = DEFAULT_PRODUCT_UUID,
) -> MagicMock:
    """Attach SiGREEN API behavior to ``mock_get`` (the patched ``_get_sigreen``)."""
    sigi = mock_get.return_value
    sigi.factory_id = factory_id
    sigi.factory_name = factory_name
    sigi.create_process_bill.side_effect = _bill_stub
    sigi.create_PCF_report.side_effect = lambda bop, **kw: _pcf_report_stub(
        bop, sigi=sigi, **kw
    )
    sigi.get_product_uuid.return_value = product_uuid
    sigi.send_factory_emissions.return_value = None
    return sigi


@contextmanager
def patch_sigreen(
    *,
    factory_id: str = DEFAULT_FACTORY_ID,
    factory_name: str = DEFAULT_FACTORY_NAME,
    product_uuid: str = DEFAULT_PRODUCT_UUID,
) -> Iterator[MagicMock]:
    """Patch ``_get_sigreen`` so ``/productionResults`` never calls the live API."""
    with patch(PATCH_TARGET) as mock_get:
        yield configure_mock_sigreen(
            mock_get,
            factory_id=factory_id,
            factory_name=factory_name,
            product_uuid=product_uuid,
        )
