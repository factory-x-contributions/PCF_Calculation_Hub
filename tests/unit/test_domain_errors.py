# SPDX-FileCopyrightText: Copyright Siemens 2026
# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the :mod:`app.domain.errors` exception hierarchy.

These tests are deliberately small. They guard against accidental
re-parenting (a future refactor moving ``IntegrationError`` out of
the ``PCFError`` tree would break the global FastAPI handler that
maps the whole tree to HTTP codes in Phase 5) and against accidental
deletion of a subclass.
"""
from __future__ import annotations

import pytest

from app.domain.errors import (
    ConfigurationError,
    DomainValidationError,
    IntegrationError,
    PCFError,
    PipelineSkipped,
)


@pytest.mark.parametrize(
    "subclass",
    [ConfigurationError, DomainValidationError, IntegrationError, PipelineSkipped],
)
def test_subclass_inherits_from_pcf_error(subclass: type[PCFError]) -> None:
    """Every domain error must be catchable as a PCFError so the FastAPI handler can reach it."""
    assert issubclass(subclass, PCFError)
    assert issubclass(subclass, Exception)


def test_pcf_error_root_does_not_inherit_from_subclasses() -> None:
    """Sanity: PCFError stays the root — no accidental cycles or sibling inheritance."""
    for subclass in (ConfigurationError, DomainValidationError, IntegrationError, PipelineSkipped):
        assert not issubclass(PCFError, subclass)


def test_subclasses_are_distinct() -> None:
    """The four leaves must not collapse into each other; the handler dispatches on type."""
    leaves = [ConfigurationError, DomainValidationError, IntegrationError, PipelineSkipped]
    for i, a in enumerate(leaves):
        for b in leaves[i + 1 :]:
            assert not issubclass(a, b), f"{a.__name__} should not inherit from {b.__name__}"
            assert not issubclass(b, a), f"{b.__name__} should not inherit from {a.__name__}"


def test_integration_error_preserves_cause_chain() -> None:
    """``raise IntegrationError(...) from exc`` is the canonical wrap pattern; verify __cause__ flows."""
    original = ValueError("downstream went boom")
    try:
        raise IntegrationError("SiGREEN POST failed") from original
    except IntegrationError as caught:
        assert caught.__cause__ is original
        assert str(caught) == "SiGREEN POST failed"


def test_can_be_caught_as_pcf_error() -> None:
    """A handler that catches only PCFError must catch every leaf — that is the contract."""
    for cls in (ConfigurationError, DomainValidationError, IntegrationError, PipelineSkipped):
        with pytest.raises(PCFError):
            raise cls("boom")
