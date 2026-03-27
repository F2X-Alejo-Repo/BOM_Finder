# 03 — Data Model

## Enums (`domain/enums.py`)

```python
class LifecycleStatus(str, Enum):
    ACTIVE = "active"
    NRND = "nrnd"              # Not Recommended for New Designs
    LAST_TIME_BUY = "last_time_buy"
    EOL = "eol"                # End of Life
    UNKNOWN = "unknown"

class StockBucket(str, Enum):
    OUT = "out"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"

class EolRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"

class RowState(str, Enum):
    IMPORTED = "imported"
    PENDING = "pending"
    QUEUED = "queued"
    ENRICHING = "enriching"
    ENRICHED = "enriched"
    WARNING = "warning"
    FAILED = "failed"
    USER_REVIEWED = "user_reviewed"

class ReplacementStatus(str, Enum):
    NONE = "none"
    CANDIDATES_FOUND = "candidates_found"
    USER_ACCEPTED = "user_accepted"
    USER_REJECTED = "user_rejected"

class JobState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"

class EvidenceType(str, Enum):
    OBSERVED = "observed"      # Directly retrieved from source
    INFERRED = "inferred"      # Derived by LLM from evidence
    ESTIMATED = "estimated"    # Best guess with low confidence
    UNKNOWN = "unknown"
```

## Domain Entities (`domain/entities.py`)

### BomProject

```python
class BomProject(SQLModel, table=True):
    """A BOM import session. Groups rows from one or more CSV files."""
    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    source_files: str = ""         # JSON list of filenames
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    rows: list["BomRow"] = Relationship(back_populates="project")
```

### BomRow

```python
class BomRow(SQLModel, table=True):
    """Canonical BOM row — the core entity of the system."""
    id: int | None = Field(default=None, primary_key=True)
    project_id: int = Field(foreign_key="bomproject.id")

    # ── Core imported fields ──
    source_file: str = ""
    original_row_index: int = 0
    designator: str = ""
    comment: str = ""
    value_raw: str = ""
    footprint: str = ""
    lcsc_link: str = ""
    lcsc_part_number: str = ""

    # ── Derived / normalized ──
    designator_list: str = ""      # JSON list of individual designators
    quantity: int = 0
    manufacturer: str = ""
    mpn: str = ""                  # Manufacturer Part Number
    package: str = ""
    category: str = ""
    param_summary: str = ""        # "100nF 50V X7R 0402"

    # ── Availability / sourcing ──
    stock_qty: int | None = None
    stock_status: str = ""         # StockBucket value
    lifecycle_status: str = "unknown"  # LifecycleStatus value
    eol_risk: str = "unknown"      # EolRisk value
    lead_time: str = ""
    moq: int | None = None
    last_checked_at: datetime | None = None
    source_url: str = ""
    source_name: str = ""
    source_confidence: str = "none"  # Confidence value
    sourcing_notes: str = ""

    # ── Replacement workflow ──
    replacement_candidate_part_number: str = ""
    replacement_candidate_link: str = ""
    replacement_candidate_mpn: str = ""
    replacement_rationale: str = ""
    replacement_match_score: float | None = None
    replacement_status: str = "none"  # ReplacementStatus value
    user_accepted_replacement: bool = False

    # ── Auditability ──
    enrichment_provider: str = ""
    enrichment_model: str = ""
    enrichment_job_id: str = ""
    enrichment_version: str = ""
    evidence_blob: str = ""        # JSON blob of Evidence records
    raw_provider_response: str = ""
    row_state: str = "imported"    # RowState value
    validation_warnings: str = ""  # JSON list of warning strings
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    project: BomProject | None = Relationship(back_populates="rows")
```

### EnrichmentResult (Pydantic model, stored as JSON in evidence_blob)

