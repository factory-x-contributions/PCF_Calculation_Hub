# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Additional :class:`app.storage.json_store.JsonStore` cases not covered by the original test file."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.storage.json_store import JsonStore


@pytest.fixture
def store(tmp_path):
    return JsonStore(
        path=tmp_path / "store.json",
        s3_bucket=None,
        s3_key=None,
        default={"version": 1, "items": []},
    )


def test_load_returns_default_when_file_missing(store: JsonStore) -> None:
    out = store.load()
    assert out == {"version": 1, "items": []}


def test_save_then_load_roundtrip(store: JsonStore, tmp_path: Path) -> None:
    store.save({"version": 1, "items": ["a"], "extra": True})
    on_disk = json.loads((tmp_path / "store.json").read_text(encoding="utf-8"))
    assert on_disk["items"] == ["a"]
    reloaded = store.load()
    assert reloaded["extra"] is True


def test_load_merges_defaults_into_partial_persisted_value(store: JsonStore, tmp_path: Path) -> None:
    """Persisted dict missing default keys must come back with the defaults filled in."""
    (tmp_path / "store.json").write_text(json.dumps({"version": 1}), encoding="utf-8")
    out = store.load()
    assert out["items"] == []  # default merged in


def test_load_recovers_from_corrupt_json(store: JsonStore, tmp_path: Path) -> None:
    """A truncated / invalid JSON file must not crash the app — fall back to defaults."""
    (tmp_path / "store.json").write_text("{not json", encoding="utf-8")
    out = store.load()
    assert out == {"version": 1, "items": []}


def test_s3_save_uploads_when_configured(tmp_path) -> None:
    fake_client = MagicMock()
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(
            path=tmp_path / "store.json",
            s3_bucket="my-bucket",
            s3_key="path/store.json",
            default={"x": 1},
        )
        store.save({"x": 2})
    fake_client.put_object.assert_called_once()
    args = fake_client.put_object.call_args.kwargs
    assert args["Bucket"] == "my-bucket"
    assert args["Key"] == "path/store.json"
