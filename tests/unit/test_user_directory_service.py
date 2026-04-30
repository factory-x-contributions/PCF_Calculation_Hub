"""Tests for :mod:`app.services.user_directory_service`."""
from __future__ import annotations

from pathlib import Path

from app.services import user_directory_service as uds


def test_upsert_and_remove_user(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(uds.settings, "allowed_users_path", str(tmp_path / "users.json"))
    data = uds.load_user_directory()
    assert data["users"] == []
    uds.upsert_directory_user("User@Example.com", role="admin", created_by="bootstrap")
    again = uds.load_user_directory()["users"]
    assert len(again) == 1
    assert again[0]["email"] == "user@example.com"
    assert again[0]["role"] == "admin"
    assert uds.is_user_admin("user@example.com") is True
    assert uds.is_user_allowed_to_sign_in("user@example.com") is True
    assert uds.remove_directory_user("User@Example.com") is True
    assert uds.list_directory_users() == []


def test_normalize_email() -> None:
    assert uds.normalize_email("  A@B.C ") == "a@b.c"
