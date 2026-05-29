# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel


class ProductionResults(BaseModel):
    workOrderName: str
    workOrderState: str
    productId: str
    productName: str
    productRevision: str
    traceabilityType: str
    producedMtus: List[str]
    uom: str
    producedQuantity: int
    scrappedQuantity: int
    actualStartTime: datetime
    actualEndTime: datetime
    locationName: str
    timestamp: datetime

