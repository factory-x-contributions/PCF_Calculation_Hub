# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.core.logging import memory_log_handler
from app.core.protected_pages import serve_protected_html

from app.services.config_service import (
    DEFAULT_SIGREEN_BASE_URL,
    DEFAULT_SIGREEN_TOKEN_URL,
    ensure_sigreen_factory_id,
    get_sigreen_token_url,
    load_app_config,
    save_app_config,
    validate_sigreen_credentials,
)
from app.services.aas_service import (
    _get_aas_interface_from_config,
    get_available_aas_shells,
    process_aas_shells_for_pcf,
)
from app.services.database_store_service import load_database
from app.services.factory_consumption_service import _load_factory_db, delete_factory_building
from app.services.bookkeeping_service import delete_work_order
from app.services.overview_service import build_overview_stats
from app.services.security_service import require_session

router = APIRouter()


@router.get("/config", response_model=None)
def config_page(request: Request):
    """Serve the configuration page when logged in; otherwise redirect to /login."""
    return serve_protected_html(request, "config.html")


@router.get("/work_order_records", response_model=None)
def work_order_records_page(request: Request):
    """Serve the Work Order Records page when logged in; otherwise redirect to /login."""
    return serve_protected_html(request, "work_order_records.html")


@router.get("/factory_energy_distribution", response_model=None)
def factory_energy_distribution_page(request: Request):
    """Serve the Factory Energy Distribution page when logged in; otherwise redirect to /login."""
    return serve_protected_html(request, "factory_energy_distribution.html")


