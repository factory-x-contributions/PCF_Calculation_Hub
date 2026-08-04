# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for grid CO2 API helpers (requests mocked)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.grid import (
    GridInterface,
    enforce_time_resolution,
)

_TEST_GRID_CLIENT_ID = "test-grid-client-id"
_TEST_GRID_CLIENT_SECRET = "test-grid-client-secret"


def _grid() -> GridInterface:
    return GridInterface(client_id=_TEST_GRID_CLIENT_ID, client_secret=_TEST_GRID_CLIENT_SECRET)


def test_enforce_time_resolution_string_inputs_extends_window() -> None:
    s = "2026-01-01T10:00:00Z"
    e = "2026-01-01T10:05:00Z"
    out_s, out_e = enforce_time_resolution(s, e, m=30)
    assert out_s.startswith("2026-01-01T10:00:00")
    assert out_e.endswith("Z")


def test_enforce_time_resolution_datetime_already_wide() -> None:
    s = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
    e = s + timedelta(hours=2)
    out_s, out_e = enforce_time_resolution(s, e, m=30)
    assert "2026-01-01T10:00:00" in out_s
    assert "2026-01-01T12:00:00" in out_e


def test_get_token_uses_cache_before_expiry() -> None:
    """Once primed, repeated get_token calls must not re-hit the IdP within the TTL window."""
    gi = _grid()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "cached-token", "expires_in": 3600}
    mock_resp.raise_for_status = MagicMock()
    with patch("app.integrations.oauth_token_cache.requests.post", return_value=mock_resp) as post:
        assert gi.get_token() == "cached-token"
        assert gi.get_token() == "cached-token"  # second call hits the cache
        post.assert_called_once()


def test_get_token_fetches_and_stores_cache() -> None:
    gi = _grid()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"access_token": "new-tok", "expires_in": 3600}
    mock_resp.raise_for_status = MagicMock()
    with patch("app.integrations.oauth_token_cache.requests.post", return_value=mock_resp) as post:
        tok = gi.get_token()
    assert tok == "new-tok"
    post.assert_called_once()


def test_get_token_cache_refresh_when_near_expiry() -> None:
    """When the cached token is past its leeway window, the next get_token must fetch fresh credentials."""
    gi = _grid()
    # Inject a deterministic clock so 'now' jumps across the leeway boundary in one test.
    fake_clock = MagicMock(side_effect=[0.0, 100_000.0])
    gi._token_cache._clock = fake_clock  # only-test surface on the TokenCache
    responses = [
        MagicMock(json=MagicMock(return_value={"access_token": "old", "expires_in": 900}), raise_for_status=MagicMock()),
        MagicMock(json=MagicMock(return_value={"access_token": "fresh", "expires_in": 900}), raise_for_status=MagicMock()),
    ]
    with patch("app.integrations.oauth_token_cache.requests.post", side_effect=responses):
        first = gi.get_token()
        second = gi.get_token()
    assert first == "old"
    assert second == "fresh"


def test_get_co2_coeff_list_empty_payload() -> None:
    """Missing or empty ``measurements`` must yield an empty coefficient list."""
    gi = _grid()
    with patch.object(gi, "get_carbon_data", return_value={}):
        assert gi.get_co2_coeff_list("2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z") == []


def test_get_carbon_data_and_coeff_list() -> None:
    gi = _grid()
    payload = {
        "measurements": [
            {"measurementValues": [{"value": 10.0}, {"value": None}, {"value": 20.0}]},
            {"measurementValues": []},
        ]
    }
    with patch.object(gi, "get_token", return_value="t"):
        with patch("app.integrations.grid.requests.get") as get:
            get.return_value.json.return_value = payload
            data = gi.get_carbon_data("2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z", zone="DE_LU")
            assert data == payload
            coeffs = gi.get_co2_coeff_list("2026-01-01T00:00:00Z", "2026-01-01T02:00:00Z")
    assert coeffs == [10.0, 20.0]
    get.assert_called()
    assert get.call_args[1]["headers"]["Authorization"] == "Bearer t"


def test_average_carbon_value_mean_and_empty() -> None:
    gi = _grid()
    data = {"measurements": [{"measurementValues": [{"value": 100.0}, {"value": 200.0}]}]}
    assert gi.average_carbon_value(data) == 150.0
    assert gi.average_carbon_value({"measurements": []}) is None


def test_get_avg_carbon_coeff() -> None:
    gi = _grid()
    with patch.object(gi, "get_carbon_data", return_value={"measurements": []}):
        assert gi.get_avg_carbon_coeff("a", "b") is None
