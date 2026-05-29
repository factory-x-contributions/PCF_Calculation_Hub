# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`app.services.pcf_service` — SiGREEN orchestration for the MES path.

The hot path is :func:`get_or_create_product_uuid` which has three branches:

1. Product exists → returns ``(uuid, False)``.
2. Product missing (404) → creates and returns ``(uuid, True)``.
3. Product missing AND ``factory_id`` blank → raises (operator must configure SiGREEN).

Plus a retry/re-lookup behaviour for the SiGREEN race where create returns 500 even
though the product exists.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services import pcf_service


def _http_error(status_code: int) -> requests.HTTPError:
    response = MagicMock()
    response.status_code = status_code
    return requests.HTTPError("boom", response=response)


def test_get_or_create_returns_existing_uuid() -> None:
    sigi = MagicMock(factory_id="f1")
    sigi.get_product_uuid.return_value = "existing-uuid"
    uuid, created = pcf_service.get_or_create_product_uuid(sigi, "P1")
    assert uuid == "existing-uuid"
    assert created is False
    sigi.create_product.assert_not_called()


def test_get_or_create_creates_when_404() -> None:
    sigi = MagicMock(factory_id="f1")
    sigi.get_product_uuid.side_effect = _http_error(404)
    sigi.create_product.return_value = "new-uuid"
    uuid, created = pcf_service.get_or_create_product_uuid(sigi, "P1")
    assert uuid == "new-uuid"
    assert created is True
    sigi.create_product.assert_called_once()


def test_get_or_create_raises_when_factory_id_missing() -> None:
    sigi = MagicMock(factory_id="")
    sigi.get_product_uuid.side_effect = _http_error(404)
    with pytest.raises(RuntimeError, match="factory_id not configured"):
        pcf_service.get_or_create_product_uuid(sigi, "P1")


def test_get_or_create_wraps_unknown_http_error_as_runtime_error() -> None:
    """Anything that isn't a 404 must surface as a RuntimeError describing the product_id."""
    sigi = MagicMock(factory_id="f1")
    sigi.get_product_uuid.side_effect = _http_error(500)
    with pytest.raises(RuntimeError, match="SiGREEN get_product_uuid failed"):
        pcf_service.get_or_create_product_uuid(sigi, "P1")


def test_get_or_create_retries_create_and_relooks_up_on_failure() -> None:
    """SiGREEN race: create raises but the product is actually there — re-lookup wins."""
    sigi = MagicMock(factory_id="f1")
    # First get returns None (404), then create blows up; re-lookup returns a real uuid.
    sigi.get_product_uuid.side_effect = [_http_error(404), "found-on-relookup"]
    sigi.create_product.side_effect = RuntimeError("create blew up")
    with patch("app.services.pcf_service.time.sleep"):  # don't actually sleep in tests
        uuid, created = pcf_service.get_or_create_product_uuid(sigi, "P1")
    assert uuid == "found-on-relookup"
    assert created is False


def test_get_or_create_wraps_unexpected_exception_as_runtime_error() -> None:
    """A non-HTTPError exception (e.g. ConnectionError) on lookup must surface as RuntimeError —
    callers want a single, well-typed error and a product_id in the message."""
    sigi = MagicMock(factory_id="f1")
    sigi.get_product_uuid.side_effect = ConnectionError("network down")
    with pytest.raises(RuntimeError, match="SiGREEN get_product_uuid failed"):
        pcf_service.get_or_create_product_uuid(sigi, "P1")


def test_get_or_create_swallows_relookup_exception_during_retry() -> None:
    """If create *and* re-lookup both raise on every attempt, the function still surfaces the
    create error wrapped in RuntimeError — it must not propagate the re-lookup error."""
    sigi = MagicMock(factory_id="f1")
    sigi.get_product_uuid.side_effect = [
        _http_error(404),       # initial lookup
        RuntimeError("boom1"),  # re-lookup attempt 1
        RuntimeError("boom2"),  # re-lookup attempt 2
        RuntimeError("boom3"),  # re-lookup attempt 3
    ]
    sigi.create_product.side_effect = RuntimeError("create blew up")
    with patch("app.services.pcf_service.time.sleep"):
        with pytest.raises(RuntimeError, match="create_product failed"):
            pcf_service.get_or_create_product_uuid(sigi, "P1")


def test_submit_factory_emissions_calls_send_with_resolved_uuid() -> None:
    fake_sigi = MagicMock(factory_id="f1")
    fake_sigi.get_product_uuid.return_value = "uuid-x"
    with patch("app.services.pcf_service._get_sigreen", return_value=fake_sigi):
        result = pcf_service.submit_factory_emissions(product_id="P1", pcf_report={"x": 1})
    assert result == "uuid-x"
    fake_sigi.send_factory_emissions.assert_called_once_with(
        product_uuid="uuid-x", PCF_report={"x": 1}
    )
