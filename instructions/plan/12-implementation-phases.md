# 12 - Implementation Phases

## Enterprise Prerequisite Gates

Before full-scope execution, these planning docs must exist and be approved:

- `13-product-scope-and-acceptance.md`
- `14-external-data-sources-and-compliance.md`
- `15-state-machine-and-workflow-contracts.md`
- `16-ai-evaluation-and-human-review.md`
- `17-data-migration-and-upgrade.md`
- `18-release-rollout-and-rollback.md`
- `19-slos-observability-and-incident-runbooks.md`
- `20-cost-and-provider-usage-guardrails.md`

If these gates are not complete, only reduced-scope execution is allowed:
import + normalization + storage + exact 5-column export.

## Phase Overview

| Phase | Name | Dependencies | Deliverables | Quality Gate |
|---|---|---|---|---|
| 1 | Project Scaffold | None | `pyproject.toml`, folder structure, empty modules, dev environment | Build installs, imports work |
| 2 | Domain Layer | Phase 1 | Entities, enums, value objects, ports | Models validate, type-check passes |
| 3 | CSV Ingestion | Phase 2 | `CsvParser`, `ColumnMatcher`, `RowNormalizer`, unit tests | Fixture CSVs parse, ingestion tests pass |
| 4 | Persistence Layer | Phase 2 + Doc 17 | SQLite, repositories, migration setup | CRUD + migration + backup/restore tests pass |
| 5 | UI Shell | Phase 2 + Doc 15 | Main window, navigation, theme, page stubs | App launches, navigation works, state contract wired |
| 6 | Import Workflow | Phase 3 + 4 + 5 + Doc 13 | Import use case, mapping dialog, import report, BOM table | Acceptance traceability for import is satisfied |
| 7 | Provider Integration | Phase 2 + 4 + Doc 14 + Doc 20 | Provider adapters, secrets, provider page | Source safety and cost controls validated |
| 8 | Enrichment Pipeline | Phase 4 + 7 + Doc 14 + Doc 15 + Doc 16 + Doc 19 + Doc 20 | Enrich use case, retriever, prompts, job manager, jobs page | Grounding, eval, state, observability, and guardrails pass |
| 9 | Part Finder and Replacement | Phase 8 + Doc 15 + Doc 16 | Finder use case, matching engine, replacement flow | Explainable ranking + human review policy pass |
| 10 | Export and Polish | Phase 6 + 8 + Doc 18 + Doc 19 | Exporter, export page, integration tests, packaging | Export spec + release checklist + rollback drill pass |

## Phase 1: Project Scaffold

Goal: runnable project skeleton with installable dependencies.

Tasks:
1. Create `pyproject.toml` with core and dev dependencies.
2. Create full package/module scaffolding.
3. Add minimal app entrypoint and bootstrap.
4. Add initial theme file and startup logging.

Quality gate:
- `pip install -e .` succeeds.
- `python -m bom_workbench` starts cleanly.

## Phase 2: Domain Layer

Goal: stable business model and interfaces.

Tasks:
1. Implement enums and domain/value objects.
2. Implement entities and ports.
3. Implement normalization and matching core services.
4. Add unit tests for entity validation and scoring logic.

Quality gate:
- Domain contracts compile and validate.
- Type checks and domain unit tests pass.

## Phase 3: CSV Ingestion

Goal: robust CSV to canonical row normalization.

Tasks:
1. Implement parser with encoding and delimiter detection.
2. Implement regex-based column matching and ambiguity handling.
3. Implement normalizer with warning preservation.
4. Add fixture-heavy tests for malformed and variant input.

Quality gate:
- All CSV fixtures parse without crash.
- No silent row drops.

## Phase 4: Persistence Layer

Goal: durable storage and migration safety.

Tasks:
1. Implement DB engine/session wiring.
2. Implement BOM and job repositories.
3. Implement migration framework and schema version checks.
4. Add migration and backup/restore tests from Doc 17.

Quality gate:
- CRUD works end-to-end.
- Migration suite and recovery suite pass.

## Phase 5: UI Shell

Goal: responsive shell with explicit state ownership.

Tasks:
1. Implement main window, page stack, and nav.
2. Implement reusable widgets and baseline page stubs.
3. Wire event loop and state transition handling per Doc 15.

Quality gate:
- App is stable, non-blocking, and navigable.
- State transitions are routed through application layer only.

## Phase 6: Import Workflow

Goal: drag/drop or pick CSV and show normalized rows.

Tasks:
1. Implement import orchestration use case.
2. Build mapping and report dialogs.
3. Implement BOM table model and inspector.
4. Add acceptance tests mapped to Doc 13 criteria.

Quality gate:
- Import flow works from file to DB to table.
- Acceptance traceability report is complete.

## Phase 7: Provider Integration

Goal: secure provider setup and model discovery.

Tasks:
1. Implement provider base types and adapters.
2. Implement secure secret storage.
3. Build provider configuration UI.
4. Add compliance/safety tests from Doc 14.
5. Add budget and cap controls from Doc 20.

Quality gate:
- Provider connection and discovery work.
- Allowlist/SSRF and budget guardrails pass.

## Phase 8: Enrichment Pipeline

Goal: grounded enrichment with full governance.

Tasks:
1. Implement enrichment orchestration.
2. Implement deterministic evidence retriever.
3. Implement job manager with resumable semantics.
4. Add evidence and job status UI.
5. Add eval suite and human review triggers from Doc 16.
6. Add telemetry and alert hooks from Doc 19.

Quality gate:
- Enrichment is grounded and traceable.
- Eval blockers are zero.
- State invariants, observability, and cost controls pass.

## Phase 9: Part Finder and Replacement

Goal: explainable candidate ranking and safe replacement.

Tasks:
1. Implement finder orchestration.
2. Implement candidate ranking and explanation display.
3. Add confirm-before-apply replacement workflow.
4. Add policy and review tests (Docs 15 and 16).

Quality gate:
- Candidate rankings are explainable.
- No silent replacements.
- Human review triggers operate correctly.

## Phase 10: Export and Polish

Goal: production-ready export and release readiness.

Tasks:
1. Implement XLSX exporter and export orchestration.
2. Implement export page and settings integrations.
3. Complete integration and packaging tests.
4. Execute release checklist and rollback drill from Doc 18.
5. Validate SLO/alert/runbook readiness from Doc 19.

Quality gate:
- Export matches exact 5-column schema requirements.
- Packaging is reproducible.
- Release and operational gates pass.

## Hard Gate Enforcement Matrix

| Gate Doc | First Blocking Phase | Required Evidence |
|---|---|---|
| `13-product-scope-and-acceptance.md` | 6 | Acceptance traceability |
| `14-external-data-sources-and-compliance.md` | 7 | Allowlist, SSRF, provenance tests |
| `15-state-machine-and-workflow-contracts.md` | 5 | Transition and invariant tests |
| `16-ai-evaluation-and-human-review.md` | 8 | Eval report, review-trigger tests |
| `17-data-migration-and-upgrade.md` | 4 | Migration and recovery tests |
| `18-release-rollout-and-rollback.md` | 10 | Rollout checklist and rollback drill |
| `19-slos-observability-and-incident-runbooks.md` | 8 | Metrics and runbook validation |
| `20-cost-and-provider-usage-guardrails.md` | 7 | Budget and circuit-breaker tests |
