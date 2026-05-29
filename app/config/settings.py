# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Application configuration loaded from environment variables.

Single source of truth — import ``settings`` from here, never from ``app.main``.
"""
from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _secure_cookie_default_for(environment: str) -> bool:
    """Use Secure cookies anywhere except local dev (HTTPS is normal off-prem)."""
    return (environment or "").strip().lower() != "local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "PCF Calculation Hub"
    environment: str = "local"
    debug: bool = False

    basic_auth_username: str = Field(default="admin", validation_alias="BASIC_AUTH_USERNAME")
    basic_auth_password: str = Field(default="admin", validation_alias="BASIC_AUTH_PASSWORD")

    session_secret_key: str = Field(default="change-me-in-production", validation_alias="SESSION_SECRET_KEY")
    session_cookie_secure: bool | None = Field(default=None, validation_alias="SESSION_COOKIE_SECURE")
    trust_forwarded_headers: bool = Field(default=False, validation_alias="TRUST_FORWARDED_HEADERS")

    database_path: str = "app/data/data_base.json"
    factory_database_path: str = "app/data/data_base_factory.json"
    factory_database_s3_bucket: str = ""
    factory_database_s3_key: str = ""
    database_s3_bucket: str = ""
    database_s3_key: str = ""
    app_config_path: str = "app/data/app_config.json"
    app_config_s3_bucket: str = ""
    app_config_s3_key: str = ""

    port_https: int = Field(default=8443, validation_alias="PORT_HTTPS")
    ssl_certfile: str | None = None
    ssl_keyfile: str | None = None

    # Microsoft Entra ID (Azure AD) — sign-in with organizational Microsoft accounts
    microsoft_entra_tenant_id: str = Field(default="", validation_alias="MICROSOFT_ENTRA_TENANT_ID")
    microsoft_entra_client_id: str = Field(default="", validation_alias="MICROSOFT_ENTRA_CLIENT_ID")
    microsoft_entra_client_secret: str = Field(default="", validation_alias="MICROSOFT_ENTRA_CLIENT_SECRET")
    # Public origin as seen in the browser (e.g. https://pcf.example.com or https://localhost:8443).
    # Required for OAuth redirect_uri when Microsoft login is enabled.
    public_base_url: str = Field(default="https://localhost:8443", validation_alias="PUBLIC_BASE_URL")
    # Allowlist of users who may sign in with Microsoft (managed via /config Users tab or JSON store).
    allowed_users_path: str = Field(default="app/data/allowed_users.json", validation_alias="ALLOWED_USERS_PATH")
    allowed_users_s3_bucket: str = Field(default="", validation_alias="ALLOWED_USERS_S3_BUCKET")
    allowed_users_s3_key: str = Field(default="", validation_alias="ALLOWED_USERS_S3_KEY")
    # Comma-separated emails: always allowed and receive admin on first login (bootstrap / break-glass).
    entra_bootstrap_admin_emails: str = Field(default="", validation_alias="ENTRA_BOOTSTRAP_ADMIN_EMAILS")
    # When True, /api/auth/login (username/password) remains available even if Entra is configured.
    enable_legacy_password_login: bool = Field(default=True, validation_alias="ENABLE_LEGACY_PASSWORD_LOGIN")

    @model_validator(mode="after")
    def _fill_defaults(self) -> "Settings":
        # Empty BASIC_AUTH_PASSWORD → fall back to "admin" so deployments are usable out of the box
        if not (self.basic_auth_password or "").strip():
            object.__setattr__(self, "basic_auth_password", "admin")
        if self.session_cookie_secure is None:
            object.__setattr__(
                self,
                "session_cookie_secure",
                _secure_cookie_default_for(self.environment),
            )
        return self


settings = Settings()
