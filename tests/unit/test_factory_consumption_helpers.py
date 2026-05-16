"""Tests for the helper functions and ``merge_general_consumption`` in
:mod:`app.services.factory_consumption_service`.

Together with :mod:`tests.unit.test_factory_consumption_service` (which covers
the high-level idle-CF allocator) and :mod:`tests.unit.test_idle_allocation`
(which covers the strategy port), these pin the entire factory-DB surface
without writing to ``app/data/``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.services import factory_consumption_service as fcs
from app.models.general_consumption import GeneralConsumptionPayload


# -- pure helpers ---------------------------------------------------------------------


@pytest.mark.parametrize("input_value,expected_iso", [
    (None, None),
    ("2026-01-01T10:00:00Z", "2026-01-01T10:00:00+00:00"),
    (datetime(2026, 1, 1, 10, tzinfo=timezone.utc), "2026-01-01T10:00:00+00:00"),
])
def test_coerce_publication_dt(input_value, expected_iso) -> None:
    out = fcs._coerce_publication_dt(input_value)
    if expected_iso is None:
        assert out is None
    else:
        assert out is not None
        assert out.isoformat() == expected_iso


def test_coerce_publication_dt_returns_none_for_unsupported_types() -> None:
    """Defensive: arbitrary numeric types must not crash this helper."""
    assert fcs._coerce_publication_dt(12345) is None


def test_publication_utc_attaches_utc_when_naive() -> None:
    dt = datetime(2026, 1, 1, 10)
    assert fcs._publication_utc(dt).tzinfo is timezone.utc


def test_publication_utc_converts_to_utc_when_aware() -> None:
    from datetime import timedelta
    tz_plus_2 = timezone(timedelta(hours=2))
    dt = datetime(2026, 1, 1, 12, tzinfo=tz_plus_2)
    out = fcs._publication_utc(dt)
    assert out.tzinfo is timezone.utc
    assert out.hour == 10  # converted from +02:00


# -- _node_total_time / _node_total_idle_time -----------------------------------------


def test_node_total_time_prefers_total_time_over_legacy_field() -> None:
    """Legacy nodes used ``total_duration_minutes``; new nodes use ``total_time``."""
    assert fcs._node_total_time({"total_time": 50, "total_duration_minutes": 999}) == 50.0
    assert fcs._node_total_time({"total_duration_minutes": 30}) == 30.0
    assert fcs._node_total_time({}) == 0.0


def test_node_total_idle_time_prefers_total_idle_time_over_legacy() -> None:
    assert fcs._node_total_idle_time({"total_idle_time": 12}) == 12.0
    assert fcs._node_total_idle_time({"total_idle_time_minutes": 7}) == 7.0
    assert fcs._node_total_idle_time({}) == 0.0


# -- _work_order_minutes_from_node ----------------------------------------------------


def test_work_order_minutes_returns_value_when_key_matches() -> None:
    wo = {"PO_1": 30.0, "PO_2": 5.0}
    assert fcs._work_order_minutes_from_node(wo, "PO_1") == 30.0


def test_work_order_minutes_trims_whitespace_in_keys() -> None:
    wo = {"  PO_1  ": 22.0}
    assert fcs._work_order_minutes_from_node(wo, "PO_1") == 22.0


def test_work_order_minutes_returns_none_for_unparseable_value() -> None:
    wo = {"PO_1": "not-a-number"}
    assert fcs._work_order_minutes_from_node(wo, "PO_1") is None


def test_work_order_minutes_returns_none_for_blank_input() -> None:
    assert fcs._work_order_minutes_from_node({"PO_1": 1}, "") is None
    assert fcs._work_order_minutes_from_node("not-a-dict", "PO_1") is None  # type: ignore[arg-type]


# -- _merge_work_orders_duration ------------------------------------------------------


def test_merge_work_orders_duration_creates_dict_when_missing() -> None:
    node: dict = {}
    fcs._merge_work_orders_duration(node, {"PO_1": 10.0})
    assert node["work_orders_duration"] == {"PO_1": 10.0}


def test_merge_work_orders_duration_accumulates_existing() -> None:
    node = {"work_orders_duration": {"PO_1": 5.0}}
    fcs._merge_work_orders_duration(node, {"PO_1": 7.0, "PO_2": 3.0})
    assert node["work_orders_duration"] == {"PO_1": 12.0, "PO_2": 3.0}


def test_merge_work_orders_duration_no_op_when_incoming_empty() -> None:
    node = {"work_orders_duration": {"PO_1": 1.0}}
    fcs._merge_work_orders_duration(node, None)
    assert node["work_orders_duration"] == {"PO_1": 1.0}


# -- _idle_activity_label disambiguator -----------------------------------------------


def test_idle_activity_label_returns_primary_when_unused() -> None:
    used: set[str] = set()
    label = fcs._idle_activity_label("B1", "M1", "Mill", used)
    assert label == "Idle_Time: Mill (B1)"
    assert label in used


def test_idle_activity_label_falls_back_to_secondary_when_primary_collides() -> None:
    used = {"Idle_Time: Mill (B1)"}
    label = fcs._idle_activity_label("B1", "M2", "Mill", used)
    assert label == "Idle_Time: Mill (B1/M2)"


def test_idle_activity_label_falls_back_to_indexed_when_both_collide() -> None:
    used = {"Idle_Time: Mill (B1)", "Idle_Time: Mill (B1/M3)"}
    label = fcs._idle_activity_label("B1", "M3", "Mill", used)
    assert label.startswith("Idle_Time: Mill (B1/M3) #")


# -- merge_general_consumption (end-to-end happy path) --------------------------------


def _payload(**overrides) -> GeneralConsumptionPayload:
    base = {
        "building_id": "B1",
        "machine_id": "M1",
        "machine_name": "Mill",
        "energy_type": "Electricity",
        "idle_consumption_total": 5.0,
        "prod_consumption_total": 30.0,
        "total_time": 60.0,
        "total_idle_time": 10.0,
        "work_orders_duration": {"PO_1": 25.0},
        "publication_datetime": "2026-01-01T10:00:00Z",
    }
    base.update(overrides)
    return GeneralConsumptionPayload.model_validate(base)


def test_merge_general_consumption_creates_node_on_first_call(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.json"
    out = fcs.merge_general_consumption(db_path, _payload())
    node = out["B1"]["M1"]["electricity"]
    assert node["entry_count"] == 1
    assert node["total_time"] == 60.0
    assert node["work_orders_duration"] == {"PO_1": 25.0}


def test_merge_general_consumption_accumulates_across_calls(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.json"
    fcs.merge_general_consumption(db_path, _payload())
    out = fcs.merge_general_consumption(db_path, _payload(idle_consumption_total=2.0))
    node = out["B1"]["M1"]["electricity"]
    assert node["entry_count"] == 2
    assert node["idle_consumption_total_kwh"] == pytest.approx(7.0)
    assert node["total_time"] == 120.0


def test_merge_general_consumption_keeps_latest_publication_datetime(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.json"
    fcs.merge_general_consumption(db_path, _payload(publication_datetime="2026-01-01T08:00:00Z"))
    out = fcs.merge_general_consumption(
        db_path, _payload(publication_datetime="2026-01-01T12:00:00Z")
    )
    node = out["B1"]["M1"]["electricity"]
    assert node["publication_datetime"].startswith("2026-01-01T12")


def test_merge_general_consumption_building_aggregate_sets_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.json"
    p = GeneralConsumptionPayload.model_validate(
        {
            "total_time": 60.0,
            "total_idle_time": 60.0,
            "building_name": "Hall A",
            "energy_type": "electricity",
            "building_id": "B99",
            "idle_consumption_total": 3.0,
        }
    )
    out = fcs.merge_general_consumption(db_path, p)
    node = out["B99"]["building_idle"]["electricity"]
    assert node["aggregate_scope"] == "building"
    assert node["machine_name"] == "Hall A"


def test_merge_general_consumption_machine_row_omits_aggregate_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "factory.json"
    out = fcs.merge_general_consumption(db_path, _payload())
    node = out["B1"]["M1"]["electricity"]
    assert "aggregate_scope" not in node


def test_load_factory_db_prefers_nonempty_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: do not let S3-first reads shadow a non-empty local factory file."""
    import json

    from app.config.settings import settings

    db_path = tmp_path / "factory.json"
    db_path.write_text(json.dumps({"OnDisk": {"M1": {"electricity": {}}}}), encoding="utf-8")
    monkeypatch.setattr(settings, "factory_database_path", str(db_path))
    monkeypatch.setattr(settings, "factory_database_s3_bucket", "bucket")
    monkeypatch.setattr(settings, "factory_database_s3_key", "key")

    out = fcs._load_factory_db(db_path)
    assert "OnDisk" in out


