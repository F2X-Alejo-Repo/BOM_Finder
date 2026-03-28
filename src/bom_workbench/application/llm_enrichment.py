"""Grounded LLM enrichment stage contract and implementation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Sequence

import structlog
from pydantic import BaseModel, ConfigDict, Field

from ..domain.entities import BomRow
from ..domain.ports import ChatConfig, ProviderResponse, RawEvidence
from ..domain.value_objects import SearchKeys

__all__ = [
    "GroundedLLMEnrichmentStage",
    "GroundedLLMResponseSchema",
    "LLMEnrichmentOutcome",
    "LLMEnrichmentPatch",
    "LLMEnrichmentRequest",
    "LLMStage",
    "LlmEnrichmentPayload",
    "LlmEnrichmentStage",
    "LlmStageResult",
    "ProviderBackedLlmEnrichmentStage",
    "StructuredEnrichmentPatch",
    "build_grounded_llm_enrichment_stage",
]

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class LLMEnrichmentPatch:
    """LLM-derived enrichment fields that can be merged onto a BOM row."""

    manufacturer: str = ""
    mpn: str = ""
    package: str = ""
    category: str = ""
    param_summary: str = ""
    stock_qty: int | None = None
    stock_status: str = ""
    lifecycle_status: str = ""
    eol_risk: str = ""
    lead_time: str = ""
    moq: int | None = None
    source_url: str = ""
    source_name: str = ""
    source_confidence: str = ""
    sourcing_notes: str = ""
    last_checked_at: datetime | None = None
    validation_warnings: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class LLMEnrichmentOutcome:
    """Structured result returned by a grounded LLM stage."""

    success: bool
    provider_name: str = ""
    model_name: str = ""
    version: str = "llm-grounded-v1"
    patch: LLMEnrichmentPatch = field(default_factory=LLMEnrichmentPatch)
    warnings: list[str] = field(default_factory=list)
    error_message: str = ""
    latency_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    raw_response: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)
    error_category: str = ""
    retry_after_seconds: float | None = None


@dataclass(slots=True, frozen=True)
class LLMEnrichmentRequest:
    """Grounded context passed into an LLM enrichment stage."""

    row_id: int
    project_id: int
    row_snapshot: dict[str, Any]
    search_keys: SearchKeys
    primary_field: str
    primary_value: str
    deterministic_snapshot: dict[str, Any]
    evidence: Sequence[RawEvidence]


class GroundedLLMResponseSchema(BaseModel):
    """Schema enforced for grounded provider responses."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    manufacturer: str = ""
    mpn: str = ""
    package: str = ""
    category: str = ""
    param_summary: str = ""
    stock_qty: int | None = None
    stock_status: str = ""
    lifecycle_status: str = ""
    eol_risk: str = ""
    lead_time: str = ""
    moq: int | None = None
    source_url: str = ""
    source_name: str = ""
    source_confidence: str = ""
    sourcing_notes: str = ""
    last_checked_at: datetime | None = None
    validation_warnings: list[str] = Field(default_factory=list)


LLMStage = Callable[[BomRow, LLMEnrichmentRequest], Awaitable[LLMEnrichmentOutcome | None]]


