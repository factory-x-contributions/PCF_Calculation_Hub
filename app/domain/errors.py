# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Domain exception hierarchy for the PCF Calculation Hub.

A single tree rooted at :class:`PCFError` lets the FastAPI handler in
:mod:`app.main` map every business-meaningful failure to a stable HTTP
response without leaking framework or library exception types across the
application boundary. ``PCFError`` itself should never be raised directly;
raise one of the four subclasses instead.

Mapping applied by the global exception handler (Phase 5):

* :class:`ConfigurationError`     -> HTTP 503 (service mis-configured)
* :class:`DomainValidationError`  -> HTTP 400 (caller violated a rule)
* :class:`IntegrationError`       -> HTTP 502 (downstream system failed)
* :class:`PipelineSkipped`        -> not an error; logged and swallowed
"""
from __future__ import annotations


class PCFError(Exception):
    """Root of the PCF Calculation Hub exception tree. Do not raise directly."""


class ConfigurationError(PCFError):
    """Required configuration is missing, malformed, or unresolved.

    Examples: empty SiGREEN credentials when authentication is required,
    factory_id that could not be resolved, an unknown ``data_source`` value,
    a material identifier mapping that does not match any SiGREEN component.
    """


class DomainValidationError(PCFError):
    """A caller-supplied input violates a business rule.

    Examples: ``/productionResults`` for a work order that has no prior
    consumption rows, an unsupported energy unit-of-measure, a negative
    quantity. Distinct from FastAPI's automatic 422 (which covers schema
    failures) — this is for rules that survive schema validation.
    """


class IntegrationError(PCFError):
    """A downstream system (SiGREEN, AAS server, Green Grid Compass) failed.

    Always wraps the original cause via ``raise IntegrationError(...) from
    exc`` so the traceback is preserved for diagnostics while the
    user-visible response stays generic.
    """


class PipelineSkipped(PCFError):
    """Control-flow signal: the current pipeline iteration should be skipped.

    Used by the AAS polling loop to declare "this shell is not ready / has
    already been processed / has no producible PCF" without treating that
    as an error. Replaces the legacy ``_ShellSkipped`` sentinel in
    :mod:`app.services.aas_service`. The global exception handler swallows
    this subclass; it never reaches an HTTP response.
    """


__all__ = [
    "PCFError",
    "ConfigurationError",
    "DomainValidationError",
    "IntegrationError",
    "PipelineSkipped",
]
