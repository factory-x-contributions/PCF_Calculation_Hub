# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for ``app.storage.JsonStore``: local IO, defaults, missing-file behaviour, S3 mirror."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.storage import JsonStore


@pytest.fixture
def tmp_json_path(tmp_path):
    return tmp_path / "store.json"


def test_load_returns_empty_when_missing(tmp_json_path) -> None:
    assert JsonStore(tmp_json_path).load() == {}


def test_load_applies_defaults(tmp_json_path) -> None:
    tmp_json_path.write_text(json.dumps({"b": 2}), encoding="utf-8")
    store = JsonStore(tmp_json_path, default={"a": 1, "b": 0})
    assert store.load() == {"a": 1, "b": 2}


def test_load_returns_empty_when_invalid_json(tmp_json_path) -> None:
    tmp_json_path.write_text("{ not json", encoding="utf-8")
    assert JsonStore(tmp_json_path).load() == {}


def test_save_then_load_roundtrip(tmp_json_path) -> None:
    store = JsonStore(tmp_json_path)
    store.save({"hello": "world"})
    assert JsonStore(tmp_json_path).load() == {"hello": "world"}


def test_save_creates_parent_directory(tmp_path) -> None:
    nested = tmp_path / "deep" / "nested" / "store.json"
    JsonStore(nested).save({"k": "v"})
    assert nested.exists()


def test_save_require_local_write_propagates_io_error(tmp_json_path) -> None:
    store = JsonStore(tmp_json_path)
    with patch("app.storage.json_store.json.dump", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            store.save({"a": 1}, require_local_write=True)


def test_save_default_swallows_local_io_error(tmp_json_path) -> None:
    store = JsonStore(tmp_json_path)
    with patch("app.storage.json_store.json.dump", side_effect=OSError("denied")):
        store.save({"a": 1})


def test_s3_read_overrides_local(tmp_json_path) -> None:
    """When configured for S3, the store mirrors S3 onto the local file before returning."""
    tmp_json_path.write_text(json.dumps({"local": True}), encoding="utf-8")
    fake_client = MagicMock()
    fake_client.get_object.return_value = {"Body": MagicMock(read=lambda: json.dumps({"s3": True}).encode())}
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(tmp_json_path, s3_bucket="b", s3_key="k")
        assert store.load() == {"s3": True}
    assert json.loads(tmp_json_path.read_text(encoding="utf-8")) == {"s3": True}


def test_s3_missing_key_falls_back_to_local(tmp_json_path) -> None:
    """A NoSuchKey from S3 must not raise — the local file is used instead."""
    tmp_json_path.write_text(json.dumps({"only": "local"}), encoding="utf-8")
    fake_client = MagicMock()
    err = Exception()
    err.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
    fake_client.get_object.side_effect = err
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(tmp_json_path, s3_bucket="b", s3_key="k")
        assert store.load() == {"only": "local"}
    fake_client.put_object.assert_called_once()  # local was synced back to S3


def test_save_writes_local_and_s3(tmp_json_path) -> None:
    fake_client = MagicMock()
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        JsonStore(tmp_json_path, s3_bucket="b", s3_key="k").save({"x": 1})
    assert json.loads(tmp_json_path.read_text(encoding="utf-8")) == {"x": 1}
    fake_client.put_object.assert_called_once()
