"""Simulation-tier fixtures: isolate JSON DB paths under tmp_path per test."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import settings


@pytest.fixture(autouse=True)
def _simulation_isolated_database_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid writing bookkeeping JSON under ``app/data/`` during TestClient runs."""
    base = tmp_path / "sim_db"
    base.mkdir(parents=True, exist_ok=True)
    db = base / "data_base.json"
    factory = base / "data_base_factory.json"
    monkeypatch.setattr(settings, "database_path", str(db))
    monkeypatch.setattr(settings, "factory_database_path", str(factory))
