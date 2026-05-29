# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Application use cases — explicit orchestrators for each HTTP / pipeline entry point.

Use cases are constructed at the composition root (:mod:`app.core.container`)
and exposed to FastAPI routers through ``Depends`` factories in
:mod:`app.api.deps`. Tests can substitute fakes either by passing port
implementations directly into a constructor (unit tests) or by overriding
the ``Depends`` factory via ``app.dependency_overrides`` (router tests).
"""
