"""Best-effort failed-login throttling (in-process; use a gateway WAF for production scale)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_LOCK = threading.Lock()
_FAILED_ATTEMPTS: dict[str, list[float]] = defaultdict(list)

_WINDOW_SEC = 60.0
_MAX_FAILURES = 15


def failed_login_exceeds_rate_limit(client_id: str) -> bool:
    """Record one failed login and return True if the client should receive HTTP 429."""
    now = time.monotonic()
    cutoff = now - _WINDOW_SEC
    with _LOCK:
        bucket = _FAILED_ATTEMPTS[client_id]
        while bucket and bucket[0] < cutoff:
            bucket.pop(0)
        bucket.append(now)
        return len(bucket) > _MAX_FAILURES
