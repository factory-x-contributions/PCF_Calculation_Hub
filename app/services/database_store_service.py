"""Work-order JSON database read/write. Backed by ``JsonStore`` (local + optional S3 mirror)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.storage import JsonStore


def _store(path: Path) -> JsonStore:
    return JsonStore(path, s3_bucket=settings.database_s3_bucket, s3_key=settings.database_s3_key)


def load_database(path: Path) -> dict[str, Any]:
    """Load the work-order database. S3 wins over local when configured."""
    return _store(path).load()


def save_database(path: Path, data: dict[str, Any]) -> None:
    """Persist the work-order database locally and to S3 (when configured)."""
    _store(path).save(data)
