<!-- SPDX-FileCopyrightText: Copyright Siemens 2026 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
# PCF Calculation Hub – HTTP API Specification & Reference (External)

This document describes the **HTTP API** of the **PCF Calculation Hub** for readers who integrate with the deployed service **without access to implementation source code**. For field-level optionality and the live schema, use **`GET /openapi.json`** (and the interactive explorers at **`/docs`** and **`/redoc`**) against your environment.

The hub turns shop-floor energy and material data into Product Carbon Footprint reports and submits them to **SiGREEN**. It supports two ingest patterns: **MES push** (clients send consumption and production over REST) and **AAS pull** (the hub polls an AAS registry and runs the same PCF pipeline against discovered shells).

| Domain | Role | Entry points |
|--------|------|--------------|
| **MES push ingestion** | Per-operation consumption (energies + materials) and per-work-order production results | `POST /consumptionData`, `POST /productionResults` |
| **Factory consumption ingest** | Idle / production kWh per building → machine → energy type | `POST /idle_consumptions` |
| **AAS pull mode** | Discover work-order shells, validate Bill-of-Process, build PCF, submit to SiGREEN | `GET/POST /api/aas/*`, background poller (when configured) |
| **Configuration & UI** | Session-protected HTML pages and JSON APIs for SiGREEN, AAS, logs, data management, user directory | `/config`, `/work_order_records`, `/factory_energy_distribution`, `/api/*` |
| **Identity** | Microsoft Entra ID (optional), legacy username/password (optional), Basic Auth for the diagnostic database view | `/api/auth/*`, `GET /data_base_view` |

| Item | Value |
|------|-------|
| Default bind | `0.0.0.0:PORT_HTTPS` (default **8443**) |
| TLS | **HTTPS** when certificate and key paths resolve to readable files (**`SSL_CERTFILE`**, **`SSL_KEYFILE`**); otherwise **HTTP** on the same port |
| Public origin | **`PUBLIC_BASE_URL`** (used to build OAuth **`redirect_uri`**) |
| Stage prefix | When **`ENVIRONMENT` ≠ `"local"`**, the leading path segment `/{environment}/` is removed before routing — so **`/dev/consumptionData`** and **`/consumptionData`** can reach the same handler |
| OpenAPI document | **`GET /openapi.json`** (**`/docs`**, **`/redoc`**) |
| Application version | **`0.1.0`** (as reported by the running service / OpenAPI metadata) |

> **Note:** Responses include **`X-Content-Type-Options: nosniff`**, **`X-Frame-Options: SAMEORIGIN`**, and **`Referrer-Policy: strict-origin-when-cross-origin`** unless overridden for a specific response.

---

## 1. Resource model

Functional areas exposed by the API:

| Area | Surface |
|------|---------|
| Consumption ingestion | `POST /consumptionData` |
| Production completion | `POST /productionResults` |
| Factory / machine energy | `POST /idle_consumptions` |
| Diagnostic JSON view | `GET /data_base_view` (Basic Auth) |
| Session auth | `/api/auth/*`, `GET /login` |
| Admin user directory | `/api/admin/users[/{email}]` |
| Operator UI & JSON APIs | `/config`, `/work_order_records`, `/factory_energy_distribution`, `/api/*` |

Persistent state is held in JSON-backed stores, optionally mirrored to S3 when the corresponding **`_*_S3_BUCKET`** / **`_*_S3_KEY`** environment variables are set:

| Logical store | Typical content | Notes |
|---------------|-----------------|--------|
| Work-order datastore | Operations, materials, PCF snapshots | Default path configurable via **`DATABASE_PATH`** |
| Factory consumption datastore | Building → machine → energy idle / production totals | Default path configurable via **`FACTORY_DATABASE_PATH`** |
| App configuration | SiGREEN, AAS, carbon-intensity, feature flags | Default path configurable via **`APP_CONFIG_PATH`** |
| Allowed users directory | Microsoft sign-in allowlist | Default path **`ALLOWED_USERS_PATH`** |

