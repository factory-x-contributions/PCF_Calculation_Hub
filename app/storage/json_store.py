# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Single JSON-on-disk store with optional S3 mirror.

Replaces three near-identical implementations that previously lived inline in
``database_store_service``, ``config_service`` and ``factory_consumption_service``.

Behaviour:
  * On read: prefer S3 (when configured); fall back to local; sync local↔S3 in either direction.
  * On write: always write local; write S3 too when configured.
  * boto3 is imported lazily so the package stays optional in non-AWS envs.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("pcf_creator_app")

JsonDict = dict[str, Any]


class JsonStore:
    def __init__(
        self,
        path: str | Path,
        *,
        s3_bucket: str | None = None,
        s3_key: str | None = None,
        default: JsonDict | None = None,
    ) -> None:
        self.path = Path(path)
        self.bucket = (s3_bucket or "").strip()
        self.key = (s3_key or "").strip()
        self._default: JsonDict = dict(default or {})

    # ------------------------------------------------------------------
    # Public API

    def load(self) -> JsonDict:
        if self._uses_s3():
            from_s3 = self._read_s3()
            if from_s3 is not None:
                self._write_local(from_s3)
                return self._with_defaults(from_s3)
            from_local = self._read_local()
            if from_local:
                self._write_s3(from_local)
            return self._with_defaults(from_local)
        return self._with_defaults(self._read_local())

    def save(self, data: JsonDict, *, require_local_write: bool = False) -> None:
        """Persist ``data``. When ``require_local_write`` is True, local IO errors propagate."""
        if require_local_write:
            self._write_local_impl(data)
        else:
            self._write_local(data)
        if self._uses_s3():
            self._write_s3(data)

    # ------------------------------------------------------------------
    # Internals

    def _uses_s3(self) -> bool:
        return bool(self.bucket and self.key)

    def _with_defaults(self, data: JsonDict) -> JsonDict:
        return {**self._default, **data} if self._default else dict(data)

    def _read_local(self) -> JsonDict:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", self.path, exc)
            return {}

    def _write_local(self, data: JsonDict) -> None:
        try:
            self._write_local_impl(data)
        except OSError as exc:
            logger.warning("Failed to write %s: %s", self.path, exc)

    def _write_local_impl(self, data: JsonDict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def _read_s3(self) -> JsonDict | None:
        client = _s3_client()
        if client is None:
            logger.warning("S3 configured for %s but boto3 unavailable; using local file.", self.path)
            return None
        for attempt in range(3):
            try:
                resp = client.get_object(Bucket=self.bucket, Key=self.key)
                payload = resp["Body"].read()
                return json.loads(payload.decode("utf-8")) if payload else {}
            except Exception as exc:
                if _is_missing_key(exc):
                    return None
                if attempt < 2:
                    time.sleep(1.5 ** attempt)
                else:
                    logger.warning("Failed to read s3://%s/%s: %s", self.bucket, self.key, exc)
        return None

    def _write_s3(self, data: JsonDict) -> None:
        client = _s3_client()
        if client is None:
            return
        for attempt in range(3):
            try:
                client.put_object(
                    Bucket=self.bucket,
                    Key=self.key,
                    Body=json.dumps(data, indent=4).encode("utf-8"),
                    ContentType="application/json",
                )
                return
            except Exception as exc:
                if attempt < 2:
                    time.sleep(1.5 ** attempt)
                else:
                    logger.warning("Failed to write s3://%s/%s: %s", self.bucket, self.key, exc)


def _s3_client():
    try:
        import boto3  # type: ignore
        from botocore.config import Config  # type: ignore
    except Exception:
        return None
    return boto3.client(
        "s3",
        config=Config(retries={"mode": "adaptive", "max_attempts": 4}, connect_timeout=10, read_timeout=30),
    )


def _is_missing_key(exc: Exception) -> bool:
    """Tell apart 'object not present' from real S3 errors so callers can fall back to defaults."""
    try:
        code = (getattr(exc, "response", {}) or {}).get("Error", {}).get("Code", "")
    except Exception:
        code = ""
    return code in {"NoSuchKey", "404", "NotFound"}
