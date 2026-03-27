# 02 — Folder Structure

```
BOM_Finder/
├── .ai/                              # (existing) AI operating model
├── .github/                          # (existing) GitHub config
├── instructions/                     # (existing) Spec + plan
│   ├── bom_llm_build_prompts.md
│   └── plan/
│       └── *.md
│
├── src/
│   └── bom_workbench/                # Main package
│       ├── __init__.py               # Package version, metadata
│       ├── __main__.py               # Entry point: python -m bom_workbench
│       ├── app.py                    # Application bootstrap, DI wiring, event loop setup
│       │
│       ├── domain/                   # DOMAIN LAYER — pure business logic, no external deps
│       │   ├── __init__.py
│       │   ├── entities.py           # BomProject, BomRow, EnrichmentResult, ReplacementCandidate
│       │   ├── enums.py              # LifecycleStatus, StockBucket, EolRisk, RowState, JobState, Confidence
│       │   ├── value_objects.py      # MatchScore, ColumnMapping, ValidationWarning, Evidence
│       │   ├── ports.py              # Abstract interfaces: IProviderAdapter, IBomRepository,
│       │   │                         #   IJobRepository, IEvidenceRetriever, IExporter, ISecretStore
│       │   ├── matching.py           # MatchingEngine — tiered matching logic, score computation
│       │   └── normalization.py      # NormalizationService — column regex matching, value cleanup
│       │
│       ├── application/              # APPLICATION LAYER — use cases, orchestration
│       │   ├── __init__.py
│       │   ├── import_bom.py         # ImportBomUseCase — CSV ingestion orchestration
│       │   ├── enrich_bom.py         # EnrichBomUseCase — enrichment pipeline orchestration
│       │   ├── find_parts.py         # FindPartsUseCase — part search + matching orchestration
│       │   ├── export_bom.py         # ExportBomUseCase — Excel export orchestration
│       │   ├── configure_provider.py # ConfigureProviderUseCase — provider setup, test connection
│       │   ├── job_manager.py        # JobManager — async task queue, concurrency, state machine
│       │   └── event_bus.py          # EventBus — lightweight pub/sub for decoupled communication
│       │
│       ├── infrastructure/           # INFRASTRUCTURE LAYER — external adapters
│       │   ├── __init__.py
│       │   │
│       │   ├── providers/            # LLM provider adapters
│       │   │   ├── __init__.py
│       │   │   ├── base.py           # ProviderCapabilities dataclass, base adapter helpers
│       │   │   ├── openai_adapter.py # OpenAI provider: model discovery, chat, structured output
│       │   │   └── anthropic_adapter.py # Anthropic provider: model discovery, messages, thinking
│       │   │
│       │   ├── persistence/          # Database layer
│       │   │   ├── __init__.py
│       │   │   ├── database.py       # Engine creation, session factory, migrations
│       │   │   ├── models.py         # SQLModel table definitions (mirror domain entities)
│       │   │   ├── bom_repository.py # SQLite implementation of IBomRepository
│       │   │   └── job_repository.py # SQLite implementation of IJobRepository
│       │   │
│       │   ├── csv/                  # CSV parsing
│       │   │   ├── __init__.py
│       │   │   ├── parser.py         # CsvParser — encoding detection, delimiter detection, parsing
│       │   │   ├── column_matcher.py # ColumnMatcher — regex alias matching, mapping generation
│       │   │   └── normalizer.py     # RowNormalizer — raw row → canonical BomRow
│       │   │
│       │   ├── export/               # Excel export
│       │   │   ├── __init__.py
│       │   │   └── xlsx_exporter.py  # XlsxExporter — openpyxl-based Excel generation
│       │   │
│       │   ├── secrets/              # Credential storage
│       │   │   ├── __init__.py
│       │   │   └── keyring_store.py  # KeyringSecretStore — OS-native secret storage
│       │   │
│       │   └── logging/              # Structured logging
│       │       ├── __init__.py
│       │       └── setup.py          # structlog configuration, redaction processors
│       │
│       └── ui/                       # PRESENTATION LAYER — PySide6 UI
│           ├── __init__.py
│           ├── main_window.py        # MainWindow — app shell, navigation, layout
│           ├── theme.py              # QSS theme definitions, color palette, dark mode
│           │
│           ├── widgets/              # Reusable UI components
│           │   ├── __init__.py
│           │   ├── status_chip.py    # StatusChip — colored pill for row/job states
│           │   ├── metric_card.py    # MetricCard — summary dashboard metric display
│           │   ├── drop_zone.py      # DropZone — drag-and-drop file target
│           │   ├── search_bar.py     # SearchBar — filterable search input
│           │   └── progress_bar.py   # AsyncProgressBar — non-blocking progress indicator
│           │
│           ├── pages/                # Tab/page views
│           │   ├── __init__.py
│           │   ├── import_page.py    # BOM Import tab
│           │   ├── bom_table_page.py # BOM Table / Enrichment tab
│           │   ├── part_finder_page.py # Part Finder / Replacement Search tab
│           │   ├── providers_page.py # LLM Providers & Models tab
│           │   ├── jobs_page.py      # Jobs / Activity / Logs tab
│           │   ├── export_page.py    # Export / Reports tab
│           │   └── settings_page.py  # Settings tab
│           │
│           ├── dialogs/              # Modal dialogs
│           │   ├── __init__.py
│           │   ├── column_mapping_dialog.py  # CSV column mapping preview + confirmation
│           │   ├── import_report_dialog.py   # Post-import summary with warnings
│           │   ├── evidence_dialog.py        # Evidence inspection for enriched fields
│           │   └── replacement_confirm_dialog.py # Confirm part replacement action
│           │
│           ├── models/               # Qt item models (view models)
│           │   ├── __init__.py
│           │   ├── bom_table_model.py  # QAbstractTableModel for BOM data
│           │   ├── job_table_model.py  # QAbstractTableModel for job queue
│           │   └── candidate_model.py  # QAbstractTableModel for replacement candidates
│           │
│           └── inspector/            # Right-side detail panel
│               ├── __init__.py
│               └── row_inspector.py  # RowInspector — selected row details, evidence, actions
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Shared fixtures: sample CSVs, mock providers, test DB
│   │
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_column_matcher.py    # Regex header matching with all alias variations
│   │   ├── test_csv_parser.py        # Encoding, delimiter, quoted fields, malformed rows
│   │   ├── test_normalizer.py        # Raw row → canonical BomRow conversion
│   │   ├── test_matching_engine.py   # Tiered matching logic, score computation
│   │   ├── test_normalization_service.py # Value cleanup, designator parsing
│   │   ├── test_entities.py          # Domain entity validation
│   │   └── test_enums.py             # Enum behavior
│   │
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_import_pipeline.py   # End-to-end CSV → BomRow in DB
│   │   ├── test_enrichment_pipeline.py # Enrichment with mock provider
│   │   ├── test_export_pipeline.py   # BomRow → XLSX validation
│   │   ├── test_job_manager.py       # Async job lifecycle
│   │   └── test_provider_adapters.py # Provider adapter contract tests
│   │
│   ├── fixtures/
│   │   ├── sample_bom_standard.csv   # Normal KiCad 9 export
│   │   ├── sample_bom_weird_headers.csv # Uppercase, spaces, dashes
│   │   ├── sample_bom_missing_cols.csv  # Missing optional columns
│   │   ├── sample_bom_extra_cols.csv    # Extra unknown columns
│   │   ├── sample_bom_quoted.csv        # Commas inside quoted fields
│   │   ├── sample_bom_malformed.csv     # Partially corrupt rows
│   │   ├── sample_bom_utf8_bom.csv      # UTF-8 BOM marker
│   │   └── sample_bom_large.csv         # 500+ rows for performance
│   │
│   └── ui/
│       ├── __init__.py
│       └── test_smoke.py             # UI smoke tests (widget creation, signal wiring)
│
├── resources/
│   ├── icons/                        # SVG icons for navigation, status, actions
│   ├── fonts/                        # Optional: bundled fonts
│   └── themes/
│       └── dark.qss                  # Default dark theme stylesheet
│
├── pyproject.toml                    # Project metadata, dependencies, build config
├── README.md                         # (existing) Project readme
├── CLAUDE.md                         # (existing) AI instructions
└── AGENTS.md                         # (existing) Agent config
```

