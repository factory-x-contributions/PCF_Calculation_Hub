"""Exercise ``/static/*`` and ``/docs`` from :mod:`app.core.static`."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_root_returns_reachability_json(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"]


def test_static_serves_existing_file(client: TestClient) -> None:
    response = client.get("/static/swagger-logo.css")
    assert response.status_code == 200
    assert "text/css" in response.headers.get("content-type", "")


def test_static_rejects_path_outside_static_dir(client: TestClient) -> None:
    response = client.get("/static/../../README.md")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_static_returns_404_for_missing_file(client: TestClient) -> None:
    response = client.get("/static/no_such_asset_file_xyz.css")
    assert response.status_code == 404


def test_docs_returns_swagger_html(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_docs_inserts_base_href_when_stage_prefix_non_empty(client: TestClient) -> None:
    with patch("app.core.static.stage_prefix", return_value="/staging"):
        response = client.get("/docs")
    assert response.status_code == 200
    assert 'href="/staging/"' in response.text


def test_docs_injects_about_banner(client: TestClient) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "About this API" in response.text


def test_docs_fallback_when_regex_misses(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """``re.subn`` may not match some Swagger templates; the ``str.replace`` path still injects the banner."""
    from starlette.responses import Response

    import app.core.static as static_mod

    compact = b'<html><body><div id="swagger-ui"></div></body></html>'

    def fake_swagger(**_kwargs):
        return Response(content=compact, media_type="text/html")

    def subn_no_match(pattern: str, repl: str, string: str, count: int = 0, flags: int = 0) -> tuple[str, int]:
        return string, 0

    monkeypatch.setattr(static_mod, "get_swagger_ui_html", fake_swagger)
    monkeypatch.setattr(static_mod.re, "subn", subn_no_match)
    response = client.get("/docs")
    assert response.status_code == 200
    assert "About this API" in response.text
