# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Tests for :mod:`app.services.config_service` — the runtime app-config layer."""
from __future__ import annotations

import json

from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import settings
from app.services import config_service


@pytest.fixture
def isolated_config_path(monkeypatch, tmp_path):
    path = tmp_path / "app_config.json"
    monkeypatch.setattr(settings, "app_config_path", str(path))
    return path


def test_load_app_config_returns_defaults_when_file_missing(isolated_config_path) -> None:
    cfg = config_service.load_app_config()
    # DEFAULT_APP_CONFIG keys must all be present in the merged result.
    for key in config_service.DEFAULT_APP_CONFIG:
        assert key in cfg


def test_save_app_config_persists_overrides(isolated_config_path) -> None:
    config_service.save_app_config({"pcf_tool": "sigreen", "carbon_intensity_constant_gco2": 410})
    on_disk = json.loads(isolated_config_path.read_text(encoding="utf-8"))
    assert on_disk["pcf_tool"] == "sigreen"
    assert on_disk["carbon_intensity_constant_gco2"] == 410


def test_get_sigreen_credentials_strips_whitespace(isolated_config_path) -> None:
    config_service.save_app_config(
        {"sigreen_client_id": "  cid  ", "sigreen_client_secret": "  csec  "}
    )
    cid, csec = config_service.get_sigreen_credentials()
    assert cid == "cid"
    assert csec == "csec"


def test_get_sigreen_token_url_falls_back_to_default(isolated_config_path) -> None:
    assert config_service.get_sigreen_token_url() == config_service.DEFAULT_SIGREEN_TOKEN_URL


def test_get_sigreen_token_url_reads_config(isolated_config_path) -> None:
    config_service.save_app_config({"sigreen_token_url": "https://custom.example/token"})
    assert config_service.get_sigreen_token_url() == "https://custom.example/token"


def test_validate_sigreen_credentials_uses_custom_token_url() -> None:
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"access_token": "abc"}
    with patch("app.services.config_service.requests.post", return_value=fake_response) as post:
        assert config_service.validate_sigreen_credentials(
            "id", "secret", token_url="https://custom.example/token"
        ) is True
    assert post.call_args[0][0] == "https://custom.example/token"


def test_validate_sigreen_credentials_uses_explicit_audience_override() -> None:
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"access_token": "abc"}
    with patch("app.services.config_service.requests.post", return_value=fake_response) as post:
        assert config_service.validate_sigreen_credentials(
            "id",
            "secret",
            token_url="https://custom.example/token",
            audience="https://app.sigreen.siemens.com/",
        ) is True
    assert post.call_args[1]["json"]["audience"] == "https://app.sigreen.siemens.com/"


def test_infer_sigreen_audience_from_base_url_prod() -> None:
    assert (
        config_service.infer_sigreen_audience_from_base_url("https://app.sigreen.siemens.com/api")
        == "https://app.sigreen.siemens.com/"
    )


def test_infer_sigreen_audience_from_base_url_uat() -> None:
    assert (
        config_service.infer_sigreen_audience_from_base_url(
            "https://app-uat.sigreen-playground.siemens.cloud/api/"
        )
        == "https://app-uat.sigreen-playground.siemens.cloud/"
    )


def test_get_sigreen_audience_infers_from_config_base_url(isolated_config_path) -> None:
    config_service.save_app_config({"sigreen_base_url": "https://app.sigreen.siemens.com/api"})
    assert config_service.get_sigreen_audience() == "https://app.sigreen.siemens.com/"


def test_validate_sigreen_credentials_infers_audience_from_base_url() -> None:
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"access_token": "abc"}
    with patch("app.services.config_service.requests.post", return_value=fake_response) as post:
        assert config_service.validate_sigreen_credentials(
            "id",
            "secret",
            token_url="https://custom.example/token",
            base_url="https://app.sigreen.siemens.com/api",
        ) is True
    assert post.call_args[1]["json"]["audience"] == "https://app.sigreen.siemens.com/"


def test_validate_sigreen_credentials_rejects_empty() -> None:
    """Missing creds short-circuit before any network call."""
    assert config_service.validate_sigreen_credentials("", "secret") is False
    assert config_service.validate_sigreen_credentials("id", "") is False


def test_validate_sigreen_credentials_returns_false_on_non_200() -> None:
    fake_response = MagicMock(status_code=401)
    with patch("app.services.config_service.requests.post", return_value=fake_response):
        assert config_service.validate_sigreen_credentials("id", "secret") is False


def test_validate_sigreen_credentials_returns_true_on_token() -> None:
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"access_token": "abc"}
    with patch("app.services.config_service.requests.post", return_value=fake_response):
        assert config_service.validate_sigreen_credentials("id", "secret") is True


def test_validate_sigreen_credentials_swallows_network_errors() -> None:
    """Network failure must return False, not propagate the exception."""
    with patch(
        "app.services.config_service.requests.post",
        side_effect=RuntimeError("network down"),
    ):
        assert config_service.validate_sigreen_credentials("id", "secret") is False


def test_ensure_sigreen_factory_id_skips_when_pcf_tool_not_sigreen(isolated_config_path) -> None:
    config_service.save_app_config({"pcf_tool": "other"})
    # Should be a no-op — ensure no SiGREENInterface is constructed.
    with patch("app.integrations.sigreen.SiGREENInterface") as ctor:
        config_service.ensure_sigreen_factory_id()
    ctor.assert_not_called()


def test_ensure_sigreen_factory_id_persists_resolved_id(isolated_config_path) -> None:
    config_service.save_app_config({"pcf_tool": "sigreen", "sigreen_factory_name": "OPC"})
    fake_sigi = MagicMock(factory_id="resolved-9")
    with patch("app.integrations.sigreen.SiGREENInterface", return_value=fake_sigi):
        config_service.ensure_sigreen_factory_id()
    assert config_service.load_app_config()["sigreen_factory_id"] == "resolved-9"
