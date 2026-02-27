"""Typed shapes for PCF bills and reports sent to SiGREEN.

These match the dicts ``SiGREENInterface.create_process_bill`` and ``create_PCF_report`` build,
so existing call sites keep working unchanged while new code gets static typing.
"""
from __future__ import annotations

from typing import TypedDict


class PCFBill(TypedDict, total=False):
    typeOfActivity: str
    total: float
    primaryDataShare: float
    shareOnTotal: float
    emissionUnit: str
    comment: str
    fossil: float
    biogenic: float
    dLuc: float
    landUse: float
    aircraft: float


class PCFBatch(TypedDict, total=False):
    batchNumber: str
    quantity: float
    assessmentYear: int
    dataSource: str
    comment: str


# 'from' is a Python keyword, so use the functional form for TypedDict.
PCFReport = TypedDict(
    "PCFReport",
    {
        "revision": str,
        "factoryId": str,
        "factory": str,
        "from": str,  # ISO timestamp, e.g. "2024-01-01T00:00:00.000Z"
        "to": str,
        "batch": PCFBatch,
        "productCarbonFootprint": float,
        "emissions": list[PCFBill],
        "comment": str,
        "sourceSystem": str,
    },
    total=False,
)
