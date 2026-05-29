# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Response

from app.config.settings import settings
from app.services.database_store_service import load_database
from app.services.security_service import verify_basic_auth


router = APIRouter()


@router.get("/data_base_view")
def view_database_pretty(
    auth: bool = Depends(verify_basic_auth),  # noqa: ARG001
) -> Response:
    """Pretty-print the JSON database, protected by basic auth."""

    db_path = Path(settings.database_path)
    content: Any = load_database(db_path)

    pretty_json = json.dumps(content, indent=4)
    html_content = f"<html><body><pre>{pretty_json}</pre></body></html>"
    return Response(content=html_content, media_type="text/html")

