# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``app.integrations.aas._normalize_energy_name`` — the canonical map for AAS energy labels."""
from __future__ import annotations

import pytest

from app.integrations.aas import ENERGY_NAME_ALIASES, _normalize_energy_name


@pytest.mark.parametrize("input_name,expected", [
    ("CompressedAir", "CompressedAir"),
    ("Compressed Air", "CompressedAir"),
    ("compressedair", "CompressedAir"),
    ("compressed air", "CompressedAir"),
    ("electricity", "electricity"),
    ("Electricity", "electricity"),
    ("ELECTRICITY", "electricity"),
])
def test_known_variants_map_to_canonical(input_name: str, expected: str) -> None:
    assert _normalize_energy_name(input_name) == expected


def test_unknown_name_returns_stripped_input() -> None:
    assert _normalize_energy_name("  Diesel  ") == "Diesel"


def test_empty_input_returns_input_unchanged() -> None:
    assert _normalize_energy_name("") == ""
    assert _normalize_energy_name(None) is None  # type: ignore[arg-type]


def test_aliases_are_defined_only_once() -> None:
    """Single source of truth — guards against the historical regression where the constant was redeclared 7x."""
    assert set(ENERGY_NAME_ALIASES) == {"CompressedAir", "electricity"}
