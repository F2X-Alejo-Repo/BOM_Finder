from __future__ import annotations

from dataclasses import dataclass

import pytest

from bom_workbench.application.find_parts import (
    PartFinderLLMSearchResponseSchema,
    PartFinderLLMResponseSchema,
    PartSearchCriteria,
    ReplacementSearchResult,
    SearchKeyResolution,
    build_grounded_part_finder_search_stage,
    build_grounded_part_finder_stage,
)
from bom_workbench.domain.entities import BomRow
from bom_workbench.domain.enums import Confidence, LifecycleStatus
from bom_workbench.domain.ports import ProviderResponse
from bom_workbench.domain.value_objects import ReplacementCandidate
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
        assert response_schema in {
            PartFinderLLMResponseSchema,
            PartFinderLLMSearchResponseSchema,
        }
        assert messages
        assert config.model == "gpt-4.1-mini"
        return self.response


def _make_row() -> BomRow:
    return BomRow(
        id=1,
        project_id=1,
        designator="C1",
        comment="100nF",
        footprint="Capacitor_SMD:C_0603_1608Metric",
        manufacturer="YAGEO",
        mpn="CC0603KRX7R9BB104",
        lcsc_part_number="C14663",
    )


def _make_results() -> list[ReplacementSearchResult]:
    return [
        ReplacementSearchResult(
            candidate=ReplacementCandidate(
                manufacturer="YAGEO",
                mpn="ALT-1",
                footprint="0603",
                package="0603",
                value_summary="100nF capacitor",
                lcsc_part_number="C10001",
                stock_qty=500,
                stock_status="medium",
                lifecycle_status=LifecycleStatus.ACTIVE,
                confidence=Confidence.HIGH,
                description="100nF capacitor 0603",
            ),
            score=0.81,
            explanation="Strong parametric match.",
            requires_manual_review=False,
        ),
        ReplacementSearchResult(
            candidate=ReplacementCandidate(
                manufacturer="YAGEO",
                mpn="ALT-2",
                footprint="0603",
                package="0603",
                value_summary="100nF capacitor",
                lcsc_part_number="C10002",
                stock_qty=120000,
                stock_status="high",
                lifecycle_status=LifecycleStatus.ACTIVE,
                confidence=Confidence.HIGH,
                description="100nF capacitor 0603",
            ),
            score=0.84,
            explanation="Strong parametric match.",
            requires_manual_review=False,
        ),
    ]


@pytest.mark.anyio
async def test_grounded_part_finder_stage_returns_ranked_decisions() -> None:
    provider = FakeProvider(
        ProviderResponse(
            content=PartFinderLLMResponseSchema(
                ranked_candidates=[
                    {
                        "candidate_id": "candidate_1",
                        "keep": True,
                        "adjusted_score": 0.66,
                        "rationale": "Good fallback.",
                    },
                    {
                        "candidate_id": "candidate_2",
                        "keep": True,
                        "adjusted_score": 0.97,
                        "rationale": "Best inventory position.",
                    },
                ],
                summary="Prefer candidate_2.",
            ).model_dump_json(),
            model="gpt-4.1-mini",
            provider="openai",
            success=True,
            usage={"total_tokens": 222},
            latency_ms=55.0,
            raw_response={"id": "resp_pf_1"},
        )
    )
    stage = build_grounded_part_finder_stage(
        provider,
        api_key="sk-test",
        model="gpt-4.1-mini",
        timeout_seconds=45,
    )

    result = await stage(
        _make_row(),
        PartSearchCriteria(
            keep_same_footprint=True,
            prefer_high_availability=True,
            minimum_stock_qty=1000,
        ),
        _make_results(),
    )

    assert result is not None
    assert result.summary == "Prefer candidate_2."
    assert result.ranked_candidates[1].candidate_id == "candidate_2"
    assert provider.calls == 1


@pytest.mark.anyio
async def test_grounded_part_finder_stage_logs_request_and_response(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO", http_debug=False)
    provider = FakeProvider(
        ProviderResponse(
            content=PartFinderLLMResponseSchema(
                ranked_candidates=[
                    {
                        "candidate_id": "candidate_1",
                        "keep": True,
                        "adjusted_score": 0.75,
                        "rationale": "Acceptable.",
                    }
                ],
                summary="Single preferred candidate.",
            ).model_dump_json(),
            model="gpt-4.1-mini",
            provider="openai",
            success=True,
            raw_response={"id": "resp_pf_logged"},
        )
    )
    stage = build_grounded_part_finder_stage(
        provider,
        api_key="sk-test",
        model="gpt-4.1-mini",
    )

    await stage(
        _make_row(),
        PartSearchCriteria(keep_same_footprint=True),
        _make_results(),
    )

    captured = capsys.readouterr()
    assert "part_finder_llm_request_prepared" in captured.err
    assert "part_finder_llm_provider_response_received" in captured.err
    assert "resp_pf_logged" in captured.err
    assert "***REDACTED***" in captured.err


@pytest.mark.anyio
async def test_grounded_part_finder_search_stage_returns_search_leads() -> None:
    provider = FakeProvider(
        ProviderResponse(
            content=PartFinderLLMSearchResponseSchema(
                search_leads=[
                    {
                        "lcsc_part_number": "C14663",
                        "footprint": "0603",
                        "param_summary": "100nF capacitor",
                        "rationale": "Strong available equivalent.",
                    }
                ],
                summary="One strong lead.",
            ).model_dump_json(),
            model="gpt-4.1-mini",
            provider="openai",
            success=True,
            raw_response={"id": "resp_pf_search"},
        )
    )
    stage = build_grounded_part_finder_search_stage(
        provider,
        api_key="sk-test",
        model="gpt-4.1-mini",
    )

    result = await stage(
        _make_row(),
        PartSearchCriteria(keep_same_footprint=True, prefer_high_availability=True),
        SearchKeyResolution(
            search_keys=SearchKeys(comment="100nF", footprint="0603"),
            primary_field="comment",
            primary_value="100nF",
            priority_order=("comment", "footprint"),
        ),
        [item.candidate for item in _make_results()],
    )

    assert result is not None
    assert result.search_leads[0].lcsc_part_number == "C14663"
    assert provider.calls == 1
