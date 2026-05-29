# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Measurement(BaseModel):
    start: datetime
    duration: int = 15
    consumption: float


class ResourceUsage(BaseModel):
    measurementType: str
    measurements: List[Measurement]


class ConsumedEnergy(BaseModel):
    type: str
    uom: str
    resourceUsage: ResourceUsage


class ConsumedMaterial(BaseModel):
    identifier: str
    materialName: str
    quantity: float
    materialUom: str


class ConsumptionData(BaseModel):
    workOrderName: str
    workOrderOperationName: str
    workUnit: str

    consumedMaterials: Optional[List[ConsumedMaterial]] = Field(default_factory=list)
    consumedEnergies: Optional[List[ConsumedEnergy]] = Field(default_factory=list)

    actualStartTime: datetime
    actualEndTime: datetime
    timestamp: datetime

