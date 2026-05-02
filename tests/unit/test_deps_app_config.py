"""Cover :func:`app.api.deps.get_app_config`."""
from __future__ import annotations

from unittest.mock import patch

from app.api.deps import get_app_config


def test_get_app_config_returns_snapshot_from_loader() -> None:
    with patch("app.services.config_service.load_app_config", return_value={"x": 1}):
        assert get_app_config() == {"x": 1}
