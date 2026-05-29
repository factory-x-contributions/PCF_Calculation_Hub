# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Application-layer strategy pipelines.

Each module here implements a :class:`Protocol` defined in :mod:`app.application.ports`.
Strategies are picked at the composition root (:mod:`app.core.container`) based on
runtime configuration so use-cases stay independent of the concrete implementation.
"""