```python
class EvidenceRecord(BaseModel):
    """A single piece of evidence supporting an enrichment claim."""
    field_name: str              # Which field this evidence supports
    value: str                   # The asserted value
    evidence_type: EvidenceType  # observed / inferred / estimated
    source_url: str = ""
    source_name: str = ""
    retrieved_at: datetime
    confidence: Confidence
    raw_snippet: str = ""        # Raw text from source
    notes: str = ""

class EnrichmentResult(BaseModel):
    """Complete enrichment output for a single BomRow."""
    row_id: int
    provider: str
    model: str
    job_id: str
    version: str = "1.0"
    evidence: list[EvidenceRecord] = []
    summary: str = ""
    warnings: list[str] = []
    raw_response: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

### ReplacementCandidate (Pydantic model)

```python
class ReplacementCandidate(BaseModel):
    """A candidate replacement part for a BomRow."""
    manufacturer: str = ""
    mpn: str = ""
    footprint: str = ""
    package: str = ""
    value_summary: str = ""      # "100nF 50V X7R"
    lcsc_link: str = ""
    lcsc_part_number: str = ""
    stock_qty: int | None = None
    lifecycle_status: LifecycleStatus = LifecycleStatus.UNKNOWN
    confidence: Confidence = Confidence.NONE
    match_score: float = 0.0
    match_explanation: str = ""  # Why it matches
    differences: str = ""        # What may differ
    warnings: list[str] = []
    evidence: list[EvidenceRecord] = []
```

### ProviderConfig

```python
class ProviderConfig(SQLModel, table=True):
    """Stored configuration for an LLM provider."""
    id: int | None = Field(default=None, primary_key=True)
    provider_name: str = ""      # "openai" | "anthropic"
    enabled: bool = False
    auth_method: str = "api_key" # "api_key" | "oauth" | etc.
    # API key stored in keyring, NOT here
    selected_model: str = ""
    cached_models: str = ""      # JSON list of available models
    models_cached_at: datetime | None = None
    timeout_seconds: int = 60
    max_retries: int = 3
    max_concurrent: int = 5
    temperature: float | None = None
    reasoning_effort: str = ""   # "low" | "medium" | "high" (Anthropic thinking)
    privacy_level: str = "full"  # "full" | "minimized" | "no_urls"
    manual_approval: bool = False
    extra_config: str = ""       # JSON for provider-specific settings
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

### Job

```python
class Job(SQLModel, table=True):
    """A tracked async job (enrichment batch, search, export)."""
    id: int | None = Field(default=None, primary_key=True)
    job_type: str = ""           # "enrich_batch" | "enrich_row" | "find_parts" | "export"
    state: str = "pending"       # JobState value
    project_id: int | None = None
    target_row_ids: str = ""     # JSON list of row IDs
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

## Value Objects (`domain/value_objects.py`)

```python
class ColumnMapping(BaseModel):
    """Maps a raw CSV column name to a canonical field name."""
    raw_column: str
    canonical_field: str
    confidence: float            # 0.0 - 1.0 matching confidence
    matched_by: str              # "exact" | "regex" | "fuzzy" | "manual"

class ValidationWarning(BaseModel):
    """A warning generated during CSV import validation."""
    row_index: int | None = None
    column: str = ""
    message: str
    severity: str = "warning"    # "warning" | "error" | "info"

class MatchScore(BaseModel):
    """Transparent scoring for part matching."""
    total: float = 0.0
    breakdown: dict[str, float] = {}  # {"value_match": 0.9, "footprint_match": 1.0, ...}
    explanation: str = ""

class ImportReport(BaseModel):
    """Summary of a CSV import operation."""
    source_file: str
    total_rows_parsed: int
    rows_imported: int
    rows_skipped: int
    column_mappings: list[ColumnMapping]
    warnings: list[ValidationWarning]
    unmapped_columns: list[str]
    duration_seconds: float
```

## SQLite Schema Notes

- All tables created via `SQLModel.metadata.create_all(engine)`
- JSON fields (designator_list, evidence_blob, cached_models, etc.) stored as TEXT with JSON serialization
- Indexes on: `BomRow.project_id`, `BomRow.lcsc_part_number`, `BomRow.row_state`, `Job.state`, `Job.project_id`
- Single database file: `~/.bom_workbench/data/workbench.db` (or user-configurable)
