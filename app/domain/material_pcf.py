# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Typed material PCF shapes used by SiGREEN lookups.

A material PCF can come back as the bare total (legacy) or as production+distribution stages.
``MaterialPCF`` is the canonical shape; ``MaterialPCFMap`` is what services pass around.
"""
from __future__ import annotations

from typing import TypedDict


class MaterialPCF(TypedDict, total=False):
    total: float
    production: float
    distribution: float


MaterialPCFMap = dict[str, MaterialPCF]
