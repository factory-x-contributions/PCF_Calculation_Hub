<!-- SPDX-FileCopyrightText: Copyright Siemens 2026 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
# PCF Calculation Hub

[![Tests](https://github.com/a-z-e-r-i-l-a/PCF-Calculation-Hub/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/a-z-e-r-i-l-a/PCF-Calculation-Hub/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/a-z-e-r-i-l-a/PCF-Calculation-Hub/graph/badge.svg?token=z4U9odxE8M)](https://codecov.io/github/a-z-e-r-i-l-a/PCF-Calculation-Hub)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE.txt)
[![Built by a-z-e-r-i-l-a](https://img.shields.io/badge/Built%20by-a--z--e--r--i--l--a-5865F2?style=flat)](https://github.com/a-z-e-r-i-l-a)

**Beta version**

The PCF Calculation Hub is a cloud-oriented service that ingests manufacturing consumption and production data, computes product carbon footprint (PCF) reports, and submits structured results to **SiGREEN** when configured.

Its purpose is not to duplicate shopfloor aggregation. It sits **northbound** of systems that already tie energy to operations—MES pushes, AAS-backed flows, or edge aggregators such as the [IIH Aggregator Wizard](https://github.com/a-z-e-r-i-l-a/IIH_Aggregator_Wizard)—and turns that structured input into bookkeeping, carbon-intensity handling, optional material PCF enrichment, and PCF submission workflows.

## Purpose

Product carbon footprinting needs consumption linked to **work orders**, **operations**, and **machines**, plus a clear split between production and non-production energy where factories track it. This hub provides the **calculation and persistence layer**: REST endpoints for consumption and production events, optional S3-backed JSON stores for cloud deployments, SiGREEN-facing PCF reporting, and a browser-based configuration UI.

The app supports both common Factory-X / Catena-X shopfloor patterns:

| Scenario | Production context | Role of this hub |
|----------|-------------------|------------------|
| **MES-driven manufacturing** | A Manufacturing Execution System (e.g. Opcenter-X) orchestrates orders; MES or middleware POSTs consumption and production payloads. | Stores operations and materials per work order, applies carbon-intensity strategy, allocates idle energy when factory consumption data is supplied, submits PCF to SiGREEN when enabled. |
| **MES-less (AAS-driven) manufacturing** | Work orders and Bill of Process live in Asset Administration Shells (e.g. AssetFox, BaSyx). | Polls or processes AAS-backed shells according to configuration and runs the same bookkeeping and PCF pipelines as the MES path. |

Upstream systems (including IIH-backed aggregators) perform **state-aware aggregation** and interval accounting; this service consumes their **outputs** and does not query IIH or ring buffers directly.

![Factory-X architecture overview](docs/images/FX_Arch.svg)

## Core capabilities

- **REST ingestion** — `POST /consumptionData` and `POST /productionResults` for operation-level energy and materials; `POST /idle_consumptions` for building/machine idle and production energy totals merged into a factory JSON store.
- **Carbon logic** — Configurable carbon-intensity mechanisms, compressed-air handling, and material PCF lookup when SiGREEN credentials are configured.
- **Bookkeeping** — Per–work-order JSON database (`data_base.json`) with compatibility for multi–energy-type operation structures.
- **PCF reporting** — Builds and submits PCF-oriented reports to SiGREEN.
- **Configuration UI** — Session-protected `/config` for data source, SiGREEN, AAS, and related settings; OpenAPI at `/docs` and `/redoc`.
- **Identity (cloud-oriented)** — Microsoft Entra ID sign-in with an administrator-managed allowlist (`allowed_users.json`, optional S3 mirror); optional legacy username/password for bootstrap or break-glass scenarios.
- **Deployment options** — Serverless handler via Mangum on AWS Lambda, or a single listener on **8443** locally and on EC2 (TLS when certificate and key files exist, otherwise HTTP on the same port).

## Quick guide

### Run locally (developer workstation)

1. **Python 3.11+** and a virtual environment: `python -m venv .venv`, then activate (Windows: `.venv\Scripts\activate`).
2. **Install dependencies:** `pip install -r requirements.txt`.
3. **Environment:** copy [`.env.example`](.env.example) → `.env` and adjust ports, secrets, and optional Entra/S3 variables.
4. **TLS (recommended):** place `cert.pem` and `key.pem` in the project root or set `SSL_CERTFILE` / `SSL_KEYFILE` in `.env`. If files are missing, `python -m app.main` still binds **8443** but serves **plain HTTP** (a warning is logged—use certs in production).
5. **Start the API:** from the repo root, `python -m app.main` listens on **`PORT_HTTPS`** (default **8443**).

   Optional single-process Uvicorn with reload:

   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8443 --reload --ssl-certfile cert.pem --ssl-keyfile key.pem
   ```

6. **Open** `https://localhost:8443/docs` (Swagger) when using TLS, or `http://localhost:8443/docs` without certs; use `/login` then `/config` for the settings UI. Basic-auth JSON view: `/data_base_view`.

Sample request bodies for manual calls live in [`tests/fixtures/http_payloads.py`](tests/fixtures/http_payloads.py).

### Deploy

- **AWS Lambda:** `handler = Mangum(app)` in [`app/main.py`](app/main.py); use the SAM template and parameters below. Configure S3 keys for database and app config so state survives redeploys.
- **EC2:** Gunicorn + Uvicorn workers via [`deploy/gunicorn_conf.py`](deploy/gunicorn_conf.py); load `.env` (or a systemd `EnvironmentFile`) for ports and TLS paths.

Integrators without source access should use [`docs/API_References_PCF_Calculation_Hub.md`](docs/API_References_PCF_Calculation_Hub.md) and the live OpenAPI document at `/openapi.json`.

### Configuration UI and authentication

| Route | Purpose |
|-------|---------|
| `/login` | Sign-in. **Microsoft Entra ID** when `MICROSOFT_ENTRA_TENANT_ID`, `MICROSOFT_ENTRA_CLIENT_ID`, `MICROSOFT_ENTRA_CLIENT_SECRET`, and `PUBLIC_BASE_URL` are set; allowlist in `allowed_users.json` (and optional `ENTRA_BOOTSTRAP_ADMIN_EMAILS`). **Legacy** username/password matches basic-auth env vars when `ENABLE_LEGACY_PASSWORD_LOGIN=true`. |
| `/config` | Session-protected dashboard: SiGREEN, AAS/MES-style settings, **Users** tab (admins) for Entra allowlist. |
| `/docs`, `/redoc` | OpenAPI UIs |

Session cookies guard `/config` and related APIs; see **Security concept** below.

## Security concept

The hub is intended for deployment behind site or cloud perimeter controls (API Gateway, reverse proxy, private VPC) rather than as an anonymously exposed internet endpoint.

- **Sessions** — Signed HTTP-only session cookies (`pcf_session`) protect the configuration UI and admin APIs; Entra OAuth state uses a short-lived separate cookie.
- **Allowlist** — Entra sign-in succeeds only for principals listed in `allowed_users.json` (optionally mirrored to S3 on Lambda).
- **Least exposure** — SiGREEN, AAS, and grid API credentials live in environment or runtime config, not in source control. Config APIs expose `*_configured` flags without returning raw secrets.
- **Diagnostic access** — `GET /data_base_view` uses HTTP Basic Auth (`BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD`) and is separate from Entra session login.
- **Transport** — Use TLS in production (`SSL_CERTFILE`, `SSL_KEYFILE`, or terminating TLS at the load balancer). Set `PUBLIC_BASE_URL` to the URL clients actually use so OAuth redirect URIs match.
- **Downstream enforcement** — SiGREEN OAuth2, AAS registry policies, and Entra tenant policies remain authoritative for their respective platforms.

## Testing and configuration concept

Configuration is **environment-first** (`.env` / Lambda parameters): database paths, S3 buckets for durable JSON, SiGREEN and AAS settings, Entra redirect base URL, session secrets, and basic auth for `/data_base_view`.

### Test tiers

CI runs **unit** and **simulation** tests with coverage. **Integration** tests target a **running** instance with optional live MES, AAS, or aggregator endpoints.

| Tier | What you prove | Where it runs | Primary inputs |
|------|----------------|---------------|----------------|
| **1. Unit tests** | Domain and services, router contracts, mocks; no live HTTP stack | Developer PC | `pytest tests/unit` |
| **2. Simulation tests** | Full FastAPI app via `TestClient`; externals mocked; temp JSON DB | Developer PC | `pytest tests/simulation -m simulation` |
| **3. Integration tests** | Real HTTP to a running app | Developer PC → local or deployed URL | `LIVE_BASE_URL`, `pytest tests/integration -m integration` |
| **4. CI** | Unit + simulation combined coverage | GitHub Actions | [`.github/workflows/ci.yml`](.github/workflows/ci.yml), Codecov |

**Codecov badge:** After the first successful upload on `main`, the badge should match pytest (~94% combined, ~96% lines). Add `CODECOV_TOKEN` from [Codecov settings](https://codecov.io/gh/a-z-e-r-i-l-a/PCF-Calculation-Hub/settings) (or install the [Codecov GitHub App](https://github.com/apps/codecov)). If Codecov shows ~81% while CI passes the 91% gate, path mapping was wrong (fixed via `relative_files = False` and `fixes` in `codecov.yml`); re-run CI on `main` after that change.

**Examples**

```bash
python -m pytest tests/unit -q
python -m pytest tests/simulation -m simulation -v
python -m pytest tests/unit tests/simulation -q --cov=app --cov-config=.coveragerc --cov-report=term-missing
```

Integration (with app running, e.g. HTTPS on 8443):

```bash
# Windows PowerShell
$env:LIVE_BASE_URL = "https://localhost:8443"; python -m pytest tests/integration -m integration -v

# macOS / Linux
LIVE_BASE_URL=https://localhost:8443 python -m pytest tests/integration -m integration -v
```

## Git reset - - soft bf4d48329114acbf07b161b1bf53f19f9daa2969Standards and interoperability

Aligned with industrial and sustainability integration patterns used in Factory-X demonstrators:

- REST/JSON for MES and middleware consumption and production events.
- Asset Administration Shell usage via the project’s AAS client (registry URL, credentials, and asset naming from configuration).
- SiGREEN REST and OAuth2-style token flows for PCF submission and material lookup.
- UTC / ISO 8601 for timestamps in APIs and stored payloads.
- PCF-oriented workflows consistent with **Factory-X / Catena-X–style** traceability: structured operational data before downstream PCF reporting.

## AWS Lambda + API Gateway (Mangum)

`handler = Mangum(app)` in [`app/main.py`](app/main.py).

### SAM (recommended)

1. Install [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) and configure `aws configure`.
2. `sam build --use-container` (or `sam build` if Python matches the template runtime).
3. `sam deploy --guided` — set stack, region, and parameters (e.g. `BasicAuthUsername` / `BasicAuthPassword` for legacy login; Entra env vars when using Microsoft sign-in).
4. Use stack output **ApiUrl** as the base for `/docs`, `/consumptionData`, `/productionResults`, `/login`, and related routes.

**Login / Lambda env:** Confirm **`BASIC_AUTH_USERNAME`** and **`BASIC_AUTH_PASSWORD`** (or Entra variables) in Lambda **Configuration → Environment variables** if password login misbehaves after deploy.

**Persistence:** The SAM template uses `/tmp` for local JSON files and S3 for durability (`DATABASE_S3_*`, `FACTORY_DATABASE_S3_*`, `APP_CONFIG_S3_*`, `ALLOWED_USERS_S3_*`). If you deploy without SAM, set matching `*_PATH` values under `/tmp` and the same S3 variables so state survives cold starts and redeploys.

**Logs:** Stdout/stderr → CloudWatch; the config UI log panel is in-memory only.

### Manual Lambda packaging

Package handler `app.main.handler` with dependencies for the chosen Python runtime; wire HTTP API `{proxy+}` to the function; mirror `.env` as Lambda environment variables.

## Microsoft Entra ID (sign-in)

Register a **Web** application in Entra; redirect URI must match:

`{PUBLIC_BASE_URL}{/stage when not local}/api/auth/microsoft/callback`

Example local: `https://localhost:8443/api/auth/microsoft/callback` (must match `PUBLIC_BASE_URL` and how you open the app). See [`.env.example`](.env.example) for `MICROSOFT_ENTRA_*`, `ENTRA_BOOTSTRAP_ADMIN_EMAILS`, `ALLOWED_USERS_*`, and `ENABLE_LEGACY_PASSWORD_LOGIN`.

## Software version compatibility

Reference stack this release is validated against:

| Application | Version |
|-------------|---------|
| PCF Calculation Hub | 0.1.0 |
| IIH Aggregation Wizard | v1.2.3 |
| Opcenter-X (MES) | 2401 |
| SiGREEN API | 1.16.9 |

## License and Copyright

Copyright Siemens 2026.

This project is licensed under the [Apache License, Version 2.0](LICENSE.txt). Please see the [NOTICE](NOTICE) file for additional third-party and project notices when present in a distribution.

**Credits:** Originally developed by **Alireza Ranjbar**, TP2.10 Team Architect during the **Factory-X** project.
