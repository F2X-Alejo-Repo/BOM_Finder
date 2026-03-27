# 01 — Architecture and ADRs

## System Architecture Overview

The application follows **hexagonal (ports & adapters) architecture** with four concentric layers:

```
┌─────────────────────────────────────────────────────────┐
│                    PRESENTATION LAYER                    │
│  PySide6 UI  ·  QSS Theming  ·  qasync Event Bridge    │
│  Widgets  ·  View Models  ·  Signal/Slot Bindings       │
├─────────────────────────────────────────────────────────┤
│                   APPLICATION LAYER                      │
│  Use Cases / Orchestrators                               │
│  ImportBomUseCase · EnrichBomUseCase · FindPartsUseCase  │
│  ExportBomUseCase · ConfigureProviderUseCase             │
│  JobManager · EventBus                                   │
├─────────────────────────────────────────────────────────┤
│                     DOMAIN LAYER                         │
│  Entities: BomRow, BomProject, EnrichmentResult,        │
│            ReplacementCandidate, ProviderConfig          │
│  Value Objects: MatchScore, Confidence, LifecycleStatus  │
│  Domain Services: MatchingEngine, NormalizationService   │
│  Ports (interfaces): IProviderAdapter, IRepository,      │
│         IEvidenceRetriever, IExporter                    │
├─────────────────────────────────────────────────────────┤
│                  INFRASTRUCTURE LAYER                    │
│  Adapters: OpenAIAdapter, AnthropicAdapter               │
│  Repositories: SQLiteBomRepository, SQLiteJobRepository  │
│  CSV Parser · Excel Exporter · Keyring SecretStore       │
│  HTTP Client (httpx) · File System · Logging             │
└─────────────────────────────────────────────────────────┘
```

## Data Flow

```
CSV File(s)
    │
    ▼
[CSV Ingestion Pipeline]
    │  detect encoding → detect delimiter → parse rows
    │  → regex column matching → normalize to canonical schema
    │  → validate → flag warnings
    ▼
[BomRow entities stored in SQLite]
    │
    ▼
[Enrichment Pipeline]  ◄── [LLM Provider Adapters]
    │  for each row:
    │    1. build search keys (LCSC#, MPN, URL, value+footprint)
    │    2. retrieve evidence (deterministic first)
    │    3. LLM reasoning on evidence (optional, second)
    │    4. score confidence, store provenance
    ▼
[Enriched BomRow + EnrichmentResult in SQLite]
    │
    ▼
[Part Finder / Matching Engine]
    │  tiered: exact LCSC → exact MPN → URL → parametric → heuristic → LLM-ranked
    │  transparent match score with explanation
    ▼
[ReplacementCandidate entities]
    │
    ▼
[User accepts replacement → BomRow updated]
    │
    ▼
[Export Pipeline]
    │  → .xlsx with Designator, Comment, Footprint, LCSC LINK, LCSC PART #
    │  → metadata sheet, formatting, hyperlinks
    ▼
Output File
```

## Key Boundaries

| Boundary | Inside | Outside |
|----------|--------|---------|
| Domain ↔ Infrastructure | Domain interfaces (ports) | Concrete adapters |
| UI ↔ Application | Signal/slot + view models | Qt widgets never call infra directly |
| App ↔ Providers | ProviderAdapter interface | OpenAI/Anthropic HTTP APIs |
| App ↔ Storage | Repository interface | SQLite via SQLModel |
| App ↔ Filesystem | Importer/Exporter interfaces | CSV files, XLSX files |

## Architecture Decision Records

### ADR-001: Hexagonal Architecture with Dependency Injection

**Decision**: Use hexagonal (ports & adapters) architecture. Domain layer defines interfaces (ports). Infrastructure implements them (adapters). Application layer orchestrates use cases.

