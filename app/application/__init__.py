# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Application layer: orchestration use cases that wire domain + services.

Public re-exports stay shallow so callers can write
``from app.application import ProductionUseCase`` without remembering the
sub-module layout.
"""

from app.application.use_cases.consumption_use_case import ConsumptionUseCase
from app.application.use_cases.production_use_case import (
    MissingConsumptionForWorkOrderError,
    ProductionUseCase,
)

__all__ = [
    "ConsumptionUseCase",
    "MissingConsumptionForWorkOrderError",
    "ProductionUseCase",
]
