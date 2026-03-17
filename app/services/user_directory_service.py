"""Persisted allowlist of Microsoft-sign-in users and their admin roles.

Stored as JSON (optional S3 mirror), editable from the configuration UI by admins.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.storage import JsonStore

logger = logging.getLogger("pcf_creator_app")

DEFAULT_STORE: dict[str, Any] = {"users": []}


def _store() -> JsonStore:
    return JsonStore(
        Path(settings.allowed_users_path),
        s3_bucket=settings.allowed_users_s3_bucket,
        s3_key=settings.allowed_users_s3_key,
        default=DEFAULT_STORE,
    )


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def parse_bootstrap_admin_emails() -> frozenset[str]:
    raw = (settings.entra_bootstrap_admin_emails or "").strip()
    if not raw:
        return frozenset()
    out: set[str] = set()
    for part in raw.split(","):
        e = normalize_email(part)
        if e:
            out.add(e)
    return frozenset(out)


def load_user_directory() -> dict[str, Any]:
    data = _store().load()
    users = data.get("users")
    if not isinstance(users, list):
        return {"users": []}
    return {"users": users}


def save_user_directory(data: dict[str, Any]) -> None:
    _store().save(data)


def _find_user_index(users: list[dict[str, Any]], email: str) -> int:
    target = normalize_email(email)
    for i, u in enumerate(users):
        if normalize_email(str(u.get("email", ""))) == target:
            return i
    return -1


def list_directory_users() -> list[dict[str, Any]]:
    users = load_user_directory().get("users") or []
    return [u for u in users if isinstance(u, dict)]


def _local_console_username() -> str:
    """Same defaulting rules as :func:`app.services.security_service._effective_username` (no import to avoid cycles)."""
    v = (settings.basic_auth_username or "").strip()
    return v if v else "admin"


def is_user_allowed_to_sign_in(principal: str) -> bool:
    """Return True if *principal* may have an active session (local username or Microsoft email)."""
    import secrets

    local_user = _local_console_username()
    if principal and secrets.compare_digest((principal or "").strip(), local_user):
        return True
    norm = normalize_email(principal)
    if not norm:
        return False
    if norm in parse_bootstrap_admin_emails():
        return True
    for u in list_directory_users():
        if normalize_email(str(u.get("email", ""))) == norm:
            return True
    return False


def is_user_admin(principal: str) -> bool:
    import secrets

    if not principal:
        return False
    local_user = _local_console_username()
    if secrets.compare_digest((principal or "").strip(), local_user):
        return True
    norm = normalize_email(principal)
    if norm in parse_bootstrap_admin_emails():
        return True
    for u in list_directory_users():
        if normalize_email(str(u.get("email", ""))) == norm:
            role = (u.get("role") or "user").strip().lower()
            return role == "admin"
    return False


def upsert_directory_user(
    email: str,
    *,
    role: str,
    display_name: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    """Add or update a user row. *role* is ``admin`` or ``user``."""
    data = load_user_directory()
    users: list[dict[str, Any]] = list(data.get("users") or [])
    norm = normalize_email(email)
    if not norm:
        raise ValueError("email required")
    r = role.strip().lower()
    if r not in ("admin", "user"):
        raise ValueError("role must be admin or user")
    idx = _find_user_index(users, norm)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    row: dict[str, Any] = {
        "email": norm,
        "role": r,
        "display_name": (display_name or "").strip(),
        "created_at": now,
        "created_by": (created_by or "").strip() or "system",
    }
    if idx >= 0:
        row["created_at"] = users[idx].get("created_at") or row["created_at"]
        users[idx] = {**users[idx], **row}
    else:
        users.append(row)
    save_user_directory({"users": users})
    return users[idx] if idx >= 0 else users[-1]


def remove_directory_user(email: str) -> bool:
    data = load_user_directory()
    users: list[dict[str, Any]] = list(data.get("users") or [])
    norm = normalize_email(email)
    new_list = [u for u in users if normalize_email(str(u.get("email", ""))) != norm]
    if len(new_list) == len(users):
        return False
    save_user_directory({"users": new_list})
    return True


def ensure_bootstrap_user_record(email: str, *, display_name: str = "") -> None:
    """Ensure an Entra bootstrap admin exists in the directory (idempotent)."""
    norm = normalize_email(email)
    if norm not in parse_bootstrap_admin_emails():
        return
    data = load_user_directory()
    users: list[dict[str, Any]] = list(data.get("users") or [])
    if _find_user_index(users, norm) >= 0:
        return
    upsert_directory_user(norm, role="admin", display_name=display_name, created_by="bootstrap")
