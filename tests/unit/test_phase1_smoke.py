"""Phase 1 smoke tests."""

from __future__ import annotations

from bom_workbench.app import bootstrap


def test_bootstrap_returns_success() -> None:
    """Bootstrap should exit cleanly during Phase 1."""
    assert bootstrap([]) == 0
