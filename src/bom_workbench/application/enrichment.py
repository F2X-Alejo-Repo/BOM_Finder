"""Deterministic enrichment use cases for BOM rows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Sequence

import structlog

from ..domain.entities import BomRow
from ..domain.ports import IBomRepository, IEvidenceRetriever, RawEvidence
from ..domain.value_objects import SearchKeys
from .state_machine import transition_row_state

__all__ = [
    "BomEnrichmentUseCase",
    "EvidenceParseResult",
    "SearchKeyResolution",
]


LLMStage = Callable[[BomRow, list[dict[str, Any]]], dict[str, Any] | None]
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
    stock_status: str
    lifecycle_status: str
    source_url: str
    source_name: str
    last_checked_at: datetime | None
    warnings: list[str] = field(default_factory=list)
    evidence_blob: str = ""
    raw_provider_response: str = ""


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

        target_row = await self._load_row(row)
        row_id = int(target_row.id or 0)
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
            return await self._mark_failed(
                target_row,
                "No usable search keys were found for enrichment.",
            )

        evidence = await self._retriever.retrieve(search_resolution.search_keys)
        logger.debug(
            "enrichment_evidence_retrieved",
            row_id=row_id,
            evidence_count=len(evidence),
            search_strategies=[record.search_strategy for record in evidence],
            first_source_url=(evidence[0].source_url if evidence else ""),
        )
        if not evidence:
            return await self._mark_warning(
                target_row,
                "Evidence retriever returned no results for the resolved search keys.",
            )

        parsed = self._parse_evidence(target_row, search_resolution, evidence)
        self._apply_parsed_evidence(target_row, parsed, evidence)

        if self._llm_stage is not None:
            # Optional placeholder only. We do not fabricate or overwrite grounded data.
            llm_patch = self._llm_stage(target_row, self._serialize_evidence_records(evidence))
            if llm_patch:
                self._apply_llm_patch(target_row, llm_patch)

        final_state = "warning" if parsed.warnings else "enriched"
        transition_row_state(target_row, final_state)
        await self._repository.save_row(target_row)
        return target_row

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
        if parsed.stock_status:
            row.stock_status = parsed.stock_status
        if parsed.lifecycle_status:
            row.lifecycle_status = parsed.lifecycle_status
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

    def _apply_llm_patch(self, row: BomRow, llm_patch: dict[str, Any]) -> None:
        # Placeholder only. Keep any optional model output fenced to the same row fields.
        allowed_fields = {
            "source_url",
            "source_name",
            "stock_status",
            "lifecycle_status",
            "validation_warnings",
        }
        for field_name, value in llm_patch.items():
            if field_name not in allowed_fields or value is None or value == "":
                continue
            setattr(row, field_name, self._clean_text(value))

    def _parse_evidence(
        self,
        row: BomRow,
        search_resolution: SearchKeyResolution,
        evidence: Sequence[RawEvidence],
    ) -> EvidenceParseResult:
        parsed_records = [self._parse_evidence_record(record) for record in evidence]
        stock_qty = self._select_int(parsed_records, "stock_qty")
        stock_status = self._select_text(parsed_records, "stock_status")
        lifecycle_status = self._select_text(parsed_records, "lifecycle_status") or "unknown"
        source_url = self._select_text(parsed_records, "source_url")
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
                "stock_status": stock_status,
                "lifecycle_status": lifecycle_status,
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
            stock_status=stock_status,
            lifecycle_status=lifecycle_status,
            source_url=source_url,
            source_name=source_name,
            warnings_count=len(warnings),
            warnings=warnings,
        )
        return EvidenceParseResult(
            stock_qty=stock_qty,
            stock_status=stock_status,
            lifecycle_status=lifecycle_status,
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
                "stock",
                "quantity",
                "qty",
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
                self._extract_text(normalized, "lifecycle_status", "lifecycle", "status")
                or self._extract_lifecycle_status_from_text(text)
            ),
            "source_url": self._extract_text(normalized, "source_url", "url"),
            "source_name": self._extract_text(normalized, "source_name", "name", "provider"),
            "retrieved_at": self._extract_text(normalized, "retrieved_at", "last_checked_at"),
        }

    def _extract_fields_from_text(self, text: str) -> dict[str, Any]:
        return {
            "stock_qty": self._extract_int_from_text(text),
            "stock_status": self._extract_stock_status_from_text(text),
            "lifecycle_status": self._normalize_lifecycle_status(
                self._extract_lifecycle_status_from_text(text)
            ),
            "source_url": self._extract_url_from_text(text),
            "source_name": self._extract_named_value(text, "source_name", "source"),
            "retrieved_at": self._extract_named_value(text, "retrieved_at", "last_checked_at"),
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
        match = re.search(r"https?://[^\s,;|]+", text, re.IGNORECASE)
        return self._clean_text(match.group(0)) if match else ""

    def _extract_named_value(self, text: str, *labels: str) -> str:
        for label in labels:
            pattern = re.compile(rf"{re.escape(label)}\s*[:=]\s*([^\n|;,]+)", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                return self._clean_text(match.group(1))
        return ""

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

    def _merge_warnings(self, current: str, warnings: Sequence[str]) -> str:
        existing = [warning for warning in self._split_warnings(current) if warning]
        for warning in warnings:
            cleaned = self._clean_text(warning)
            if cleaned and cleaned not in existing:
                existing.append(cleaned)
        if not existing:
            return ""
        return json.dumps(existing, ensure_ascii=True, separators=(",", ":"))

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
