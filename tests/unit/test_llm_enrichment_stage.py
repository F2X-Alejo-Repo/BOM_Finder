from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from bom_workbench.application.llm_enrichment import (
    GroundedLLMResponseSchema,
    LLMEnrichmentRequest,
    build_grounded_llm_enrichment_stage,
)
from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.ports import ProviderResponse, RawEvidence
from bom_workbench.domain.value_objects import SearchKeys
from bom_workbench.logging_config import configure_logging


@dataclass
class FakeProvider:
    response: ProviderResponse
    calls: int = 0

    def get_name(self) -> str:
        return "openai"

    async def chat_structured(self, messages, response_schema, config):  # noqa: ANN001
        self.calls += 1
        assert response_schema is GroundedLLMResponseSchema
        assert messages
        assert config.model == "gpt-4.1-mini"
        return self.response


def _make_row() -> BomRow:
    return BomRow(
        id=1,
        project_id=1,
        designator="R1",
        comment="10k resistor",
        mpn="RC0402FR-0710KL",
        lcsc_part_number="C25744",
    )


def _make_request() -> LLMEnrichmentRequest:
    return LLMEnrichmentRequest(
        row_id=1,
        project_id=1,
        row_snapshot={"designator": "R1"},
        search_keys=SearchKeys(lcsc_part_number="C25744"),
        primary_field="lcsc_part_number",
        primary_value="C25744",
        deterministic_snapshot={"parsed": {"stock_qty": 200}},
        evidence=[
            RawEvidence(
                source_url="https://vendor.test/part/C25744",
                source_name="LCSC",
                retrieved_at=datetime(2026, 3, 1, 12, 30, tzinfo=UTC),
                content_type="text/html",
                raw_content="stock_qty: 200\nlifecycle_status: active\nmoq: 1\n",
                search_strategy="lcsc_part_number",
            )
        ],
    )


@pytest.mark.anyio
async def test_grounded_llm_stage_returns_structured_patch() -> None:
    provider = FakeProvider(
        ProviderResponse(
            content=GroundedLLMResponseSchema(
                stock_status="high",
                lifecycle_status="active",
                eol_risk="low",
                moq=1,
                source_name="LCSC",
                source_confidence="high",
                sourcing_notes="Grounded from supplier evidence.",
            ).model_dump_json(),
            model="gpt-4.1-mini",
            provider="openai",
            success=True,
            usage={"total_tokens": 321},
            latency_ms=88.5,
            raw_response={"id": "resp_123"},
        )
    )
    stage = build_grounded_llm_enrichment_stage(
        provider,
        api_key="sk-test",
        model="gpt-4.1-mini",
        timeout_seconds=45,
    )

    result = await stage(_make_row(), _make_request())

    assert result is not None
    assert result.success is True
    assert result.provider_name == "openai"
    assert result.model_name == "gpt-4.1-mini"
    assert result.patch.stock_status == "high"
    assert result.patch.moq == 1
    assert result.patch.source_confidence == "high"
    assert provider.calls == 1


@pytest.mark.anyio
async def test_grounded_llm_stage_reports_provider_failure() -> None:
    provider = FakeProvider(
        ProviderResponse(
            content="",
            model="gpt-4.1-mini",
            provider="openai",
            success=False,
            error_message="OpenAI chat failed with HTTP 500.",
            error_category="server_error",
            retry_after_seconds=1.5,
        )
    )
    stage = build_grounded_llm_enrichment_stage(
        provider,
        api_key="sk-test",
        model="gpt-4.1-mini",
    )

    result = await stage(_make_row(), _make_request())

    assert result is not None
    assert result.success is False
    assert result.provider_name == "openai"
    assert result.error_category == "server_error"
    assert result.retry_after_seconds == 1.5
    assert provider.calls == 1


@pytest.mark.anyio
async def test_grounded_llm_stage_logs_request_and_response(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", http_debug=False)
    provider = FakeProvider(
        ProviderResponse(
            content=GroundedLLMResponseSchema(
                stock_status="high",
                lifecycle_status="active",
            ).model_dump_json(),
            model="gpt-4.1-mini",
            provider="openai",
            success=True,
            raw_response={"id": "resp_logged"},
        )
    )
    stage = build_grounded_llm_enrichment_stage(
        provider,
        api_key="sk-test",
        model="gpt-4.1-mini",
    )

    await stage(_make_row(), _make_request())

    captured = capsys.readouterr()
    assert "grounded_llm_request_prepared" in captured.err
    assert "grounded_llm_provider_response_received" in captured.err
    assert "C25744" in captured.err
    assert "resp_logged" in captured.err
    assert "***REDACTED***" in captured.err
