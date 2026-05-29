# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Tests for the S3-mirroring branches of :class:`app.storage.json_store.JsonStore`.

The local-only flows are covered by :mod:`tests.unit.test_json_store` and
:mod:`tests.unit.test_json_store_extras`. This file exercises:

* S3 read branch that falls back to local when S3 returns NoSuchKey.
* S3 read branch that uploads local content when S3 is empty (write-back).
* S3 read branch that retries transient errors then logs a warning.
* :func:`_is_missing_key` heuristic across the documented error shapes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.storage.json_store import JsonStore, _is_missing_key, _s3_client


def _missing_key_exception() -> Exception:
    exc = Exception("nope")
    exc.response = {"Error": {"Code": "NoSuchKey"}}  # type: ignore[attr-defined]
    return exc


def _ok_get_object(payload: bytes) -> dict:
    body = MagicMock()
    body.read.return_value = payload
    return {"Body": body}


def test_load_returns_local_when_s3_returns_missing_key(tmp_path) -> None:
    """``NoSuchKey`` from S3 must promote the local copy to S3 — not crash or wipe."""
    local_path = tmp_path / "store.json"
    local_path.write_text('{"x": 1}', encoding="utf-8")
    fake_client = MagicMock()
    fake_client.get_object.side_effect = _missing_key_exception()
    fake_client.put_object = MagicMock()
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(local_path, s3_bucket="b", s3_key="k", default={"x": 0})
        out = store.load()
    assert out["x"] == 1
    fake_client.put_object.assert_called_once()  # local content uploaded back to S3


def test_load_caches_s3_payload_locally(tmp_path) -> None:
    """A successful S3 read must overwrite the local copy with the canonical payload."""
    local_path = tmp_path / "store.json"
    fake_client = MagicMock()
    fake_client.get_object.return_value = _ok_get_object(b'{"x": 99}')
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(local_path, s3_bucket="b", s3_key="k")
        out = store.load()
    assert out == {"x": 99}
    assert local_path.exists()
    assert '"x": 99' in local_path.read_text(encoding="utf-8")


def test_load_returns_defaults_when_boto3_unavailable(tmp_path, caplog) -> None:
    """If ``boto3`` is not installed, the store must fall back gracefully — no crash."""
    local_path = tmp_path / "store.json"
    with patch("app.storage.json_store._s3_client", return_value=None):
        store = JsonStore(local_path, s3_bucket="b", s3_key="k", default={"x": 0})
        out = store.load()
    assert out == {"x": 0}
    assert any("boto3 unavailable" in r.message for r in caplog.records)


def test_load_handles_empty_s3_payload(tmp_path) -> None:
    fake_client = MagicMock()
    fake_client.get_object.return_value = _ok_get_object(b"")
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(tmp_path / "store.json", s3_bucket="b", s3_key="k", default={"x": 0})
        out = store.load()
    assert out == {"x": 0}


def test_save_writes_to_s3_when_configured(tmp_path) -> None:
    fake_client = MagicMock()
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        store = JsonStore(tmp_path / "store.json", s3_bucket="b", s3_key="k")
        store.save({"x": 7})
    fake_client.put_object.assert_called_once()
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["ContentType"] == "application/json"


def test_save_swallows_s3_errors_after_retry(tmp_path, caplog) -> None:
    fake_client = MagicMock()
    fake_client.put_object.side_effect = RuntimeError("transient")
    with patch("app.storage.json_store._s3_client", return_value=fake_client):
        with patch("app.storage.json_store.time.sleep"):  # speed up retries
            store = JsonStore(tmp_path / "store.json", s3_bucket="b", s3_key="k")
            store.save({"x": 1})  # must not raise
    assert any("Failed to write s3" in r.message for r in caplog.records)


# -- _is_missing_key heuristic ----------------------------------------------------------


@pytest.mark.parametrize("code,expected", [
    ("NoSuchKey", True),
    ("404", True),
    ("NotFound", True),
    ("AccessDenied", False),
    ("", False),
])
def test_is_missing_key_recognises_known_codes(code: str, expected: bool) -> None:
    exc = Exception("x")
    exc.response = {"Error": {"Code": code}}  # type: ignore[attr-defined]
    assert _is_missing_key(exc) is expected


def test_is_missing_key_returns_false_for_exception_without_response() -> None:
    assert _is_missing_key(RuntimeError("plain")) is False


# -- _s3_client lazy import -----------------------------------------------------------


def test_s3_client_returns_none_when_boto3_missing() -> None:
    """Simulate ``import boto3`` raising — function must return None, not propagate."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "boto3":
            raise ImportError("not installed")
        return real_import(name, *a, **k)

    with patch("builtins.__import__", side_effect=fake_import):
        assert _s3_client() is None
