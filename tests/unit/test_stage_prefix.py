"""Unit tests for ``app.core.stage_prefix.prepare_static_html_for_stage``.

The current rewriter has a known quirk: the strip-already-prefixed pass also strips its own
just-injected ``<base href>``, leaving ``<base href="">``. ``<base href="">`` resolves to the
document URL per HTML spec, so the page still works because the *next* pass turns all absolute
paths into relative ones (which the browser then resolves against the document URL). These
tests pin the *current behavior* — they would also catch any future change that stops
producing relative paths under a stage.
"""
from __future__ import annotations

from contextlib import contextmanager

from app.config.settings import settings as _settings
from app.core.stage_prefix import prepare_static_html_for_stage, stage_prefix


@contextmanager
def _override_environment(env: str):
    """Temporarily override settings.environment (Pydantic v2 BaseSettings is mutable by default)."""
    original = _settings.environment
    _settings.environment = env
    try:
        yield
    finally:
        _settings.environment = original


def test_local_environment_returns_html_unchanged() -> None:
    with _override_environment("local"):
        assert stage_prefix() == ""
        html = "<html><head></head><body><a href='/api/foo'></a></body></html>"
        assert prepare_static_html_for_stage(html) == html


def test_dev_stage_resolves_to_dev() -> None:
    with _override_environment("dev"):
        assert stage_prefix() == "/dev"


def test_dev_stage_makes_absolute_paths_relative() -> None:
    """Production correctness rests on this: under a stage, ``src="/static/x"`` becomes ``src="static/x"``."""
    with _override_environment("dev"):
        out = prepare_static_html_for_stage(
            '<html><head></head><body><script src="/static/foo.js"></script></body></html>'
        )
        assert 'src="/static/foo.js"' not in out
        assert 'src="static/foo.js"' in out


def test_dev_stage_strips_existing_stage_prefix() -> None:
    """``/dev/static/foo`` must not become ``/dev/dev/static/foo``."""
    with _override_environment("dev"):
        out = prepare_static_html_for_stage(
            '<html><head></head><body><script src="/dev/static/foo.js"></script></body></html>'
        )
        assert "/dev/dev/" not in out
        assert 'src="static/foo.js"' in out


def test_dev_stage_rewrites_api_fetches_to_relative() -> None:
    with _override_environment("dev"):
        out = prepare_static_html_for_stage(
            "<html><head></head><body><script>fetch('/api/foo')</script></body></html>"
        )
        assert "fetch('api/foo')" in out
        assert "fetch('/api/foo')" not in out
