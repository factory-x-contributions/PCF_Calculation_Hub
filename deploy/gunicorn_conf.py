# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path

# Disable Python output buffering so logs appear in CloudWatch / journald immediately
os.environ.setdefault("PYTHONUNBUFFERED", "1")

# Single listener on PORT_HTTPS (default 8443); TLS when cert/key exist, else HTTP on that port
port_https = os.environ.get("PORT_HTTPS", "8443")
ssl_certfile = os.environ.get("SSL_CERTFILE") or "cert.pem"
ssl_keyfile = os.environ.get("SSL_KEYFILE") or "key.pem"

# Resolve cert/key paths relative to project root (current working directory when gunicorn starts)
_cert = Path(ssl_certfile).expanduser().resolve()
_key = Path(ssl_keyfile).expanduser().resolve()
_ssl_available = _cert.is_file() and _key.is_file()

bind = f"0.0.0.0:{port_https}"
if _ssl_available:
    certfile = str(_cert)
    keyfile = str(_key)

# Use 1 worker so Application Logs panel shows AAS/background thread logs (in-memory buffer is per-worker).
# Set GUNICORN_WORKERS=4 for production if needed, but /api/logs will then miss worker-isolated logs.
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 60
keepalive = 5
loglevel = "info"
accesslog = "-"  # stdout — visible in CloudWatch / journald
errorlog = "-"  # stdout