@router.get("/api/factory_energy_distribution")
def get_factory_energy_distribution(
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """Return data_base_factory.json for the Factory Energy Distribution UI."""
    path = Path(settings.factory_database_path)
    data = _load_factory_db(path)
    return JSONResponse(content=data)


@router.delete("/api/factory_energy_distribution/{building_id:path}")
def delete_factory_energy_building(
    building_id: str,
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """Remove all idle consumption data for one building (one key in data_base_factory.json)."""
    db_path = Path(settings.factory_database_path)
    if delete_factory_building(db_path, building_id):
        return JSONResponse(content={"status": "ok", "deleted": building_id})
    return JSONResponse(status_code=404, content={"detail": "Building not found."})


@router.get("/api/data_explorer")
def get_data_explorer(
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """Return the full database JSON for the Data Explorer tree view."""
    db_path = Path(settings.database_path)
    content = load_database(db_path)
    return JSONResponse(content=content)


@router.delete("/api/data_explorer/{work_order_name:path}")
def delete_work_order_record(
    work_order_name: str,
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """Delete a work order record from the database."""
    db_path = Path(settings.database_path)
    if delete_work_order(db_path, work_order_name):
        return JSONResponse(content={"status": "ok", "deleted": work_order_name})
    return JSONResponse(status_code=404, content={"detail": "Work order not found."})


@router.get("/api/overview_stats")
def get_overview_stats(
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """Return summary statistics for the overview dashboard."""
    db_path = Path(settings.database_path)
    db = load_database(db_path)
    return JSONResponse(content=build_overview_stats(db))


@router.get("/api/logs")
def get_logs(
    _: Annotated[str, Depends(require_session)],
    after: int = 0,
) -> JSONResponse:
    """Return recent application log entries. Pass ?after=<id> for incremental polling."""
    entries = memory_log_handler.get_entries(after_id=after)
    return JSONResponse(content={"entries": entries})


@router.get("/api/aas/shells")
def get_aas_shells(
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """List available AAS shells when data source is AAS."""
    result = get_available_aas_shells()
    return JSONResponse(content=result)


@router.post("/api/aas/process_shells")
def post_aas_process_shells(
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """
    When data source is AAS: find available shells, validate BOP (all Ended/Aborted),
    calculate consumption and carbon footprint, create PCF report, submit to SiGREEN.
    Skips shells that already had PCF calculated.
    """
    result = process_aas_shells_for_pcf()
    return JSONResponse(content=result)


@router.get("/api/config")
def get_config(
    _: Annotated[str, Depends(require_session)],
) -> dict[str, Any]:
    """Return current app configuration (Sigreen credentials, etc.). Requires session."""
    ensure_sigreen_factory_id()
    cfg = load_app_config()
    result = dict(cfg)
    if result.get("data_source") == "aas":
        try:
            aasi = _get_aas_interface_from_config()
            if aasi:
                result["aas_status"] = {
                    "aas_type": aasi.aas_type,
                    "aas_base_url": aasi.registry_base_url,
                    "asset_name": aasi.asset_name or "",
                }
            else:
                result["aas_status"] = {"aas_type": "", "aas_base_url": "", "asset_name": ""}
        except Exception:
            result["aas_status"] = {"aas_type": "?", "aas_base_url": "?", "asset_name": "?"}
    return result


@router.post("/api/config")
async def post_config(
    request: Request,
    _: Annotated[str, Depends(require_session)],
) -> JSONResponse:
    """Save app configuration. Requires session. Accepts JSON body with config keys."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"detail": "JSON object expected."})
    allowed = {
        "data_source", "pcf_tool",
        "sigreen_base_url", "sigreen_token_url", "sigreen_client_id", "sigreen_client_secret",
        "sigreen_factory_name", "sigreen_factory_id",
        "sigreen_product_identifier_type",
        "carbon_intensity_source", "carbon_intensity_constant_gco2",
        "pcf_include_bom",
        "aas_base_url", "aas_asset_name", "aas_client_id", "aas_client_secret",
        "aas_type", "aas_check_period_minutes",
    }
    current = load_app_config()
    # Build effective credentials: new values from body, or keep current when blank
    new_id = body.get("sigreen_client_id")
    new_secret = body.get("sigreen_client_secret")
    if new_id is not None:
        new_id = (new_id or "").strip()
    if new_secret is not None:
        new_secret = (new_secret or "").strip()
    effective_id = new_id if (new_id is not None and new_id != "") else current.get("sigreen_client_id", "")
    effective_secret = new_secret if (new_secret is not None and new_secret != "") else current.get("sigreen_client_secret", "")
    new_token_url = body.get("sigreen_token_url")
    if new_token_url is not None:
        new_token_url = (new_token_url or "").strip()
    effective_token_url = (
        new_token_url
        if (new_token_url is not None and new_token_url != "")
        else get_sigreen_token_url(current)
    )
    new_base_url = body.get("sigreen_base_url")
    if new_base_url is not None:
        new_base_url = (new_base_url or "").strip()
    effective_base_url = (
        new_base_url
        if (new_base_url is not None and new_base_url != "")
        else (current.get("sigreen_base_url") or "").strip() or DEFAULT_SIGREEN_BASE_URL
    )

    # If we're changing any Sigreen credential, validate before saving
    sigreen_changed = (
        (new_id is not None and new_id != current.get("sigreen_client_id"))
        or (new_secret is not None and new_secret != "" and new_secret != current.get("sigreen_client_secret"))
    )
    sigreen_oauth_changed = (
        sigreen_changed
        or (new_token_url is not None and new_token_url != get_sigreen_token_url(current))
        or (new_base_url is not None and new_base_url != (current.get("sigreen_base_url") or "").strip())
    )
    if sigreen_oauth_changed:
        if sigreen_changed and (not effective_id or not effective_secret):
            return JSONResponse(
                status_code=400,
                content={"detail": "Client ID and Client Secret are both required for SiGREEN."},
            )
        if effective_id and effective_secret and not validate_sigreen_credentials(
            effective_id,
            effective_secret,
            token_url=effective_token_url,
            base_url=effective_base_url,
        ):
            return JSONResponse(
                status_code=400,
                content={"detail": "The credentials are not correct. Please check the Client ID and Client Secret."},
            )

    for k in allowed:
        v = body.get(k)
        if v is None:
            continue
        if k == "sigreen_client_secret" and v == "":
            continue
        if k == "aas_type" and v not in ("AAS (BaSyx)", "AAS (AssetFox)"):
            v = "AAS (AssetFox)"
        if k == "aas_check_period_minutes":
            try:
                v = max(0.0, min(1440.0, float(v)))
            except (ValueError, TypeError):
                v = 0
        if k == "sigreen_token_url" and isinstance(v, str):
            v = (v or "").strip() or DEFAULT_SIGREEN_TOKEN_URL
        if k == "sigreen_product_identifier_type" and isinstance(v, str):
            v = (v or "Product ID").strip() or "Product ID"
        if k == "carbon_intensity_source" and v not in ("constant", "green_grid_compass"):
            v = "constant"
        if k == "carbon_intensity_constant_gco2":
            try:
                v = max(0.0, float(v))
            except (ValueError, TypeError):
                v = 350
        if k == "pcf_include_bom":
            v = bool(v) if v is not None else True
        current[k] = v
    # When factory name changes, clear old factory_id so we resolve fresh
    if "sigreen_factory_name" in body and body.get("sigreen_factory_name") is not None:
        current["sigreen_factory_id"] = ""
    save_app_config(current)
    # Resolve factory_id from SiGREEN when SiGREEN config was saved
    if any(k in body for k in ("sigreen_client_id", "sigreen_client_secret", "sigreen_token_url", "sigreen_base_url")):
        from app.integrations.sigreen import clear_sigreen_token_cache

        clear_sigreen_token_cache()
    if any(k in body for k in ("sigreen_factory_name", "pcf_tool", "sigreen_base_url", "sigreen_token_url")):
        ensure_sigreen_factory_id()
        current = load_app_config()
    return JSONResponse(content={"status": "ok", "config": current})
