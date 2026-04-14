# Security Concept

**Document type:** Technical security description  
**Subject:** PCF Creator Application  
**Audience:** Architects, security officers, operators, and integration partners  

*Replace the following placeholders when issuing a controlled release: document identifier, version, revision date, classification, and owner.*

---

## 1. Purpose and scope

This document describes the security objectives, controls, and residual risks associated with the PCF Creator application. It applies to all deployment models described in the project documentation (local development, server deployment, and serverless deployment on AWS).

The application is intended as a **proof-of-concept and demonstrator** for product carbon footprint (PCF) workflows. It exposes REST APIs for integration with manufacturing systems and a web-based configuration interface. Organizational policies, network zoning, identity federation, and cloud account governance remain outside the scope of this document; they must be applied according to the deploying organization’s standards.

## 2. Security objectives

| Objective | Description |
|--------|-------------|
| **Confidentiality** | Protect credentials, session state, integration secrets, and operational data against unauthorized disclosure. |
| **Integrity** | Ensure configuration and bookkeeping data are modified only through defined interfaces; protect session tokens from forgery. |
| **Availability** | Rely on standard hosting practices; the application does not implement clustering or distributed denial-of-service mitigation by itself. |
| **Accountability** | Support traceability through server-side logging; authentication diagnostics avoid recording raw secrets. |

## 3. Trust boundaries and roles

The system distinguishes three access patterns:

1. **Browser-based operator access**  
   Operators use a login page and receive a **signed session cookie** after successful authentication. Session-protected pages and APIs require a valid session.

2. **HTTP Basic Authentication**  
   Selected administrative endpoints (for example read-only views of the JSON database) require **Basic** credentials. Verification uses **constant-time** comparison of username and password to mitigate simple timing attacks.

3. **Machine-to-machine REST APIs**  
   Consumption and production endpoints are intended for **trusted upstream systems** (for example MES or similar). The application does **not** implement per-client API keys or OAuth for these interfaces; **network isolation**, **API gateways**, **mutual TLS**, or **upstream identity** are the primary controls for restricting who may invoke them in production.

## 4. Authentication mechanisms

### 4.1 Operator credentials

Operator and Basic authentication credentials are defined in environment configuration. Default values may exist for development; **production deployments must replace** them with strong, unique values managed through secure configuration (environment variables, secrets managers, or equivalent).

### 4.2 Session tokens

After successful login, the server issues a session token stored in an **HTTP-only** cookie. The token is **cryptographically signed** using a server-side secret (`SESSION_SECRET_KEY`) so that clients cannot forge valid tokens. Session lifetime is **bounded** (seven days in the current implementation).

If the deployment environment is not `local` and the signing key remains at its documented default placeholder, the application **logs a warning** at startup to prompt operators to set a strong secret.

### 4.3 Session cookie flags

The **`Secure`** attribute on the session cookie is set according to configuration:

- If **`SESSION_COOKIE_SECURE`** is set in the environment, that value is used.
- If it is **unset**, the default is **`Secure=true`** when `ENVIRONMENT` is not `local`, and **`Secure=false`** for local development (so plain HTTP remains usable for development).

The cookie **`SameSite`** is set to **`Lax`** to reduce cross-site request risk in common browsing patterns while preserving typical same-site navigation.

## 5. Transport security

**TLS** is supported for the application process via configurable certificate and key paths. Many environments terminate TLS on a **load balancer** or **API gateway** instead; in those cases, transport protection is governed by the platform.

Operators should ensure that **session cookies and Basic credentials** are not transmitted over untrusted networks without encryption.

## 6. Rate limiting and abuse mitigation

**Failed login attempts** are tracked per client identifier in a sliding time window. After a configurable threshold of failures within that window, further login attempts receive **HTTP 429 (Too Many Requests)** with a **`Retry-After`** hint. Successful authentications do not increment this counter.

The client identifier is derived from the **direct client address** unless **`TRUST_FORWARDED_HEADERS`** is enabled. When enabled, the **first** address in the **`X-Forwarded-For`** header is used. This option must be **enabled only** when the application sits behind a **trusted reverse proxy** that sanitizes or overwrites this header; otherwise clients could spoof addresses.

This mechanism is **in-process** and does not coordinate across multiple worker processes or instances. For distributed deployments, **additional** rate limiting at the gateway or WAF is recommended.

## 7. HTTP security headers

The application adds baseline response headers where not already present:

- **`X-Content-Type-Options: nosniff`**
- **`X-Frame-Options: SAMEORIGIN`**
- **`Referrer-Policy: strict-origin-when-cross-origin`**

These are **defense-in-depth** measures and complement, but do not replace, controls at reverse proxies and browsers.

## 8. Input validation and error handling

API inputs are validated with **schema-defined models** before business logic executes. Internal failures return **generic** error responses to clients; detailed diagnostics are intended for **server-side logs** only, reducing information leakage to untrusted callers.

## 9. Data and secrets

### 9.1 Configuration and bookkeeping data

Application configuration and JSON bookkeeping data may be stored on the local filesystem or, in cloud deployments, in **object storage** as described in deployment documentation. **Access to buckets, files, and backups** must be restricted and audited according to organizational policy.

### 9.2 Third-party credentials

Credentials for external systems (for example SiGREEN client credentials and, where used, AAS-related secrets) are stored in application configuration and may be persisted in the same stores as above. They must be treated as **confidential**.

### 9.3 Environment variables

Relevant variables include, among others:

| Variable | Role |
|----------|------|
| `BASIC_AUTH_USERNAME` / `BASIC_AUTH_PASSWORD` | Credentials for Basic-protected endpoints |
| `SESSION_SECRET_KEY` | Signing key for session cookies |
| `SESSION_COOKIE_SECURE` | Optional override for the `Secure` cookie flag |
| `TRUST_FORWARDED_HEADERS` | Whether to trust `X-Forwarded-For` for rate-limit identity |
| `ENVIRONMENT` | Drives defaults for session cookie security when `SESSION_COOKIE_SECURE` is unset |

See the project’s `.env.example` for the authoritative list and descriptions.

## 10. Logging and privacy

Logging is structured so that **failed logins** can be diagnosed without writing **passwords** to logs (for example length-based diagnostics in some paths). Operators should still treat logs as **sensitive** and apply access control and retention policies consistent with data protection requirements.

## 11. Residual risks and organizational controls

The following are **not** fully addressed by the application alone and should be covered by **architecture and operations**:

- **Rate limiting and DDoS protection** at scale (perimeter WAF, API gateway, cloud shields)
- **Cross-origin (CORS)** policy for browser access to APIs; the typical assumption is **trusted integration** rather than public browser clients
- **Central identity providers** (for example enterprise IdP) if password-based login is insufficient for policy
- **Dependency and container image vulnerability management** and patch cadence
- **Incident response** and **backup and recovery** for configuration and data stores
- **Strict-Transport-Security** and other policy headers at the **edge**, when appropriate for the deployment

Together, the in-application controls and these external measures form a **defence-in-depth** posture appropriate to the deployment context.

## 12. Document maintenance

This document should be reviewed when the application’s authentication model, data stores, or deployment targets change materially. Version control history and release notes should record substantive updates.

---

*End of document.*
