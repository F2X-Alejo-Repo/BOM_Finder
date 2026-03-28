"""Deterministic enrichment use cases for BOM rows."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

import structlog

from ..domain.entities import BomRow
from ..domain.ports import IBomRepository, IEvidenceRetriever, RawEvidence
from ..domain.value_objects import SearchKeys
from .llm_enrichment import (
    LLMEnrichmentOutcome,
    LLMEnrichmentPatch,
    LLMEnrichmentRequest,
    LLMStage,
)
from .state_machine import transition_row_state

__all__ = [
    "BomEnrichmentUseCase",
    "EvidenceParseResult",
    "EnrichmentExecutionResult",
    "EnrichmentExecutionTelemetry",
    "LLMEnrichmentOutcome",
    "LLMEnrichmentPatch",
    "LLMEnrichmentRequest",
    "LLMStage",
    "SearchKeyResolution",
]

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class SearchKeyResolution:
    """Resolved search keys and the primary field used to build them."""

    search_keys: SearchKeys
    primary_field: str
    primary_value: str
    priority_order: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class EvidenceParseResult:
    """Deterministic enrichment fields parsed from retrieved evidence."""

    stock_qty: int | None
    moq: int | None
    stock_status: str
    lifecycle_status: str
    lead_time: str
    source_url: str
    source_name: str
    last_checked_at: datetime | None
    warnings: list[str] = field(default_factory=list)
    evidence_blob: str = ""
    raw_provider_response: str = ""


@dataclass(slots=True, frozen=True)
class EnrichmentExecutionTelemetry:
    """Execution metrics exposed to adaptive job scheduling."""

    latency_ms: float = 0.0
    usage: dict[str, int] = field(default_factory=dict)
    error_category: str = ""
    rate_limited: bool = False
    retry_after_seconds: float | None = None


@dataclass(slots=True, frozen=True)
class EnrichmentExecutionResult:
    """Outcome returned by adaptive enrichment executors."""

    row: BomRow
    success: bool
    telemetry: EnrichmentExecutionTelemetry = field(default_factory=EnrichmentExecutionTelemetry)


class BomEnrichmentUseCase:
    """Resolve evidence for BOM rows and persist deterministic updates."""

    _PRIMARY_SEARCH_FIELDS: tuple[str, ...] = (
        "lcsc_part_number",
        "mpn",
        "source_url",
        "comment",
        "footprint",
        "category",
        "param_summary",
    )
    _STOCK_STATUS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\b(in\s*stock|available|availability\s*:\s*high)\b", re.IGNORECASE), "high"),
        (re.compile(r"\b(low\s*stock|limited\s*stock|availability\s*:\s*low)\b", re.IGNORECASE), "low"),
        (re.compile(r"\b(out\s*of\s*stock|unavailable|availability\s*:\s*out)\b", re.IGNORECASE), "out"),
        (re.compile(r"\b(medium|availability\s*:\s*medium)\b", re.IGNORECASE), "medium"),
    )
    _LIFECYCLE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\b(not\s*recommended\s*for\s*new\s*designs|nrnd)\b", re.IGNORECASE), "nrnd"),
        (re.compile(r"\b(last\s*time\s*buy|ltb)\b", re.IGNORECASE), "last_time_buy"),
        (re.compile(r"\b(end\s*of\s*life|eol|obsolete)\b", re.IGNORECASE), "eol"),
        (re.compile(r"\b(active|in\s*production|production)\b", re.IGNORECASE), "active"),
    )

    def __init__(
        self,
        repository: IBomRepository,
        retriever: IEvidenceRetriever,
        *,
        llm_stage: LLMStage | None = None,
    ) -> None:
        self._repository = repository
        self._retriever = retriever
        self._llm_stage = llm_stage

    async def enrich_row(self, row: BomRow | int) -> BomRow:
        """Enrich a single row or row id deterministically."""

        return (await self.enrich_row_with_result(row)).row

    async def enrich_row_with_result(self, row: BomRow | int) -> EnrichmentExecutionResult:
        """Enrich a single row and return telemetry for adaptive scheduling."""

        target_row = await self._load_row(row)
        row_id = int(target_row.id or 0)
        telemetry = EnrichmentExecutionTelemetry()
        logger.debug(
            "enrichment_row_started",
            row_id=row_id,
            designator=self._clean_text(target_row.designator),
            lcsc_part_number=self._clean_text(target_row.lcsc_part_number),
            mpn=self._clean_text(target_row.mpn),
        )
        transition_row_state(target_row, "queued")
        await self._repository.save_row(target_row)
        transition_row_state(target_row, "enriching")
        await self._repository.save_row(target_row)

        search_resolution = self.resolve_search_keys(target_row)
        logger.debug(
            "enrichment_search_keys_resolved",
            row_id=row_id,
            primary_field=search_resolution.primary_field,
            primary_value=search_resolution.primary_value,
            search_keys=search_resolution.search_keys.model_dump(mode="json"),
        )
        if not search_resolution.primary_value:
            failed_row = await self._mark_failed(
                target_row,
                "No usable search keys were found for enrichment.",
            )
            return EnrichmentExecutionResult(row=failed_row, success=False, telemetry=telemetry)

        evidence = await self._retriever.retrieve(search_resolution.search_keys)
        logger.debug(
            "enrichment_evidence_retrieved",
            row_id=row_id,
            evidence_count=len(evidence),
            search_strategies=[record.search_strategy for record in evidence],
            first_source_url=(evidence[0].source_url if evidence else ""),
        )
        if not evidence:
            warning_row = await self._mark_warning(
                target_row,
                "Evidence retriever returned no results for the resolved search keys.",
            )
            return EnrichmentExecutionResult(row=warning_row, success=True, telemetry=telemetry)

        parsed = self._parse_evidence(target_row, search_resolution, evidence)
        self._apply_parsed_evidence(target_row, parsed, evidence)

        llm_outcome: LLMEnrichmentOutcome | None = None
        if self._llm_stage is not None:
            request = self._build_llm_request(
                target_row,
                search_resolution,
                evidence,
                parsed,
            )
            logger.info(
                "enrichment_llm_stage_dispatch",
                row_id=row_id,
                provider=target_row.enrichment_provider,
                model=target_row.enrichment_model,
                primary_field=request.primary_field,
                primary_value=request.primary_value,
                evidence_count=len(request.evidence),
                deterministic_snapshot=request.deterministic_snapshot,
            )
            try:
                llm_outcome = await self._llm_stage(target_row, request)
            except Exception as exc:  # pragma: no cover - defensive boundary
                logger.exception(
                    "enrichment_llm_stage_failed",
                    row_id=row_id,
                    error=str(exc),
                )
                self._append_warning(
                    target_row,
                    "Grounded LLM stage raised an unexpected exception.",
                )
            else:
                if llm_outcome is not None:
                    logger.info(
                        "enrichment_llm_stage_completed",
                        row_id=row_id,
                        success=llm_outcome.success,
                        provider_name=llm_outcome.provider_name,
                        model_name=llm_outcome.model_name,
                        warnings=llm_outcome.warnings,
                        error_message=llm_outcome.error_message,
                        usage=llm_outcome.usage,
                        latency_ms=llm_outcome.latency_ms,
                        raw_response=llm_outcome.raw_response,
                        raw_payload=llm_outcome.raw_payload,
                        error_category=llm_outcome.error_category,
                        retry_after_seconds=llm_outcome.retry_after_seconds,
                    )
                    telemetry = EnrichmentExecutionTelemetry(
                        latency_ms=llm_outcome.latency_ms,
                        usage=dict(llm_outcome.usage),
                        error_category=self._clean_text(llm_outcome.error_category),
                        rate_limited=self._clean_text(llm_outcome.error_category) == "rate_limit",
                        retry_after_seconds=llm_outcome.retry_after_seconds,
                    )
                    self._apply_llm_outcome(target_row, llm_outcome)

        final_state = (
            "warning"
            if self._split_warnings(target_row.validation_warnings)
            or (llm_outcome is not None and (not llm_outcome.success or bool(llm_outcome.warnings)))
            else "enriched"
        )
        transition_row_state(target_row, final_state)
        await self._repository.save_row(target_row)
        return EnrichmentExecutionResult(
            row=target_row,
            success=target_row.row_state != "failed",
            telemetry=telemetry,
        )

    async def enrich_rows(self, row_ids: Sequence[int]) -> list[BomRow]:
        """Enrich a batch of row ids sequentially."""

        results: list[BomRow] = []
        for row_id in row_ids:
            results.append(await self.enrich_row(row_id))
        return results

    def resolve_search_keys(self, row: BomRow) -> SearchKeyResolution:
        """Resolve search keys from a row using deterministic priority."""

        lcsc_part_number = self._clean_text(row.lcsc_part_number)
        mpn = self._clean_text(row.mpn)
        source_url = self._clean_text(row.source_url or row.lcsc_link)
        comment = self._clean_text(row.comment or row.value_raw)
        footprint = self._clean_text(row.footprint)
        category = self._clean_text(row.category)
        param_summary = self._clean_text(row.param_summary)

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

    async def _load_row(self, row: BomRow | int) -> BomRow:
        if isinstance(row, BomRow):
            return row

        loaded = await self._repository.get_row(row)
        if loaded is None:
            raise ValueError(f"Unknown row id: {row}")
        return loaded

    def _resolve_primary_field(self, search_keys: SearchKeys) -> tuple[str, str]:
        for field_name in self._PRIMARY_SEARCH_FIELDS:
            value = self._clean_text(getattr(search_keys, field_name, ""))
            if value:
                return field_name, value
        return "", ""

    async def _mark_failed(self, row: BomRow, warning_message: str) -> BomRow:
        self._append_warning(row, warning_message)
        transition_row_state(row, "failed")
        await self._repository.save_row(row)
        return row

    async def _mark_warning(self, row: BomRow, warning_message: str) -> BomRow:
        self._append_warning(row, warning_message)
        transition_row_state(row, "warning")
        await self._repository.save_row(row)
        return row

    def _apply_parsed_evidence(
        self,
        row: BomRow,
        parsed: EvidenceParseResult,
        evidence: Sequence[RawEvidence],
    ) -> None:
        if parsed.stock_qty is not None:
            row.stock_qty = parsed.stock_qty
        if parsed.moq is not None:
            row.moq = parsed.moq
        if parsed.stock_status:
            row.stock_status = parsed.stock_status
        if parsed.lifecycle_status:
            row.lifecycle_status = parsed.lifecycle_status
        if parsed.lead_time:
            row.lead_time = parsed.lead_time
        if parsed.source_url:
            row.source_url = parsed.source_url
        if parsed.source_name:
            row.source_name = parsed.source_name
        if parsed.last_checked_at is not None:
            row.last_checked_at = parsed.last_checked_at

        row.enrichment_provider = "deterministic"
        row.enrichment_model = "deterministic-parser"
        row.enrichment_version = "phase8-v1"
        row.validation_warnings = self._merge_warnings(row.validation_warnings, parsed.warnings)
        row.evidence_blob = parsed.evidence_blob
        row.raw_provider_response = parsed.raw_provider_response

    def _build_llm_request(
        self,
        row: BomRow,
        search_resolution: SearchKeyResolution,
        evidence: Sequence[RawEvidence],
        parsed: EvidenceParseResult,
    ) -> LLMEnrichmentRequest:
        row_snapshot = self._row_snapshot(row)
        deterministic_snapshot = {
            "row_id": row.id,
            "primary_field": search_resolution.primary_field,
            "primary_value": search_resolution.primary_value,
            "search_keys": search_resolution.search_keys.model_dump(mode="json"),
            "parsed": {
                "stock_qty": parsed.stock_qty,
                "moq": parsed.moq,
                "stock_status": parsed.stock_status,
                "lifecycle_status": parsed.lifecycle_status,
                "lead_time": parsed.lead_time,
                "source_url": parsed.source_url,
                "source_name": parsed.source_name,
                "last_checked_at": parsed.last_checked_at.isoformat()
                if parsed.last_checked_at
                else "",
            },
            "warnings": list(parsed.warnings),
            "evidence_blob": parsed.evidence_blob,
        }
        return LLMEnrichmentRequest(
            row_id=int(row.id or 0),
            project_id=int(row.project_id or 0),
            row_snapshot=row_snapshot,
            search_keys=search_resolution.search_keys,
            primary_field=search_resolution.primary_field,
            primary_value=search_resolution.primary_value,
            deterministic_snapshot=deterministic_snapshot,
            evidence=evidence,
        )

    def _apply_llm_outcome(self, row: BomRow, llm_outcome: LLMEnrichmentOutcome) -> None:
        patch = llm_outcome.patch
        logger.info(
            "enrichment_llm_outcome_applying",
            row_id=int(row.id or 0),
            provider_name=llm_outcome.provider_name,
            model_name=llm_outcome.model_name,
            patch=asdict(patch),
            warnings=llm_outcome.warnings,
            error_message=llm_outcome.error_message,
        )
        if llm_outcome.provider_name:
            row.enrichment_provider = llm_outcome.provider_name
        if llm_outcome.model_name:
            row.enrichment_model = llm_outcome.model_name
        if llm_outcome.version:
            row.enrichment_version = llm_outcome.version

        if patch.manufacturer and not self._clean_text(row.manufacturer):
            row.manufacturer = self._clean_text(patch.manufacturer)
        if patch.mpn and not self._clean_text(row.mpn):
            row.mpn = self._clean_text(patch.mpn)
        if patch.package and not self._clean_text(row.package):
            row.package = self._clean_text(patch.package)
        if patch.category and not self._clean_text(row.category):
            row.category = self._clean_text(patch.category)
        if patch.param_summary and not self._clean_text(row.param_summary):
            row.param_summary = self._clean_text(patch.param_summary)
        if patch.stock_qty is not None and row.stock_qty is None:
            row.stock_qty = patch.stock_qty
        if patch.stock_status and not self._clean_text(row.stock_status):
            normalized = self._normalize_stock_status(patch.stock_status)
            if normalized:
                row.stock_status = normalized
        if patch.lifecycle_status and self._clean_text(row.lifecycle_status) in {"", "unknown"}:
            normalized = self._normalize_lifecycle_status(patch.lifecycle_status)
            if normalized:
                row.lifecycle_status = normalized
        if patch.eol_risk and self._clean_text(row.eol_risk) in {"", "unknown"}:
            normalized = self._normalize_eol_risk(patch.eol_risk)
            if normalized:
                row.eol_risk = normalized
        if patch.lead_time and not self._clean_text(row.lead_time):
            row.lead_time = self._clean_text(patch.lead_time)
        if patch.moq is not None and row.moq is None:
            row.moq = patch.moq
        if patch.source_url and not self._clean_text(row.source_url):
            row.source_url = self._clean_text(patch.source_url)
        if patch.source_name and not self._clean_text(row.source_name):
            row.source_name = self._clean_text(patch.source_name)
        if patch.source_confidence and self._clean_text(row.source_confidence) in {"", "none"}:
            normalized_confidence = self._normalize_confidence(patch.source_confidence)
            if normalized_confidence:
                row.source_confidence = normalized_confidence
        if patch.sourcing_notes:
            row.sourcing_notes = self._merge_text(row.sourcing_notes, patch.sourcing_notes)
        if patch.last_checked_at is not None and row.last_checked_at is None:
            row.last_checked_at = patch.last_checked_at

        if patch.validation_warnings:
            row.validation_warnings = self._merge_warnings(
                row.validation_warnings,
                patch.validation_warnings,
            )
        if llm_outcome.warnings:
            row.validation_warnings = self._merge_warnings(
                row.validation_warnings,
                llm_outcome.warnings,
            )
        if llm_outcome.error_message:
            self._append_warning(row, llm_outcome.error_message)

        row.evidence_blob = self._combine_evidence_blob(row.evidence_blob, llm_outcome)
        if llm_outcome.raw_response:
            row.raw_provider_response = self._merge_llm_raw_response(
                row.raw_provider_response,
                llm_outcome.raw_payload or {"raw_response": llm_outcome.raw_response},
            )
        elif llm_outcome.raw_payload:
            row.raw_provider_response = self._merge_llm_raw_response(
                row.raw_provider_response,
                llm_outcome.raw_payload,
            )

        if row.stock_status == "" and row.stock_qty is not None:
            inferred_stock_status = self._infer_stock_status(row.stock_qty)
            if inferred_stock_status:
                row.stock_status = inferred_stock_status
        if row.eol_risk in {"", "unknown"}:
            inferred_eol_risk = self._infer_eol_risk(row.stock_status, row.lifecycle_status)
            if inferred_eol_risk:
                row.eol_risk = inferred_eol_risk

    def _parse_evidence(
        self,
        row: BomRow,
        search_resolution: SearchKeyResolution,
        evidence: Sequence[RawEvidence],
    ) -> EvidenceParseResult:
        parsed_records = [self._parse_evidence_record(record) for record in evidence]
        stock_qty = self._select_int(parsed_records, "stock_qty")
        moq = self._select_int(parsed_records, "moq")
        stock_status = self._select_text(parsed_records, "stock_status")
        lifecycle_status = self._select_text(parsed_records, "lifecycle_status") or "unknown"
        lead_time = self._select_text(parsed_records, "lead_time")
        source_url = self._select_text(parsed_records, "source_url")
        if self._is_unusable_source_url(source_url):
            source_url = ""
        source_name = self._select_text(parsed_records, "source_name")
        last_checked_at = self._select_latest_timestamp(parsed_records)

        warnings: list[str] = []
        if stock_qty is None:
            warnings.append("No stock quantity was parsed from retrieved evidence.")
        if not stock_status:
            stock_status = self._infer_stock_status(stock_qty)
            if stock_status:
                warnings.append("Stock status was inferred from stock quantity.")
        if not lifecycle_status or lifecycle_status == "unknown":
            warnings.append("No lifecycle status was parsed from retrieved evidence.")
        if not source_url:
            source_url = self._clean_text(row.source_url or row.lcsc_link)
        if not source_url:
            warnings.append("No source URL was available from evidence or the row.")
        if not source_name:
            source_name = self._clean_text(row.source_name)
        if not source_name:
            warnings.append("No source name was available from evidence or the row.")
        if last_checked_at is None:
            warnings.append("No retrieval timestamp was available from evidence.")

        evidence_payload = {
            "row_id": row.id,
            "primary_field": search_resolution.primary_field,
            "primary_value": search_resolution.primary_value,
            "search_keys": search_resolution.search_keys.model_dump(mode="json"),
            "parsed": {
                "stock_qty": stock_qty,
                "moq": moq,
                "stock_status": stock_status,
                "lifecycle_status": lifecycle_status,
                "lead_time": lead_time,
                "source_url": source_url,
                "source_name": source_name,
                "last_checked_at": last_checked_at.isoformat() if last_checked_at else "",
            },
            "warnings": warnings,
        }
        raw_payload = self._serialize_evidence_records(evidence)
        logger.debug(
            "enrichment_parse_summary",
            row_id=int(row.id or 0),
            stock_qty=stock_qty,
            moq=moq,
            stock_status=stock_status,
            lifecycle_status=lifecycle_status,
            lead_time=lead_time,
            source_url=source_url,
            source_name=source_name,
            warnings_count=len(warnings),
            warnings=warnings,
        )
        return EvidenceParseResult(
            stock_qty=stock_qty,
            moq=moq,
            stock_status=stock_status,
            lifecycle_status=lifecycle_status,
            lead_time=lead_time,
            source_url=source_url,
            source_name=source_name,
            last_checked_at=last_checked_at,
            warnings=warnings,
            evidence_blob=json.dumps(
                evidence_payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
                default=str,
            ),
            raw_provider_response=raw_payload,
        )

    def _parse_evidence_record(self, evidence: RawEvidence) -> dict[str, Any]:
        payload = {
            "source_url": self._clean_text(evidence.source_url),
            "source_name": self._clean_text(evidence.source_name),
            "retrieved_at": evidence.retrieved_at.isoformat() if evidence.retrieved_at else "",
            "search_strategy": self._clean_text(evidence.search_strategy),
            "raw_content": self._clean_text(evidence.raw_content),
        }

        content = self._try_parse_json(evidence.raw_content)
        if isinstance(content, dict):
            logger.debug(
                "enrichment_evidence_record_json",
                source_url=payload["source_url"],
                search_strategy=payload["search_strategy"],
                top_level_keys=sorted(content.keys())[:20],
            )
            extracted = self._extract_fields_from_mapping(content)
        elif self._looks_like_html_document(evidence.raw_content):
            logger.debug(
                "enrichment_evidence_record_html",
                source_url=payload["source_url"],
                search_strategy=payload["search_strategy"],
                raw_preview=self._short_text(payload["raw_content"]),
            )
            extracted = self._extract_fields_from_html(
                evidence.raw_content,
                fallback_source_url=payload["source_url"],
            )
        else:
            logger.debug(
                "enrichment_evidence_record_text",
                source_url=payload["source_url"],
                search_strategy=payload["search_strategy"],
                raw_preview=self._short_text(payload["raw_content"]),
            )
            extracted = self._extract_fields_from_text(evidence.raw_content)

        for field_name, value in extracted.items():
            if value not in (None, ""):
                payload[field_name] = value
        return payload

    def _extract_fields_from_mapping(self, content: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_mapping_keys(content)
        text = json.dumps(normalized, ensure_ascii=True, sort_keys=True, default=str)
        return {
            "stock_qty": self._extract_int(
                normalized,
                "stock_qty",
                "inventory_level",
                "stock",
                "stock_number",
                "quantity",
                "qty",
            ),
            "moq": self._extract_int(
                normalized,
                "moq",
                "min_order_qty",
                "min_buy_number",
                "minimum_order_quantity",
            ),
            "stock_status": self._extract_text(
                normalized,
                "stock_status",
                "stock",
                "availability",
                "availability_status",
            )
            or self._extract_stock_status_from_text(text),
            "lifecycle_status": self._normalize_lifecycle_status(
                self._extract_text(
                    normalized,
                    "lifecycle_status",
                    "lifecycle",
                    "product_cycle",
                    "status",
                )
                or self._extract_lifecycle_status_from_text(text)
            ),
            "lead_time": self._extract_text(normalized, "lead_time", "leadtime"),
            "source_url": self._extract_text(normalized, "source_url", "url"),
            "source_name": self._extract_text(normalized, "source_name", "name", "provider"),
            "retrieved_at": self._extract_text(normalized, "retrieved_at", "last_checked_at"),
        }

    def _extract_fields_from_text(self, text: str) -> dict[str, Any]:
        return {
            "stock_qty": self._extract_int_from_text(text),
            "moq": self._extract_int_from_named_values(text, "moq", "min_buy_number"),
            "stock_status": self._extract_stock_status_from_text(text),
            "lifecycle_status": self._normalize_lifecycle_status(
                self._extract_lifecycle_status_from_text(text)
            ),
            "lead_time": self._extract_named_value(text, "lead_time", "leadtime"),
            "source_url": self._extract_url_from_text(text),
            "source_name": self._extract_named_value(text, "source_name", "source"),
            "retrieved_at": self._extract_named_value(text, "retrieved_at", "last_checked_at"),
        }

    def _extract_fields_from_html(
        self,
        text: str,
        *,
        fallback_source_url: str,
    ) -> dict[str, Any]:
        if self._looks_like_generic_search_shell(text):
            return {}

        title_match = re.search(r"<title>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        title_text = self._clean_html_text(title_match.group(1) if title_match else "")
        stock_status = self._extract_stock_status_from_text(title_text)
        lifecycle_status = self._normalize_lifecycle_status(
            self._extract_lifecycle_status_from_text(title_text)
        )

        return {
            "stock_status": stock_status,
            "lifecycle_status": lifecycle_status,
            "source_url": fallback_source_url,
        }

    def _select_int(self, records: Sequence[dict[str, Any]], field_name: str) -> int | None:
        for record in records:
            value = record.get(field_name)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        return None

    def _select_text(self, records: Sequence[dict[str, Any]], field_name: str) -> str:
        for record in records:
            value = self._clean_text(record.get(field_name, ""))
            if value:
                return value
        return ""

    def _select_latest_timestamp(self, records: Sequence[dict[str, Any]]) -> datetime | None:
        timestamps: list[datetime] = []
        for record in records:
            value = record.get("retrieved_at")
            if isinstance(value, datetime):
                timestamps.append(value)
                continue
            if isinstance(value, str) and value:
                parsed = self._parse_datetime(value)
                if parsed is not None:
                    timestamps.append(parsed)
        if not timestamps:
            return None
        return max(timestamps)

    def _extract_int(self, content: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            value = content.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str):
                match = re.search(r"\d+", value)
                if match:
                    return int(match.group(0))
        return None

    def _extract_text(self, content: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = content.get(key)
            if value is None:
                continue
            text = self._clean_text(value)
            if text:
                return text
        return ""

    def _extract_int_from_text(self, text: str) -> int | None:
        patterns = (
            r"(?:stock_qty|stock|quantity|qty)\s*[:=]\s*(\d+)",
            r"(?:stock_qty|stock|quantity|qty)\D+(\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = int(match.group(1))
                logger.debug(
                    "enrichment_stock_qty_pattern_match",
                    pattern=pattern,
                    matched_value=value,
                    context=self._short_text(
                        text[max(match.start() - 60, 0) : min(match.end() + 80, len(text))]
                    ),
                )
                return value
        logger.debug(
            "enrichment_stock_qty_not_found",
            raw_preview=self._short_text(text),
        )
        return None

    def _extract_stock_status_from_text(self, text: str) -> str:
        for pattern, status in self._STOCK_STATUS_PATTERNS:
            if pattern.search(text):
                return status
        return ""

    def _extract_lifecycle_status_from_text(self, text: str) -> str:
        for pattern, status in self._LIFECYCLE_PATTERNS:
            if pattern.search(text):
                return status
        return ""

    def _normalize_lifecycle_status(self, value: str) -> str:
        normalized = self._clean_text(value).casefold().replace(" ", "_").replace("-", "_")
        if normalized in {"normal"}:
            return "active"
        if normalized in {"ltb", "last_time_buy"}:
            return "last_time_buy"
        if normalized in {"nrnd", "not_recommended_for_new_designs"}:
            return "nrnd"
        if normalized in {"eol", "end_of_life", "obsolete"}:
            return "eol"
        if normalized in {"active", "production", "in_production"}:
            return "active"
        if normalized in {"", "unknown"}:
            return "unknown"
        return normalized

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

    def _extract_url_from_text(self, text: str) -> str:
        match = re.search(r"https?://[^\s,;|\"'<>]+", text, re.IGNORECASE)
        return self._clean_text(match.group(0)) if match else ""

    def _extract_named_value(self, text: str, *labels: str) -> str:
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}\s*[:=]\s*([^\n|;,]+)", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return self._clean_text(match.group(1))
        return ""

    def _extract_int_from_named_values(self, text: str, *labels: str) -> int | None:
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}\s*[:=]\s*(-?\d+)", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return int(match.group(1))
        return None

    def _normalize_mapping_keys(self, content: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in content.items():
            text_key = self._clean_text(key).casefold().replace(" ", "_")
            text_key = re.sub(r"[^a-z0-9_]+", "", text_key)
            normalized[text_key] = value
        return normalized

    def _serialize_evidence_records(self, evidence: Sequence[RawEvidence]) -> str:
        payload = []
        for record in evidence:
            payload.append(
                {
                    "source_url": self._clean_text(record.source_url),
                    "source_name": self._clean_text(record.source_name),
                    "retrieved_at": record.retrieved_at.isoformat() if record.retrieved_at else "",
                    "content_type": self._clean_text(record.content_type),
                    "search_strategy": self._clean_text(record.search_strategy),
                    "raw_content": self._clean_text(record.raw_content),
                }
            )
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str)

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

    def _combine_evidence_blob(self, deterministic_blob: str, llm_outcome: LLMEnrichmentOutcome) -> str:
        deterministic_payload = self._try_parse_json(deterministic_blob)
        if deterministic_payload is None:
            deterministic_payload = deterministic_blob
        llm_payload = {
            "provider": llm_outcome.provider_name,
            "model": llm_outcome.model_name,
            "version": llm_outcome.version,
            "success": llm_outcome.success,
            "warnings": list(llm_outcome.warnings),
            "error_message": llm_outcome.error_message,
            "latency_ms": llm_outcome.latency_ms,
            "usage": dict(llm_outcome.usage),
            "patch": asdict(llm_outcome.patch),
            "raw_payload": dict(llm_outcome.raw_payload),
        }
        return json.dumps(
            {
                "deterministic": deterministic_payload,
                "llm": llm_payload,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )

    def _merge_text(self, current: str, addition: str) -> str:
        current_text = self._clean_text(current)
        addition_text = self._clean_text(addition)
        if not current_text:
            return addition_text
        if not addition_text:
            return current_text
        if addition_text in current_text:
            return current_text
        return current_text + "\n" + addition_text

    def _normalize_stock_status(self, value: str) -> str:
        normalized = self._clean_text(value).casefold().replace(" ", "_").replace("-", "_")
        if normalized in {"", "unknown"}:
            return ""
        if normalized in {"high", "available", "in_stock", "in_stock_now"}:
            return "high"
        if normalized in {"medium", "moderate", "mid"}:
            return "medium"
        if normalized in {"low", "limited", "scarce"}:
            return "low"
        if normalized in {"out", "out_of_stock", "unavailable", "none"}:
            return "out"
        return ""

    def _normalize_eol_risk(self, value: str) -> str:
        normalized = self._clean_text(value).casefold().replace(" ", "_").replace("-", "_")
        if normalized in {"", "unknown"}:
            return ""
        if normalized in {"low", "medium", "high"}:
            return normalized
        if normalized in {"none", "minimal"}:
            return "low"
        if normalized in {"elevated", "moderate"}:
            return "medium"
        if normalized in {"severe", "critical"}:
            return "high"
        return ""

    def _normalize_confidence(self, value: str) -> str:
        normalized = self._clean_text(value).casefold().replace(" ", "_").replace("-", "_")
        if normalized in {"", "unknown"}:
            return ""
        if normalized in {"none", "low", "medium", "high"}:
            return normalized
        if normalized in {"verified", "certain"}:
            return "high"
        if normalized in {"likely", "probable"}:
            return "medium"
        if normalized in {"possible", "weak"}:
            return "low"
        return ""

    def _infer_eol_risk(self, stock_status: str, lifecycle_status: str) -> str:
        lifecycle = self._normalize_lifecycle_status(lifecycle_status)
        stock = self._normalize_stock_status(stock_status)
        if lifecycle in {"eol", "last_time_buy", "nrnd"}:
            return "high"
        if stock == "out":
            return "high"
        if stock == "low":
            return "medium"
        if stock == "medium":
            return "low"
        if lifecycle == "active" and stock == "high":
            return "low"
        return "medium" if lifecycle == "active" else ""

    def _merge_warnings(self, current: str, warnings: Sequence[str]) -> str:
        existing = [warning for warning in self._split_warnings(current) if warning]
        for warning in warnings:
            cleaned = self._clean_text(warning)
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        if not existing:
            return ""
        return json.dumps(existing, ensure_ascii=True, separators=(",", ":"))

    def _merge_llm_raw_response(
        self,
        current: str,
        llm_payload: dict[str, Any],
    ) -> str:
        current_payload = self._try_parse_json(current)
        if current_payload is None:
            current_payload = current
        return json.dumps(
            {
                "deterministic_evidence": current_payload,
                "llm_stage": llm_payload,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        )

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
        return [segment for segment in re.split(r"[|;\n]+", cleaned) if segment.strip()]

    def _append_warning(self, row: BomRow, warning: str) -> None:
        row.validation_warnings = self._merge_warnings(row.validation_warnings, [warning])

    def _clean_text(self, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        return text

    def _short_text(self, value: object, *, max_length: int = 220) -> str:
        text = self._clean_text(value)
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _try_parse_json(self, value: str) -> Any:
        text = self._clean_text(value)
        if not text:
            return None
        if not text.startswith("{") and not text.startswith("["):
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _parse_datetime(self, value: str) -> datetime | None:
        text = self._clean_text(value)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def _looks_like_html_document(self, text: str) -> bool:
        preview = text[:512].casefold()
        return "<html" in preview or "<!doctype html" in preview

    def _looks_like_generic_search_shell(self, text: str) -> bool:
        lowered = text.casefold()
        if "lcsc electronics - electronic components distributor" in lowered:
            return True
        return "routepath:\\\"/search\\\"" in lowered or 'routepath:"/search"' in lowered

    def _clean_html_text(self, value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value)
        return " ".join(text.split())

    def _is_unusable_source_url(self, value: str) -> bool:
        text = self._clean_text(value).casefold()
        if not text:
            return False
        if "favicon.ico" in text:
            return True
        return "/search?" in text or text.endswith("/search")
