"""Unit tests for enrichment row state transition guards."""

from __future__ import annotations

import pytest

from bom_workbench.application.state_machine import (
    RowStateTransition,
    transition_row_state,
    validate_row_state_transition,
)
from bom_workbench.domain.entities import BomRow


def test_validate_row_state_transition_allows_expected_path() -> None:
    transition = validate_row_state_transition("queued", "enriching")

    assert transition == RowStateTransition(current_state="queued", next_state="enriching")


def test_transition_row_state_mutates_row_in_place() -> None:
    row = BomRow(project_id=1, row_state="queued")

    transition = transition_row_state(row, "enriching")

    assert row.row_state == "enriching"
    assert transition.current_state == "queued"
    assert transition.next_state == "enriching"


def test_validate_row_state_transition_rejects_illegal_path() -> None:
    with pytest.raises(ValueError):
        validate_row_state_transition("imported", "enriched")

