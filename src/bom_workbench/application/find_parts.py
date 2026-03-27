"""Deterministic replacement search and application use cases."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from ..domain.entities import BomRow
from ..domain.enums import Confidence, EvidenceType, LifecycleStatus, ReplacementStatus
from ..domain.matching import MatchingEngine
from ..domain.ports import IBomRepository, IEvidenceRetriever, RawEvidence
from ..domain.value_objects import EvidenceRecord, ReplacementCandidate, SearchKeys

__all__ = [
    "FindPartsUseCase",
    "PartSearchCriteria",
    "ReplacementApplicationResult",
    "ReplacementConfirmationRequired",
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


@dataclass(slots=True, frozen=True)
class SearchKeyResolution:
    """Resolved search keys and the primary field used to build them."""

    search_keys: SearchKeys
    primary_field: str
    primary_value: str
    priority_order: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ReplacementSearchResult:
    """Ranked replacement candidate returned to the caller."""

    candidate: ReplacementCandidate
    score: float
    explanation: str
    requires_manual_review: bool


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
    ) -> None:
        self._repository = repository
        self._retriever = retriever
        self._matching_engine = matching_engine or MatchingEngine()
        self._manual_review_threshold = manual_review_threshold

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

        context_row = await self._resolve_context_row(row_id=row_id, criteria=criteria)
        search_resolution = self.resolve_search_keys(context_row, criteria=criteria)
        if not search_resolution.primary_value:
            return []

        evidence = await self._retriever.retrieve(search_resolution.search_keys)
        candidates = self._parse_candidates(evidence)
        if not candidates:
            return []

        scored_candidates = self._matching_engine.rank_candidates(context_row, candidates)
        results: list[ReplacementSearchResult] = []
        for candidate, score in scored_candidates:
            ranked_candidate = candidate.model_copy(
                update={
                    "match_score": score.total,
                    "match_explanation": score.explanation,
                }
            )
            results.append(
                ReplacementSearchResult(
                    candidate=ranked_candidate,
                    score=score.total,
                    explanation=score.explanation,
                    requires_manual_review=self._requires_manual_review(ranked_candidate, score.total),
                )
            )
        return results

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
            self._row_value(row, "param_summary"),
            criteria_data.get("value", ""),
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
        row = base_row.model_copy(deep=True) if base_row is not None else BomRow(project_id=0)
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
            row.param_summary,
            criteria_data.get("value", ""),
        )
        row.manufacturer = self._first_non_empty(
            criteria_data.get("manufacturer", ""),
            row.manufacturer,
        )
        return row

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

        candidate = ReplacementCandidate(
            manufacturer=self._extract_text(payload, "manufacturer", "brand", "vendor"),
            mpn=self._extract_text(payload, "mpn", "manufacturer_part_number", "part_number"),
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
            lcsc_part_number=self._extract_text(payload, "lcsc_part_number", "part_number"),
            stock_qty=stock_qty,
            lifecycle_status=lifecycle_status,
            confidence=self._extract_confidence(payload),
            match_score=0.0,
            match_explanation="",
            differences=self._extract_text(payload, "differences"),
            warnings=self._extract_warnings(payload),
            evidence=[evidence_record],
            part_number=self._extract_text(payload, "part_number", "lcsc_part_number", "mpn"),
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
    ) -> dict[str, str]:
        if criteria is None:
            return {}
        if isinstance(criteria, PartSearchCriteria):
            data = asdict(criteria)
        else:
            data = dict(criteria)

        normalized: dict[str, str] = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, Mapping):
                continue
            normalized[self._normalize_key(key)] = self._clean_text(value)
        return normalized

    def _criteria_part_number(self, criteria: Mapping[str, str], *, prefer_lcsc: bool) -> str:
        part_number = self._clean_text(criteria.get("part_number", ""))
        if not part_number:
            return ""
        if self._looks_like_lcsc_part_number(part_number):
            return part_number if prefer_lcsc else ""
        return "" if prefer_lcsc else part_number

    def _looks_like_lcsc_part_number(self, value: str) -> bool:
        normalized = self._normalize_key(value)
        return normalized.startswith("c") and any(char.isdigit() for char in normalized)

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
