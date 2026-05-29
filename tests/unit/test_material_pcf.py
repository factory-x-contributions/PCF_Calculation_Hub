# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``app.services.material_pcf``: SiGREEN lookup + breakdown math."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.material_pcf import (
    fetch_material_pcf_map,
    material_breakdown_for,
)


def _config(**overrides):
    base = {
        "pcf_tool": "sigreen",
        "pcf_include_bom": True,
        "material_identifier_mapping": {},
    }
    base.update(overrides)
    return base


@pytest.fixture
def sigi_with(materials_returning):
    sigi = MagicMock()
    sigi.get_material_pcf_per_unit_kg.side_effect = lambda ident: materials_returning.get(ident)
    return sigi


def test_returns_empty_when_no_materials() -> None:
    assert fetch_material_pcf_map([]) == {}


def test_skips_when_pcf_tool_not_sigreen() -> None:
    with patch("app.services.material_pcf.load_app_config", return_value=_config(pcf_tool="other")):
        assert fetch_material_pcf_map(["A"], sigi=MagicMock()) == {}


def test_skips_when_pcf_include_bom_disabled() -> None:
    with patch("app.services.material_pcf.load_app_config", return_value=_config(pcf_include_bom=False)):
        assert fetch_material_pcf_map(["A"], sigi=MagicMock()) == {}


@pytest.mark.parametrize("materials_returning", [
    {"A": {"total": 1.0, "production": 0.7, "distribution": 0.3}},
])
def test_uses_identifier_when_no_mapping(sigi_with) -> None:
    with patch("app.services.material_pcf.load_app_config", return_value=_config()):
        result = fetch_material_pcf_map(["A"], sigi=sigi_with)
    assert result == {"A": {"total": 1.0, "production": 0.7, "distribution": 0.3}}


@pytest.mark.parametrize("materials_returning", [
    {"SIGREEN_ID": {"total": 2.0, "production": 1.5, "distribution": 0.5}},
])
def test_applies_identifier_mapping(sigi_with) -> None:
    """Result is keyed by the *original* MES identifier, not the mapped SiGREEN ID."""
    cfg = _config(material_identifier_mapping={"MES_CODE": "SIGREEN_ID"})
    with patch("app.services.material_pcf.load_app_config", return_value=cfg):
        result = fetch_material_pcf_map(["MES_CODE"], sigi=sigi_with)
    assert "MES_CODE" in result
    assert result["MES_CODE"]["total"] == 2.0


@pytest.mark.parametrize("materials_returning", [{"A": None}])
def test_skips_materials_without_pcf_data(sigi_with) -> None:
    with patch("app.services.material_pcf.load_app_config", return_value=_config()):
        assert fetch_material_pcf_map(["A"], sigi=sigi_with) == {}


def test_material_breakdown_computes_per_material_and_total() -> None:
    materials = {
        "M1": {"quantity": 2.0, "unit": "piece"},
        "M2": {"quantity": 3.0, "unit": "kg"},
    }
    pcf_map = {
        "M1": {"total": 1.5, "production": 1.0, "distribution": 0.5},
        "M2": {"total": 2.0},  # no stages
    }
    breakdown, total = material_breakdown_for(materials, pcf_map)

    assert total == pytest.approx(2.0 * 1.5 + 3.0 * 2.0)
    assert breakdown["M1"]["carbon_footprint_kg"] == pytest.approx(3.0)
    assert breakdown["M1"]["carbon_footprint_per_unit"] == 1.5
    assert breakdown["M1"]["carbon_footprint_production_per_unit"] == 1.0
    assert breakdown["M1"]["carbon_footprint_distribution_per_unit"] == 0.5
    assert breakdown["M2"]["carbon_footprint_kg"] == pytest.approx(6.0)
    assert "carbon_footprint_production_per_unit" not in breakdown["M2"]


def test_material_breakdown_skips_unknown_materials() -> None:
    materials = {"M1": {"quantity": 1.0, "unit": "piece"}}
    breakdown, total = material_breakdown_for(materials, pcf_map={})
    assert breakdown == {}
    assert total == 0.0


def test_returns_empty_when_sigi_factory_returns_none() -> None:
    """If no explicit ``sigi`` is given AND the factory returns None (SiGREEN unconfigured),
    the function must return an empty map without raising — callers cope by skipping BOM."""
    with patch("app.services.material_pcf.load_app_config", return_value=_config()):
        with patch(
            "app.services.material_pcf.build_sigreen_for_material_lookup",
            return_value=None,
        ):
            assert fetch_material_pcf_map(["A"]) == {}


def test_skips_blank_identifiers() -> None:
    """Materials with empty identifiers must not be looked up — protects against bad MES rows."""
    sigi = MagicMock()
    sigi.get_material_pcf_per_unit_kg.return_value = {"total": 1.0}
    with patch("app.services.material_pcf.load_app_config", return_value=_config()):
        result = fetch_material_pcf_map(["   ", "", None], sigi=sigi)
    assert result == {}
    sigi.get_material_pcf_per_unit_kg.assert_not_called()


def test_swallows_lookup_exception_and_skips_material(caplog) -> None:
    """A SiGREEN error on one material must not abort the whole lookup — log & skip."""
    sigi = MagicMock()
    sigi.get_material_pcf_per_unit_kg.side_effect = [
        RuntimeError("502 bad gateway"),
        {"total": 1.0, "production": 0.7, "distribution": 0.3},
    ]
    with patch("app.services.material_pcf.load_app_config", return_value=_config()):
        result = fetch_material_pcf_map(["BadOne", "GoodOne"], sigi=sigi)
    assert "BadOne" not in result
    assert result.get("GoodOne", {}).get("total") == 1.0
    assert any("PCF lookup failed" in r.message for r in caplog.records)


def test_returns_empty_when_identifier_mapping_is_not_dict() -> None:
    """Defensive: a corrupt ``material_identifier_mapping`` (non-dict) must collapse to an empty mapping."""
    sigi = MagicMock()
    sigi.get_material_pcf_per_unit_kg.return_value = {"total": 1.0}
    cfg = _config(material_identifier_mapping="not-a-dict")
    with patch("app.services.material_pcf.load_app_config", return_value=cfg):
        result = fetch_material_pcf_map(["A"], sigi=sigi)
    # Mapping is dropped, original key is used as-is
    assert "A" in result
