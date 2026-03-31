"""Deterministic replacement search and application use cases."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Mapping, Sequence

import structlog
from pydantic import BaseModel, ConfigDict, Field

from ..domain.entities import BomRow
from ..domain.enums import Confidence, EvidenceType, LifecycleStatus, ReplacementStatus
from ..domain.matching import MatchingEngine
from ..domain.ports import (
    ChatConfig,
    IBomRepository,
    IEvidenceRetriever,
    ProviderResponse,
    RawEvidence,
)
from ..domain.value_objects import EvidenceRecord, ReplacementCandidate, SearchKeys

__all__ = [
    "FindPartsUseCase",
    "GroundedPartFinderStage",
    "PartSearchCriteria",
    "ReplacementBatch",
    "ReplacementApplicationResult",
    "ReplacementConfirmationRequired",
    "PartFinderLLMResponseSchema",
    "build_grounded_part_finder_stage",
    "ReplacementSearchResult",
    "SearchKeyResolution",
]


_DEFAULT_REVIEW_THRESHOLD = 0.75
_RISKY_LIFECYCLE_STATUSES = {
    LifecycleStatus.NRND.value,
    LifecycleStatus.LAST_TIME_BUY.value,
    LifecycleStatus.EOL.value,
    LifecycleStatus.UNKNOWN.value,
}
_OUT_OF_STOCK_STATUSES = {
    "out",
    "out_of_stock",
    "unavailable",
}
_HIGH_AVAILABILITY_STATUSES = {
    "high",
    "in_stock",
    "available",
}
_MAX_LLM_SEARCH_LEADS = 5
_MAX_LLM_RERANK_CANDIDATES = 12
_LLM_SCORE_BLEND = 0.35

logger = structlog.get_logger(__name__)


def _utc_epoch() -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(slots=True, frozen=True)
class PartSearchCriteria:
    """Explicit criteria used to seed a replacement search."""

    part_number: str = ""
    lcsc_part_number: str = ""
    mpn: str = ""
    source_url: str = ""
    comment: str = ""
    value: str = ""
    footprint: str = ""
    category: str = ""
    param_summary: str = ""
    manufacturer: str = ""
    active_only: bool = False
    in_stock: bool = False
    lcsc_available: bool = False
    keep_same_footprint: bool = False
    keep_same_manufacturer: bool = False
    prefer_high_availability: bool = False
    minimum_stock_qty: int | None = None


@dataclass(slots=True, frozen=True)
class SearchKeyResolution:
    """Resolved search keys and the primary field used to build them."""

    search_keys: SearchKeys
    primary_field: str
    primary_value: str
    priority_order: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class SearchPlanStep:
    """One deterministic retrieval step in the replacement search plan."""

    label: str
    search_keys: SearchKeys
    stop_if_candidates_at_least: int | None = None


@dataclass(slots=True, frozen=True)
class ReplacementSearchResult:
    """Ranked replacement candidate returned to the caller."""

    candidate: ReplacementCandidate
    score: float
    explanation: str
    requires_manual_review: bool


class PartFinderLLMDecisionSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    candidate_id: str
    keep: bool = True
    adjusted_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class PartFinderLLMResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ranked_candidates: list[PartFinderLLMDecisionSchema] = Field(default_factory=list)
    summary: str = ""


class PartFinderLLMSearchLeadSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    part_number: str = ""
    lcsc_part_number: str = ""
    mpn: str = ""
    footprint: str = ""
    category: str = ""
    param_summary: str = ""
    manufacturer: str = ""
    rationale: str = ""


class PartFinderLLMSearchResponseSchema(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    search_leads: list[PartFinderLLMSearchLeadSchema] = Field(default_factory=list)
    summary: str = ""


PartFinderLLMStage = Callable[
    [BomRow, PartSearchCriteria, Sequence[ReplacementSearchResult]],
    Awaitable[PartFinderLLMResponseSchema | None],
]


PartFinderLLMSearchStage = Callable[
    [BomRow, PartSearchCriteria, SearchKeyResolution, Sequence[ReplacementCandidate]],
    Awaitable[PartFinderLLMSearchResponseSchema | None],
]


class GroundedPartFinderSearchStage:
    """Provider-backed grounded search planner for replacement candidate expansion."""

    def __init__(
        self,
        provider_source: Any,
        *,
        api_key: str = "",
        model: str = "",
        timeout_seconds: int = 60,
        max_tokens: int = 1200,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        allow_manual_approval: bool = False,
        system_prompt: str = "",
    ) -> None:
        self._provider_source = provider_source
        self._api_key = self._clean_text(api_key)
        self._model = self._clean_text(model)
        self._timeout_seconds = max(10, int(timeout_seconds or 60))
        self._max_tokens = max(512, int(max_tokens or 1200))
        self._temperature = temperature
        self._reasoning_effort = self._clean_text(reasoning_effort)
        self._allow_manual_approval = allow_manual_approval
        self._system_prompt = self._build_system_prompt(system_prompt)

    async def __call__(
        self,
        row: BomRow,
        criteria: PartSearchCriteria,
        search_resolution: SearchKeyResolution,
        reference_candidates: Sequence[ReplacementCandidate],
    ) -> PartFinderLLMSearchResponseSchema | None:
        logger.info(
            "part_finder_llm_search_stage_started",
            row_id=int(row.id or 0),
            project_id=int(row.project_id or 0),
            primary_field=search_resolution.primary_field,
            primary_value=search_resolution.primary_value,
            reference_candidate_count=len(reference_candidates),
            direct_adapter=self._is_direct_adapter(),
        )
        if self._is_direct_adapter():
            return await self._run_with_adapter(
                adapter=self._provider_source,
                provider_name=self._clean_text(
                    getattr(self._provider_source, "get_name", lambda: "")()
                ),
                api_key=self._api_key,
                model=self._model,
                row=row,
                criteria=criteria,
                search_resolution=search_resolution,
                reference_candidates=reference_candidates,
            )

        runtimes = await self._list_runtimes()
        if not runtimes:
            return None

        for runtime in runtimes:
            if not self._allow_manual_approval and bool(getattr(runtime, "manual_approval", False)):
                continue
            provider_name = self._clean_text(getattr(runtime, "provider", ""))
            model_name = self._clean_text(getattr(runtime, "model", ""))
            api_key = self._clean_text(getattr(runtime, "api_key", ""))
            if not provider_name or not model_name or not api_key:
                continue
            adapter = self._resolve_adapter(provider_name)
            if adapter is None:
                continue
            response = await self._run_with_adapter(
                adapter=adapter,
                provider_name=provider_name,
                api_key=api_key,
                model=model_name,
                row=row,
                criteria=criteria,
                search_resolution=search_resolution,
                reference_candidates=reference_candidates,
                runtime=runtime,
            )
            if response is not None:
                return response
        return None

    async def _run_with_adapter(
        self,
        *,
        adapter: Any,
        provider_name: str,
        api_key: str,
        model: str,
        row: BomRow,
        criteria: PartSearchCriteria,
        search_resolution: SearchKeyResolution,
        reference_candidates: Sequence[ReplacementCandidate],
        runtime: Any | None = None,
    ) -> PartFinderLLMSearchResponseSchema | None:
        if not provider_name:
            provider_name = self._clean_text(getattr(adapter, "get_name", lambda: "")())
        if not model and runtime is not None:
            model = self._clean_text(getattr(runtime, "model", ""))
        if not api_key and runtime is not None:
            api_key = self._clean_text(getattr(runtime, "api_key", ""))
        if not provider_name or not model or not api_key:
            return None
        if not hasattr(adapter, "chat_structured"):
            return None

        messages = self._build_messages(
            row=row,
            criteria=criteria,
            search_resolution=search_resolution,
            reference_candidates=reference_candidates,
        )
        config = self._build_chat_config(api_key=api_key, model=model, runtime=runtime)
        logger.info(
            "part_finder_llm_search_request_prepared",
            row_id=int(row.id or 0),
            provider=provider_name,
            model=model,
            criteria_payload=self._criteria_payload(criteria),
            search_resolution={
                "primary_field": search_resolution.primary_field,
                "primary_value": search_resolution.primary_value,
                "search_keys": search_resolution.search_keys.model_dump(mode="json"),
            },
            reference_candidates=self._reference_candidate_payloads(reference_candidates),
            chat_config=self._chat_config_payload(config),
        )

        try:
            response: ProviderResponse = await adapter.chat_structured(
                messages,
                PartFinderLLMSearchResponseSchema,
                config,
            )
        except Exception as exc:  # pragma: no cover - service boundary
            logger.exception(
                "part_finder_llm_search_provider_exception",
                row_id=int(row.id or 0),
                provider=provider_name,
                model=model,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None

        logger.info(
            "part_finder_llm_search_response_received",
            row_id=int(row.id or 0),
            provider=self._clean_text(response.provider) or provider_name,
            model=self._clean_text(response.model) or model,
            success=response.success,
            latency_ms=response.latency_ms,
            usage=dict(response.usage),
            error_category=self._clean_text(response.error_category),
            retry_after_seconds=response.retry_after_seconds,
            response_content=self._clean_text(response.content),
            raw_response=dict(response.raw_response),
        )
        if not response.success:
            return None

        try:
            parsed = PartFinderLLMSearchResponseSchema.model_validate_json(response.content)
        except Exception as exc:
            logger.warning(
                "part_finder_llm_search_validation_failed",
                row_id=int(row.id or 0),
                provider=self._clean_text(response.provider) or provider_name,
                model=self._clean_text(response.model) or model,
                error_type=type(exc).__name__,
                response_content=self._clean_text(response.content),
                raw_response=dict(response.raw_response),
            )
            return None

        logger.info(
            "part_finder_llm_search_plan_received",
            row_id=int(row.id or 0),
            provider=self._clean_text(response.provider) or provider_name,
            model=self._clean_text(response.model) or model,
            summary=parsed.summary,
            search_leads=[lead.model_dump(mode="json") for lead in parsed.search_leads],
        )
        return parsed

    async def _list_runtimes(self) -> list[Any]:
        if not hasattr(self._provider_source, "list_enabled_runtime_configs"):
            return []
        runtimes = await self._provider_source.list_enabled_runtime_configs()
        if not isinstance(runtimes, list):
            return []
        return list(runtimes)

    def _resolve_adapter(self, provider_name: str) -> Any | None:
        if not hasattr(self._provider_source, "get_adapter"):
            return None
        try:
            return self._provider_source.get_adapter(provider_name)
        except Exception:  # pragma: no cover - adapter lookup is a service boundary
            return None

    def _is_direct_adapter(self) -> bool:
        return hasattr(self._provider_source, "chat_structured") and not hasattr(
            self._provider_source,
            "list_enabled_runtime_configs",
        )

    def _build_chat_config(
        self,
        *,
        api_key: str,
        model: str,
        runtime: Any | None = None,
    ) -> ChatConfig:
        if runtime is not None and hasattr(runtime, "to_chat_config"):
            config = runtime.to_chat_config(
                system_prompt=self._system_prompt,
                max_tokens=self._max_tokens,
            )
            if self._temperature is not None:
                config.temperature = self._temperature
            if self._reasoning_effort:
                config.reasoning_effort = self._reasoning_effort
            if self._timeout_seconds:
                config.timeout_seconds = self._timeout_seconds
            config.api_key = api_key
            config.model = model
            config.response_format = "json_object"
            return config

        return ChatConfig(
            api_key=api_key,
            model=model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout_seconds=self._timeout_seconds,
            reasoning_effort=self._reasoning_effort or None,
            response_format="json_object",
            system_prompt=self._system_prompt,
        )

    def _build_messages(
        self,
        *,
        row: BomRow,
        criteria: PartSearchCriteria,
        search_resolution: SearchKeyResolution,
        reference_candidates: Sequence[ReplacementCandidate],
    ) -> list[dict[str, str]]:
        payload = {
            "purpose": "grounded_part_replacement_search_planning",
            "instruction": (
                "Use the supplied BOM row, explicit criteria, resolved search keys, and reference candidates "
                "to propose additional search leads. These leads will be validated by deterministic supplier "
                "lookup, so prefer exact MPNs or LCSC part numbers when possible."
            ),
            "row": self._row_payload(row),
            "criteria": self._criteria_payload(criteria),
            "search_resolution": {
                "primary_field": search_resolution.primary_field,
                "primary_value": search_resolution.primary_value,
                "search_keys": search_resolution.search_keys.model_dump(mode="json"),
            },
            "reference_candidates": self._reference_candidate_payloads(reference_candidates),
        }
        return [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                    default=str,
                ),
            },
        ]

    def _row_payload(self, row: BomRow) -> dict[str, Any]:
        return {
            "row_id": int(row.id or 0),
            "project_id": int(row.project_id or 0),
            "designator": self._clean_text(row.designator),
            "comment": self._clean_text(row.comment),
            "value_raw": self._clean_text(row.value_raw),
            "footprint": self._clean_text(row.footprint),
            "package": self._clean_text(row.package),
            "manufacturer": self._clean_text(row.manufacturer),
            "mpn": self._clean_text(row.mpn),
            "lcsc_part_number": self._clean_text(row.lcsc_part_number),
            "category": self._clean_text(row.category),
            "param_summary": self._clean_text(row.param_summary),
            "quantity": int(row.quantity or 0),
            "stock_qty": row.stock_qty,
            "stock_status": self._clean_text(row.stock_status),
            "lifecycle_status": self._clean_text(row.lifecycle_status),
        }

    def _criteria_payload(self, criteria: PartSearchCriteria) -> dict[str, Any]:
        return {
            "part_number": self._clean_text(criteria.part_number),
            "lcsc_part_number": self._clean_text(criteria.lcsc_part_number),
            "mpn": self._clean_text(criteria.mpn),
            "source_url": self._clean_text(criteria.source_url),
            "comment": self._clean_text(criteria.comment),
            "value": self._clean_text(criteria.value),
            "footprint": self._clean_text(criteria.footprint),
            "category": self._clean_text(criteria.category),
            "param_summary": self._clean_text(criteria.param_summary),
            "manufacturer": self._clean_text(criteria.manufacturer),
            "active_only": criteria.active_only,
            "in_stock": criteria.in_stock,
            "lcsc_available": criteria.lcsc_available,
            "keep_same_footprint": criteria.keep_same_footprint,
            "keep_same_manufacturer": criteria.keep_same_manufacturer,
            "prefer_high_availability": criteria.prefer_high_availability,
            "minimum_stock_qty": criteria.minimum_stock_qty,
        }

    def _reference_candidate_payloads(
        self,
        candidates: Sequence[ReplacementCandidate],
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for candidate in candidates[:3]:
            payloads.append(
                {
                    "manufacturer": self._clean_text(candidate.manufacturer),
                    "mpn": self._clean_text(candidate.mpn),
                    "part_number": self._clean_text(candidate.part_number),
                    "lcsc_part_number": self._clean_text(candidate.lcsc_part_number),
                    "footprint": self._clean_text(candidate.footprint),
                    "package": self._clean_text(candidate.package),
                    "value_summary": self._clean_text(candidate.value_summary),
                    "description": self._clean_text(candidate.description),
                    "stock_qty": candidate.stock_qty,
                    "stock_status": self._clean_text(candidate.stock_status),
                    "lifecycle_status": self._clean_text(candidate.lifecycle_status),
                    "lcsc_link": self._clean_text(candidate.lcsc_link),
                }
            )
        return payloads

    def _chat_config_payload(self, config: ChatConfig) -> dict[str, Any]:
        return {
            "api_key": config.api_key,
            "model": config.model,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout_seconds": config.timeout_seconds,
            "reasoning_effort": config.reasoning_effort,
            "response_format": config.response_format,
            "system_prompt": config.system_prompt,
        }

    def _build_system_prompt(self, extra_prompt: str) -> str:
        parts = [
            "You are a grounded part replacement search planner.",
            "Use only the supplied BOM row, explicit criteria, resolved search keys, and reference candidates.",
            "Generate search leads, not final replacement claims.",
            "Treat keep_same_footprint, keep_same_manufacturer, and minimum_stock_qty as hard constraints.",
            "Prefer same value and same footprint first, like a sourcing engineer would.",
            "Electrical value equivalence is mandatory: do not confuse different resistor or capacitor values just because package or stock looks attractive.",
            "Prefer exact MPNs or LCSC part numbers that are likely broadly available on LCSC.",
            "If minimum_stock_qty is set, only suggest leads that are likely to satisfy that numeric threshold from grounded supplier evidence.",
            "If you are uncertain, return fewer leads instead of inventing options.",
            "Return at most 5 leads and only data that matches the schema.",
        ]
        if extra_prompt.strip():
            parts.append(extra_prompt.strip())
        return "\n\n".join(parts)

    def _clean_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class GroundedPartFinderStage:
    """Provider-backed grounded reranker for deterministic replacement candidates."""

    def __init__(
        self,
        provider_source: Any,
        *,
        api_key: str = "",
        model: str = "",
        timeout_seconds: int = 60,
        max_tokens: int = 1400,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        allow_manual_approval: bool = False,
        system_prompt: str = "",
    ) -> None:
        self._provider_source = provider_source
        self._api_key = self._clean_text(api_key)
        self._model = self._clean_text(model)
        self._timeout_seconds = max(10, int(timeout_seconds or 60))
        self._max_tokens = max(512, int(max_tokens or 1400))
        self._temperature = temperature
        self._reasoning_effort = self._clean_text(reasoning_effort)
        self._allow_manual_approval = allow_manual_approval
        self._system_prompt = self._build_system_prompt(system_prompt)

    async def __call__(
        self,
        row: BomRow,
        criteria: PartSearchCriteria,
        candidates: Sequence[ReplacementSearchResult],
    ) -> PartFinderLLMResponseSchema | None:
        if len(candidates) < 2:
            return None
        logger.info(
            "part_finder_llm_stage_started",
            row_id=int(row.id or 0),
            project_id=int(row.project_id or 0),
            candidate_count=len(candidates),
            direct_adapter=self._is_direct_adapter(),
            keep_same_footprint=criteria.keep_same_footprint,
            keep_same_manufacturer=criteria.keep_same_manufacturer,
            prefer_high_availability=criteria.prefer_high_availability,
            minimum_stock_qty=criteria.minimum_stock_qty,
        )
        if self._is_direct_adapter():
            return await self._run_with_adapter(
                adapter=self._provider_source,
                provider_name=self._clean_text(getattr(self._provider_source, "get_name", lambda: "")()),
                api_key=self._api_key,
                model=self._model,
                row=row,
                criteria=criteria,
                candidates=candidates,
            )

        runtimes = await self._list_runtimes()
        if not runtimes:
            return None

        for runtime in runtimes:
            if not self._allow_manual_approval and bool(getattr(runtime, "manual_approval", False)):
                continue
            provider_name = self._clean_text(getattr(runtime, "provider", ""))
            model_name = self._clean_text(getattr(runtime, "model", ""))
            api_key = self._clean_text(getattr(runtime, "api_key", ""))
            if not provider_name or not model_name or not api_key:
                continue
            adapter = self._resolve_adapter(provider_name)
            if adapter is None:
                continue
            response = await self._run_with_adapter(
                adapter=adapter,
                provider_name=provider_name,
                api_key=api_key,
                model=model_name,
                row=row,
                criteria=criteria,
                candidates=candidates,
                runtime=runtime,
            )
            if response is not None:
                return response
        return None

    async def _run_with_adapter(
        self,
        *,
        adapter: Any,
        provider_name: str,
        api_key: str,
        model: str,
        row: BomRow,
        criteria: PartSearchCriteria,
        candidates: Sequence[ReplacementSearchResult],
        runtime: Any | None = None,
    ) -> PartFinderLLMResponseSchema | None:
        if not provider_name:
            provider_name = self._clean_text(getattr(adapter, "get_name", lambda: "")())
        if not model and runtime is not None:
            model = self._clean_text(getattr(runtime, "model", ""))
        if not api_key and runtime is not None:
            api_key = self._clean_text(getattr(runtime, "api_key", ""))
        if not provider_name or not model or not api_key:
            return None
        if not hasattr(adapter, "chat_structured"):
            return None

        messages = self._build_messages(row=row, criteria=criteria, candidates=candidates)
        config = self._build_chat_config(api_key=api_key, model=model, runtime=runtime)
        logger.info(
            "part_finder_llm_request_prepared",
            row_id=int(row.id or 0),
            provider=provider_name,
            model=model,
            candidate_count=len(candidates),
            criteria_payload=self._criteria_payload(criteria),
            candidate_payloads=self._candidate_payloads(candidates),
            chat_config=self._chat_config_payload(config),
        )

        try:
            response: ProviderResponse = await adapter.chat_structured(
                messages,
                PartFinderLLMResponseSchema,
                config,
            )
        except Exception as exc:  # pragma: no cover - service boundary
            logger.exception(
                "part_finder_llm_provider_exception",
                row_id=int(row.id or 0),
                provider=provider_name,
                model=model,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return None

        logger.info(
            "part_finder_llm_provider_response_received",
            row_id=int(row.id or 0),
            provider=self._clean_text(response.provider) or provider_name,
            model=self._clean_text(response.model) or model,
            success=response.success,
            latency_ms=response.latency_ms,
            usage=dict(response.usage),
            error_category=self._clean_text(response.error_category),
            retry_after_seconds=response.retry_after_seconds,
            response_content=self._clean_text(response.content),
            raw_response=dict(response.raw_response),
        )
        if not response.success:
            logger.warning(
                "part_finder_llm_provider_response_failed",
                row_id=int(row.id or 0),
                provider=self._clean_text(response.provider) or provider_name,
                model=self._clean_text(response.model) or model,
                error_message=self._clean_text(response.error_message),
                raw_response=dict(response.raw_response),
            )
            return None

        try:
            parsed = PartFinderLLMResponseSchema.model_validate_json(response.content)
        except Exception as exc:
            logger.warning(
                "part_finder_llm_response_validation_failed",
                row_id=int(row.id or 0),
                provider=self._clean_text(response.provider) or provider_name,
                model=self._clean_text(response.model) or model,
                error_type=type(exc).__name__,
                response_content=self._clean_text(response.content),
                raw_response=dict(response.raw_response),
            )
            return None

        logger.info(
            "part_finder_llm_response_parsed",
            row_id=int(row.id or 0),
            provider=self._clean_text(response.provider) or provider_name,
            model=self._clean_text(response.model) or model,
            summary=parsed.summary,
            ranked_candidates=[decision.model_dump(mode="json") for decision in parsed.ranked_candidates],
        )
        return parsed

    async def _list_runtimes(self) -> list[Any]:
        if not hasattr(self._provider_source, "list_enabled_runtime_configs"):
            return []
        runtimes = await self._provider_source.list_enabled_runtime_configs()
        if not isinstance(runtimes, list):
            return []
        return list(runtimes)

    def _resolve_adapter(self, provider_name: str) -> Any | None:
        if not hasattr(self._provider_source, "get_adapter"):
            return None
        try:
            return self._provider_source.get_adapter(provider_name)
        except Exception:  # pragma: no cover - adapter lookup is a service boundary
            return None

    def _is_direct_adapter(self) -> bool:
        return hasattr(self._provider_source, "chat_structured") and not hasattr(
            self._provider_source,
            "list_enabled_runtime_configs",
        )

    def _build_chat_config(
        self,
        *,
        api_key: str,
        model: str,
        runtime: Any | None = None,
    ) -> ChatConfig:
        if runtime is not None and hasattr(runtime, "to_chat_config"):
            config = runtime.to_chat_config(
                system_prompt=self._system_prompt,
                max_tokens=self._max_tokens,
            )
            if self._temperature is not None:
                config.temperature = self._temperature
            if self._reasoning_effort:
                config.reasoning_effort = self._reasoning_effort
            if self._timeout_seconds:
                config.timeout_seconds = self._timeout_seconds
            config.api_key = api_key
            config.model = model
            config.response_format = "json_object"
            return config

        return ChatConfig(
            api_key=api_key,
            model=model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout_seconds=self._timeout_seconds,
            reasoning_effort=self._reasoning_effort or None,
            response_format="json_object",
            system_prompt=self._system_prompt,
        )

    def _build_messages(
        self,
        *,
        row: BomRow,
        criteria: PartSearchCriteria,
        candidates: Sequence[ReplacementSearchResult],
    ) -> list[dict[str, str]]:
        payload = {
            "purpose": "grounded_part_replacement_ranking",
            "instruction": (
                "Use only the supplied BOM row, explicit criteria, and deterministic candidates. "
                "Do not invent supplier data or candidate identifiers."
            ),
            "row": self._row_payload(row),
            "criteria": self._criteria_payload(criteria),
            "candidates": self._candidate_payloads(candidates),
        }
        return [
            {"role": "system", "content": self._system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    payload,
                    ensure_ascii=True,
                    indent=2,
                    sort_keys=True,
                    default=str,
                ),
            },
        ]

    def _row_payload(self, row: BomRow) -> dict[str, Any]:
        return {
            "row_id": int(row.id or 0),
            "project_id": int(row.project_id or 0),
            "designator": self._clean_text(row.designator),
            "comment": self._clean_text(row.comment),
            "value_raw": self._clean_text(row.value_raw),
            "footprint": self._clean_text(row.footprint),
            "package": self._clean_text(row.package),
            "manufacturer": self._clean_text(row.manufacturer),
            "mpn": self._clean_text(row.mpn),
            "lcsc_part_number": self._clean_text(row.lcsc_part_number),
            "category": self._clean_text(row.category),
            "param_summary": self._clean_text(row.param_summary),
            "quantity": int(row.quantity or 0),
            "stock_qty": row.stock_qty,
            "stock_status": self._clean_text(row.stock_status),
            "lifecycle_status": self._clean_text(row.lifecycle_status),
        }

    def _criteria_payload(self, criteria: PartSearchCriteria) -> dict[str, Any]:
        return {
            "part_number": self._clean_text(criteria.part_number),
            "lcsc_part_number": self._clean_text(criteria.lcsc_part_number),
            "mpn": self._clean_text(criteria.mpn),
            "source_url": self._clean_text(criteria.source_url),
            "comment": self._clean_text(criteria.comment),
            "value": self._clean_text(criteria.value),
            "footprint": self._clean_text(criteria.footprint),
            "category": self._clean_text(criteria.category),
            "param_summary": self._clean_text(criteria.param_summary),
            "manufacturer": self._clean_text(criteria.manufacturer),
            "active_only": criteria.active_only,
            "in_stock": criteria.in_stock,
            "lcsc_available": criteria.lcsc_available,
            "keep_same_footprint": criteria.keep_same_footprint,
            "keep_same_manufacturer": criteria.keep_same_manufacturer,
            "prefer_high_availability": criteria.prefer_high_availability,
            "minimum_stock_qty": criteria.minimum_stock_qty,
        }

    def _candidate_payloads(
        self,
        candidates: Sequence[ReplacementSearchResult],
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for index, result in enumerate(candidates, start=1):
            candidate = result.candidate
            payloads.append(
                {
                    "candidate_id": self._candidate_id(index),
                    "manufacturer": self._clean_text(candidate.manufacturer),
                    "mpn": self._clean_text(candidate.mpn),
                    "part_number": self._clean_text(candidate.part_number),
                    "lcsc_part_number": self._clean_text(candidate.lcsc_part_number),
                    "footprint": self._clean_text(candidate.footprint),
                    "package": self._clean_text(candidate.package),
                    "value_summary": self._clean_text(candidate.value_summary),
                    "description": self._clean_text(candidate.description),
                    "stock_qty": candidate.stock_qty,
                    "stock_status": self._clean_text(candidate.stock_status),
                    "lifecycle_status": self._clean_text(candidate.lifecycle_status),
                    "confidence": self._clean_text(
                        candidate.confidence.value
                        if hasattr(candidate.confidence, "value")
                        else candidate.confidence
                    ),
                    "match_score": float(result.score),
                    "match_explanation": self._clean_text(result.explanation),
                    "requires_manual_review": bool(result.requires_manual_review),
                    "warnings": list(candidate.warnings),
                    "lcsc_link": self._clean_text(candidate.lcsc_link),
                }
            )
        return payloads

    def _chat_config_payload(self, config: ChatConfig) -> dict[str, Any]:
        return {
            "api_key": config.api_key,
            "model": config.model,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "timeout_seconds": config.timeout_seconds,
            "reasoning_effort": config.reasoning_effort,
            "response_format": config.response_format,
            "system_prompt": config.system_prompt,
        }

    def _build_system_prompt(self, extra_prompt: str) -> str:
        parts = [
            "You are a grounded part replacement ranking assistant.",
            "Use only the supplied BOM row, explicit criteria, and deterministic candidate list.",
            "Never invent candidate identifiers, stock data, lifecycle data, or package data.",
            "Treat keep_same_footprint, keep_same_manufacturer, and minimum_stock_qty as hard constraints.",
            "Prefer candidates with stronger availability, healthy lifecycle, and better deterministic match quality.",
            "Return only data that matches the schema.",
        ]
        if extra_prompt.strip():
            parts.append(extra_prompt.strip())
        return "\n\n".join(parts)

    def _candidate_id(self, index: int) -> str:
        return f"candidate_{index}"

    def _clean_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


def build_grounded_part_finder_stage(
    provider_source: Any,
    *,
    api_key: str = "",
    model: str = "",
    timeout_seconds: int = 60,
    max_tokens: int = 1400,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    allow_manual_approval: bool = False,
    system_prompt: str = "",
) -> GroundedPartFinderStage:
    """Build a grounded LLM reranker for replacement candidates."""

    return GroundedPartFinderStage(
        provider_source,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        allow_manual_approval=allow_manual_approval,
        system_prompt=system_prompt,
    )


def build_grounded_part_finder_search_stage(
    provider_source: Any,
    *,
    api_key: str = "",
    model: str = "",
    timeout_seconds: int = 60,
    max_tokens: int = 1200,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    allow_manual_approval: bool = False,
    system_prompt: str = "",
) -> GroundedPartFinderSearchStage:
    """Build a grounded LLM search planner for replacement candidate expansion."""

    return GroundedPartFinderSearchStage(
        provider_source,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        allow_manual_approval=allow_manual_approval,
        system_prompt=system_prompt,
    )


@dataclass(slots=True, frozen=True)
class ReplacementBatch:
    """A grouped batch of BOM rows that can share one replacement search."""

    group_key: str
    label: str
    row_ids: tuple[int, ...]
    designators: tuple[str, ...]
    exemplar_row_id: int


@dataclass(slots=True, frozen=True)
class ReplacementApplicationResult:
    """Outcome returned after persisting a confirmed replacement."""

    row: BomRow
    candidate: ReplacementCandidate
    applied: bool


class ReplacementConfirmationRequired(PermissionError):
    """Raised when a replacement is applied without explicit confirmation."""


class FindPartsUseCase:
    """Search, rank, and apply part replacements deterministically."""

    _BROAD_FALLBACK_THRESHOLD = 3
    _PRIMARY_SEARCH_FIELDS: tuple[str, ...] = (
        "lcsc_part_number",
        "mpn",
        "source_url",
        "comment",
        "footprint",
        "category",
        "param_summary",
    )

    def __init__(
        self,
        repository: IBomRepository,
        retriever: IEvidenceRetriever,
        *,
        matching_engine: MatchingEngine | None = None,
        manual_review_threshold: float = _DEFAULT_REVIEW_THRESHOLD,
        llm_search_stage: PartFinderLLMSearchStage | None = None,
        llm_stage: PartFinderLLMStage | None = None,
    ) -> None:
        self._repository = repository
        self._retriever = retriever
        self._matching_engine = matching_engine or MatchingEngine()
        self._manual_review_threshold = manual_review_threshold
        self._llm_search_stage = llm_search_stage
        self._llm_stage = llm_stage

    async def find_candidates_for_row(self, row_id: int) -> list[ReplacementSearchResult]:
        """Convenience wrapper for row-driven searches."""

        return await self.find_candidates(row_id=row_id)

    async def find_candidates(
        self,
        *,
        row_id: int | None = None,
        criteria: PartSearchCriteria | Mapping[str, Any] | None = None,
    ) -> list[ReplacementSearchResult]:
        """Search replacement candidates from a row id or explicit criteria."""

        if row_id is None and criteria is None:
            raise ValueError("Either row_id or criteria must be provided.")

        criteria_model = self._coerce_criteria_model(criteria)
        criteria_data = self._coerce_criteria(criteria_model)
        context_row = await self._resolve_context_row(row_id=row_id, criteria=criteria)
        search_resolution = self.resolve_search_keys(context_row, criteria=criteria)
        if not search_resolution.primary_value:
            return []

        search_plan = self._build_search_plan(search_resolution.search_keys)
        evidence = await self._retrieve_search_plan_evidence(search_plan)
        initial_candidates = self._parse_candidates(evidence)
        if self._llm_search_stage is not None:
            evidence = await self._expand_evidence_with_llm(
                context_row,
                criteria_model,
                search_resolution,
                evidence,
                initial_candidates,
            )
        candidates = self._parse_candidates(evidence)
        if not candidates:
            return []

        scored_candidates = self._matching_engine.rank_candidates(context_row, candidates)
        results: list[ReplacementSearchResult] = []
        for candidate, score in scored_candidates:
            score_value = score.total
            explanation = score.explanation
            if criteria_model.prefer_high_availability:
                score_value, explanation = self._apply_availability_preference(
                    candidate,
                    score_value,
                    explanation,
                )
            ranked_candidate = candidate.model_copy(
                update={
                    "match_score": score_value,
                    "match_explanation": explanation,
                }
            )
            rejection_reasons = self._candidate_filter_rejection_reasons(
                ranked_candidate,
                criteria_model,
                context_row,
            )
            if rejection_reasons:
                logger.info(
                    "part_finder_candidate_filtered_out",
                    row_id=int(context_row.id or 0),
                    project_id=int(context_row.project_id or 0),
                    candidate_mpn=self._clean_text(ranked_candidate.mpn),
                    candidate_lcsc_part_number=self._clean_text(ranked_candidate.lcsc_part_number),
                    candidate_stock_qty=ranked_candidate.stock_qty,
                    candidate_stock_status=self._clean_text(ranked_candidate.stock_status),
                    candidate_footprint=self._clean_text(ranked_candidate.footprint),
                    candidate_package=self._clean_text(ranked_candidate.package),
                    candidate_value_summary=self._clean_text(ranked_candidate.value_summary),
                    reasons=rejection_reasons,
                )
                continue
            results.append(
                ReplacementSearchResult(
                    candidate=ranked_candidate,
                    score=score_value,
                    explanation=explanation,
                    requires_manual_review=self._requires_manual_review(
                        ranked_candidate,
                        score_value,
                    ),
                )
            )
        if self._llm_stage is not None and len(results) > 1:
            results = await self._rerank_with_llm(context_row, criteria_model, results)
        return self._sort_results(results)

    async def apply_replacement(
        self,
        row_id: int,
        candidate: ReplacementCandidate | Mapping[str, Any],
        confirmed: bool,
    ) -> ReplacementApplicationResult:
        """Persist a confirmed replacement onto the target row."""

        if not confirmed:
            raise ReplacementConfirmationRequired(
                "Replacement application requires explicit confirmation."
            )

        row = await self._load_row(row_id)
        candidate_model = self._coerce_candidate(candidate)
        self._apply_candidate_to_row(row, candidate_model)
        saved_row = await self._repository.save_row(row)
        return ReplacementApplicationResult(row=saved_row, candidate=candidate_model, applied=True)

    async def apply_replacement_to_rows(
        self,
        row_ids: Sequence[int],
        candidate: ReplacementCandidate | Mapping[str, Any],
        confirmed: bool,
    ) -> list[ReplacementApplicationResult]:
        """Persist one confirmed replacement across multiple BOM rows."""

        normalized_row_ids: list[int] = []
        for row_id in row_ids:
            value = int(row_id)
            if value > 0 and value not in normalized_row_ids:
                normalized_row_ids.append(value)
        results: list[ReplacementApplicationResult] = []
        for row_id in normalized_row_ids:
            results.append(await self.apply_replacement(row_id, candidate, confirmed))
        return results

    def build_replacement_batches(self, rows: Sequence[BomRow]) -> list[ReplacementBatch]:
        """Group similar rows so one candidate search can be reused safely."""

        grouped: "OrderedDict[str, list[BomRow]]" = OrderedDict()
        for row in rows:
            row_id = int(row.id or 0)
            if row_id <= 0:
                continue
            key = self._replacement_group_key(row)
            grouped.setdefault(key, []).append(row)

        batches: list[ReplacementBatch] = []
        for key, grouped_rows in grouped.items():
            exemplar = grouped_rows[0]
            designators = tuple(
                self._clean_text(row.designator) or f"Row {int(row.id or 0)}"
                for row in grouped_rows
            )
            row_ids = tuple(int(row.id or 0) for row in grouped_rows if int(row.id or 0) > 0)
            if not row_ids:
                continue
            batches.append(
                ReplacementBatch(
                    group_key=key,
                    label=self._replacement_group_label(exemplar),
                    row_ids=row_ids,
                    designators=designators,
                    exemplar_row_id=row_ids[0],
                )
            )
        return batches

    def resolve_search_keys(
        self,
        row: BomRow | None,
        *,
        criteria: PartSearchCriteria | Mapping[str, Any] | None = None,
    ) -> SearchKeyResolution:
        """Resolve search keys from a row and optional explicit criteria."""

        criteria_data = self._coerce_criteria(criteria)

        lcsc_part_number = self._first_non_empty(
            criteria_data.get("lcsc_part_number", ""),
            self._criteria_part_number(criteria_data, prefer_lcsc=True),
            self._row_value(row, "lcsc_part_number"),
            self._row_value(row, "mpn") if not criteria_data.get("part_number", "") else "",
        )
        mpn = self._first_non_empty(
            criteria_data.get("mpn", ""),
            self._criteria_part_number(criteria_data, prefer_lcsc=False),
            self._row_value(row, "mpn"),
        )
        source_url = self._first_non_empty(
            criteria_data.get("source_url", ""),
            self._row_value(row, "source_url"),
            self._row_value(row, "lcsc_link"),
        )
        comment = self._first_non_empty(
            criteria_data.get("comment", ""),
            criteria_data.get("value", ""),
            self._row_value(row, "comment"),
            self._row_value(row, "value_raw"),
        )
        footprint = self._first_non_empty(
            criteria_data.get("footprint", ""),
            self._row_value(row, "footprint"),
        )
        category = self._first_non_empty(
            criteria_data.get("category", ""),
            self._row_value(row, "category"),
        )
        param_summary = self._first_non_empty(
            criteria_data.get("param_summary", ""),
            criteria_data.get("comment", ""),
            self._row_value(row, "param_summary"),
            self._row_value(row, "comment"),
            criteria_data.get("value", ""),
            self._row_value(row, "value_raw"),
        )

        resolved = SearchKeys(
            lcsc_part_number=lcsc_part_number,
            mpn=mpn,
            source_url=source_url,
            comment=comment,
            footprint=footprint,
            category=category,
            param_summary=param_summary,
        )
        primary_field, primary_value = self._resolve_primary_field(resolved)
        return SearchKeyResolution(
            search_keys=resolved,
            primary_field=primary_field,
            primary_value=primary_value,
            priority_order=self._PRIMARY_SEARCH_FIELDS,
        )

    def _build_search_plan(self, search_keys: SearchKeys) -> list[SearchPlanStep]:
        plan: list[SearchPlanStep] = []
        seen_fingerprints: set[str] = set()

        def add_step(
            label: str,
            step_keys: SearchKeys,
            *,
            stop_if_candidates_at_least: int | None = None,
        ) -> None:
            fingerprint = self._search_keys_fingerprint(step_keys)
            if not fingerprint or fingerprint in seen_fingerprints:
                return
            seen_fingerprints.add(fingerprint)
            plan.append(
                SearchPlanStep(
                    label=label,
                    search_keys=step_keys,
                    stop_if_candidates_at_least=stop_if_candidates_at_least,
                )
            )

        if any(
            self._clean_text(value)
            for value in (
                search_keys.lcsc_part_number,
                search_keys.mpn,
                search_keys.source_url,
            )
        ):
            add_step(
                "exact_reference",
                SearchKeys(
                    lcsc_part_number=search_keys.lcsc_part_number,
                    mpn=search_keys.mpn,
                    source_url=search_keys.source_url,
                ),
            )

        focused_summary = self._first_non_empty(
            search_keys.param_summary,
            search_keys.comment,
        )
        if focused_summary:
            add_step(
                "value_footprint",
                SearchKeys(
                    comment=focused_summary,
                    footprint=search_keys.footprint,
                    category=search_keys.category,
                    param_summary=focused_summary,
                ),
                stop_if_candidates_at_least=self._BROAD_FALLBACK_THRESHOLD,
            )
            add_step(
                "broad_text",
                SearchKeys(
                    comment=focused_summary,
                    category=search_keys.category,
                    param_summary=focused_summary,
                ),
            )
        return plan

    async def _retrieve_search_plan_evidence(
        self,
        search_plan: Sequence[SearchPlanStep],
    ) -> list[RawEvidence]:
        merged_evidence: list[RawEvidence] = []
        for step in search_plan:
            step_evidence = list(await self._retriever.retrieve(step.search_keys))
            if step_evidence:
                merged_evidence = self._merge_raw_evidence(merged_evidence, step_evidence)
            if step.stop_if_candidates_at_least is None:
                continue
            if len(self._parse_candidates(merged_evidence)) >= step.stop_if_candidates_at_least:
                break
        return merged_evidence

    async def _resolve_context_row(
        self,
        *,
        row_id: int | None,
        criteria: PartSearchCriteria | Mapping[str, Any] | None,
    ) -> BomRow:
        if row_id is not None:
            row = await self._load_row(row_id)
            if criteria is None:
                return row
            merged = self._build_row_from_criteria(criteria, base_row=row)
            return merged

        return self._build_row_from_criteria(criteria)

    def _build_row_from_criteria(
        self,
        criteria: PartSearchCriteria | Mapping[str, Any] | None,
        *,
        base_row: BomRow | None = None,
    ) -> BomRow:
        criteria_data = self._coerce_criteria(criteria)
        row = self._detached_row_copy(base_row) if base_row is not None else BomRow(project_id=0)
        row.lcsc_part_number = self._first_non_empty(
            criteria_data.get("lcsc_part_number", ""),
            self._criteria_part_number(criteria_data, prefer_lcsc=True),
            row.lcsc_part_number,
        )
        row.mpn = self._first_non_empty(
            criteria_data.get("mpn", ""),
            self._criteria_part_number(criteria_data, prefer_lcsc=False),
            row.mpn,
        )
        row.source_url = self._first_non_empty(criteria_data.get("source_url", ""), row.source_url)
        row.lcsc_link = self._first_non_empty(criteria_data.get("source_url", ""), row.lcsc_link)
        row.comment = self._first_non_empty(criteria_data.get("comment", ""), row.comment)
        if not row.comment:
            row.comment = self._first_non_empty(criteria_data.get("value", ""), row.value_raw)
        row.value_raw = self._first_non_empty(criteria_data.get("value", ""), row.value_raw)
        row.footprint = self._first_non_empty(criteria_data.get("footprint", ""), row.footprint)
        row.category = self._first_non_empty(criteria_data.get("category", ""), row.category)
        row.param_summary = self._first_non_empty(
            criteria_data.get("param_summary", ""),
            criteria_data.get("comment", ""),
            row.param_summary,
            row.comment,
            criteria_data.get("value", ""),
            row.value_raw,
        )
        row.manufacturer = self._first_non_empty(
            criteria_data.get("manufacturer", ""),
            row.manufacturer,
        )
        return row

    def _detached_row_copy(self, row: BomRow) -> BomRow:
        data = row.model_dump(exclude={"project"})
        return BomRow.model_validate(data)

    async def _load_row(self, row_id: int) -> BomRow:
        row = await self._repository.get_row(row_id)
        if row is None:
            raise ValueError(f"Unknown row id: {row_id}")
        return row

    def _parse_candidates(self, evidence: Sequence[RawEvidence]) -> list[ReplacementCandidate]:
        parsed_candidates: "OrderedDict[str, ReplacementCandidate]" = OrderedDict()
        for raw_evidence in evidence:
            for candidate_data in self._extract_candidate_payloads(raw_evidence.raw_content):
                candidate = self._candidate_from_payload(candidate_data, raw_evidence)
                signature = self._candidate_signature(candidate)
                if signature not in parsed_candidates:
                    parsed_candidates[signature] = candidate
                    continue
                parsed_candidates[signature] = self._merge_candidates(
                    parsed_candidates[signature],
                    candidate,
                )
        return list(parsed_candidates.values())

    def _extract_candidate_payloads(self, raw_content: str) -> list[Mapping[str, Any]]:
        content = self._try_parse_json(raw_content)
        if isinstance(content, list):
            return [item for item in content if isinstance(item, Mapping)]
        if isinstance(content, Mapping):
            if isinstance(content.get("candidates"), list):
                return [item for item in content["candidates"] if isinstance(item, Mapping)]
            if isinstance(content.get("results"), list):
                return [item for item in content["results"] if isinstance(item, Mapping)]
            return [content]

        blocks = [block.strip() for block in re.split(r"\n\s*\n", raw_content.strip()) if block.strip()]
        if not blocks:
            return []
        return [self._parse_text_block(block) for block in blocks]

    def _parse_text_block(self, block: str) -> Mapping[str, Any]:
        payload: dict[str, Any] = {}
        for line in block.splitlines():
            match = re.match(r"\s*([A-Za-z0-9 _./-]+)\s*[:=]\s*(.+?)\s*$", line)
            if not match:
                continue
            key = self._normalize_key(match.group(1))
            value = match.group(2).strip()
            payload[key] = value
        if not payload:
            payload["description"] = block.strip()
        return payload

    def _candidate_from_payload(
        self,
        payload: Mapping[str, Any],
        raw_evidence: RawEvidence,
    ) -> ReplacementCandidate:
        evidence_record = EvidenceRecord(
            field_name="replacement_candidate",
            value=self._clean_text(raw_evidence.raw_content),
            evidence_type=EvidenceType.OBSERVED,
            source_url=self._clean_text(raw_evidence.source_url),
            source_name=self._clean_text(raw_evidence.source_name),
            retrieved_at=raw_evidence.retrieved_at or _utc_epoch(),
            confidence=Confidence.MEDIUM,
            raw_snippet=self._clean_text(raw_evidence.raw_content)[:250],
            notes=self._clean_text(raw_evidence.search_strategy),
        )

        stock_qty = self._extract_int(
            payload,
            "stock_qty",
            "stock",
            "quantity",
            "qty",
        )
        stock_status = self._normalize_stock_status(
            self._extract_text(
                payload,
                "stock_status",
                "availability",
                "availability_status",
                "stock_bucket",
            )
        )
        if not stock_status:
            stock_status = self._infer_stock_status(stock_qty)

        lifecycle_status = self._normalize_lifecycle_status(
            self._extract_text(payload, "lifecycle_status", "lifecycle", "status")
        )

        raw_part_number = self._extract_text(payload, "part_number")
        raw_lcsc_part_number = self._extract_text(payload, "lcsc_part_number")
        lcsc_part_number = self._first_non_empty(
            raw_lcsc_part_number
            if self._looks_like_lcsc_part_number(raw_lcsc_part_number)
            else "",
            raw_part_number if self._looks_like_lcsc_part_number(raw_part_number) else "",
        )
        part_number = self._first_non_empty(
            raw_part_number,
            raw_lcsc_part_number,
            self._extract_text(payload, "mpn"),
        )
        mpn = self._first_non_empty(
            self._extract_text(payload, "mpn", "manufacturer_part_number"),
            "" if self._looks_like_lcsc_part_number(part_number) else part_number,
        )

        candidate = ReplacementCandidate(
            manufacturer=self._extract_text(payload, "manufacturer", "brand", "vendor"),
            mpn=mpn,
            footprint=self._extract_text(payload, "footprint"),
            package=self._extract_text(payload, "package", "pkg"),
            value_summary=self._extract_text(
                payload,
                "value_summary",
                "value",
                "description",
                "summary",
                "param_summary",
            ),
            lcsc_link=self._extract_text(payload, "lcsc_link", "source_url", "url", "link"),
            lcsc_part_number=lcsc_part_number,
            stock_qty=stock_qty,
            lifecycle_status=lifecycle_status,
            confidence=self._extract_confidence(payload),
            match_score=0.0,
            match_explanation="",
            differences=self._extract_text(payload, "differences"),
            warnings=self._extract_warnings(payload),
            evidence=[evidence_record],
            part_number=part_number,
            description=self._extract_text(payload, "description", "summary", "value_summary"),
            stock_status=stock_status,
        )
        return candidate

    def _merge_candidates(
        self,
        left: ReplacementCandidate,
        right: ReplacementCandidate,
    ) -> ReplacementCandidate:
        merged_evidence = [*left.evidence]
        for record in right.evidence:
            if record not in merged_evidence:
                merged_evidence.append(record)
        merged_warnings = list(dict.fromkeys([*left.warnings, *right.warnings]))
        return left.model_copy(
            update={
                "manufacturer": self._first_non_empty(left.manufacturer, right.manufacturer),
                "mpn": self._first_non_empty(left.mpn, right.mpn),
                "footprint": self._first_non_empty(left.footprint, right.footprint),
                "package": self._first_non_empty(left.package, right.package),
                "value_summary": self._first_non_empty(left.value_summary, right.value_summary),
                "lcsc_link": self._first_non_empty(left.lcsc_link, right.lcsc_link),
                "lcsc_part_number": self._first_non_empty(
                    left.lcsc_part_number,
                    right.lcsc_part_number,
                ),
                "stock_qty": left.stock_qty if left.stock_qty is not None else right.stock_qty,
                "lifecycle_status": left.lifecycle_status
                if left.lifecycle_status != LifecycleStatus.UNKNOWN
                else right.lifecycle_status,
                "confidence": left.confidence
                if left.confidence != Confidence.NONE
                else right.confidence,
                "match_score": max(left.match_score, right.match_score),
                "match_explanation": self._first_non_empty(
                    left.match_explanation,
                    right.match_explanation,
                ),
                "differences": self._first_non_empty(left.differences, right.differences),
                "warnings": merged_warnings,
                "evidence": merged_evidence,
                "part_number": self._first_non_empty(left.part_number, right.part_number),
                "description": self._first_non_empty(left.description, right.description),
                "stock_status": self._first_non_empty(left.stock_status, right.stock_status),
            }
        )

    def _candidate_signature(self, candidate: ReplacementCandidate) -> str:
        return "|".join(
            [
                self._normalize_key(candidate.lcsc_part_number),
                self._normalize_key(candidate.part_number),
                self._normalize_key(candidate.mpn),
                self._normalize_key(candidate.lcsc_link),
            ]
        )

    def _replacement_group_key(self, row: BomRow) -> str:
        lcsc_part_number = self._clean_text(row.lcsc_part_number)
        if lcsc_part_number:
            return f"lcsc:{self._normalize_key(lcsc_part_number)}"
        mpn = self._clean_text(row.mpn)
        if mpn:
            return f"mpn:{self._normalize_key(mpn)}"
        manufacturer = self._clean_text(row.manufacturer)
        value = self._clean_text(row.comment or row.value_raw)
        footprint = self._clean_text(row.footprint)
        return "|".join(
            [
                "shape",
                self._normalize_key(manufacturer),
                self._normalize_key(value),
                self._normalize_key(footprint),
            ]
        )

    def _replacement_group_label(self, row: BomRow) -> str:
        return self._first_non_empty(
            row.mpn,
            row.lcsc_part_number,
            row.comment,
            row.value_raw,
            row.designator,
            "replacement batch",
        )

    def _requires_manual_review(self, candidate: ReplacementCandidate, score: float) -> bool:
        if score < self._manual_review_threshold:
            return True
        if self._is_risky_lifecycle(candidate.lifecycle_status):
            return True
        if self._is_out_of_stock(candidate):
            return True
        return False

    def _is_risky_lifecycle(self, lifecycle_status: LifecycleStatus | str) -> bool:
        normalized = self._normalize_lifecycle_status(lifecycle_status)
        return normalized in _RISKY_LIFECYCLE_STATUSES

    def _is_out_of_stock(self, candidate: ReplacementCandidate) -> bool:
        if candidate.stock_qty is not None and candidate.stock_qty <= 0:
            return True
        return self._normalize_stock_status(candidate.stock_status) in _OUT_OF_STOCK_STATUSES

    async def _expand_evidence_with_llm(
        self,
        context_row: BomRow,
        criteria: PartSearchCriteria,
        search_resolution: SearchKeyResolution,
        evidence: Sequence[RawEvidence],
        initial_candidates: Sequence[ReplacementCandidate],
    ) -> list[RawEvidence]:
        try:
            response = await self._llm_search_stage(
                context_row,
                criteria,
                search_resolution,
                tuple(initial_candidates),
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.exception(
                "part_finder_llm_search_stage_failed",
                row_id=int(context_row.id or 0),
                project_id=int(context_row.project_id or 0),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return list(evidence)

        if response is None or not response.search_leads:
            return list(evidence)

        merged_evidence = list(evidence)
        seen_keys = {
            self._search_keys_fingerprint(search_resolution.search_keys),
        }
        logger.info(
            "part_finder_llm_search_expansion_started",
            row_id=int(context_row.id or 0),
            project_id=int(context_row.project_id or 0),
            lead_count=len(response.search_leads),
            summary=response.summary,
        )
        for lead in response.search_leads[:_MAX_LLM_SEARCH_LEADS]:
            search_keys = self._search_keys_from_llm_lead(lead, context_row, criteria)
            fingerprint = self._search_keys_fingerprint(search_keys)
            if not fingerprint or fingerprint in seen_keys:
                continue
            seen_keys.add(fingerprint)
            try:
                extra_evidence = await self._retriever.retrieve(search_keys)
            except Exception as exc:  # pragma: no cover - defensive boundary
                logger.exception(
                    "part_finder_llm_search_retrieve_failed",
                    row_id=int(context_row.id or 0),
                    project_id=int(context_row.project_id or 0),
                    error_type=type(exc).__name__,
                    error=str(exc),
                    search_keys=search_keys.model_dump(mode="json"),
                )
                continue
            if not extra_evidence:
                continue
            logger.info(
                "part_finder_llm_search_retrieve_succeeded",
                row_id=int(context_row.id or 0),
                project_id=int(context_row.project_id or 0),
                search_keys=search_keys.model_dump(mode="json"),
                evidence_count=len(extra_evidence),
                rationale=self._clean_text(lead.rationale),
            )
            merged_evidence.extend(extra_evidence)
        return merged_evidence

    def _search_keys_from_llm_lead(
        self,
        lead: PartFinderLLMSearchLeadSchema,
        context_row: BomRow,
        criteria: PartSearchCriteria,
    ) -> SearchKeys:
        lead_part_number = self._clean_text(lead.part_number)
        lead_lcsc = self._first_non_empty(
            lead.lcsc_part_number,
            lead_part_number if self._looks_like_lcsc_part_number(lead_part_number) else "",
        )
        lead_mpn = self._first_non_empty(
            lead.mpn,
            "" if lead_lcsc else lead_part_number,
        )
        return SearchKeys(
            lcsc_part_number=lead_lcsc,
            mpn=lead_mpn,
            source_url=self._first_non_empty(
                self._compatible_search_source_url(criteria.source_url, lead_lcsc, lead_mpn),
                self._compatible_search_source_url(context_row.source_url, lead_lcsc, lead_mpn),
                self._compatible_search_source_url(context_row.lcsc_link, lead_lcsc, lead_mpn),
            ),
            comment=self._first_non_empty(
                criteria.comment,
                criteria.value,
                context_row.comment,
                context_row.value_raw,
            ),
            footprint=self._first_non_empty(
                lead.footprint,
                criteria.footprint,
                context_row.footprint,
                context_row.package,
            ),
            category=self._first_non_empty(
                lead.category,
                criteria.category,
                context_row.category,
            ),
            param_summary=self._first_non_empty(
                lead.param_summary,
                criteria.param_summary,
                context_row.param_summary,
                criteria.value,
                context_row.comment,
                context_row.value_raw,
            ),
        )

    def _merge_raw_evidence(
        self,
        left: Sequence[RawEvidence],
        right: Sequence[RawEvidence],
    ) -> list[RawEvidence]:
        merged: list[RawEvidence] = []
        seen: set[str] = set()
        for record in [*left, *right]:
            fingerprint = json.dumps(
                {
                    "source_url": self._clean_text(record.source_url),
                    "source_name": self._clean_text(record.source_name),
                    "content_type": self._clean_text(record.content_type),
                    "raw_content": self._clean_text(record.raw_content),
                    "search_strategy": self._clean_text(record.search_strategy),
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            merged.append(record)
        return merged

    def _search_keys_fingerprint(self, search_keys: SearchKeys) -> str:
        if not any(
            self._clean_text(value)
            for value in (
                search_keys.lcsc_part_number,
                search_keys.mpn,
                search_keys.source_url,
                search_keys.comment,
                search_keys.footprint,
                search_keys.category,
                search_keys.param_summary,
            )
        ):
            return ""
        return json.dumps(
            search_keys.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    def _compatible_search_source_url(
        self,
        source_url: str,
        lcsc_part_number: str,
        mpn: str,
    ) -> str:
        normalized_url = self._clean_text(source_url)
        if not normalized_url:
            return ""
        lowered_url = normalized_url.casefold()
        if any(token in lowered_url for token in ("/search", "componentsearch", "/parts")):
            return normalized_url
        for identifier in (self._clean_text(lcsc_part_number), self._clean_text(mpn)):
            if identifier and identifier.casefold() in lowered_url:
                return normalized_url
        if not self._clean_text(lcsc_part_number) and not self._clean_text(mpn):
            return normalized_url
        return ""

    def _candidate_matches_filters(
        self,
        candidate: ReplacementCandidate,
        criteria: PartSearchCriteria,
        context_row: BomRow,
    ) -> bool:
        return not self._candidate_filter_rejection_reasons(candidate, criteria, context_row)

    def _candidate_filter_rejection_reasons(
        self,
        candidate: ReplacementCandidate,
        criteria: PartSearchCriteria,
        context_row: BomRow,
    ) -> list[str]:
        reasons: list[str] = []
        if criteria.active_only and self._is_non_active_lifecycle(candidate.lifecycle_status):
            reasons.append("active_only")
        if criteria.in_stock and self._is_out_of_stock(candidate):
            reasons.append("in_stock")
        if criteria.lcsc_available and not self._candidate_has_lcsc_availability(candidate):
            reasons.append("lcsc_available")
        if criteria.minimum_stock_qty is not None:
            if not self._meets_minimum_stock_qty(candidate, criteria.minimum_stock_qty):
                reasons.append(f"minimum_stock_qty:{criteria.minimum_stock_qty}")
        if criteria.keep_same_footprint and not self._matches_same_footprint(context_row, candidate):
            reasons.append("keep_same_footprint")
        if criteria.keep_same_manufacturer and not self._matches_same_manufacturer(
            context_row,
            candidate,
        ):
            reasons.append("keep_same_manufacturer")
        return reasons

    def _is_non_active_lifecycle(self, lifecycle_status: LifecycleStatus | str) -> bool:
        normalized = self._normalize_lifecycle_status(lifecycle_status)
        return normalized in {
            LifecycleStatus.NRND.value,
            LifecycleStatus.LAST_TIME_BUY.value,
            LifecycleStatus.EOL.value,
        }

    def _meets_minimum_stock_qty(
        self,
        candidate: ReplacementCandidate,
        minimum_stock_qty: int,
    ) -> bool:
        if minimum_stock_qty <= 0:
            return True
        if candidate.stock_qty is not None:
            return candidate.stock_qty >= minimum_stock_qty
        estimated_floor = self._estimated_stock_qty_floor(candidate)
        if estimated_floor is None:
            return False
        return estimated_floor >= minimum_stock_qty

    def _estimated_stock_qty_floor(
        self,
        candidate: ReplacementCandidate,
    ) -> int | None:
        stock_status = self._normalize_stock_status(candidate.stock_status)
        floors = {
            "high": 1_000,
            "medium": 100,
            "low": 10,
            "out": 0,
        }
        return floors.get(stock_status)

    async def _rerank_with_llm(
        self,
        context_row: BomRow,
        criteria: PartSearchCriteria,
        results: list[ReplacementSearchResult],
    ) -> list[ReplacementSearchResult]:
        llm_scope = list(results[:_MAX_LLM_RERANK_CANDIDATES])
        untouched = list(results[_MAX_LLM_RERANK_CANDIDATES:])
        try:
            response = await self._llm_stage(context_row, criteria, tuple(llm_scope))
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.exception(
                "part_finder_llm_stage_failed",
                row_id=int(context_row.id or 0),
                project_id=int(context_row.project_id or 0),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return results

        if response is None or not response.ranked_candidates:
            return results

        logger.info(
            "part_finder_llm_rerank_received",
            row_id=int(context_row.id or 0),
            project_id=int(context_row.project_id or 0),
            candidate_count=len(llm_scope),
            decision_count=len(response.ranked_candidates),
            summary=response.summary,
        )
        decisions = {
            self._normalize_key(decision.candidate_id): decision
            for decision in response.ranked_candidates
            if self._clean_text(decision.candidate_id)
        }
        reranked: list[ReplacementSearchResult] = []
        for index, result in enumerate(llm_scope, start=1):
            decision = decisions.get(self._normalize_key(f"candidate_{index}"))
            if decision is not None and not decision.keep:
                continue
            if decision is None:
                reranked.append(result)
                continue
            score_value = self._blend_llm_score(result.score, decision.adjusted_score)
            explanation = result.explanation
            rationale = self._clean_text(decision.rationale)
            if rationale:
                explanation = f"{result.explanation} LLM rerank: {rationale}"
            candidate = result.candidate.model_copy(
                update={
                    "match_score": score_value,
                    "match_explanation": explanation,
                }
            )
            reranked.append(
                ReplacementSearchResult(
                    candidate=candidate,
                    score=score_value,
                    explanation=explanation,
                    requires_manual_review=self._requires_manual_review(candidate, score_value),
                )
            )
        return self._sort_results([*reranked, *untouched])

    def _sort_results(
        self,
        results: Sequence[ReplacementSearchResult],
    ) -> list[ReplacementSearchResult]:
        return sorted(
            list(results),
            key=lambda result: (
                -float(result.score),
                self._normalize_key(result.candidate.lcsc_part_number),
                self._normalize_key(result.candidate.part_number),
                self._normalize_key(result.candidate.mpn),
            ),
        )

    def _apply_availability_preference(
        self,
        candidate: ReplacementCandidate,
        score: float,
        explanation: str,
    ) -> tuple[float, str]:
        bonus = self._availability_preference_bonus(candidate)
        if bonus <= 0.0:
            return score, explanation
        updated = min(1.0, round(score + bonus, 6))
        return updated, f"{explanation} Availability preference bonus applied (+{bonus:.3f})."

    def _availability_preference_bonus(self, candidate: ReplacementCandidate) -> float:
        if self._is_out_of_stock(candidate):
            return 0.0
        bonus = 0.0
        stock_qty = candidate.stock_qty
        if stock_qty is not None and stock_qty > 0:
            if stock_qty >= 1_000_000:
                bonus += 0.10
            elif stock_qty >= 100_000:
                bonus += 0.08
            elif stock_qty >= 10_000:
                bonus += 0.06
            elif stock_qty >= 1_000:
                bonus += 0.04
            elif stock_qty >= 100:
                bonus += 0.02
        stock_status = self._normalize_stock_status(candidate.stock_status)
        if stock_status == "high":
            bonus += 0.03
        elif stock_status == "medium":
            bonus += 0.02
        elif stock_status == "low":
            bonus += 0.01
        if candidate.confidence == Confidence.HIGH:
            bonus += 0.01
        return min(0.12, round(bonus, 6))

    def _matches_same_footprint(
        self,
        context_row: BomRow,
        candidate: ReplacementCandidate,
    ) -> bool:
        context_values = self._footprint_constraint_tokens(
            context_row.footprint,
            context_row.package,
        )
        candidate_values = self._footprint_constraint_tokens(
            candidate.footprint,
            candidate.package,
            candidate.description,
        )
        if not context_values:
            return True
        if not candidate_values:
            return False
        return not context_values.isdisjoint(candidate_values)

    def _matches_same_manufacturer(
        self,
        context_row: BomRow,
        candidate: ReplacementCandidate,
    ) -> bool:
        expected = self._normalize_key(context_row.manufacturer)
        if not expected:
            return True
        return self._normalize_key(candidate.manufacturer) == expected

    def _footprint_constraint_tokens(self, *values: object) -> set[str]:
        text = " ".join(self._clean_text(value) for value in values if self._clean_text(value))
        if not text:
            return set()
        normalized = self._normalize_key(text)
        tokens = {
            match.group(0)
            for match in re.finditer(r"\b[a-z]{2,8}-?\d{1,4}\b|\b\d{4}\b", normalized)
        }
        if not tokens and normalized:
            tokens.add(normalized)
        if any(size in normalized for size in ("0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512")):
            for size in ("0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512"):
                if size in normalized:
                    tokens.add(size)
        return tokens

    def _blend_llm_score(self, base_score: float, adjusted_score: float) -> float:
        llm_score = float(adjusted_score or 0.0)
        if llm_score <= 0.0:
            return base_score
        blended = (base_score * (1.0 - _LLM_SCORE_BLEND)) + (llm_score * _LLM_SCORE_BLEND)
        return max(0.0, min(1.0, round(blended, 6)))

    def _apply_candidate_to_row(self, row: BomRow, candidate: ReplacementCandidate) -> None:
        row.replacement_candidate_part_number = self._first_non_empty(
            candidate.lcsc_part_number,
            candidate.part_number,
            candidate.mpn,
        )
        row.replacement_candidate_link = candidate.lcsc_link
        row.replacement_candidate_mpn = self._first_non_empty(candidate.mpn, candidate.part_number)
        row.replacement_rationale = self._first_non_empty(
            candidate.match_explanation,
            f"Selected candidate {self._candidate_label(candidate)}.",
        )
        row.replacement_match_score = candidate.match_score
        row.replacement_status = ReplacementStatus.USER_ACCEPTED.value
        row.user_accepted_replacement = True

        row.manufacturer = self._first_non_empty(candidate.manufacturer, row.manufacturer)
        row.mpn = self._first_non_empty(candidate.mpn, candidate.part_number, row.mpn)
        row.package = self._first_non_empty(candidate.package, row.package)
        row.footprint = self._first_non_empty(candidate.footprint, row.footprint)
        row.lcsc_part_number = self._first_non_empty(candidate.lcsc_part_number, row.lcsc_part_number)
        row.lcsc_link = self._first_non_empty(candidate.lcsc_link, row.lcsc_link)
        row.stock_qty = candidate.stock_qty
        row.stock_status = self._first_non_empty(candidate.stock_status, row.stock_status)
        row.lifecycle_status = self._normalize_lifecycle_status(candidate.lifecycle_status)
        row.source_url = self._first_non_empty(candidate.lcsc_link, self._candidate_source_url(candidate))
        row.source_name = self._candidate_source_name(candidate, row.source_name)
        row.source_confidence = self._confidence_value(candidate.confidence)
        row.sourcing_notes = self._merge_notes(row.sourcing_notes, candidate)
        if candidate.description and not row.param_summary:
            row.param_summary = candidate.description

    def _candidate_source_url(self, candidate: ReplacementCandidate) -> str:
        if candidate.evidence:
            return self._clean_text(candidate.evidence[0].source_url)
        return ""

    def _candidate_source_name(self, candidate: ReplacementCandidate, fallback: str) -> str:
        if candidate.evidence:
            return self._first_non_empty(candidate.evidence[0].source_name, fallback)
        return fallback

    def _merge_notes(self, current: str, candidate: ReplacementCandidate) -> str:
        notes = [note for note in self._split_notes(current) if note]
        selected_note = (
            f"Applied replacement {self._candidate_label(candidate)} with score {candidate.match_score:.3f}."
        )
        if candidate.lcsc_link:
            selected_note += f" Source: {candidate.lcsc_link}."
        elif candidate.evidence:
            selected_note += f" Source: {candidate.evidence[0].source_url}."
        notes.append(selected_note)
        return " | ".join(dict.fromkeys(notes))

    def _split_notes(self, value: str) -> list[str]:
        cleaned = self._clean_text(value)
        if not cleaned:
            return []
        return [segment.strip() for segment in re.split(r"[|;\n]+", cleaned) if segment.strip()]

    def _resolve_primary_field(self, search_keys: SearchKeys) -> tuple[str, str]:
        for field_name in self._PRIMARY_SEARCH_FIELDS:
            value = self._clean_text(getattr(search_keys, field_name, ""))
            if value:
                return field_name, value
        return "", ""

    def _coerce_candidate(
        self,
        candidate: ReplacementCandidate | Mapping[str, Any],
    ) -> ReplacementCandidate:
        if isinstance(candidate, ReplacementCandidate):
            return candidate
        return ReplacementCandidate.model_validate(candidate)

    def _coerce_criteria(
        self,
        criteria: PartSearchCriteria | Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        data = asdict(self._coerce_criteria_model(criteria))

        normalized: dict[str, Any] = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, bool):
                normalized[self._normalize_key(key)] = value
                continue
            if isinstance(value, Mapping):
                continue
            normalized[self._normalize_key(key)] = self._clean_text(value)
        return normalized

    def _coerce_criteria_model(
        self,
        criteria: PartSearchCriteria | Mapping[str, Any] | None,
    ) -> PartSearchCriteria:
        if criteria is None:
            return PartSearchCriteria()
        if isinstance(criteria, PartSearchCriteria):
            return criteria

        raw = dict(criteria)
        integer_value: int | None = None
        minimum_stock_qty = raw.get("minimum_stock_qty")
        if isinstance(minimum_stock_qty, int):
            integer_value = minimum_stock_qty if minimum_stock_qty > 0 else None
        elif isinstance(minimum_stock_qty, str) and minimum_stock_qty.strip().isdigit():
            parsed = int(minimum_stock_qty.strip())
            integer_value = parsed if parsed > 0 else None

        return PartSearchCriteria(
            part_number=self._clean_text(raw.get("part_number", "")),
            lcsc_part_number=self._clean_text(raw.get("lcsc_part_number", "")),
            mpn=self._clean_text(raw.get("mpn", "")),
            source_url=self._clean_text(raw.get("source_url", "")),
            comment=self._clean_text(raw.get("comment", "")),
            value=self._clean_text(raw.get("value", "")),
            footprint=self._clean_text(raw.get("footprint", "")),
            category=self._clean_text(raw.get("category", "")),
            param_summary=self._clean_text(raw.get("param_summary", "")),
            manufacturer=self._clean_text(raw.get("manufacturer", "")),
            active_only=self._criteria_flag(raw, "active_only"),
            in_stock=self._criteria_flag(raw, "in_stock"),
            lcsc_available=self._criteria_flag(raw, "lcsc_available"),
            keep_same_footprint=self._criteria_flag(raw, "keep_same_footprint"),
            keep_same_manufacturer=self._criteria_flag(raw, "keep_same_manufacturer"),
            prefer_high_availability=self._criteria_flag(raw, "prefer_high_availability"),
            minimum_stock_qty=integer_value,
        )

    def _criteria_flag(self, criteria: Mapping[str, Any], key: str) -> bool:
        value = criteria.get(self._normalize_key(key), False)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return bool(value)

    def _candidate_has_lcsc_availability(self, candidate: ReplacementCandidate) -> bool:
        if self._looks_like_lcsc_part_number(candidate.lcsc_part_number):
            return True
        link = self._clean_text(candidate.lcsc_link).casefold()
        return "lcsc.com" in link

    def _criteria_part_number(self, criteria: Mapping[str, str], *, prefer_lcsc: bool) -> str:
        part_number = self._clean_text(criteria.get("part_number", ""))
        if not part_number:
            return ""
        if self._looks_like_lcsc_part_number(part_number):
            return part_number if prefer_lcsc else ""
        return "" if prefer_lcsc else part_number

    def _looks_like_lcsc_part_number(self, value: str) -> bool:
        text = self._clean_text(value).upper()
        return bool(re.fullmatch(r"C\d{3,}", text))

    def _first_non_empty(self, *values: object) -> str:
        for value in values:
            text = self._clean_text(value)
            if text:
                return text
        return ""

    def _row_value(self, row: BomRow | None, field_name: str) -> str:
        if row is None:
            return ""
        return self._clean_text(getattr(row, field_name, ""))

    def _extract_text(self, payload: Mapping[str, Any], *keys: str) -> str:
        normalized = self._normalize_mapping_keys(payload)
        for key in keys:
            value = normalized.get(self._normalize_key(key))
            if value is None:
                continue
            text = self._clean_text(value)
            if text:
                return text
        return ""

    def _extract_int(self, payload: Mapping[str, Any], *keys: str) -> int | None:
        normalized = self._normalize_mapping_keys(payload)
        for key in keys:
            value = normalized.get(self._normalize_key(key))
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                match = re.search(r"-?\d+", value)
                if match:
                    return int(match.group(0))
        return None

    def _extract_confidence(self, payload: Mapping[str, Any]) -> Confidence:
        text = self._extract_text(payload, "confidence", "source_confidence")
        normalized = self._normalize_key(text)
        mapping = {
            "high": Confidence.HIGH,
            "medium": Confidence.MEDIUM,
            "low": Confidence.LOW,
            "none": Confidence.NONE,
            "very_high": Confidence.HIGH,
            "very_low": Confidence.LOW,
        }
        return mapping.get(normalized, Confidence.NONE)

    def _extract_warnings(self, payload: Mapping[str, Any]) -> list[str]:
        warnings = self._normalize_mapping_keys(payload).get("warnings", [])
        if isinstance(warnings, list):
            return [self._clean_text(item) for item in warnings if self._clean_text(item)]
        text = self._clean_text(warnings)
        if not text:
            return []
        return [segment.strip() for segment in re.split(r"[|;\n]+", text) if segment.strip()]

    def _normalize_lifecycle_status(self, value: LifecycleStatus | str) -> str:
        if isinstance(value, LifecycleStatus):
            return value.value
        normalized = self._normalize_key(value)
        replacements = {
            "inproduction": LifecycleStatus.ACTIVE.value,
            "production": LifecycleStatus.ACTIVE.value,
            "active": LifecycleStatus.ACTIVE.value,
            "nrnd": LifecycleStatus.NRND.value,
            "notrecommendedfornewdesigns": LifecycleStatus.NRND.value,
            "not_recommended_for_new_designs": LifecycleStatus.NRND.value,
            "lasttimebuy": LifecycleStatus.LAST_TIME_BUY.value,
            "last_time_buy": LifecycleStatus.LAST_TIME_BUY.value,
            "ltb": LifecycleStatus.LAST_TIME_BUY.value,
            "endoflife": LifecycleStatus.EOL.value,
            "eol": LifecycleStatus.EOL.value,
            "obsolete": LifecycleStatus.EOL.value,
            "unknown": LifecycleStatus.UNKNOWN.value,
        }
        return replacements.get(normalized, normalized or LifecycleStatus.UNKNOWN.value)

    def _normalize_stock_status(self, value: object) -> str:
        normalized = self._normalize_key(value)
        replacements = {
            "instock": "high",
            "available": "high",
            "high": "high",
            "medium": "medium",
            "limited": "low",
            "low": "low",
            "outofstock": "out",
            "out_of_stock": "out",
            "out": "out",
            "unavailable": "out",
            "unknown": "unknown",
        }
        return replacements.get(normalized, normalized)

    def _infer_stock_status(self, stock_qty: int | None) -> str:
        if stock_qty is None:
            return ""
        if stock_qty <= 0:
            return "out"
        if stock_qty <= 10:
            return "low"
        if stock_qty <= 100:
            return "medium"
        return "high"

    def _confidence_value(self, confidence: Confidence | str) -> str:
        if isinstance(confidence, Confidence):
            return confidence.value
        return self._normalize_key(confidence) or Confidence.NONE.value

    def _candidate_label(self, candidate: ReplacementCandidate) -> str:
        for value in (
            candidate.lcsc_part_number,
            candidate.part_number,
            candidate.mpn,
            candidate.manufacturer,
            candidate.description,
        ):
            text = self._clean_text(value)
            if text:
                return text
        return "replacement candidate"

    def _try_parse_json(self, value: str) -> Any:
        text = self._clean_text(value)
        if not text or text[0] not in "[{":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _normalize_mapping_keys(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            normalized[self._normalize_key(key)] = value
        return normalized

    def _normalize_key(self, value: object) -> str:
        text = self._clean_text(value).casefold().replace(" ", "_")
        return re.sub(r"[^a-z0-9_]+", "", text)

    def _clean_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()
