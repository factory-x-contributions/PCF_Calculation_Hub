"""Unit tests for GeneralConsumptionPayload model_validator (rates)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.general_consumption import BUILDING_IDLE_MACHINE_ID, GeneralConsumptionPayload


def test_alias_total_duration_populates_total_time() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "Total_duration": 120.0,
            "total_idle_time": 30.0,
            "machine_id": "m1",
            "energy_type": "electricity",
            "machine_name": "M1",
            "building_id": "b1",
            "idle_consumption_total": 10.0,
        }
    )
    assert p.total_time == 120.0


def test_computed_idle_and_prod_rates_when_omitted() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 10.0,
            "machine_id": "m1",
            "energy_type": "electricity",
            "machine_name": "M1",
            "building_id": "b1",
            "idle_consumption_total": 5.0,
            "prod_consumption_total": 15.0,
        }
    )
    assert p.idle_consumption_rate == pytest.approx(5.0)
    assert p.prod_consumption_rate == pytest.approx(15.0)


def test_rates_zero_when_total_time_zero() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 0.0,
            "total_idle_time": 0.0,
            "machine_id": "m1",
            "energy_type": "electricity",
            "machine_name": "M1",
            "building_id": "b1",
            "idle_consumption_total": 5.0,
            "prod_consumption_total": 3.0,
        }
    )
    assert p.idle_consumption_rate == 0.0
    assert p.prod_consumption_rate == 0.0


def test_explicit_rates_skip_validator_updates() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 10.0,
            "machine_id": "m1",
            "energy_type": "electricity",
            "machine_name": "M1",
            "building_id": "b1",
            "idle_consumption_total": 5.0,
            "idle_consumption_rate": 1.5,
            "prod_consumption_total": 0.0,
            "prod_consumption_rate": 2.5,
        }
    )
    assert p.idle_consumption_rate == 1.5
    assert p.prod_consumption_rate == 2.5


def test_publication_datetime_alias() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 0.0,
            "machine_id": "m1",
            "energy_type": "electricity",
            "machine_name": "M1",
            "building_id": "b1",
            "idle_consumption_total": 1.0,
            "Publication_datetime": "2026-03-26T14:30:00.000Z",
        }
    )
    assert p.publication_datetime == datetime(2026, 3, 26, 14, 30, tzinfo=timezone.utc)


def test_building_level_idle_fills_reserved_machine_key_and_name() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 1380.5853,
            "total_idle_time": 1380.5853,
            "building_name": "G21_Hall",
            "energy_type": "electricity",
            "building_id": "G21_Hall",
            "idle_consumption_total": 12.37044,
            "idle_consumption_rate": 0.53762,
            "publication_datetime": "2026-05-16T14:08:56.100Z",
        }
    )
    assert p.machine_id == BUILDING_IDLE_MACHINE_ID
    assert p.machine_name == "G21_Hall"


def test_building_level_idle_display_fallback_to_building_id() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 60.0,
            "energy_type": "electricity",
            "building_id": "B-hall-1",
            "idle_consumption_total": 1.0,
        }
    )
    assert p.machine_id == BUILDING_IDLE_MACHINE_ID
    assert p.machine_name == "B-hall-1"


def test_only_machine_name_replicates_as_id() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 0.0,
            "energy_type": "electricity",
            "machine_name": "Mill-A",
            "building_id": "b1",
            "idle_consumption_total": 1.0,
        }
    )
    assert p.machine_id == "Mill-A"
    assert p.machine_name == "Mill-A"


def test_only_machine_id_replicates_as_name() -> None:
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 0.0,
            "energy_type": "electricity",
            "machine_id": "M-001",
            "building_id": "b1",
            "idle_consumption_total": 1.0,
        }
    )
    assert p.machine_id == "M-001"
    assert p.machine_name == "M-001"
