# FX TP210 — PCF Calculation Hub (Section 5.2) traceability

This matrix maps **FX_tp210_aggregation_app-v3** themes under **§5.2 PCF Calculation Hub** (User Interface, Configuration, API Reference, Security Concept, Testing, Error Handling) to **implementation modules** and **tests**. Verbatim wording should be reconciled against the controlled Word document when issuing releases.

| Req ID | Topic (spec area) | Implementation | Gap / notes | Test tier |
|--------|-------------------|----------------|-------------|-----------|
| HUB-5.2.1 | User interface (operator-facing pages) | [`app/api/routers/auth.py`](../app/api/routers/auth.py), [`config.py`](../app/api/routers/config.py), [`app/static/`](../app/static/), [`app/core/protected_pages.py`](../app/core/protected_pages.py) | Extend UI only when spec adds fields | simulation / manual |
| HUB-5.2.2 | Configuration (Sigreen, data source, AAS) | [`app/services/config_service.py`](../app/services/config_service.py), [`app/data/app_config.json`](../app/data/app_config.json), env via [`app/config/settings.py`](../app/config/settings.py) | S3 mirror paths in settings | unit (`test_json_store`, config paths), simulation |
| HUB-5.2.3 | API — consumption ingestion | [`app/api/routers/consumption.py`](../app/api/routers/consumption.py), [`app/application/mes_workflow.py`](../app/application/mes_workflow.py), [`app/models/consumption.py`](../app/models/consumption.py) | Routers delegate to application layer | simulation [`tests/simulation/test_api.py`](../tests/simulation/test_api.py), unit bookkeeping |
| HUB-5.2.3 | API — production / PCF finalize | [`app/api/routers/production.py`](../app/api/routers/production.py), [`mes_workflow.py`](../app/application/mes_workflow.py), [`app/services/pcf_service.py`](../app/services/pcf_service.py) | Same | simulation, unit PCF builder |
| HUB-5.2.3 | API — general consumption | [`app/api/routers/general_consumption.py`](../app/api/routers/general_consumption.py) | — | unit model tests |
| HUB-5.2.3 | API — admin / debug views | [`app/api/routers/admin.py`](../app/api/routers/admin.py) | Basic-auth boundary | simulation / integration |
| HUB-5.2.3 | AAS-driven PCF (pull path) | [`app/services/aas_service.py`](../app/services/aas_service.py), [`app/core/lifespan.py`](../app/core/lifespan.py), [`app/application/aas_polling.py`](../app/application/aas_polling.py) | Heavy integration surface | unit (`test_aas*` helpers), live env optional |
| HUB-5.2.4 | Security concept | [`docs/security-concept.md`](security-concept.md), [`app/services/security_service.py`](../app/services/security_service.py), [`app/services/login_rate_limit.py`](../app/services/login_rate_limit.py), [`middleware.py`](../app/core/middleware.py) | Gateway/WAF out of app scope | unit security / rate limit |
| HUB-5.2.5 | Testing strategy | [`pytest.ini`](../pytest.ini), [`tests/unit/`](../tests/unit/), [`tests/simulation/`](../tests/simulation/), [`tests/integration/`](../tests/integration/), [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Integration tier needs `LIVE_BASE_URL` | CI runs unit + simulation |
| HUB-5.2.6 | Error handling | [`app/core/middleware.py`](../app/core/middleware.py) (422 handler), router `HTTPException`, logging | Align external error JSON with spec tables if extended | simulation asserts 400/422 |

## SiGREEN client construction (cross-cutting)

| Req ID | Topic | Implementation |
|--------|-------|----------------|
| HUB-SIG-1 | Emission submission (MES path, factory refresh) | [`app/services/sigreen_factory.py`](../app/services/sigreen_factory.py) — `build_sigreen_for_emissions()` |
| HUB-SIG-2 | Material BOM lookup | `build_sigreen_for_material_lookup()` |
| HUB-SIG-3 | AAS batch pipeline (cached factory id) | `build_sigreen_for_aas_pipeline()` |

## Exit criterion

Each row has an **owned module** and **test tier**; gaps marked **N/A / future** should be updated when the Word specification adds normative requirements.
