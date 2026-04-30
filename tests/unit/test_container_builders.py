"""Cover :mod:`app.core.container` builder functions."""
from __future__ import annotations

from unittest.mock import patch

from app.core import container as container_mod


def test_build_material_pcf_fetcher_delegates_with_log_label() -> None:
    with patch("app.services.material_pcf.fetch_material_pcf_map") as fetch:
        fetch.return_value = {"mat": 0.1}
        fn = container_mod.build_material_pcf_fetcher()
        out = fn([{"materialId": "mat"}])
    assert out == {"mat": 0.1}
    fetch.assert_called_once()
    assert fetch.call_args.kwargs.get("log_label") == "SiGREEN"


def test_build_app_config_loader_returns_load_app_config() -> None:
    with patch("app.services.config_service.load_app_config") as load:
        load.return_value = {"carbon_intensity_source": "constant"}
        fn = container_mod.build_app_config_loader()
        assert fn() == load.return_value
        load.assert_called_once()


def test_build_aas_pcf_processor_returns_process_fn() -> None:
    with patch("app.services.aas_service.process_aas_shells_for_pcf") as proc:
        proc.return_value = {"processed": 0}
        fn = container_mod.build_aas_pcf_processor()
        assert fn() == {"processed": 0}
        proc.assert_called_once()
