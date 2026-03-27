"""Unit tests for deterministic enrichment application behavior."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from bom_workbench.application.enrichment import BomEnrichmentUseCase
from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.ports import RawEvidence


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


def _build_use_case(rows: list[BomRow], evidence: list[RawEvidence]) -> BomEnrichmentUseCase:
    return BomEnrichmentUseCase(FakeRepository(rows), FakeRetriever(evidence))


def _make_row(**kwargs) -> BomRow:
    return BomRow(project_id=1, **kwargs)


@pytest.mark.parametrize(
    ("row_kwargs", "expected_field", "expected_value", "expected_source_url"),
    [
        (
            {
                "id": 1,
                "lcsc_part_number": "  C25744  ",
                "mpn": "MPN-IGNORED",
                "lcsc_link": "https://vendor.test/parts/C25744",
                "comment": "10k resistor",
            },
            "lcsc_part_number",
            "C25744",
            "https://vendor.test/parts/C25744",
        ),
        (
            {
                "id": 2,
                "lcsc_part_number": "",
                "mpn": "  ABC-123  ",
                "source_url": "https://vendor.test/parts/abc-123",
                "comment": "logic ic",
            },
            "mpn",
            "ABC-123",
            "https://vendor.test/parts/abc-123",
        ),
    ],
)
def test_resolve_search_keys_uses_priority_order(
    row_kwargs: dict[str, str | int],
    expected_field: str,
    expected_value: str,
    expected_source_url: str,
) -> None:
    use_case = _build_use_case([], [])
    row = _make_row(**row_kwargs)

    resolution = use_case.resolve_search_keys(row)

    assert resolution.priority_order[0] == "lcsc_part_number"
    assert resolution.primary_field == expected_field
    assert resolution.primary_value == expected_value
    assert resolution.search_keys.source_url == expected_source_url


@pytest.mark.anyio
async def test_enrich_row_without_evidence_marks_warning() -> None:
    row = _make_row(id=10, mpn="ABC123", comment="control ic")
    use_case = _build_use_case([row], [])

    enriched = await use_case.enrich_row(10)

    assert enriched.row_state == "warning"
    warnings = json.loads(enriched.validation_warnings)
    assert any("no results" in warning.lower() for warning in warnings)


@pytest.mark.anyio
async def test_enrich_row_without_search_keys_marks_failed() -> None:
    row = _make_row(id=11)
    retriever = FakeRetriever([])
    use_case = BomEnrichmentUseCase(FakeRepository([row]), retriever)

    enriched = await use_case.enrich_row(11)

    assert enriched.row_state == "failed"
    warnings = json.loads(enriched.validation_warnings)
    assert any("search keys" in warning.lower() for warning in warnings)
    assert retriever.calls == []


@pytest.mark.anyio
async def test_enrich_row_parses_evidence_deterministically() -> None:
    row = _make_row(id=12, lcsc_part_number="C777")
    evidence = [
        RawEvidence(
            source_url="https://vendor.test/part/C777",
            source_name="Vendor X",
            retrieved_at=datetime(2026, 3, 1, 12, 30, tzinfo=UTC),
            content_type="text/plain",
            raw_content=(
                "stock_qty: 250\n"
                "stock_status: in stock\n"
                "lifecycle_status: active\n"
            ),
            search_strategy="lcsc_part_number",
        )
    ]
    use_case = _build_use_case([row], evidence)

    enriched = await use_case.enrich_row(12)

    assert enriched.row_state == "enriched"
    assert enriched.stock_qty == 250
    assert enriched.stock_status == "high"
    assert enriched.lifecycle_status == "active"
    assert enriched.source_url == "https://vendor.test/part/C777"
    assert enriched.source_name == "Vendor X"
    assert enriched.last_checked_at == datetime(2026, 3, 1, 12, 30, tzinfo=UTC)
    assert enriched.evidence_blob
    assert enriched.raw_provider_response


@pytest.mark.anyio
async def test_enrich_rows_processes_batch_ids_in_order() -> None:
    rows = [
        _make_row(id=20, lcsc_part_number="C100"),
        _make_row(id=21, mpn="U200"),
    ]
    evidence = [
        RawEvidence(
            source_url="https://vendor.test/part/C100",
            source_name="Vendor X",
            retrieved_at=datetime(2026, 3, 2, 9, 0, tzinfo=UTC),
            content_type="text/plain",
            raw_content=(
                "stock_qty: 8\n"
                "stock_status: low stock\n"
                "lifecycle_status: active\n"
            ),
            search_strategy="lcsc_part_number",
        )
    ]
    use_case = _build_use_case(rows, evidence)

    enriched_rows = await use_case.enrich_rows([20, 21])

    assert [row.id for row in enriched_rows] == [20, 21]
    assert all(row.row_state == "enriched" for row in enriched_rows)
