"""Unit tests for :func:`app.services.overview_service.build_overview_stats`.

This is the function that the ``/api/overview_stats`` router calls
(Phase 1 routed it through here instead of inlining its own copy).
The fixtures below drive both the legacy ``BOP`` schema and the
structured ``operations`` schema so the two code branches stay
covered as the format evolves.
"""
from __future__ import annotations

import pytest

from app.services.overview_service import build_overview_stats


@pytest.fixture
def legacy_db() -> dict:
    """One work order in the legacy ``BOP`` numeric-mapping format with a final PCF."""
    return {
        "PO_LEGACY": {
            "BOP": {"OP10": 100.0, "OP20": 50.0},
            "BOM": {"Aluprofil-001": {"total_quantity": 150.0, "uom": "mm"}},
            "pcf": {
                "productCarbonFootprint": 175.0,
                "factory": "OPC",
                "batch": {"batchNumber": "B-1", "quantity": 10},
                "emissions": [{"emissionUnit": "kgCO2e/piece", "primaryDataShare": 0.95}],
            },
            "product_name": "Legacy Engine Block",
        }
    }


@pytest.fixture
def structured_db() -> dict:
    """One work order in the new ``operations`` format with split-by-type energy."""
    return {
        "PO_NEW": {
            "operations": {
                "OP10-Fraesen": {
                    "energy": {
                        "Electricity": {"carbon_footprint_kg": 39.7, "total_consumption": 113.4, "uom": "kWh"},
                        "CompressedAir": {"carbon_footprint_kg": 0.21, "total_consumption": 5.0, "uom": "M3"},
                    }
                },
                "OP20-Drilling": {
                    "energy": {
                        "Electricity": {"carbon_footprint_kg": 12.3, "total_consumption": 34.0, "uom": "kWh"},
                    }
                },
            },
            "materials": {
                "Screw_M6": {
                    "total_quantity": 50.0,
                    "uom": "piece",
                    "carbon_footprint_kg": 5.0,
                }
            },
            "pcf": {
                "productCarbonFootprint": 57.21,
                "factory": "OPC",
                "batch": {"batchNumber": "B-2", "quantity": 5},
                "emissions": [{"emissionUnit": "kgCO2e/piece", "primaryDataShare": 1.0}],
            },
            "product_name": "Bracket",
        }
    }


def test_empty_database_returns_zero_totals() -> None:
    stats = build_overview_stats({})
    assert stats["work_order_count"] == 0
    assert stats["total_operations"] == 0
    assert stats["total_materials"] == 0
    assert stats["total_energy_kwh"] == 0.0
    assert stats["total_carbon_footprint_kg"] == 0.0
    assert stats["pcf_count"] == 0
    assert stats["latest_pcf_work_order"] is None
    assert stats["work_orders"] == []
    assert stats["products"] == []


def test_legacy_bop_summed_into_carbon_footprint(legacy_db: dict) -> None:
    """Legacy schema has no consumption telemetry; only CF must be summed (consumption stays 0)."""
    stats = build_overview_stats(legacy_db)
    assert stats["work_order_count"] == 1
    assert stats["total_operations"] == 2
    assert stats["total_materials"] == 1
    assert stats["total_energy_kwh"] == 0.0  # legacy BOP has no consumption
    assert stats["total_carbon_footprint_kg"] == pytest.approx(150.0)
    assert stats["pcf_count"] == 1
    assert stats["latest_pcf_work_order"] == "PO_LEGACY"
    assert stats["latest_pcf_value"] == pytest.approx(175.0)


def test_structured_format_sums_energy_and_cf(structured_db: dict) -> None:
    stats = build_overview_stats(structured_db)
    assert stats["work_order_count"] == 1
    assert stats["total_operations"] == 2
    assert stats["total_materials"] == 1
    # 113.4 + 5.0 + 34.0 = 152.4 kWh
    assert stats["total_energy_kwh"] == pytest.approx(152.4)
    # 39.7 + 0.21 + 12.3 = 52.21 kg
    assert stats["total_carbon_footprint_kg"] == pytest.approx(52.21)
    assert stats["pcf_count"] == 1
    assert stats["work_orders"][0]["name"] == "PO_NEW"
    assert stats["work_orders"][0]["operations"] == 2


def test_products_section_only_includes_work_orders_with_pcf() -> None:
    """A WO without a finalized PCF must not appear in the ``products`` section."""
    db = {
        "PO_PENDING": {
            "operations": {"OP10": {"energy": {"Electricity": {"carbon_footprint_kg": 1.0}}}},
            "materials": {},
            # no "pcf" key
        },
        "PO_DONE": {
            "operations": {"OP10": {"energy": {"Electricity": {"carbon_footprint_kg": 2.0}}}},
            "materials": {},
            "pcf": {
                "productCarbonFootprint": 2.0,
                "factory": "OPC",
                "batch": {"batchNumber": "B-3", "quantity": 1},
                "emissions": [{"emissionUnit": "kgCO2e/piece"}],
            },
            "product_name": "X",
        },
    }
    stats = build_overview_stats(db)
    assert stats["pcf_count"] == 1
    assert {p["work_order"] for p in stats["products"]} == {"PO_DONE"}


def test_products_section_carries_factory_and_batch_metadata(structured_db: dict) -> None:
    stats = build_overview_stats(structured_db)
    assert len(stats["products"]) == 1
    product = stats["products"][0]
    assert product["work_order"] == "PO_NEW"
    assert product["product_name"] == "Bracket"
    assert product["factory"] == "OPC"
    assert product["batch_number"] == "B-2"
    assert product["quantity"] == 5
    assert product["emission_unit"] == "kgCO2e/piece"
    assert product["primary_data_share"] == 1.0


def test_legacy_pcf_field_uppercase_is_recognized() -> None:
    """Some older fixtures store the report under ``PCF`` (uppercase) instead of ``pcf``."""
    db = {
        "PO_OLD": {
            "operations": {},
            "materials": {},
            "PCF": {
                "productCarbonFootprint": 99.0,
                "factory": "OPC",
                "batch": {},
                "emissions": [],
            },
        }
    }
    stats = build_overview_stats(db)
    assert stats["pcf_count"] == 1
    assert stats["latest_pcf_value"] == pytest.approx(99.0)
    assert any(p["work_order"] == "PO_OLD" for p in stats["products"])


def test_pcf_with_null_value_does_not_count(structured_db: dict) -> None:
    """A ``pcf`` dict with ``productCarbonFootprint=None`` must not bump pcf_count."""
    db = dict(structured_db)
    db["PO_PENDING"] = {
        "operations": {},
        "materials": {},
        "pcf": {"productCarbonFootprint": None, "factory": "", "batch": {}, "emissions": []},
    }
    stats = build_overview_stats(db)
    # Only PO_NEW counts
    assert stats["pcf_count"] == 1
