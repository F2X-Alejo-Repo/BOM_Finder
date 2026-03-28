"""Unit tests for deterministic enrichment application behavior."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from bom_workbench.application.enrichment import (
    BomEnrichmentUseCase,
    EnrichmentExecutionResult,
    LLMEnrichmentOutcome,
    LLMEnrichmentPatch,
    LLMEnrichmentRequest,
)
from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.ports import RawEvidence

_C14663_SEARCH_SHELL_HTML = """<!doctype html>
<html lang="en">
  <head>
    <title>LCSC Electronics - Electronic Components Distributor</title>
    <link rel="shortcut icon" href="https://static.lcsc.com/feassets/pc/images/favicon.ico">
  </head>
  <body>
    <script>window.__NUXT__=function(e){return{layout:"v2Main",routePath:"/search",config:{}}}(null)</script>
    <div>Search shell only, no product data for C14663.</div>
  </body>
</html>"""

_C14663_STRUCTURED_PAYLOAD = {
    "source_url": "https://www.lcsc.com/product-detail/C14663.html",
    "source_name": "LCSC",
    "lcsc_part_number": "C14663",
    "product_name": "YAGEO CC0603KRX7R9BB104",
    "manufacturer": "YAGEO",
    "mpn": "CC0603KRX7R9BB104",
    "category": "Capacitors/Ceramic Capacitors",
    "package": "0603",
    "description": "100nF ±10% 50V Ceramic Capacitor X7R 0603",
    "param_summary": "100nF ±10% 50V Ceramic Capacitor X7R 0603",
    "stock_qty": 2314200,
    "stock_status": "high",
    "lifecycle_status": "active",
    "product_cycle": "normal",
    "moq": 100,
    "order_multiple": 100,
    "standard_pack_quantity": 4000,
    "packaging": "Tape & Reel (TR)",
    "price_currency": "USD",
    "unit_price_usd": 0.0015,
    "price_tiers": [
        {"quantity": 100, "unit_price_usd": 0.0028, "extended_price_usd": 0.28, "currency": "$"},
        {"quantity": 4000, "unit_price_usd": 0.0018, "extended_price_usd": 7.2, "currency": "$"},
        {"quantity": 48000, "unit_price_usd": 0.0015, "extended_price_usd": 72.0, "currency": "$"},
    ],
}


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


class FakeLlmStage:
    def __init__(self, result: LLMEnrichmentOutcome | None) -> None:
        self.result = result
        self.calls: list[tuple[int | None, LLMEnrichmentRequest]] = []

    async def __call__(
        self,
        row: BomRow,
        request: LLMEnrichmentRequest,
    ) -> LLMEnrichmentOutcome | None:
        self.calls.append((row.id, request))
        return self.result


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


@pytest.mark.anyio
async def test_enrich_row_applies_llm_patch_and_metadata() -> None:
    row = _make_row(id=30, lcsc_part_number="C900")
    evidence = [
        RawEvidence(
            source_url="https://vendor.test/part/C900",
            source_name="Vendor X",
            retrieved_at=datetime(2026, 3, 4, 10, 0, tzinfo=UTC),
            content_type="text/plain",
            raw_content="stock_qty: 15\nstock_status: medium\nlifecycle_status: active\n",
            search_strategy="lcsc_part_number",
        )
    ]
    llm_stage = FakeLlmStage(
        LLMEnrichmentOutcome(
            success=True,
            provider_name="openai",
            model_name="gpt-4.1-mini",
            patch=LLMEnrichmentPatch(
                moq=5,
                eol_risk="medium",
                source_confidence="high",
                sourcing_notes="Supplier page indicates MOQ 5.",
            ),
            raw_response='{"moq": 5}',
        )
    )
    use_case = BomEnrichmentUseCase(
        FakeRepository([row]),
        FakeRetriever(evidence),
        llm_stage=llm_stage,
    )

    enriched = await use_case.enrich_row(30)

    assert enriched.row_state == "enriched"
    assert enriched.moq == 5
    assert enriched.eol_risk == "medium"
    assert enriched.source_confidence == "high"
    assert "MOQ 5" in enriched.sourcing_notes
    assert enriched.enrichment_provider == "openai"
    assert enriched.enrichment_model == "gpt-4.1-mini"
    assert "llm-grounded-v1" in enriched.evidence_blob
    assert llm_stage.calls


@pytest.mark.anyio
async def test_enrich_row_with_result_exposes_llm_telemetry() -> None:
    row = _make_row(id=300, lcsc_part_number="C900")
    evidence = [
        RawEvidence(
            source_url="https://vendor.test/part/C900",
            source_name="Vendor X",
            retrieved_at=datetime(2026, 3, 4, 10, 0, tzinfo=UTC),
            content_type="text/plain",
            raw_content="stock_qty: 15\nstock_status: medium\nlifecycle_status: active\n",
            search_strategy="lcsc_part_number",
        )
    ]
    llm_stage = FakeLlmStage(
        LLMEnrichmentOutcome(
            success=False,
            provider_name="openai",
            model_name="gpt-4.1-mini",
            latency_ms=812.0,
            usage={"total_tokens": 4321},
            error_category="rate_limit",
            retry_after_seconds=2.5,
            error_message="OpenAI structured chat failed with HTTP 429.",
        )
    )
    use_case = BomEnrichmentUseCase(
        FakeRepository([row]),
        FakeRetriever(evidence),
        llm_stage=llm_stage,
    )

    result = await use_case.enrich_row_with_result(300)

    assert isinstance(result, EnrichmentExecutionResult)
    assert result.success is True
    assert result.telemetry.latency_ms == 812.0
    assert result.telemetry.usage["total_tokens"] == 4321
    assert result.telemetry.rate_limited is True
    assert result.telemetry.retry_after_seconds == 2.5


@pytest.mark.anyio
async def test_enrich_row_merges_deterministic_and_llm_warnings() -> None:
    row = _make_row(id=31, lcsc_part_number="C901")
    evidence = [
        RawEvidence(
            source_url="https://vendor.test/part/C901",
            source_name="Vendor X",
            retrieved_at=datetime(2026, 3, 4, 10, 0, tzinfo=UTC),
            content_type="text/plain",
            raw_content="stock_qty: 15\n",
            search_strategy="lcsc_part_number",
        )
    ]
    llm_stage = FakeLlmStage(
        LLMEnrichmentOutcome(
            success=True,
            provider_name="openai",
            model_name="gpt-4.1-mini",
            patch=LLMEnrichmentPatch(
                source_confidence="high",
                sourcing_notes="Confirmed from a grounded supplier page.",
                validation_warnings=["LLM could not confirm lead time."],
            ),
            warnings=["Model suggested a confidence downgrade."],
            raw_response='{"source_confidence":"high"}',
        )
    )
    use_case = BomEnrichmentUseCase(
        FakeRepository([row]),
        FakeRetriever(evidence),
        llm_stage=llm_stage,
    )

    enriched = await use_case.enrich_row(31)

    assert enriched.row_state == "warning"
    warnings = json.loads(enriched.validation_warnings)
    assert any("lifecycle status" in warning.lower() for warning in warnings)
    assert any("lead time" in warning.lower() for warning in warnings)
    assert enriched.source_confidence == "high"
    assert "grounded supplier page" in enriched.sourcing_notes.lower()


@pytest.mark.anyio
async def test_enrich_row_marks_warning_when_llm_stage_raises() -> None:
    row = _make_row(id=32, lcsc_part_number="C902")
    evidence = [
        RawEvidence(
            source_url="https://vendor.test/part/C902",
            source_name="Vendor X",
            retrieved_at=datetime(2026, 3, 4, 10, 0, tzinfo=UTC),
            content_type="text/plain",
            raw_content="stock_qty: 15\nlifecycle_status: active\n",
            search_strategy="lcsc_part_number",
        )
    ]

    class RaisingStage:
        async def __call__(self, row: BomRow, request: LLMEnrichmentRequest) -> None:  # noqa: ARG002
            raise RuntimeError("provider timeout")

    use_case = BomEnrichmentUseCase(
        FakeRepository([row]),
        FakeRetriever(evidence),
        llm_stage=RaisingStage(),
    )

    enriched = await use_case.enrich_row(32)

    assert enriched.row_state == "warning"
    warnings = json.loads(enriched.validation_warnings)
    assert any("grounded llm stage" in warning.lower() for warning in warnings)
    assert enriched.stock_qty == 15


@pytest.mark.anyio
async def test_enrich_row_does_not_extract_garbage_from_generic_lcsc_shell_html() -> None:
    row = _make_row(
        id=33,
        lcsc_part_number="C14663",
        lcsc_link="https://jlcpcb.com/partdetail/Yageo-CC0603KRX7R9BB104/C14663",
    )
    evidence = [
        RawEvidence(
            source_url="https://www.lcsc.com/search?searchTerm=C14663",
            source_name="LCSC",
            retrieved_at=datetime(2026, 3, 27, 21, 42, tzinfo=UTC),
            content_type="text/html",
            raw_content=_C14663_SEARCH_SHELL_HTML,
            search_strategy="lcsc_part_number",
        )
    ]
    use_case = _build_use_case([row], evidence)

    enriched = await use_case.enrich_row(33)

    assert enriched.row_state == "warning"
    assert enriched.stock_qty is None
    assert enriched.source_url == "https://jlcpcb.com/partdetail/Yageo-CC0603KRX7R9BB104/C14663"
    assert "favicon.ico" not in enriched.source_url
    warnings = json.loads(enriched.validation_warnings)
    assert any("no stock quantity" in warning.lower() for warning in warnings)
    assert any("no lifecycle status" in warning.lower() for warning in warnings)


@pytest.mark.anyio
async def test_enrich_row_applies_structured_c14663_payload_fields() -> None:
    row = _make_row(
        id=34,
        lcsc_part_number="C14663",
        lcsc_link="https://jlcpcb.com/partdetail/Yageo-CC0603KRX7R9BB104/C14663",
    )
    evidence = [
        RawEvidence(
            source_url="https://www.lcsc.com/product-detail/C14663.html",
            source_name="LCSC",
            retrieved_at=datetime(2026, 3, 27, 23, 32, tzinfo=UTC),
            content_type="application/json",
            raw_content=json.dumps(_C14663_STRUCTURED_PAYLOAD),
            search_strategy="lcsc_product_detail",
        )
    ]
    use_case = _build_use_case([row], evidence)

    enriched = await use_case.enrich_row(34)

    assert enriched.row_state == "enriched"
    assert enriched.stock_qty == 2314200
    assert enriched.stock_status == "high"
    assert enriched.lifecycle_status == "active"
    assert enriched.moq == 100
    assert enriched.source_url == "https://www.lcsc.com/product-detail/C14663.html"
    assert enriched.source_name == "LCSC"
    assert enriched.last_checked_at == datetime(2026, 3, 27, 23, 32, tzinfo=UTC)
    warnings = json.loads(enriched.validation_warnings or "[]")
    assert warnings == []
    evidence_blob = json.loads(enriched.evidence_blob)
    assert evidence_blob["parsed"]["stock_qty"] == 2314200
    assert evidence_blob["parsed"]["moq"] == 100
    assert evidence_blob["parsed"]["lifecycle_status"] == "active"
