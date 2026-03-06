"""Static-file serving and Swagger UI customization for both EC2 and Lambda deployments."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.config.settings import settings
from app.core.stage_prefix import stage_prefix

_ABOUT_BANNER_HTML = (
    '<div id="pcf-docs-about" style="margin:0 0 1rem;padding:1rem 1.25rem;background:#fff;'
    'border:1px solid rgba(59,130,246,.3);border-radius:8px;font-size:14px;line-height:1.6;color:#333">'
    '<h3 style="margin:0 0 0.5rem;font-size:1rem">About this API</h3>'
    '<p style="margin:0 0 0.5rem">REST API for production and consumption data, Product Carbon Footprint (PCF) computation, '
    'and SiGREEN integration. Ingest consumption data from MES or AAS, calculate carbon footprints, and submit PCF reports to SiGREEN.</p>'
    '<p style="margin:0;font-size:13px;color:#555">Developed by <strong>Alireza Ranjbar</strong> within the <strong>Factory-X</strong> project.</p>'
    '</div>'
)


def install_static_routes(app: FastAPI) -> None:
    """Mount /static and a Swagger UI customised with our branding."""
    static_dir = (Path(__file__).resolve().parent.parent / "static").resolve()

    @app.get("/static/{path:path}", include_in_schema=False)
    async def serve_static(path: str):
        file_path = (static_dir / path).resolve()
        if not str(file_path).startswith(str(static_dir)) or not file_path.is_file():
            return JSONResponse(content={"detail": "Not Found"}, status_code=404)
        return FileResponse(file_path)

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html(request: Request):
        stage = stage_prefix()
        openapi_url = "openapi.json" if stage else app.openapi_url
        swagger_css_url = "static/swagger-logo.css" if stage else "/static/swagger-logo.css"
        response = get_swagger_ui_html(
            openapi_url=openapi_url,
            title=f"{settings.app_name} - Swagger UI",
            swagger_css_url=swagger_css_url,
        )
        body = response.body.decode("utf-8")
        if stage:
            body = body.replace("<head>", f'<head>\n  <base href="{stage}/">', 1)
        about_script = (
            '<div id="swagger-ui"></div>'
            '<script>(function(){var c=document.getElementById("swagger-ui");if(c){var a=document.createElement("div");'
            f"a.innerHTML='{_ABOUT_BANNER_HTML}';"
            'c.parentNode.insertBefore(a.firstChild,c);}})();</script>'
        )
        body, n = re.subn(
            r'<div\s+id="swagger-ui"\s*>\s*</div>',
            about_script,
            body,
            count=1,
        )
        if n == 0:
            body = body.replace('<div id="swagger-ui"></div>', about_script, 1)
        return HTMLResponse(content=body)
