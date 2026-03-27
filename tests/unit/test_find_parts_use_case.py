"""Unit tests for deterministic replacement search and application."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from bom_workbench.application.find_parts import (
    FindPartsUseCase,
    PartSearchCriteria,
    ReplacementConfirmationRequired,
)
from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.enums import Confidence, LifecycleStatus
from bom_workbench.domain.ports import RawEvidence
from bom_workbench.domain.value_objects import EvidenceRecord, ReplacementCandidate


class FakeRepository:
    def __init__(self, rows: list[BomRow]) -> None:
        self.rows = {row.id: row for row in rows if row.id is not None}
        self.saved_rows: list[BomRow] = []

    async def get_row(self, row_id: int) -> BomRow | None:
        return self.rows.get(row_id)

    async def save_row(self, row: BomRow) -> BomRow:
        if row.id is not None:
            self.rows[row.id] = row
        self.saved_rows.append(row)
        return row


class FakeRetriever:
    def __init__(self, evidence: list[RawEvidence]) -> None:
        self.evidence = evidence
        self.calls: list[object] = []

    async def retrieve(self, search_keys: object) -> list[RawEvidence]:
        self.calls.append(search_keys)
        return self.evidence


def _make_row(**kwargs) -> BomRow:
    return BomRow(project_id=1, **kwargs)


def _make_evidence(payload: object, *, strategy: str = "candidate_scan") -> RawEvidence:
    return RawEvidence(
        source_url="https://vendor.test/search",
        source_name="Vendor Test",
        retrieved_at=datetime(2026, 3, 27, 12, 0, tzinfo=UTC),
        content_type="application/json",
        raw_content=json.dumps(payload, separators=(",", ":"), sort_keys=True),
        search_strategy=strategy,
    )


def _make_candidate(**kwargs) -> ReplacementCandidate:
    return ReplacementCandidate(
        manufacturer=kwargs.get("manufacturer", ""),
        mpn=kwargs.get("mpn", ""),
        footprint=kwargs.get("footprint", ""),
        package=kwargs.get("package", ""),
        value_summary=kwargs.get("value_summary", ""),
        lcsc_link=kwargs.get("lcsc_link", ""),
        lcsc_part_number=kwargs.get("lcsc_part_number", ""),
        stock_qty=kwargs.get("stock_qty"),
        lifecycle_status=kwargs.get("lifecycle_status", LifecycleStatus.UNKNOWN),
        confidence=kwargs.get("confidence", Confidence.NONE),
        match_score=kwargs.get("match_score", 0.0),
        match_explanation=kwargs.get("match_explanation", ""),
        differences=kwargs.get("differences", ""),
        warnings=kwargs.get("warnings", []),
        evidence=kwargs.get("evidence", []),
        part_number=kwargs.get("part_number", ""),
        description=kwargs.get("description", ""),
        stock_status=kwargs.get("stock_status", ""),
    )


@pytest.mark.anyio
async def test_find_candidates_from_row_is_deterministic() -> None:
    row = _make_row(
        id=1,
        mpn="R-0603-10K",
        comment="10k resistor",
        footprint="0603",
    )
    evidence_a = _make_evidence(
        [
            {
                "manufacturer": "Beta Parts",
                "mpn": "R-0603-10K-B",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 50,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "Alpha Parts",
                "mpn": "R-0603-10K-A",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 50,
                "lifecycle_status": "active",
                "confidence": "high",
            },
        ]
    )
    evidence_b = _make_evidence(
        [
            {
                "manufacturer": "Alpha Parts",
                "mpn": "R-0603-10K-A",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 50,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "Beta Parts",
                "mpn": "R-0603-10K-B",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 50,
                "lifecycle_status": "active",
                "confidence": "high",
            },
        ]
    )

    use_case_a = FindPartsUseCase(FakeRepository([row]), FakeRetriever([evidence_a]))
    use_case_b = FindPartsUseCase(FakeRepository([row]), FakeRetriever([evidence_b]))

    results_a = await use_case_a.find_candidates_for_row(1)
    results_b = await use_case_b.find_candidates_for_row(1)

    assert [result.candidate.mpn for result in results_a] == [
        "R-0603-10K-A",
        "R-0603-10K-B",
    ]
    assert [result.candidate.mpn for result in results_b] == [
        "R-0603-10K-A",
        "R-0603-10K-B",
    ]
    assert [result.score for result in results_a] == [result.score for result in results_b]
    assert [result.explanation for result in results_a] == [
        result.explanation for result in results_b
    ]
    assert use_case_a._retriever.calls[0].mpn == "R-0603-10K"


@pytest.mark.anyio
async def test_find_candidates_from_explicit_criteria_uses_priority_order() -> None:
    evidence = _make_evidence(
        [
            {
                "manufacturer": "Gamma Components",
                "mpn": "C12345-ALT",
                "footprint": "0402",
                "value_summary": "10k resistor",
                "stock_qty": 120,
                "lifecycle_status": "active",
                "confidence": "high",
            }
        ]
    )
    use_case = FindPartsUseCase(FakeRepository([]), FakeRetriever([evidence]))

    results = await use_case.find_candidates(
        criteria=PartSearchCriteria(part_number="C12345", footprint="0402", value="10k resistor")
    )

    assert len(results) == 1
    assert use_case._retriever.calls[0].lcsc_part_number == "C12345"
    assert use_case._retriever.calls[0].footprint == "0402"
    assert results[0].candidate.mpn == "C12345-ALT"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "candidate_payload",
    [
        {
            "manufacturer": "Delta Parts",
            "mpn": "DIFF-123",
            "footprint": "0402",
            "value_summary": "1uF capacitor",
            "stock_qty": 250,
            "lifecycle_status": "active",
            "confidence": "high",
        },
        {
            "manufacturer": "Omega Parts",
            "mpn": "R-0603-10K",
            "footprint": "0603",
            "value_summary": "10k resistor",
            "stock_qty": 0,
            "lifecycle_status": "eol",
            "confidence": "high",
        },
    ],
)
async def test_find_candidates_flags_manual_review_for_low_score_or_risky_supply(
    candidate_payload: dict[str, object],
) -> None:
    row = _make_row(
        id=7,
        mpn="R-0603-10K",
        comment="10k resistor",
        footprint="0603",
    )
    evidence = _make_evidence([candidate_payload])
    use_case = FindPartsUseCase(FakeRepository([row]), FakeRetriever([evidence]))

    results = await use_case.find_candidates_for_row(7)

    assert results[0].requires_manual_review is True
    if candidate_payload["mpn"] == "R-0603-10K":
        assert results[0].score == pytest.approx(0.95)
    else:
        assert results[0].score < 0.75


@pytest.mark.anyio
async def test_apply_replacement_requires_confirmation_before_persisting() -> None:
    row = _make_row(id=11, mpn="OLD-1", comment="old part")
    repo = FakeRepository([row])
    use_case = FindPartsUseCase(repo, FakeRetriever([]))
    candidate = _make_candidate(
        manufacturer="Acme",
        mpn="ACM-123",
        footprint="0603",
        package="0603",
        value_summary="10k resistor",
        lcsc_link="https://vendor.test/parts/acm-123",
        lcsc_part_number="C12345",
        stock_qty=500,
        lifecycle_status=LifecycleStatus.ACTIVE,
        confidence=Confidence.HIGH,
        match_score=0.94,
        match_explanation="Strong match",
        part_number="C12345",
        description="10k resistor",
        stock_status="high",
    )

    with pytest.raises(ReplacementConfirmationRequired):
        await use_case.apply_replacement(11, candidate, confirmed=False)

    assert repo.saved_rows == []
    assert repo.rows[11].mpn == "OLD-1"


@pytest.mark.anyio
async def test_apply_replacement_persists_selected_supplier_fields() -> None:
    row = _make_row(id=12, mpn="OLD-2", comment="old part", footprint="0402")
    repo = FakeRepository([row])
    use_case = FindPartsUseCase(repo, FakeRetriever([]))
    candidate = _make_candidate(
        manufacturer="Acme",
        mpn="ACM-123",
        footprint="0603",
        package="0603",
        value_summary="10k resistor",
        lcsc_link="https://vendor.test/parts/acm-123",
        lcsc_part_number="C12345",
        stock_qty=500,
        lifecycle_status=LifecycleStatus.ACTIVE,
        confidence=Confidence.HIGH,
        match_score=0.94,
        match_explanation="Strong match",
        part_number="C12345",
        description="10k resistor",
        stock_status="high",
    )

    result = await use_case.apply_replacement(12, candidate, confirmed=True)

    assert result.applied is True
    assert repo.saved_rows == [row]
    assert row.replacement_candidate_part_number == "C12345"
    assert row.replacement_candidate_mpn == "ACM-123"
    assert row.replacement_candidate_link == "https://vendor.test/parts/acm-123"
    assert row.replacement_status == "user_accepted"
    assert row.user_accepted_replacement is True
    assert row.mpn == "ACM-123"
    assert row.footprint == "0603"
    assert row.stock_status == "high"
    assert row.lifecycle_status == "active"
    assert row.source_url == "https://vendor.test/parts/acm-123"
    assert row.source_confidence == "high"
    assert "Applied replacement" in row.sourcing_notes
