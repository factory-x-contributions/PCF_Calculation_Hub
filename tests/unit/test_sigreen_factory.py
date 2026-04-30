"""Tests for :mod:`app.services.sigreen_factory` — the single SiGREEN construction site.

Phase 3 made this module the only place that knows how to construct a
``SiGREENInterface``. These tests pin the three factory functions:

* :func:`build_sigreen_for_emissions` — always re-resolves factory_id.
* :func:`build_sigreen_for_material_lookup` — returns ``None`` when SiGREEN is disabled.
* :func:`build_sigreen_for_aas_pipeline` — uses the cached factory_id from config.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import sigreen_factory


@pytest.fixture(autouse=True)
def _stub_sigreen_interface():
    """Replace the real SiGREENInterface ctor so the tests don't make HTTPS calls."""
    fake_class = MagicMock()
    fake_class.return_value = MagicMock(factory_id="resolved-id")
    with patch("app.integrations.sigreen.SiGREENInterface", fake_class):
        yield fake_class


def test_build_for_emissions_re_resolves_factory_id(_stub_sigreen_interface) -> None:
    """The emissions factory always calls ``ensure_sigreen_factory_id`` so a stale cached id is refreshed."""
    with patch("app.services.sigreen_factory.ensure_sigreen_factory_id") as ensure:
        with patch(
            "app.services.sigreen_factory.load_app_config",
            return_value={"sigreen_factory_name": "OPC", "sigreen_base_url": "https://x"},
        ):
            sigi = sigreen_factory.build_sigreen_for_emissions()

    ensure.assert_called_once()
    assert sigi is not None


def test_build_for_material_lookup_returns_none_when_pcf_tool_not_sigreen(
    _stub_sigreen_interface,
) -> None:
    """When the operator selected a non-SiGREEN PCF tool, no client is constructed."""
    with patch(
        "app.services.sigreen_factory.load_app_config",
        return_value={"pcf_tool": "other"},
    ):
        result = sigreen_factory.build_sigreen_for_material_lookup()
    assert result is None


def test_build_for_material_lookup_returns_client_when_sigreen_selected(
    _stub_sigreen_interface,
) -> None:
    with patch(
        "app.services.sigreen_factory.load_app_config",
        return_value={"pcf_tool": "sigreen", "sigreen_factory_name": "OPC"},
    ):
        result = sigreen_factory.build_sigreen_for_material_lookup()
    assert result is not None


def test_build_for_aas_pipeline_uses_cached_factory_id_from_config(
    _stub_sigreen_interface,
) -> None:
    """The AAS pipeline reuses the cached factory_id for performance — verify it's passed through."""
    with patch("app.services.sigreen_factory.ensure_sigreen_factory_id"):
        with patch(
            "app.services.sigreen_factory.load_app_config",
            return_value={
                "sigreen_factory_name": "OPC",
                "sigreen_factory_id": "cached-id",
                "sigreen_base_url": "https://x",
            },
        ):
            sigreen_factory.build_sigreen_for_aas_pipeline()

    # The class was called with factory_id="cached-id", not None.
    call_kwargs = _stub_sigreen_interface.call_args.kwargs
    assert call_kwargs["factory_id"] == "cached-id"


def test_build_for_aas_pipeline_logs_warning_when_factory_id_unresolved(
    _stub_sigreen_interface, caplog
) -> None:
    """Unresolved factory_id is non-fatal but must surface a warning so the operator notices."""
    _stub_sigreen_interface.return_value.factory_id = ""
    with patch("app.services.sigreen_factory.ensure_sigreen_factory_id"):
        with patch(
            "app.services.sigreen_factory.load_app_config",
            return_value={"sigreen_factory_name": "OPC"},
        ):
            sigreen_factory.build_sigreen_for_aas_pipeline()
    assert any("factory_id not resolved" in r.message for r in caplog.records)


def test_default_factory_name_when_config_missing(_stub_sigreen_interface) -> None:
    with patch("app.services.sigreen_factory.ensure_sigreen_factory_id"):
        with patch("app.services.sigreen_factory.load_app_config", return_value={}):
            sigreen_factory.build_sigreen_for_emissions()
    call_kwargs = _stub_sigreen_interface.call_args.kwargs
    assert call_kwargs["factory_name"] == "OPC"
