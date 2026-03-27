"""Domain entity tables for BOM Workbench."""

from datetime import UTC, datetime
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel

__all__ = [
    "BomProject",
    "BomRow",
    "ProviderConfig",
    "Job",
]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class BomProject(SQLModel, table=True):
    """A BOM import session that groups rows from one or more source files."""

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    source_files: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    rows: list["BomRow"] = Relationship(back_populates="project")


class BomRow(SQLModel, table=True):
    """Canonical BOM row stored for import, enrichment, and review."""

    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="bomproject.id", index=True)

    source_file: str = ""
    original_row_index: int = 0
    designator: str = ""
    comment: str = ""
    value_raw: str = ""
    footprint: str = ""
    lcsc_link: str = ""
    lcsc_part_number: str = ""

    designator_list: str = ""
    quantity: int = 0
    manufacturer: str = ""
    mpn: str = ""
    package: str = ""
    category: str = ""
    param_summary: str = ""

    stock_qty: int | None = None
    stock_status: str = ""
    lifecycle_status: str = "unknown"
    eol_risk: str = "unknown"
    lead_time: str = ""
    moq: int | None = None
    last_checked_at: datetime | None = None
    source_url: str = ""
    source_name: str = ""
    source_confidence: str = "none"
    sourcing_notes: str = ""

    replacement_candidate_part_number: str = ""
    replacement_candidate_link: str = ""
    replacement_candidate_mpn: str = ""
    replacement_rationale: str = ""
    replacement_match_score: float | None = None
    replacement_status: str = "none"
    user_accepted_replacement: bool = False

    enrichment_provider: str = ""
    enrichment_model: str = ""
    enrichment_job_id: str = ""
    enrichment_version: str = ""
    evidence_blob: str = ""
    raw_provider_response: str = ""
    row_state: str = "imported"
    validation_warnings: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    project: Optional[BomProject] = Relationship(back_populates="rows")


class ProviderConfig(SQLModel, table=True):
    """Stored configuration for an LLM provider."""

    id: int | None = Field(default=None, primary_key=True)
    provider_name: str = ""
    enabled: bool = False
    auth_method: str = "api_key"
    selected_model: str = ""
    cached_models: str = ""
    models_cached_at: datetime | None = None
    timeout_seconds: int = 60
    max_retries: int = 3
    max_concurrent: int = 5
    temperature: float | None = None
    reasoning_effort: str = ""
    privacy_level: str = "full"
    manual_approval: bool = False
    extra_config: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Job(SQLModel, table=True):
    """A tracked async job for enrichment, search, or export work."""

    id: int | None = Field(default=None, primary_key=True)
    job_type: str = ""
    state: str = "pending"
    project_id: int | None = Field(default=None, foreign_key="bomproject.id", index=True)
    target_row_ids: str = ""
    total_rows: int = 0
    completed_rows: int = 0
    failed_rows: int = 0
    provider_name: str = ""
    model_name: str = ""
    error_message: str = ""
    retry_count: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    created_at: datetime = Field(default_factory=_utc_now)
