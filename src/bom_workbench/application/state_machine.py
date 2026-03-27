"""Row state transition helpers for enrichment workflows."""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.enums import RowState

__all__ = [
    "ROW_STATE_TRANSITIONS",
    "RowStateTransition",
    "normalize_row_state",
    "transition_row_state",
    "validate_row_state_transition",
]


ROW_STATE_TRANSITIONS: dict[str, set[str]] = {
    RowState.IMPORTED.value: {RowState.QUEUED.value, RowState.FAILED.value},
    RowState.PENDING.value: {RowState.QUEUED.value, RowState.FAILED.value},
    RowState.QUEUED.value: {RowState.ENRICHING.value, RowState.FAILED.value},
    RowState.ENRICHING.value: {
        RowState.ENRICHED.value,
        RowState.WARNING.value,
        RowState.FAILED.value,
    },
    RowState.ENRICHED.value: {RowState.QUEUED.value},
    RowState.WARNING.value: {RowState.QUEUED.value},
    RowState.FAILED.value: {RowState.QUEUED.value},
    RowState.CANCELLED.value: set(),
    RowState.SKIPPED_BY_USER.value: set(),
    RowState.USER_REVIEWED.value: {RowState.QUEUED.value},
}


@dataclass(slots=True, frozen=True)
class RowStateTransition:
    """A validated state hop for a BOM row."""

    current_state: str
    next_state: str


def normalize_row_state(value: object) -> str:
    """Normalize a state value to the canonical string form."""

    if isinstance(value, RowState):
        return value.value
    if value is None:
        return ""
    text = str(value).strip().casefold()
    return text


def validate_row_state_transition(current_state: object, next_state: object) -> RowStateTransition:
    """Raise if a row state transition is not allowed."""

    current = normalize_row_state(current_state)
    next_value = normalize_row_state(next_state)
    if not next_value:
        raise ValueError("Next row state is required.")
    if current == next_value:
        return RowStateTransition(current_state=current, next_state=next_value)

    allowed = ROW_STATE_TRANSITIONS.get(current, set())
    if next_value not in allowed:
        raise ValueError(f"Invalid row state transition: {current or '<empty>'} -> {next_value}")
    return RowStateTransition(current_state=current, next_state=next_value)


def transition_row_state(row: object, next_state: object) -> RowStateTransition:
    """Validate and apply a row state transition in place."""

    current_state = getattr(row, "row_state", "")
    transition = validate_row_state_transition(current_state, next_state)
    setattr(row, "row_state", transition.next_state)
    return transition