**Why**:
- Providers (OpenAI, Anthropic) must be swappable without touching domain logic
- Testing requires mocking external dependencies at clean boundaries
- Future providers or data sources can be added without refactoring core
- The spec explicitly requires "no provider logic mixed into UI code"

**Impact**: Every external integration (LLM APIs, SQLite, filesystem, keyring) is behind an interface. Slightly more files, but dramatically better testability and maintainability.

### ADR-002: qasync for Qt + asyncio Integration

**Decision**: Use `qasync` to bridge PySide6's event loop with Python's `asyncio` event loop, running a single unified loop.

**Why**:
- All network operations (LLM API calls, potential web scraping) must be async and non-blocking
- PySide6 has its own event loop; asyncio has its own. qasync merges them
- Alternative (threading + signals) is error-prone and harder to reason about for complex job management

**Impact**: All service methods are `async def`. UI triggers coroutines via `asyncio.ensure_future()`. Cancellation is native via `asyncio.Task.cancel()`.

### ADR-003: SQLite + SQLModel for Local Persistence

**Decision**: Use SQLite for all local data (BOM projects, rows, enrichment results, job history, provider configs). Use SQLModel (built on SQLAlchemy 2.x + Pydantic) for the ORM.

**Why**:
- Desktop app = no external database server
- SQLite is zero-config, file-based, supports concurrent reads
- SQLModel gives Pydantic validation + SQLAlchemy ORM in one model class
- Partial completion persistence and resumable jobs require durable storage

**Impact**: Single `bom_workbench.db` file per workspace. Migrations via Alembic if schema evolves.

### ADR-004: Evidence-First Enrichment (No Hallucination Architecture)

**Decision**: Enrichment pipeline always retrieves deterministic evidence first. LLM is used only to interpret/synthesize/rank retrieved evidence. Every asserted fact carries provenance metadata.

**Why**:
- The spec is emphatic: "The LLM must NEVER invent stock quantity, lifecycle status, EOL status, source URLs, lead times, part numbers, compatibility claims"
- Users need to trust the data for procurement decisions
- Auditability requires every fact to trace back to a source

**Impact**: The enrichment pipeline has explicit "retrieve" and "reason" stages. Evidence is stored as structured records. Confidence is always explicit. The UI shows evidence inspection for any enriched field.

### ADR-005: Provider Capability Matrix

**Decision**: Define a `ProviderCapabilities` data class that each adapter declares. UI adapts dynamically based on what the selected provider supports.

**Why**:
- OpenAI and Anthropic have different feature sets (reasoning control, structured output, tool use, batch, streaming)
- The spec requires runtime model discovery, not hardcoded lists
- UI must show/hide controls based on what's available

**Impact**: `ProviderCapabilities` includes booleans like `supports_model_discovery`, `supports_reasoning_control`, `supports_structured_output`, etc. The settings UI reads this to enable/disable controls per provider.

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | LLM providers return inconsistent/hallucinated data | High | High | Evidence-first architecture; confidence scoring; never use LLM as sole source of truth |
| R2 | CSV format variations break ingestion | Medium | High | Extensive regex alias matching; fuzzy normalization; validation with warnings instead of silent drops |
| R3 | qasync compatibility issues with PySide6 | Medium | Medium | Pin versions; integration tests early; fallback to QThread-based async bridge if needed |
| R4 | Provider API rate limiting | High | Medium | Bounded concurrency via semaphores; exponential backoff via tenacity; user-configurable limits |
| R5 | Large BOMs (1000+ rows) slow UI | Medium | Medium | Table virtualization; incremental updates; background enrichment with row-level state |
| R6 | API key security on Windows | Low | High | Use keyring for OS-native credential storage; never log secrets; mask in UI |
| R7 | Runtime model discovery APIs change | Medium | Low | Cache model lists locally; graceful fallback to last known list; manual entry option |
| R8 | openpyxl hyperlink handling edge cases | Low | Medium | Test with various URL formats; sanitize formula-like text; explicit UTF-8 encoding |
