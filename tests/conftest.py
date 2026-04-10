"""Shared pytest fixtures for the PCF Creator API test suite.

Provides:
- ``client``: a session-scoped FastAPI ``TestClient``.
- ``reset_database``: removes both the work-order DB and the factory DB before a test runs
  (the factory DB carried PO-allocation rows from previous test runs and polluted PCF totals
  in any test that didn't explicitly clean it).
- ``get_stored_pcf``: factory fixture returning a callable that reads
  ``productCarbonFootprint`` for a given work-order from the JSON DB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Iterator, Optional

import pytest
from fastapi.testclient import TestClient

from app.config.settings import settings
from app.main import app


def _delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def reset_database() -> None:
    _delete_if_exists(Path(settings.database_path))
    _delete_if_exists(Path(settings.factory_database_path))


@pytest.fixture
def get_stored_pcf() -> Callable[[str], Optional[float]]:
    def _get(work_order: str) -> Optional[float]:
        db_path = Path(settings.database_path)
        if not db_path.exists():
            return None
        with db_path.open("r", encoding="utf-8") as f:
            db = json.load(f)
        record = db.get(work_order) or {}
        pcf = record.get("pcf") or {}
        return pcf.get("productCarbonFootprint")

    return _get
