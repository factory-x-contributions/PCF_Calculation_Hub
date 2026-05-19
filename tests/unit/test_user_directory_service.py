"""Tests for :mod:`app.services.user_directory_service`.

The directory holds the Entra allowlist (and admin role assignments). Every
access path matters because it gates the configuration UI: a bug here either
locks legitimate admins out or — worse — lets an unknown principal sign in.

These tests cover:
* Normal CRUD: ``upsert_directory_user`` (insert + update) and ``remove_directory_user``.
* Identity rules: ``is_user_allowed_to_sign_in`` / ``is_user_admin`` for the
  local console user, bootstrap admin emails, directory members, and unknowns.
* Validation: blank email and bad role raise ``ValueError``.
* Bootstrap idempotency: ``ensure_bootstrap_user_record`` adds the row on first
  call but is a no-op on subsequent calls (and on principals who are not bootstrap admins).
* Corrupt persistence: a malformed JSON store must not poison the in-memory directory.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import user_directory_service as uds


@pytest.fixture
def isolated_store(tmp_path, monkeypatch) -> Path:
    """Redirect the JSON store to a temp path with no S3 mirror."""
    path = tmp_path / "users.json"
    monkeypatch.setattr(uds.settings, "allowed_users_path", str(path))
    monkeypatch.setattr(uds.settings, "allowed_users_s3_bucket", "")
    monkeypatch.setattr(uds.settings, "allowed_users_s3_key", "")
    monkeypatch.setattr(uds.settings, "entra_bootstrap_admin_emails", "")
    return path


def test_upsert_and_remove_user(isolated_store: Path) -> None:
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
    assert uds.normalize_email("") == ""
    assert uds.normalize_email(None) == ""  # type: ignore[arg-type]


# -- parse_bootstrap_admin_emails ---------------------------------------------


def test_parse_bootstrap_admin_emails_empty_when_unset(monkeypatch) -> None:
    monkeypatch.setattr(uds.settings, "entra_bootstrap_admin_emails", "  ")
    assert uds.parse_bootstrap_admin_emails() == frozenset()


def test_parse_bootstrap_admin_emails_splits_and_normalises(monkeypatch) -> None:
    monkeypatch.setattr(
        uds.settings,
        "entra_bootstrap_admin_emails",
        "Alice@Example.com, , Bob@Example.com",
    )
    out = uds.parse_bootstrap_admin_emails()
    assert out == frozenset({"alice@example.com", "bob@example.com"})


# -- load_user_directory ------------------------------------------------------


def test_load_user_directory_returns_empty_when_users_field_is_not_list(
    isolated_store: Path,
) -> None:
    isolated_store.write_text(json.dumps({"users": "not-a-list"}), encoding="utf-8")
    data = uds.load_user_directory()
    assert data == {"users": []}


def test_list_directory_users_filters_non_dict_entries(isolated_store: Path) -> None:
    isolated_store.write_text(
        json.dumps({"users": [
            {"email": "good@example.com", "role": "user"},
            "not-a-dict",
            42,
        ]}),
        encoding="utf-8",
    )
    out = uds.list_directory_users()
    assert out == [{"email": "good@example.com", "role": "user"}]


# -- is_user_allowed_to_sign_in / is_user_admin -------------------------------


def test_is_user_allowed_for_local_console_username(isolated_store: Path, monkeypatch) -> None:
    """The local console user is always allowed and always admin."""
    monkeypatch.setattr(uds.settings, "basic_auth_username", "admin")
    assert uds.is_user_allowed_to_sign_in("admin") is True
    assert uds.is_user_admin("admin") is True


def test_is_user_allowed_returns_false_for_blank(isolated_store: Path) -> None:
    assert uds.is_user_allowed_to_sign_in("") is False
    assert uds.is_user_admin("") is False


def test_is_user_allowed_for_bootstrap_admin(isolated_store: Path, monkeypatch) -> None:
    monkeypatch.setattr(uds.settings, "entra_bootstrap_admin_emails", "boss@example.com")
    assert uds.is_user_allowed_to_sign_in("boss@example.com") is True
    assert uds.is_user_admin("boss@example.com") is True


def test_is_user_admin_returns_false_for_directory_user_role(
    isolated_store: Path,
) -> None:
    uds.upsert_directory_user("regular@example.com", role="user")
    assert uds.is_user_allowed_to_sign_in("regular@example.com") is True
    # role=user → not an admin
    assert uds.is_user_admin("regular@example.com") is False


def test_is_user_not_admin_when_not_in_directory(isolated_store: Path) -> None:
    assert uds.is_user_admin("stranger@example.com") is False


# -- upsert_directory_user validation -----------------------------------------


def test_upsert_rejects_blank_email(isolated_store: Path) -> None:
    with pytest.raises(ValueError, match="email required"):
        uds.upsert_directory_user("   ", role="user")


def test_upsert_rejects_bad_role(isolated_store: Path) -> None:
    with pytest.raises(ValueError, match="role must be"):
        uds.upsert_directory_user("user@x", role="superadmin")


def test_upsert_updates_existing_row_in_place(isolated_store: Path) -> None:
    """Calling upsert twice for the same email updates role + display_name but keeps original created_at."""
    first = uds.upsert_directory_user(
        "rotating@example.com", role="user", display_name="First", created_by="admin",
    )
    original_created_at = first["created_at"]
    updated = uds.upsert_directory_user(
        "rotating@example.com", role="admin", display_name="Second", created_by="admin2",
    )
    assert updated["role"] == "admin"
    assert updated["display_name"] == "Second"
    assert updated["created_at"] == original_created_at
    assert len(uds.list_directory_users()) == 1


def test_upsert_defaults_created_by_to_system_when_blank(isolated_store: Path) -> None:
    row = uds.upsert_directory_user("anon@example.com", role="user", created_by="  ")
    assert row["created_by"] == "system"


# -- remove_directory_user ----------------------------------------------------


def test_remove_returns_false_when_user_missing(isolated_store: Path) -> None:
    assert uds.remove_directory_user("ghost@example.com") is False


# -- ensure_bootstrap_user_record --------------------------------------------


def test_ensure_bootstrap_user_record_noop_for_non_bootstrap_email(
    isolated_store: Path, monkeypatch
) -> None:
    """Only emails in ENTRA_BOOTSTRAP_ADMIN_EMAILS should be auto-added; everyone else is left alone."""
    monkeypatch.setattr(uds.settings, "entra_bootstrap_admin_emails", "boss@example.com")
    uds.ensure_bootstrap_user_record("random@example.com", display_name="Random")
    assert uds.list_directory_users() == []


def test_ensure_bootstrap_user_record_adds_admin_on_first_call(
    isolated_store: Path, monkeypatch
) -> None:
    monkeypatch.setattr(uds.settings, "entra_bootstrap_admin_emails", "BOSS@example.com")
    uds.ensure_bootstrap_user_record("Boss@Example.com", display_name="The Boss")
    users = uds.list_directory_users()
    assert len(users) == 1
    assert users[0]["email"] == "boss@example.com"
    assert users[0]["role"] == "admin"


def test_ensure_bootstrap_user_record_is_idempotent(
    isolated_store: Path, monkeypatch
) -> None:
    """Second call for the same bootstrap email must not add a duplicate row."""
    monkeypatch.setattr(uds.settings, "entra_bootstrap_admin_emails", "boss@example.com")
    uds.ensure_bootstrap_user_record("boss@example.com")
    uds.ensure_bootstrap_user_record("boss@example.com")
    assert len(uds.list_directory_users()) == 1

