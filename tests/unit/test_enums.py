"""Baseline tests for domain enum contracts."""

from __future__ import annotations

from enum import Enum

import pytest


enums = pytest.importorskip("bom_workbench.domain.enums")


def _enum_values(enum_cls: type[Enum]) -> list[str]:
    return [member.value for member in enum_cls]


def test_enum_types_are_string_enums() -> None:
    """Every domain enum should remain a str-backed Enum for serialization."""
    expected_names = [
        "LifecycleStatus",
        "StockBucket",
        "EolRisk",
        "RowState",
        "ReplacementStatus",
        "JobState",
        "Confidence",
        "EvidenceType",
    ]

    for name in expected_names:
        enum_cls = getattr(enums, name)
        assert issubclass(enum_cls, str)
        assert issubclass(enum_cls, Enum)


def test_enum_presence_and_values() -> None:
    """Enum members should match the documented phase-2 data model."""
    assert _enum_values(enums.LifecycleStatus) == [
        "active",
        "nrnd",
        "last_time_buy",
        "eol",
        "unknown",
    ]
    assert _enum_values(enums.StockBucket) == ["out", "low", "medium", "high", "unknown"]
    assert _enum_values(enums.EolRisk) == ["low", "medium", "high", "unknown"]
    assert _enum_values(enums.RowState) == [
        "imported",
        "pending",
        "queued",
        "enriching",
        "enriched",
        "warning",
        "failed",
        "cancelled",
        "skipped_by_user",
        "user_reviewed",
    ]
    assert _enum_values(enums.ReplacementStatus) == [
        "none",
        "candidates_found",
        "user_accepted",
        "user_rejected",
    ]
    assert _enum_values(enums.JobState) == [
        "pending",
        "queued",
        "running",
        "paused",
        "completed",
        "completed_with_errors",
        "failed",
        "cancelled",
    ]
    assert _enum_values(enums.Confidence) == ["high", "medium", "low", "none"]
    assert _enum_values(enums.EvidenceType) == ["observed", "inferred", "estimated", "unknown"]
