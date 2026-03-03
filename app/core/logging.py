"""Logging setup: terminal stream + in-memory ring buffer for the dashboard log panel."""
from __future__ import annotations

import logging
import sys
import threading
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any

LOGGER_NAME = "pcf_creator_app"


class MemoryLogHandler(logging.Handler):
    """Ring buffer that keeps the last *maxlen* records for the dashboard."""

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._counter = 0

    def emit(self, record: logging.LogRecord) -> None:
        tb = "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else None
        with self._lock:
            self._counter += 1
            self._buffer.append({
                "id": self._counter,
                "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "traceback": tb,
            })

    def get_entries(self, after_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            return [e for e in self._buffer if e["id"] > after_id]


class _FlushingStreamHandler(logging.StreamHandler):
    """StreamHandler that flushes after every emit so logs appear immediately under Lambda/Docker/systemd."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        try:
            self.stream.flush()
        except Exception:
            pass


memory_log_handler = MemoryLogHandler(maxlen=500)


def configure_logging() -> logging.Logger:
    """Configure root logging once. Logs go to stderr and the in-memory ring buffer."""
    stream_handler = _FlushingStreamHandler(sys.stderr)
    stream_handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
        handlers=[stream_handler],
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = True

    if memory_log_handler not in logger.handlers:
        logger.addHandler(memory_log_handler)
    for uv_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uv_name)
        if memory_log_handler not in uv_logger.handlers:
            uv_logger.addHandler(memory_log_handler)
    return logger