def test_load_factory_db_empty_file_does_not_resync_stale_s3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After deleting the last building, {} on disk must not trigger S3 restoring ghosts."""
    from unittest.mock import patch

    from app.config.settings import settings
    from app.storage.json_store import JsonStore

    db_path = tmp_path / "factory.json"
    db_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(settings, "factory_database_path", str(db_path))
    monkeypatch.setattr(settings, "factory_database_s3_bucket", "bucket")
    monkeypatch.setattr(settings, "factory_database_s3_key", "key")

    with patch.object(JsonStore, "_read_s3", return_value={"Ghost": {"M": {}}}):
        out = fcs._load_factory_db(db_path)
    assert out == {}
    assert "Ghost" not in out


def test_delete_factory_building_resolves_trimmed_json_key(tmp_path: Path) -> None:
    import json

    db_path = tmp_path / "factory.json"
    db_path.write_text(json.dumps({"  G21_Hall  ": {"M": {"electricity": {}}}}), encoding="utf-8")
    assert fcs.delete_factory_building(db_path, "G21_Hall") is True
    remaining = json.loads(db_path.read_text(encoding="utf-8"))
    assert remaining == {}


def test_merge_general_consumption_drops_legacy_minute_fields(tmp_path: Path) -> None:
    """When a legacy node is loaded, the merger must rename ``*_minutes`` to the new keys."""
    import json

    db_path = tmp_path / "factory.json"
    db_path.write_text(json.dumps({
        "B1": {"M1": {"electricity": {
            "total_duration_minutes": 30,
            "total_idle_time_minutes": 5,
            "idle_consumption_total_kwh": 1.0,
            "prod_consumption_total_kwh": 4.0,
            "work_orders_duration": {},
            "machine_name": "Mill",
            "entry_count": 1,
        }}}
    }), encoding="utf-8")
    out = fcs.merge_general_consumption(db_path, _payload(total_time=10.0, total_idle_time=2.0))
    node = out["B1"]["M1"]["electricity"]
    assert "total_duration_minutes" not in node
    assert "total_idle_time_minutes" not in node
    assert node["total_time"] == 40.0
    assert node["total_idle_time"] == 7.0