```
┌────────────────────────────────────────────────────────────────────┐
│                     PCF Calculation Hub (HTTP API)               │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Ingestion (no session — trusted upstream)                   │  │
│  │    POST /consumptionData         → Consumption payload        │  │
│  │    POST /productionResults       → Production completion      │  │
│  │    POST /idle_consumptions    → General consumption       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Auth & session                                              │  │
│  │    GET  /api/auth/options        — public                    │  │
│  │    POST /api/auth/login          — legacy username/password  │  │
│  │    GET  /api/auth/microsoft/...  — Entra OAuth start/callback│  │
│  │    GET  /api/auth/session        — who am I                  │  │
│  │    GET  /api/auth/logout         — clear cookie              │  │
│  │    GET  /login                   — login HTML                │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Session-protected UI pages                                  │  │
│  │    GET  /config                                              │  │
│  │    GET  /work_order_records                                  │  │
│  │    GET  /factory_energy_distribution                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Session-protected JSON APIs (/api/*)                        │  │
│  │    GET    /api/data_explorer                                 │  │
│  │    DEL    /api/data_explorer/{work_order_name}               │  │
│  │    GET    /api/factory_energy_distribution                   │  │
│  │    DEL    /api/factory_energy_distribution/{building_id}     │  │
│  │    GET    /api/overview_stats                                │  │
│  │    GET    /api/logs?after=<id>                               │  │
│  │    GET    /api/aas/shells                                    │  │
│  │    POST   /api/aas/process_shells                            │  │
│  │    GET    /api/config        ─┐                              │  │
│  │    POST   /api/config        ─┴ allowlisted keys             │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Admin user directory (session + admin role)                 │  │
│  │    GET    /api/admin/users                                   │  │
│  │    POST   /api/admin/users                                   │  │
│  │    DELETE /api/admin/users/{email:path}                      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Diagnostic (Basic Auth)                                     │  │
│  │    GET /data_base_view  — pretty-printed work-order JSON      │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Static & documentation                                      │  │
│  │    GET /static/{path}     /docs    /redoc    /openapi.json   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 2. Authentication & authorization

Mechanisms layered per route:

| Mechanism | Cookie / header | Applies to | Notes |
|-----------|-----------------|------------|-------|
| **None** | – | `POST /consumptionData`, `POST /productionResults`, `POST /idle_consumptions`, `GET /api/auth/options`, `GET /login`, `GET /openapi.json`, `/docs`, `/redoc`, `/static/*` | Ingestion endpoints assume a trusted network perimeter (MES, middleware, operator tools). Enforcement is deployment-specific. |
| **HTTP Basic** | **`Authorization: Basic …`** | `GET /data_base_view` | Username / password from **`BASIC_AUTH_USERNAME`** / **`BASIC_AUTH_PASSWORD`** (deployment defaults apply when unset). |
| **Session cookie** | **`pcf_session`** (HttpOnly, **`SameSite=Lax`**, signed using **`SESSION_SECRET_KEY`**) | Session **`/api/*`** routes and **`/config`**, **`/work_order_records`**, **`/factory_energy_distribution`** | Issued after legacy login or Microsoft OAuth callback. Lifetime **7 days**. Cookie **`Secure`** is enabled outside **`ENVIRONMENT=local`** unless overridden by **`SESSION_COOKIE_SECURE`**. |
| **Admin session** | Same cookie + admin principal | **`GET` / `POST` / `DELETE /api/admin/users/*`** | Requires a directory **`role: "admin"`** or a match against **`ENTRA_BOOTSTRAP_ADMIN_EMAILS`**. |

### 2.1 Session payload

The **`pcf_session`** cookie carries an HMAC-signed, time-limited payload (JSON) with conceptual fields:

```json
{ "v": 2, "kind": "local" | "entra", "principal": "<user>", "iat": <unix-seconds> }
```

Expired tokens, version mismatches, and principals removed from the allowlist are rejected. A legacy **`username|timestamp`** string form may still be accepted for backward compatibility.

### 2.2 Login rate limiting

Repeated failed legacy logins are throttled **per client IP**. Excess attempts return **`429`** with **`Retry-After: 60`**.

### 2.3 OAuth state (CSRF protection)

Microsoft sign-in uses a signed nonce in the **`pcf_oauth_state`** cookie (short TTL). Callbacks fail closed when cookie, query **`state`**, or signature disagree. Errors redirect to **`/login?signin=error`** and clear auth cookies.

---

## 3. Data models

The **required** columns describe what a client **must send** when submitting JSON. Detailed shapes also appear under **`GET /openapi.json`**.

### 3.1 `ConsumptionData` (`POST /consumptionData`)

Per-operation consumption envelope. Energy and material arrays are optional at validation time — but **`POST /productionResults`** still refuses to finalize when no consumption rows exist for the work order.

```
ConsumptionData
├── workOrderName              (string)
├── workOrderOperationName     (string)
├── workUnit                   (string)
├── consumedMaterials[]        (default [])
│   └── ConsumedMaterial
│       ├── identifier         (string)
│       ├── materialName       (string)
│       ├── quantity           (float)
│       └── materialUom        (string)
├── consumedEnergies[]         (default [])
│   └── ConsumedEnergy
│       ├── type               (string)
│       ├── uom                (string)
│       └── resourceUsage      (ResourceUsage)
│           ├── measurementType (string)
│           └── measurements[] (Measurement)
│               ├── start       (datetime)
│               ├── duration    (int, default 15)   ← minutes
│               └── consumption (float)
├── actualStartTime            (datetime)
├── actualEndTime              (datetime)
└── timestamp                  (datetime)
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **workOrderName** | `string` | Yes | Stable work-order identifier shared across ingestion and **`/productionResults`**. |
| **workOrderOperationName** | `string` | Yes | Operation / routing-step identifier within the work order. |
| **workUnit** | `string` | Yes | Logical work unit or machine grouping as reported upstream. |
| **consumedMaterials** | array | No (default `[]`) | Material lines used for BOM-style SiGREEN lookup when **`pcf_include_bom`** is enabled. |
| **consumedEnergies** | array | No (default `[]`) | Interval energy measurements aggregated by the hub. |
| **actualStartTime** | `datetime` | Yes | Operation window start (ISO 8601; **`Z`** accepted). |
| **actualEndTime** | `datetime` | Yes | Operation window end. |
| **timestamp** | `datetime` | Yes | Producer emission time; stored with bookkeeping. |

| Sub-field | Type | Required | Description |
|-----------|------|----------|-------------|
| **ConsumedMaterial.identifier** | `string` | Yes | Stable material id used for SiGREEN component lookup. |
| **ConsumedMaterial.materialName** | `string` | Yes | Display name persisted in bookkeeping. |
| **ConsumedMaterial.quantity** | `float` | Yes | Quantity in **`materialUom`**. |
| **ConsumedMaterial.materialUom** | `string` | Yes | UOM (e.g. **`kg`**). |
| **ConsumedEnergy.type** | `string` | Yes | Carrier label (**`Electricity`**, **`CompressedAir`**, …). |
| **ConsumedEnergy.uom** | `string` | Yes | Unit (**`kWh`**, **`MJ`**, **`m3`**, …). Non-electricity carriers are normalized server-side to kWh-equivalent for accumulation. |
| **ResourceUsage.measurementType** | `string` | Yes | Semantic type (**`DELTA`**, …). |
| **ResourceUsage.measurements** | array | Yes | One or more intervals within the operation window. |
| **Measurement.start** | `datetime` | Yes | Interval start. |
| **Measurement.duration** | `int` | No (default **`15`**) | Length **in minutes**. |
| **Measurement.consumption** | `float` | Yes | Consumed amount in parent **`uom`**. |

### 3.2 `ProductionResults` (`POST /productionResults`)

Completes the work order: assembles PCF, submits emissions to SiGREEN, persists snapshots.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **workOrderName** | `string` | Yes | Must match prior **`/consumptionData`** for the order. **`400`** when no consumption exists. |
| **workOrderState** | `string` | Yes | Terminal producer state (**`Completed`**, …). |
| **productId** | `string` | Yes | Canonical product identifier for SiGREEN. |
| **productName** | `string` | Yes | Display name in stored PCF snapshot. |
| **productRevision** | `string` | Yes | Product revision label. |
| **traceabilityType** | `string` | Yes | Producer traceability strategy. |
| **producedMtus** | array of strings | Yes | Serialized / lot identifiers; may be empty. |
| **uom** | `string` | Yes | **`producedQuantity`** unit (**`piece`**, …). |
| **producedQuantity** | `int` | Yes | Good quantity. |
| **scrappedQuantity** | `int` | Yes | Scrap count. |
| **actualStartTime** | `datetime` | Yes | Order window start. |
| **actualEndTime** | `datetime` | Yes | Order window end. |
| **locationName** | `string` | Yes | Facility / geography label in outbound payload. |
| **timestamp** | `datetime` | Yes | Producer emission time. |

### 3.3 `GeneralConsumptionPayload` (`POST /idle_consumptions`)

Idle and production consumption for one machine / building slice and energy type. Typical source: **IIH Aggregator Wizard** or equivalent edge aggregation.

```
GeneralConsumptionPayload
├── building_id                   (string)
├── machine_id                    (string)
├── machine_name                  (string)
├── energy_type                   (string)              ── e.g. "electricity"
├── total_time                    (float)               ── minutes
├── total_idle_time               (float)               ── minutes
├── work_orders_duration          (map<string, float>)  ── minutes per WO id
├── idle_consumption_total        (float)               ── kWh
├── idle_consumption_rate         (float)               ── kWh/h, derivable
├── prod_consumption_total        (float, default 0.0)  ── kWh
├── prod_consumption_rate         (float)               ── kWh/h, derivable
└── publication_datetime          (datetime)
```

> **Compatibility:** The server accepts alternate names for several keys so older publishers keep working:

| Canonical | Accepted aliases |
|-----------|------------------|
| `total_time` | `Total_duration`, `total_duration` |
| `total_idle_time` | `Total_idle_time` |
| `prod_consumption_total` | `Prod_consumption_total` |
| `prod_consumption_rate` | `Prod_consumption_rate` |
| `publication_datetime` | `Publication_datetime` |

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **building_id** | `string` | Yes | Top-level grouping in the factory store. |
| **machine_id** | `string` | Yes | Stable machine key. |
| **machine_name** | `string` | Yes | Display name (last write wins). |
| **energy_type** | `string` | Yes | Lowercased before use as nested key (**`electricity`**, **`compressed_air`**, …). |
| **total_time** | `float` | Yes | Reporting window **minutes** (fractional OK). |
| **total_idle_time** | `float` | Yes | Idle minutes (**`total_time`** when no production). |
| **work_orders_duration** | object | No | Minutes per work order; merged **additively** into persisted totals. |
| **idle_consumption_total** | `float` | Yes | Idle **kWh** for the window. |
| **idle_consumption_rate** | `float` | No (derived) | kWh/h; omitted → **`idle_consumption_total / (total_time / 60)`**. |
| **prod_consumption_total** | `float` | No (default **`0.0`**) | Production **kWh**; idle-only clients may omit. |
| **prod_consumption_rate** | `float` | No (derived) | kWh/h; derived similarly when omitted. |
| **publication_datetime** | `datetime` | No | Observation time. |

### 3.4 `UserUpsertBody` (`POST /api/admin/users`)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| **email** | `string` (3–320 chars) | Yes | User email; normalized server-side. |
| **role** | **`"admin"` \| `"user"`** | No (default **`"user"`**) | Directory role. |

### 3.5 App configuration (`/api/config`)

**`GET /api/config`** returns built-in defaults merged with persisted JSON. When **`data_source == "aas"`**, an **`aas_status`** block summarizes registry connectivity/context.

**`POST /api/config`** accepts JSON; only **allowlisted** top-level keys are applied. Unknown keys are ignored; omitted keys retain previous values.

| Key | Type | Description |
|-----|------|-------------|
| **data_source** | `string` | Anything other than **`"aas"`** → MES push path. **`"aas"`** → **`/api/aas/*`** and background polling (unless disabled). |
| **pcf_tool** | `string` | Integration target (e.g. **`sigreen`**). When **`sigreen`**, factory id can be resolved from SiGREEN. |
| **sigreen_base_url** | `string` | SiGREEN REST base URL. |
| **sigreen_client_id**, **sigreen_client_secret** | `string` | OAuth2 credentials. Changing either triggers a **live credential check** before save; failure → **`400`**. Empty secret preserves the stored secret. |
| **sigreen_factory_name**, **sigreen_factory_id** | `string` | Factory naming + resolved identifier. Changing name clears cached id for re-resolution. |
| **sigreen_product_identifier_type** | `string` | Default **`Product ID`**. |
| **carbon_intensity_source** | **`constant` \| `green_grid_compass`** | Grid intensity source; invalid → **`constant`**. |
| **carbon_intensity_constant_gco2** | `float ≥ 0` | gCO₂e/kWh when **`constant`**; invalid → **`350`**. |
| **pcf_include_bom** | `bool` | Whether **`/productionResults`** enriches PCF using material lookup. |
| **aas_base_url**, **aas_asset_name**, **aas_client_id**, **aas_client_secret** | `string` | Registry access parameters. |
| **aas_type** | **`AAS (BaSyx)` \| `AAS (AssetFox)`** | Invalid → **`AAS (AssetFox)`**. |
| **aas_check_period_minutes** | `float`, **0–1440** | Polling interval (**0** disables). Out-of-range values clamp; bad types → **`0`**. |

> **Note:** Some advanced keys exist only on disk (**e.g.** material identifier mapping for SiGREEN) and are **not** writable through **`POST /api/config`**.

---

## 4. Endpoint catalogue

Unless noted, JSON endpoints:

- use **`application/json`** for requests and responses,
- return **`201 Created`** for successful ingestion POSTs and **`200 OK`** otherwise,

and propagate errors consistently (§5).

Paths below omit optional **`/{environment}/`** prefixes (§5.1).

### 4.1 Ingestion (no auth)

#### `POST /consumptionData`

Stores one operation’s consumption and returns aggregated totals.

**Request:** §3.1.

**Success `201`:**

```json
{
  "workOrder": "PO_40003",
  "operation": "OP10-Fraesen",
  "total_energy_consumption_kwh": 82.0,
  "total_carbon_footprint_kg": 28.7,
  "materials_count": 0,
  "energy_types_count": 1,
  "database_record": { "...": "..." },
  "_api_version": "energy-split-v2"
}
```

| Field | Type | Description |
|-------|------|-------------|
| **workOrder** | `string` | Echo **`workOrderName`**. |
| **operation** | `string` | Echo **`workOrderOperationName`**. |
| **total_energy_consumption_kwh** | `float` | Aggregated operation energy (**kWh**). |
| **total_carbon_footprint_kg** | `float` | Aggregated CO₂e (**kg**). |
| **materials_count** | `int` | Count of persisted material lines. |
| **energy_types_count** | `int` | Count of persisted energy lines. |
| **database_record** | `object` | Opaque bookkeeping slice returned for debugging — do not rely on stability across releases. |
| **_api_version** | `string` | Compatibility token carried on responses (currently `energy-split-v2`). Treat as informational. |

#### `POST /productionResults`

Request: §3.2.

**Success `201`:**

```json
{
  "workOrderName": "PO_40003",
  "productId": "ABC-123",
  "productUuid": "0a4f...e9b",
  "producedQuantity": 100,
  "timestamp": "2026-06-16T18:00:00Z"
}
```

**`400`** with **`{"detail": "No consumption data found for given workOrderName"}`** when no prior ingestion exists.

#### `POST /idle_consumptions`

Merge into factory store under **`building_id → machine_id → energy_type`**. Repeated submits for the same triple **accumulate**.

**Success `201`:**

```json
{
  "status": "accepted",
  "building_id": "HALL_01",
  "machine_id": "DMG01",
  "energy_type": "electricity",
  "database_path": "<server-configured path>"
}
```

The **`database_path`** field echoes the resolved server path (deployment-specific).

---

### 4.2 Diagnostic (Basic Auth)

#### `GET /data_base_view`

Returns the full work-order datastore as **`text/html`** (**`<pre>`** JSON).

**`401`** with **`WWW-Authenticate: Basic`** when credentials missing or invalid.

---

### 4.3 Authentication & session

#### `GET /api/auth/options`

Public capability discovery.

```json
{
  "microsoft": { "enabled": true,  "login_url": "/api/auth/microsoft/login" },
  "legacy_password": { "enabled": false }
}
```

Microsoft enables when **`MICROSOFT_ENTRA_TENANT_ID`**, **`MICROSOFT_ENTRA_CLIENT_ID`**, and **`MICROSOFT_ENTRA_CLIENT_SECRET`** are all set. Legacy password enables when **`ENABLE_LEGACY_PASSWORD_LOGIN=true`** **or** Microsoft is not configured.

#### `GET /login`

Returns login HTML with stage-aware base URL when prefixed deployments are active.

#### `POST /api/auth/login`

Legacy login — JSON **`{ "username", "password" }`** or **`application/x-www-form-urlencoded`**. Leading/trailing whitespace trimmed.

| Status | Body |
|--------|------|
| `200` | `{ "redirect": "/config" }` + **`pcf_session`** |
| `401` | **`Invalid username or password`** |
| `403` | Password login disabled (**Microsoft-only** mode). |
| `429` | Too many attempts + **`Retry-After: 60`**. |

#### `GET /api/auth/microsoft/login`

Starts OAuth **`302`**; sets **`pcf_oauth_state`**.

**`503`** when Entra variables unset.

#### `GET /api/auth/microsoft/callback`

Completes OAuth, sets session, redirects to **`/config`** or error routes (**`/login?signin=…`**).

#### `GET /api/auth/session`

| Status | Body |
|--------|------|
| `200` | `{ "principal": "<user>", "is_admin": true \| false }` |
| `401` | Missing / expired / invalid |

#### `GET /api/auth/logout`

Clears cookies · **`302`** → **`/login`**.

---

### 4.4 Admin user directory

Requires **session + admin**.

#### `GET /api/admin/users`

```json
{ "users": [ { "email": "alice@example.com", "role": "admin", "created_by": "...", "...": "..." } ] }
```

#### `POST /api/admin/users`

Body §3.4.

| Status | Body |
|--------|------|
| `200` | `{ "user": { ... } }` |
| `400` | Validation error |

#### `DELETE /api/admin/users/{email:path}`

| Status | Body |
|--------|------|
| `200` | `{ "status": "ok", "deleted": "<normalized-email>" }` |
| `400` | Invalid email |
| `404` | Not found |

---

### 4.5 Session UI pages

| Path | Purpose |
|------|---------|
| `GET /config` | Configuration dashboard |
| `GET /work_order_records` | Work-order explorer |
| `GET /factory_energy_distribution` | Factory / machine energy |

Unauthenticated callers receive **`302`** → **`/login`**. Served HTML is rewritten for stage prefixes so relative navigation works behind **`/{environment}/`**.

---

### 4.6 Session JSON APIs

#### `GET /api/data_explorer`

Whole work-order JSON object keyed by **`workOrderName`**.

#### `DELETE /api/data_explorer/{work_order_name:path}`

#### `GET /api/factory_energy_distribution`

Nested **`building_id → machine_id → energy_type`** totals.

#### `DELETE /api/factory_energy_distribution/{building_id:path}`

#### `GET /api/overview_stats`

Aggregated KPIs (counts, totals, lists). Example:

```json
{
  "work_order_count": 12,
  "total_operations": 47,
  "total_materials": 23,
  "total_energy_kwh": 1234.5,
  "total_carbon_footprint_kg": 432.1,
  "pcf_count": 8,
  "latest_pcf_work_order": "PO_40003",
  "latest_pcf_value": 28.7,
  "work_orders": [ { "name": "...", "operations": 4, "materials": 2, "energy_kwh": 82.0, "carbon_footprint_kg": 28.7, "pcf": 28.7 } ],
  "products": [ { "work_order": "...", "product_name": "...", "factory": "...", "pcf_value": 28.7, "batch_number": "...", "quantity": 100, "processes": 3, "materials": 2, "emission_unit": "kgCO2e/piece", "primary_data_share": 0.85 } ]
}
```

#### `GET /api/logs?after=<id>`

Recent log entries from an in-memory buffer. Incremental callers pass the last seen **`id`**.

```json
{
  "entries": [
    { "id": 1024, "timestamp": "2026-05-06T08:30:00.123Z", "level": "INFO", "logger": "pcf_creator_app", "message": "..." }
  ]
}
```

Exception-backed entries may include **`traceback`**.

#### `GET /api/aas/shells`

```json
{ "shell_ids": ["urn:shell:WO-2026-...", "..."], "error": null }
```

**`error`** when **`data_source` ≠ `aas`**, base URL unset, or registry failure (human-readable).

#### `POST /api/aas/process_shells`

Runs one discovery / validation / submission cycle. **`200`** typical with **`processed`** / **`skipped`** / **`shells_processed`**. Shell-level failures append to **`errors`** without aborting siblings.

#### `GET /api/config`

Merged configuration; **`aas_status`** when in AAS mode.

> **Caveat:** Secrets (**`sigreen_client_secret`**, **`aas_client_secret`**) **may appear in plaintext** — treat **`GET`** as sensitive and rely on session protection.

#### `POST /api/config`

Allowlisted keys §3.5. Behaviour summary:

| Rule | Effect |
|------|--------|
| Invalid **`aas_type`** | Reset **`AAS (AssetFox)`**. |
| **`aas_check_period_minutes`** | Clip **`[0, 1440]`**; coerce bad types → **`0`**. |
| Carbon intensity enums / numbers | Clamp / reset per §3.5. |
| **`pcf_include_bom`** | Coerced **`bool`**. |
| **`sigreen_client_secret`** | Empty → preserve existing. |
| SiGREEN credential verify | **`400`** on failure. |

**Success:** `{ "status": "ok", "config": { ... } }`  
Non-object JSON → **`400`** **`JSON object expected`**.

---

### 4.7 Static & documentation

| Path | Purpose |
|------|---------|
| `GET /static/{path:path}` | Static hosting; traversal **`404`**. |
| `GET /docs` | Custom Swagger UI. |
| `GET /redoc` | ReDoc. |
| `GET /openapi.json` | Machine-readable schema. |

---

## 5. Cross-cutting concerns

### 5.1 Stage prefix

When **`ENVIRONMENT` ≠ `"local"`**, **`/{environment}/...`** prefixes are stripped before routing behind gateways or proxies.

Static login / operator pages inject **`<base href="/{environment}/">`** where needed so **`fetch('/api/...')`** resolves correctly under a prefix.

### 5.2 Error mapping

Layers:

1. **Request validation (`422`).** Structured errors plus **`received_body_preview`** (≤ about **4 KB**) for debugging malformed bodies:

   ```json
   {
     "detail": "Request validation failed",
     "errors": [ "..." ],
     "received_body_preview": "..."
   }
   ```

2. **Typed business/integration failures.**

   | Scenario | HTTP | Body |
   |-----------|------|------|
   | Caller violates a persisted business rule **after** schema acceptance | **`400`** | `{ "detail": "<message>" }` |
   | Mandatory configuration missing / unusable (**SiGREEN**, **AAS**, mode mismatch, …) | **`503`** | `{ "detail": "<message>" }` |
   | Downstream outage (**SiGREEN**, **AAS registry**, **Green Grid Compass**) | **`502`** | `{ "detail": "<message>" }` |
   | Internal **`204`** | Reserved — background control edge case; callers should treat as anomaly if seen via HTTP |

3. **Unhandled server errors (`500`).** **`{ "detail": "Internal server error" }`**; details logged server-side only.

Additional common statuses: **`401`**, **`403`**, **`429`** (**`Retry-After`** on abusive login bursts).

### 5.3 Security headers

Responses default to:

```
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: strict-origin-when-cross-origin
```

### 5.4 Background AAS poller

When **`data_source`** is **`aas`** and **`aas_check_period_minutes > 0`**, a background scheduler periodically runs the same work as **`POST /api/aas/process_shells`**. Failures roll to logs; loops continue.

### 5.5 Storage

JSON files plus optional **S3** mirrors (see environment table). Saves are atomic on the local filesystem where supported.

---

## 6. Environment variables

Configure through the process environment **and/or** `.env` (UTF-8) loaded by the service.

| Variable | Default | Description |
|----------|---------|-------------|
| `ENVIRONMENT` | `local` | Non-local enables stage stripping, **`Secure`** cookies defaults, warns on placeholder **`SESSION_SECRET_KEY`**. |
| `PORT_HTTPS` | `8443` | Listening port (**HTTP or HTTPS**). |
| `SSL_CERTFILE`, `SSL_KEYFILE` | – | Enable TLS when both readable. |
| `SESSION_SECRET_KEY` | *(placeholder)* | HMAC signing for cookies — **must** be secret in production. |
| `SESSION_COOKIE_SECURE` | _auto_ | Force **`Secure`** attribute. |
| `TRUST_FORWARDED_HEADERS` | `false` | Honor **`X-Forwarded-For`** for login rate limiting. |
| `BASIC_AUTH_USERNAME`, `BASIC_AUTH_PASSWORD` | `admin` | Basic auth for **`/data_base_view`**. Empty password falls back to **`admin`**. |
| `MICROSOFT_ENTRA_TENANT_ID`, `MICROSOFT_ENTRA_CLIENT_ID`, `MICROSOFT_ENTRA_CLIENT_SECRET` | – | All three ⇒ Microsoft SSO. |
| `PUBLIC_BASE_URL` | `https://localhost:8443` | Builds OAuth **`redirect_uri`**. |
| `ALLOWED_USERS_PATH` | *(deployment default)* | Microsoft allowlist JSON path. |
| `ALLOWED_USERS_S3_BUCKET`, `ALLOWED_USERS_S3_KEY` | – | S3-backed allowlist mirror. |
| `ENTRA_BOOTSTRAP_ADMIN_EMAILS` | – | Comma list — bootstrap admins / always-allowed principals. |
| `ENABLE_LEGACY_PASSWORD_LOGIN` | `true` | When **`false`** and Microsoft configured · legacy **`POST`** returns **`403`**. |
| `DATABASE_PATH` | *(deployment default)* | Work-order store. |
| `FACTORY_DATABASE_PATH` | *(deployment default)* | Factory store. |
| `FACTORY_DATABASE_S3_BUCKET` / `FACTORY_DATABASE_S3_KEY` | – | S3 mirror for factory store. |
| `APP_CONFIG_PATH` | *(deployment default)* | App config store. |
| `DATABASE_S3_BUCKET` / `DATABASE_S3_KEY` | – | S3 mirror for work-order datastore. |
| `APP_CONFIG_S3_BUCKET` / `APP_CONFIG_S3_KEY` | – | Config mirror. |
| `DEBUG` | `false` | Reserved / future verbosity. |

---

## 7. End-to-end examples

### 7.1 MES push (single WO / op)

Consumption:

```bash
curl -X POST https://hub.example.net:8443/consumptionData \
  -H 'Content-Type: application/json' \
  -d '{
    "workOrderName": "PO_40003",
    "workOrderOperationName": "OP10-Fraesen",
    "workUnit": "DMG-WorkUnit-1",
    "consumedEnergies": [
      {
        "type": "Electricity",
        "uom": "kWh",
        "resourceUsage": {
          "measurementType": "DELTA",
          "measurements": [
            { "start": "2026-06-16T16:05:00Z", "duration": 15, "consumption": 12 },
            { "start": "2026-06-16T16:20:00Z", "duration": 15, "consumption": 70 }
          ]
        }
      }
    ],
    "consumedMaterials": [],
    "actualStartTime": "2026-06-16T16:05:00Z",
    "actualEndTime":   "2026-06-16T16:53:00Z",
    "timestamp":       "2026-06-16T17:00:00Z"
  }'
```

Completion:

```bash
curl -X POST https://hub.example.net:8443/productionResults \
  -H 'Content-Type: application/json' \
  -d '{
    "workOrderName": "PO_40003",
    "workOrderState": "Completed",
    "productId": "ABC-123",
    "productName": "Bracket A",
    "productRevision": "Rev-2",
    "traceabilityType": "lot",
    "producedMtus": ["MTU-1001", "MTU-1002"],
    "uom": "piece",
    "producedQuantity": 100,
    "scrappedQuantity": 0,
    "actualStartTime": "2026-06-16T16:05:00Z",
    "actualEndTime":   "2026-06-16T17:30:00Z",
    "locationName":    "Erlangen",
    "timestamp":       "2026-06-16T18:00:00Z"
  }'
```

### 7.2 Factory consumption

```bash
curl -X POST https://hub.example.net:8443/idle_consumptions \
  -H 'Content-Type: application/json' \
  -d '{
    "building_id": "HALL_01",
    "machine_id":  "DMG01",
    "machine_name": "DMG MORI NLX 2500",
    "energy_type": "electricity",
    "total_time": 60.0,
    "total_idle_time": 12.0,
    "idle_consumption_total": 0.45,
    "prod_consumption_total": 4.20,
    "work_orders_duration": { "PO_40003": 24.5, "PO_40004": 23.5 },
    "publication_datetime": "2026-06-16T18:00:00Z"
  }'
```

### 7.3 AAS mode (manual)

Use session cookie from browser login **or**:

```bash
curl -c cookies.txt -X POST https://hub.example.net:8443/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{ "username": "<user>", "password": "<pass>" }'
```

Configure and drive:

```bash
curl -b cookies.txt -X POST https://hub.example.net:8443/api/config \
  -H 'Content-Type: application/json' \
  -d '{
    "data_source": "aas",
    "aas_type": "AAS (AssetFox)",
    "aas_base_url": "https://test.assetfox.apps.siemens.cloud/api/aas/v3",
    "aas_client_id": "...",
    "aas_client_secret": "...",
    "aas_check_period_minutes": 5
  }'

curl -b cookies.txt https://hub.example.net:8443/api/aas/shells
curl -b cookies.txt -X POST https://hub.example.net:8443/api/aas/process_shells
```

---

## 8. Data-type reference

| Type token | Meaning | Example |
|------------|---------|---------|
| `string` | UTF-8 JSON string | **`"PO_40003"`** |
| `int` | JSON integer | **`100`** |
| `float` | JSON number | **`28.7`** |
| `bool` | JSON boolean | **`true`** |
| `string \| null` | Nullable string | **`null`** |
| `datetime` | ISO **8601** timestamp (**`Z`** or **`±HH:MM`**) | **`"2026-06-16T16:05:00Z"`** |
| `array<T>` | JSON array | **`[]`** |
| `map<K,V>` | JSON object, string keys | **`{ "PO_40003": 24.5 }`** |

---

## 9. Operational notes for integrators

1. **Call order (MES)** — ingest all **`/consumptionData`** for a **`workOrderName`** **before** **`/productionResults`**, or receive **`400`**.  
2. **Idempotency** — repeated consumption rows **merge**. **`/productionResults`** overwrites the PCF snapshot. **`/idle_consumptions`** **adds**. Enforce uniqueness upstream if needed.  
3. **Energy UOM** — send native units; conversion to comparable **kWh** happens server-side.  
4. **Material PCF** — with **`pcf_include_bom`**, lookups use **`consumedMaterials.identifier`**. Missing mappings surface as **`503`** until **`material_identifier_mapping`** exists in the persisted app-configuration file on the server (not editable via **`POST /api/config`** allowlist).  
5. **Prefixes** — both **`/{env}/`** and unprefixed paths can work (see **section 5.1**).  
6. **Diagnostics** — inspect **`received_body_preview`** inside **`422`**.  
7. **Polling** — background AAS ticks without HTTP when enabled; **`POST`** can force a refresh.

---

## 10. Companion documents (conceptual)

- **[Security concept](security-concept.md)** — identity, secrets, operational posture.

- **[Traceability §5–2](traceability-section-5-2.md)** — audit trail for production submission.

Where this narrative and **`GET /openapi.json`** diverge on field optionality or schema, **`openapi.json`** for **your deployment** wins.
