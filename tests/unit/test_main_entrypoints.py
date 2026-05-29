# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Tests for :func:`app.main._run_server` and Lambda ``handler``."""
from __future__ import annotations

import json

import pytest

from app.config.settings import settings


def test_run_server_uses_tls_when_cert_files_exist(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.main as main

    cert = tmp_path / "test.crt"
    key = tmp_path / "test.key"
    cert.write_text("x", encoding="utf-8")
    key.write_text("y", encoding="utf-8")
    monkeypatch.setattr(main.settings, "ssl_certfile", str(cert))
    monkeypatch.setattr(main.settings, "ssl_keyfile", str(key))

    called: list[dict] = []

    def fake_run(*args, **kwargs) -> None:
        called.append(kwargs)

    monkeypatch.setattr("app.main.uvicorn.run", fake_run)
    main._run_server()
    assert called
    assert called[0]["port"] == settings.port_https
    assert called[0]["ssl_certfile"] == str(cert)
    assert called[0]["ssl_keyfile"] == str(key)


def test_run_server_plain_http_when_no_tls(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Without cert/key files, still bind ``port_https`` with plain HTTP."""
    import app.main as main

    monkeypatch.setattr(main.settings, "ssl_certfile", None)
    monkeypatch.setattr(main.settings, "ssl_keyfile", None)

    called: list[dict] = []

    def fake_run(*args, **kwargs) -> None:
        called.append(kwargs)

    monkeypatch.setattr("app.main.uvicorn.run", fake_run)
    with caplog.at_level("WARNING"):
        main._run_server()
    assert "not TLS" in caplog.text or "HTTP" in caplog.text
    assert called
    assert called[0]["port"] == settings.port_https
    assert "ssl_certfile" not in called[0]


def test_mangum_handler_get_openapi_json() -> None:
    """Smoke-test the AWS Lambda entrypoint against an API Gateway HTTP API v2-shaped event."""
    from app.main import handler

    event = {
        "version": "2.0",
        "routeKey": "GET /openapi.json",
        "rawPath": "/openapi.json",
        "rawQueryString": "",
        "headers": {},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": "/openapi.json",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
            }
        },
        "isBase64Encoded": False,
        "body": None,
    }
    result = handler(event, None)
    assert result["statusCode"] == 200
    body = result["body"]
    if result.get("isBase64Encoded"):
        import base64

        body = base64.b64decode(body).decode("utf-8")
    spec = json.loads(body)
    assert "openapi" in spec
