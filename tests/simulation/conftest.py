# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Simulation-tier fixtures: isolated DB paths and offline SiGREEN."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from app.config.settings import settings
from tests.simulation.sigreen_mock import DEFAULT_PRODUCT_UUID, patch_sigreen


@pytest.fixture(autouse=True)
def _simulation_isolated_database_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid writing bookkeeping JSON under ``app/data/`` during TestClient runs."""
    base = tmp_path / "sim_db"
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "database_path", str(base / "data_base.json"))
    monkeypatch.setattr(settings, "factory_database_path", str(base / "data_base_factory.json"))


@pytest.fixture
def mock_sigreen() -> Iterator[MagicMock]:
    """Offline SiGREEN client for endpoints that submit factory emissions."""
    with patch_sigreen(product_uuid=DEFAULT_PRODUCT_UUID) as sigi:
        yield sigi
