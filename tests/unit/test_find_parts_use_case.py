"""Unit tests for deterministic replacement search and application."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from bom_workbench.application.find_parts import (
    FindPartsUseCase,
    PartFinderLLMSearchResponseSchema,
    PartSearchCriteria,
    PartFinderLLMResponseSchema,
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
async def test_find_candidates_with_row_and_criteria_uses_detached_context_copy() -> None:
    row = _make_row(
        id=5,
        lcsc_part_number="C11111",
        mpn="BASE-MPN",
        comment="original comment",
        footprint="0603",
        source_url="https://vendor.test/base",
    )
    repo = FakeRepository([row])
    evidence = _make_evidence(
        [
            {
                "manufacturer": "Gamma Components",
                "mpn": "ALT-MPN",
                "footprint": "0805",
                "value_summary": "override value",
                "stock_qty": 120,
                "lifecycle_status": "active",
                "confidence": "high",
            }
        ]
    )
    use_case = FindPartsUseCase(repo, FakeRetriever([evidence]))

    results = await use_case.find_candidates(
        row_id=5,
        criteria=PartSearchCriteria(
            part_number="C22222",
            source_url="https://vendor.test/override",
            comment="override comment",
            footprint="0805",
        ),
    )

    assert len(results) == 1
    assert use_case._retriever.calls[0].lcsc_part_number == "C22222"
    assert use_case._retriever.calls[0].source_url == "https://vendor.test/override"
    assert use_case._retriever.calls[0].comment == "override comment"
    assert use_case._retriever.calls[0].footprint == "0805"
    assert repo.rows[5].lcsc_part_number == "C11111"
    assert repo.rows[5].source_url == "https://vendor.test/base"
    assert repo.rows[5].comment == "original comment"
    assert repo.rows[5].footprint == "0603"


@pytest.mark.anyio
async def test_find_candidates_applies_requested_filters() -> None:
    evidence = _make_evidence(
        [
            {
                "manufacturer": "Good Parts",
                "mpn": "GOOD-1",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 250,
                "lifecycle_status": "active",
                "confidence": "high",
                "lcsc_part_number": "C12345",
                "lcsc_link": "https://www.lcsc.com/product-detail/C12345.html",
            },
            {
                "manufacturer": "Risky Parts",
                "mpn": "RISKY-1",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 250,
                "lifecycle_status": "eol",
                "confidence": "high",
                "lcsc_part_number": "C54321",
                "lcsc_link": "https://www.lcsc.com/product-detail/C54321.html",
            },
            {
                "manufacturer": "NoStock Parts",
                "mpn": "NOSTOCK-1",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 0,
                "lifecycle_status": "active",
                "confidence": "high",
                "lcsc_part_number": "C99999",
                "lcsc_link": "https://www.lcsc.com/product-detail/C99999.html",
            },
            {
                "manufacturer": "OffSite Parts",
                "mpn": "OFFSITE-1",
                "footprint": "0603",
                "value_summary": "10k resistor",
                "stock_qty": 250,
                "lifecycle_status": "active",
                "confidence": "high",
                "part_number": "ALT-1",
                "lcsc_link": "https://vendor.test/parts/alt-1",
            },
        ]
    )
    use_case = FindPartsUseCase(FakeRepository([]), FakeRetriever([evidence]))

    results = await use_case.find_candidates(
        criteria=PartSearchCriteria(
            part_number="C12345",
            footprint="0603",
            value="10k resistor",
            active_only=True,
            in_stock=True,
            lcsc_available=True,
        )
    )

    assert [result.candidate.mpn for result in results] == ["GOOD-1"]


@pytest.mark.anyio
async def test_find_candidates_applies_constraint_preferences() -> None:
    row = _make_row(
        id=8,
        mpn="CAP-100N",
        manufacturer="YAGEO",
        footprint="Capacitor_SMD:C_0603_1608Metric",
        package="0603",
        comment="100nF",
    )
    evidence = _make_evidence(
        [
            {
                "manufacturer": "YAGEO",
                "mpn": "MATCH-1",
                "footprint": "0603",
                "package": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 2500,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "KEMET",
                "mpn": "WRONG-MANUFACTURER",
                "footprint": "0603",
                "package": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 2500,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "YAGEO",
                "mpn": "WRONG-FOOTPRINT",
                "footprint": "0805",
                "package": "0805",
                "value_summary": "100nF capacitor",
                "stock_qty": 2500,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "YAGEO",
                "mpn": "LOW-STOCK",
                "footprint": "0603",
                "package": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 25,
                "lifecycle_status": "active",
                "confidence": "high",
            },
        ]
    )
    use_case = FindPartsUseCase(FakeRepository([row]), FakeRetriever([evidence]))

    results = await use_case.find_candidates(
        row_id=8,
        criteria=PartSearchCriteria(
            keep_same_footprint=True,
            keep_same_manufacturer=True,
            minimum_stock_qty=100,
        ),
    )

    assert [result.candidate.mpn for result in results] == ["MATCH-1"]


@pytest.mark.anyio
async def test_find_candidates_prefers_high_availability() -> None:
    row = _make_row(id=9, comment="100nF capacitor", footprint="0603")
    evidence = _make_evidence(
        [
            {
                "manufacturer": "Alpha Parts",
                "mpn": "LOW-QTY",
                "footprint": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 150,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "Beta Parts",
                "mpn": "HIGH-QTY",
                "footprint": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 250000,
                "lifecycle_status": "active",
                "confidence": "high",
            },
        ]
    )
    use_case = FindPartsUseCase(FakeRepository([row]), FakeRetriever([evidence]))

    results = await use_case.find_candidates(
        row_id=9,
        criteria=PartSearchCriteria(prefer_high_availability=True),
    )

    assert results[0].candidate.mpn == "HIGH-QTY"
    assert "Availability preference bonus applied" in results[0].explanation


@pytest.mark.anyio
async def test_find_candidates_applies_grounded_llm_rerank() -> None:
    row = _make_row(id=10, comment="100nF capacitor", footprint="0603")
    evidence = _make_evidence(
        [
            {
                "manufacturer": "Alpha Parts",
                "mpn": "ALPHA-1",
                "footprint": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 500,
                "lifecycle_status": "active",
                "confidence": "high",
            },
            {
                "manufacturer": "Beta Parts",
                "mpn": "BETA-1",
                "footprint": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 500,
                "lifecycle_status": "active",
                "confidence": "high",
            },
        ]
    )

    async def fake_llm_stage(row, criteria, candidates):  # noqa: ANN001
        assert row.id == 10
        assert criteria.keep_same_footprint is True
        assert len(candidates) == 2
        return PartFinderLLMResponseSchema(
            ranked_candidates=[
                {
                    "candidate_id": "candidate_1",
                    "keep": True,
                    "adjusted_score": 0.30,
                    "rationale": "Acceptable fallback.",
                },
                {
                    "candidate_id": "candidate_2",
                    "keep": True,
                    "adjusted_score": 0.98,
                    "rationale": "Best supply profile and fit.",
                },
            ],
            summary="Prefer candidate_2.",
        )

    use_case = FindPartsUseCase(
        FakeRepository([row]),
        FakeRetriever([evidence]),
        llm_stage=fake_llm_stage,
    )

    results = await use_case.find_candidates(
        row_id=10,
        criteria=PartSearchCriteria(keep_same_footprint=True),
    )

    assert results[0].candidate.mpn == "BETA-1"
    assert "LLM rerank" in results[0].explanation


@pytest.mark.anyio
async def test_find_candidates_expands_search_with_grounded_llm_leads() -> None:
    row = _make_row(id=13, comment="100nF", footprint="0603", category="Capacitors/Ceramic Capacitors")

    initial_evidence = _make_evidence(
        [
            {
                "manufacturer": "Fallback Parts",
                "mpn": "FALLBACK-1",
                "footprint": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 50,
                "lifecycle_status": "active",
                "confidence": "high",
            }
        ]
    )
    expanded_evidence = _make_evidence(
        [
            {
                "manufacturer": "YAGEO",
                "mpn": "CC0603KRX7R9BB104",
                "footprint": "0603",
                "value_summary": "100nF capacitor",
                "stock_qty": 2314200,
                "lifecycle_status": "active",
                "confidence": "high",
                "lcsc_part_number": "C14663",
                "lcsc_link": "https://www.lcsc.com/product-detail/C14663.html",
            }
        ],
        strategy="llm_search_lead",
    )

    class SearchAwareRetriever:
        def __init__(self) -> None:
            self.calls: list[object] = []

        async def retrieve(self, search_keys: object) -> list[RawEvidence]:
            self.calls.append(search_keys)
            if getattr(search_keys, "lcsc_part_number", "") == "C14663":
                return [expanded_evidence]
            return [initial_evidence]

    async def fake_llm_search_stage(row, criteria, search_resolution, candidates):  # noqa: ANN001
        assert row.id == 13
        assert search_resolution.primary_field in {"comment", "footprint", "category"}
        assert len(candidates) == 1
        return PartFinderLLMSearchResponseSchema(
            search_leads=[
                {
                    "lcsc_part_number": "C14663",
                    "footprint": "0603",
                    "category": "Capacitors/Ceramic Capacitors",
                    "param_summary": "100nF capacitor",
                    "rationale": "Known high-availability equivalent.",
                }
            ],
            summary="Expand with one strong LCSC lead.",
        )

    retriever = SearchAwareRetriever()
    use_case = FindPartsUseCase(
        FakeRepository([row]),
        retriever,
        llm_search_stage=fake_llm_search_stage,
    )

    results = await use_case.find_candidates(row_id=13)

    assert len(retriever.calls) == 2
    assert results[0].candidate.lcsc_part_number == "C14663"


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


@pytest.mark.anyio
async def test_build_replacement_batches_groups_similar_rows() -> None:
    use_case = FindPartsUseCase(FakeRepository([]), FakeRetriever([]))
    rows = [
        _make_row(id=20, mpn="CAP-100N", designator="C1", footprint="0603", comment="100nF"),
        _make_row(id=21, mpn="CAP-100N", designator="C2", footprint="0603", comment="100nF"),
        _make_row(id=22, mpn="REG-3V3", designator="U1", footprint="SOT-223", comment="3.3V regulator"),
    ]

    batches = use_case.build_replacement_batches(rows)

    assert len(batches) == 2
    assert batches[0].row_ids == (20, 21)
    assert batches[0].designators == ("C1", "C2")
    assert batches[0].exemplar_row_id == 20
    assert batches[1].row_ids == (22,)


@pytest.mark.anyio
async def test_apply_replacement_to_rows_updates_each_row() -> None:
    row_a = _make_row(id=30, mpn="OLD-A", comment="old part a")
    row_b = _make_row(id=31, mpn="OLD-B", comment="old part b")
    repo = FakeRepository([row_a, row_b])
    use_case = FindPartsUseCase(repo, FakeRetriever([]))
    candidate = _make_candidate(
        manufacturer="Acme",
        mpn="ACM-BULK",
        footprint="0603",
        package="0603",
        value_summary="10k resistor",
        lcsc_link="https://vendor.test/parts/acm-bulk",
        lcsc_part_number="C54321",
        stock_qty=250,
        lifecycle_status=LifecycleStatus.ACTIVE,
        confidence=Confidence.HIGH,
        match_score=0.91,
        match_explanation="Strong grouped match",
        part_number="C54321",
        description="10k resistor",
        stock_status="high",
    )

    results = await use_case.apply_replacement_to_rows([30, 31], candidate, confirmed=True)

    assert len(results) == 2
    assert row_a.mpn == "ACM-BULK"
    assert row_b.mpn == "ACM-BULK"
    assert row_a.replacement_status == "user_accepted"
    assert row_b.replacement_status == "user_accepted"
