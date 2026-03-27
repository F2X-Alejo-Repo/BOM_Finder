"""Pydantic value objects for the BOM Workbench domain."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import Confidence, EvidenceType, LifecycleStatus, StockBucket


class DomainModel(BaseModel):
    """Base value object settings for stricter domain contracts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ColumnMapping(DomainModel):
    """Maps one raw CSV header to a canonical field."""

    raw_column: str
    canonical_field: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    matched_by: str = "regex"


class ValidationWarning(DomainModel):
    """Validation warning tied to a row or field."""

    code: str
    message: str
    row_index: int | None = None
    field_name: str | None = None
    severity: Confidence = Confidence.MEDIUM


class MatchScore(DomainModel):
    """Transparent score details for replacement ranking."""

    total: float = Field(default=0.0, ge=0.0, le=1.0)
    breakdown: dict[str, float] = Field(default_factory=dict)
    explanation: str = ""


class ImportReport(DomainModel):
    """Result summary for one import operation."""

    source_file: str
    row_count: int = 0
    imported_count: int = 0
    warning_count: int = 0
    error_count: int = 0
    unmapped_columns: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class EvidenceRecord(DomainModel):
    """A single evidence record supporting an enriched claim."""

    field_name: str
    value: str
    evidence_type: EvidenceType
    source_url: str = ""
    source_name: str = ""
    retrieved_at: datetime
    confidence: Confidence
    raw_snippet: str = ""
    notes: str = ""


class EnrichmentResult(DomainModel):
    """Enrichment output persisted per row/job run."""

    row_id: int
    provider: str
    model: str
    job_id: str
    version: str = "1.0"
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    summary: str = ""
    warnings: list[str] = Field(default_factory=list)
    raw_response: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class ReplacementCandidate(DomainModel):
    """Replacement candidate payload used by matching and UI."""

    manufacturer: str = ""
    mpn: str = ""
    footprint: str = ""
    package: str = ""
    value_summary: str = ""
    lcsc_link: str = ""
    lcsc_part_number: str = ""
    stock_qty: int | None = None
    lifecycle_status: LifecycleStatus = LifecycleStatus.UNKNOWN
    confidence: Confidence = Confidence.NONE
    match_score: float = 0.0
    match_explanation: str = ""
    differences: str = ""
    warnings: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)

    # Compatibility fields used by early matching heuristics.
    part_number: str = ""
    description: str = ""
    stock_status: str = ""


class SearchKeys(DomainModel):
    """Canonical lookup keys for deterministic retrieval."""

    lcsc_part_number: str = ""
    mpn: str = ""
    source_url: str = ""
    comment: str = ""
    footprint: str = ""
    category: str = ""
    param_summary: str = ""