class GroundedLLMEnrichmentStage:
    """Async grounded enrichment stage with provider and runtime fallbacks."""

    def __init__(
        self,
        provider_source: Any,
        *,
        api_key: str = "",
        model: str = "",
        timeout_seconds: int = 60,
        max_tokens: int = 2048,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
        allow_manual_approval: bool = False,
        system_prompt: str = "",
    ) -> None:
        self._provider_source = provider_source
        self._api_key = self._clean_text(api_key)
        self._model = self._clean_text(model)
        self._timeout_seconds = max(10, int(timeout_seconds or 60))
        self._max_tokens = max(256, int(max_tokens or 2048))
        self._temperature = temperature
        self._reasoning_effort = self._clean_text(reasoning_effort)
        self._allow_manual_approval = allow_manual_approval
        self._system_prompt = self._build_system_prompt(system_prompt)

    async def __call__(
        self,
        row: BomRow,
        request: LLMEnrichmentRequest,
    ) -> LLMEnrichmentOutcome | None:
        logger.info(
            "grounded_llm_stage_started",
            row_id=int(row.id or 0),
            project_id=int(row.project_id or 0),
            primary_field=request.primary_field,
            primary_value=request.primary_value,
            evidence_count=len(request.evidence),
            direct_adapter=self._is_direct_adapter(),
        )
        if self._is_direct_adapter():
            return await self._run_with_adapter(
                adapter=self._provider_source,
                provider_name=self._clean_text(getattr(self._provider_source, "get_name", lambda: "")()),
                api_key=self._api_key,
                model=self._model,
                row=row,
                request=request,
            )

        runtimes = await self._list_runtimes()
        if not runtimes:
            return None

        warnings: list[str] = []
        for runtime in runtimes:
            if not self._allow_manual_approval and bool(getattr(runtime, "manual_approval", False)):
                continue

            provider_name = self._clean_text(getattr(runtime, "provider", ""))
            model_name = self._clean_text(getattr(runtime, "model", ""))
            api_key = self._clean_text(getattr(runtime, "api_key", ""))
            if not provider_name or not model_name or not api_key:
                warnings.append(
                    f"Skipping incomplete grounded runtime configuration for '{provider_name or 'unknown'}'."
                )
                continue

            adapter = self._resolve_adapter(provider_name)
            if adapter is None:
                warnings.append(f"No adapter is registered for provider '{provider_name}'.")
                continue

            outcome = await self._run_with_adapter(
                adapter=adapter,
                provider_name=provider_name,
                api_key=api_key,
                model=model_name,
                row=row,
                request=request,
                runtime=runtime,
            )
            if outcome is None:
                continue
            if outcome.success:
                return outcome

            warnings.extend(outcome.warnings or [])
            if outcome.error_message:
                warnings.append(outcome.error_message)

        if warnings:
            return LLMEnrichmentOutcome(
                success=False,
                provider_name="",
                model_name="",
                warnings=self._deduplicate_strings(warnings),
                error_message="Grounded LLM enrichment could not complete with any enabled runtime.",
            )
        return None

    async def _run_with_adapter(
        self,
        *,
        adapter: Any,
        provider_name: str,
        api_key: str,
        model: str,
        row: BomRow,
        request: LLMEnrichmentRequest,
        runtime: Any | None = None,
    ) -> LLMEnrichmentOutcome | None:
        if not provider_name:
            provider_name = self._clean_text(getattr(adapter, "get_name", lambda: "")())
        if not model and runtime is not None:
            model = self._clean_text(getattr(runtime, "model", ""))
        if not api_key and runtime is not None:
            api_key = self._clean_text(getattr(runtime, "api_key", ""))
        if not provider_name or not model or not api_key:
            return LLMEnrichmentOutcome(
                success=False,
                provider_name=provider_name,
                model_name=model,
                warnings=["Grounded LLM runtime is missing provider, model, or API key."],
                error_message="Grounded LLM runtime is incomplete.",
                error_category="configuration_error",
            )

        if not hasattr(adapter, "chat_structured"):
            return LLMEnrichmentOutcome(
                success=False,
                provider_name=provider_name,
                model_name=model,
                warnings=[f"Provider '{provider_name}' does not support structured chat."],
                error_message="Structured chat is unavailable for the selected provider.",
                error_category="configuration_error",
            )

        config = self._build_chat_config(api_key=api_key, model=model, runtime=runtime)
        messages = self._build_messages(row=row, request=request)
        logger.info(
            "grounded_llm_request_prepared",
            row_id=int(row.id or 0),
            provider=provider_name,
            model=model,
            request_payload=self._request_payload(request),
            message_payload=messages,
            chat_config=self._chat_config_payload(config),
        )

        try:
            response: ProviderResponse = await adapter.chat_structured(
                messages,
                GroundedLLMResponseSchema,
                config,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            logger.exception(
                "grounded_llm_provider_exception",
                row_id=int(row.id or 0),
                provider=provider_name,
                model=model,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return LLMEnrichmentOutcome(
                success=False,
                provider_name=provider_name,
                model_name=model,
                warnings=[f"Grounded LLM provider call failed: {type(exc).__name__}."],
                error_message=str(exc),
                error_category="provider_exception",
            )

        logger.info(
            "grounded_llm_provider_response_received",
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
            warnings = [self._clean_text(response.error_message) or "Grounded LLM provider failed."]
            logger.warning(
                "grounded_llm_provider_response_failed",
                row_id=int(row.id or 0),
                provider=self._clean_text(response.provider) or provider_name,
                model=self._clean_text(response.model) or model,
                error_message=self._clean_text(response.error_message),
                raw_response=dict(response.raw_response),
            )
            return LLMEnrichmentOutcome(
                success=False,
                provider_name=self._clean_text(response.provider) or provider_name,
                model_name=self._clean_text(response.model) or model,
                warnings=warnings,
                error_message=self._clean_text(response.error_message)
                or "Grounded LLM provider call failed.",
                latency_ms=response.latency_ms,
                usage=dict(response.usage),
                raw_response=self._clean_text(response.content),
                raw_payload=dict(response.raw_response),
                error_category=self._clean_text(response.error_category),
                retry_after_seconds=response.retry_after_seconds,
            )

        try:
            parsed = GroundedLLMResponseSchema.model_validate_json(response.content)
        except Exception as exc:
            logger.warning(
                "grounded_llm_response_schema_validation_failed",
                row_id=int(row.id or 0),
                provider=self._clean_text(response.provider) or provider_name,
                model=self._clean_text(response.model) or model,
                error_type=type(exc).__name__,
                response_content=self._clean_text(response.content),
                raw_response=dict(response.raw_response),
            )
            return LLMEnrichmentOutcome(
                success=False,
                provider_name=self._clean_text(response.provider) or provider_name,
                model_name=self._clean_text(response.model) or model,
                warnings=[f"Grounded LLM response validation failed: {type(exc).__name__}."],
                error_message="Grounded LLM response could not be parsed as JSON.",
                latency_ms=response.latency_ms,
                usage=dict(response.usage),
                raw_response=self._clean_text(response.content),
                raw_payload=dict(response.raw_response),
                error_category="validation_error",
            )

        patch = self._patch_from_schema(parsed)
        warnings = self._deduplicate_strings(list(parsed.validation_warnings))
        logger.info(
            "grounded_llm_response_parsed",
            row_id=int(row.id or 0),
            provider=self._clean_text(response.provider) or provider_name,
            model=self._clean_text(response.model) or model,
            patch=self._patch_payload(patch),
            warnings=warnings,
        )
        return LLMEnrichmentOutcome(
            success=True,
            provider_name=self._clean_text(response.provider) or provider_name,
            model_name=self._clean_text(response.model) or model,
            patch=patch,
            warnings=warnings,
            latency_ms=response.latency_ms,
            usage=dict(response.usage),
            raw_response=self._clean_text(response.content),
            raw_payload=dict(response.raw_response),
        )

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
            if not self._temperature is None:
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

    def _build_messages(self, *, row: BomRow, request: LLMEnrichmentRequest) -> list[dict[str, str]]:
        payload = {
            "purpose": "grounded_bom_enrichment",
            "instruction": (
                "Use the deterministic evidence and the row snapshot as the grounding source. "
                "Do not invent values that are not supported by the supplied evidence."
            ),
            "row": self._row_snapshot(row),
            "request": self._request_payload(request),
            "evidence": [self._evidence_payload(record) for record in request.evidence],
        }
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True, default=str)},
        ]

    def _request_payload(self, request: LLMEnrichmentRequest) -> dict[str, Any]:
        return {
            "row_id": request.row_id,
            "project_id": request.project_id,
            "primary_field": request.primary_field,
            "primary_value": request.primary_value,
            "search_keys": request.search_keys.model_dump(mode="json"),
            "row_snapshot": dict(request.row_snapshot),
            "deterministic_snapshot": dict(request.deterministic_snapshot),
        }

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

    def _patch_payload(self, patch: LLMEnrichmentPatch) -> dict[str, Any]:
        return {
            "manufacturer": patch.manufacturer,
            "mpn": patch.mpn,
            "package": patch.package,
            "category": patch.category,
            "param_summary": patch.param_summary,
            "stock_qty": patch.stock_qty,
            "stock_status": patch.stock_status,
            "lifecycle_status": patch.lifecycle_status,
            "eol_risk": patch.eol_risk,
            "lead_time": patch.lead_time,
            "moq": patch.moq,
            "source_url": patch.source_url,
            "source_name": patch.source_name,
            "source_confidence": patch.source_confidence,
            "sourcing_notes": patch.sourcing_notes,
            "last_checked_at": (
                patch.last_checked_at.isoformat() if patch.last_checked_at is not None else ""
            ),
            "validation_warnings": list(patch.validation_warnings),
        }

    def _patch_from_schema(self, schema: GroundedLLMResponseSchema) -> LLMEnrichmentPatch:
        return LLMEnrichmentPatch(
            manufacturer=self._clean_text(schema.manufacturer),
            mpn=self._clean_text(schema.mpn),
            package=self._clean_text(schema.package),
            category=self._clean_text(schema.category),
            param_summary=self._clean_text(schema.param_summary),
            stock_qty=schema.stock_qty,
            stock_status=self._clean_text(schema.stock_status),
            lifecycle_status=self._clean_text(schema.lifecycle_status),
            eol_risk=self._clean_text(schema.eol_risk),
            lead_time=self._clean_text(schema.lead_time),
            moq=schema.moq,
            source_url=self._clean_text(schema.source_url),
            source_name=self._clean_text(schema.source_name),
            source_confidence=self._clean_text(schema.source_confidence),
            sourcing_notes=self._clean_text(schema.sourcing_notes),
            last_checked_at=schema.last_checked_at.astimezone(UTC)
            if schema.last_checked_at is not None
            else None,
            validation_warnings=self._deduplicate_strings(schema.validation_warnings),
        )

    def _row_snapshot(self, row: BomRow) -> dict[str, Any]:
        return {
            "row_id": row.id,
            "project_id": row.project_id,
            "designator": row.designator,
            "comment": row.comment,
            "value_raw": row.value_raw,
            "footprint": row.footprint,
            "lcsc_link": row.lcsc_link,
            "lcsc_part_number": row.lcsc_part_number,
            "manufacturer": row.manufacturer,
            "mpn": row.mpn,
            "package": row.package,
            "category": row.category,
            "param_summary": row.param_summary,
            "stock_qty": row.stock_qty,
            "stock_status": row.stock_status,
            "lifecycle_status": row.lifecycle_status,
            "eol_risk": row.eol_risk,
            "lead_time": row.lead_time,
            "moq": row.moq,
            "last_checked_at": row.last_checked_at.isoformat() if row.last_checked_at else "",
            "source_url": row.source_url,
            "source_name": row.source_name,
            "source_confidence": row.source_confidence,
            "sourcing_notes": row.sourcing_notes,
            "enrichment_provider": row.enrichment_provider,
            "enrichment_model": row.enrichment_model,
            "enrichment_version": row.enrichment_version,
            "row_state": row.row_state,
            "validation_warnings": self._split_warnings(row.validation_warnings),
        }

    def _evidence_payload(self, evidence: RawEvidence) -> dict[str, Any]:
        return {
            "source_url": self._clean_text(evidence.source_url),
            "source_name": self._clean_text(evidence.source_name),
            "retrieved_at": evidence.retrieved_at.isoformat() if evidence.retrieved_at else "",
            "content_type": self._clean_text(evidence.content_type),
            "search_strategy": self._clean_text(evidence.search_strategy),
            "raw_content": self._clean_text(evidence.raw_content),
        }

    def _build_system_prompt(self, extra_prompt: str) -> str:
        parts = [
            "You are a grounded BOM enrichment assistant.",
            "Use only the supplied row snapshot, deterministic snapshot, and evidence.",
            "If a field cannot be supported, leave it empty or null.",
            "Prefer conservative values over speculation.",
            "Return only data that matches the schema.",
        ]
        if extra_prompt.strip():
            parts.append(extra_prompt.strip())
        return "\n\n".join(parts)

    def _deduplicate_strings(self, values: Sequence[str]) -> list[str]:
        deduped: list[str] = []
        for value in values:
            cleaned = self._clean_text(value)
            if cleaned and cleaned not in deduped:
                deduped.append(cleaned)
        return deduped

    def _clean_text(self, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _split_warnings(self, value: str) -> list[str]:
        cleaned = self._clean_text(value)
        if not cleaned:
            return []
        if cleaned.startswith("["):
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError:
                return [cleaned]
            if isinstance(parsed, list):
                return [self._clean_text(item) for item in parsed if self._clean_text(item)]
            return [cleaned]
        return [segment for segment in cleaned.replace("\r", "\n").split("\n") if segment.strip()]


LlmEnrichmentPayload = GroundedLLMResponseSchema
LlmStageResult = LLMEnrichmentOutcome
LlmEnrichmentStage = GroundedLLMEnrichmentStage
ProviderBackedLlmEnrichmentStage = GroundedLLMEnrichmentStage
StructuredEnrichmentPatch = LLMEnrichmentPatch


def build_grounded_llm_enrichment_stage(
    provider_source: Any,
    *,
    api_key: str = "",
    model: str = "",
    timeout_seconds: int = 60,
    max_tokens: int = 2048,
    temperature: float | None = None,
    reasoning_effort: str | None = None,
    allow_manual_approval: bool = False,
    system_prompt: str = "",
) -> GroundedLLMEnrichmentStage:
    """Build an async grounded enrichment stage around a provider source."""

    return GroundedLLMEnrichmentStage(
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
