"""When deployed behind API Gateway with a stage path (e.g. /dev), rewrite static HTML so all relative URLs resolve under the stage."""
from __future__ import annotations

from app.config.settings import settings


def stage_prefix() -> str:
    """Return '/dev' (etc.) in deployed stages, '' for local."""
    return f"/{settings.environment}" if settings.environment != "local" else ""


_PROTECTED_PATHS = ("/api/", "/config", "/login", "/work_order_records", "/factory_energy_distribution")


def prepare_static_html_for_stage(html: str) -> str:
    """Inject ``<base href="/stage/">`` and rewrite absolute paths so the page works under any stage."""
    prefix = stage_prefix()
    if not prefix:
        return html
    html = html.replace("<head>", f'<head>\n  <base href="{prefix}/">', 1)

    # Strip stage prefix already in src/href (e.g. /dev/static/ → static/) to avoid double prefixes
    prefix_slash = prefix + "/"
    html = html.replace(f'="{prefix_slash}', '="').replace(f"='{prefix_slash}", "='")
    # Make remaining absolute paths relative
    html = html.replace('="/', '="').replace("='/", "='")
    html = html.replace(' ="/', '="').replace(" ='/", "='")
    # Rewrite fetch('/api/...') / location.href='/config' etc. so they resolve under <base href>
    for path in _PROTECTED_PATHS:
        bare = path.lstrip("/")
        # Bare-path use ('/config', '/login', ...) — match the closing quote so we don't grab '/api'
        if not path.endswith("/"):
            html = html.replace(f"'{path}'", f"'{bare}'").replace(f'"{path}"', f'"{bare}"')
        # Path-with-suffix use (fetch('/api/foo'), navigate('/config/sub'), ...) — match the next char as part of bare
        html = html.replace(f"'{path}", f"'{bare}").replace(f'"{path}', f'"{bare}')
    return html