## Module Responsibilities Summary

| Module | Primary Responsibility | Key Classes |
|--------|----------------------|-------------|
| `domain/entities.py` | Business entities | `BomProject`, `BomRow`, `EnrichmentResult`, `ReplacementCandidate` |
| `domain/ports.py` | Interfaces / contracts | `IProviderAdapter`, `IBomRepository`, `IJobRepository`, `IExporter`, `ISecretStore` |
| `domain/matching.py` | Part matching logic | `MatchingEngine` |
| `domain/normalization.py` | Data cleanup | `NormalizationService` |
| `application/job_manager.py` | Async job orchestration | `JobManager`, `Job`, `JobState` |
| `application/event_bus.py` | Decoupled messaging | `EventBus` |
| `infrastructure/csv/parser.py` | CSV file parsing | `CsvParser` |
| `infrastructure/csv/column_matcher.py` | Header → field mapping | `ColumnMatcher` |
| `infrastructure/providers/openai_adapter.py` | OpenAI integration | `OpenAIProviderAdapter` |
| `infrastructure/providers/anthropic_adapter.py` | Anthropic integration | `AnthropicProviderAdapter` |
| `infrastructure/persistence/bom_repository.py` | BOM data storage | `SqliteBomRepository` |
| `infrastructure/export/xlsx_exporter.py` | Excel file generation | `XlsxExporter` |
| `ui/main_window.py` | App shell | `MainWindow` |
| `ui/pages/bom_table_page.py` | Core data view | `BomTablePage` |
| `ui/models/bom_table_model.py` | Table data binding | `BomTableModel` |
