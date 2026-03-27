# KiCad BOM Intelligence Workbench — Master Implementation Plan

## Plan Documents

| # | Document | Scope |
|---|----------|-------|
| 01 | [architecture-and-adrs.md](01-architecture-and-adrs.md) | System architecture, hexagonal layers, ADRs, risk register |
| 02 | [folder-structure.md](02-folder-structure.md) | Complete project tree with every module and file |
| 03 | [data-model.md](03-data-model.md) | Pydantic schemas, SQLModel entities, enums, relationships |
| 04 | [csv-ingestion.md](04-csv-ingestion.md) | CSV parsing pipeline, column matching, normalization |
| 05 | [provider-integration.md](05-provider-integration.md) | LLM provider abstraction, adapters, capability matrix |
| 06 | [enrichment-pipeline.md](06-enrichment-pipeline.md) | Sourcing pipeline, evidence model, matching engine |
| 07 | [ui-design.md](07-ui-design.md) | Widget hierarchy, tabs, theming, signals, UX patterns |
| 08 | [export-system.md](08-export-system.md) | Excel export, formatting, metadata sheet |
| 09 | [job-management.md](09-job-management.md) | Async task queue, concurrency, state machine |
| 10 | [security-and-observability.md](10-security-and-observability.md) | Secrets, privacy, logging, redaction |
| 11 | [testing-strategy.md](11-testing-strategy.md) | Test plan, fixtures, edge cases |
| 12 | [implementation-phases.md](12-implementation-phases.md) | 10-phase build order with dependencies and quality gates |
| 13 | [product-scope-and-acceptance.md](13-product-scope-and-acceptance.md) | Personas, scope slices, non-goals, measurable acceptance |
| 14 | [external-data-sources-and-compliance.md](14-external-data-sources-and-compliance.md) | Approved sources, legal constraints, retrieval safety contract |
| 15 | [state-machine-and-workflow-contracts.md](15-state-machine-and-workflow-contracts.md) | Row/job state transitions, invariants, workflow ownership |
| 16 | [ai-evaluation-and-human-review.md](16-ai-evaluation-and-human-review.md) | Eval suites, thresholds, review gates, prompt/model governance |
| 17 | [data-migration-and-upgrade.md](17-data-migration-and-upgrade.md) | Alembic policy, schema compatibility, backup/restore, upgrade path |
| 18 | [release-rollout-and-rollback.md](18-release-rollout-and-rollback.md) | Release channels, rollout checklist, rollback triggers and comms |
| 19 | [slos-observability-and-incident-runbooks.md](19-slos-observability-and-incident-runbooks.md) | SLIs/SLOs, alerts, diagnostics, incident runbook contracts |
| 20 | [cost-and-provider-usage-guardrails.md](20-cost-and-provider-usage-guardrails.md) | Token/cost budgets, hard limits, circuit breakers, spend controls |

## Context

**Problem**: KiCad 9 users need a way to take BOM CSV exports, enrich them with market intelligence (stock, lifecycle, EOL risk, alternates), find replacement parts, and produce clean procurement-ready Excel files. No existing tool combines CSV normalization + LLM-powered enrichment + part matching + professional export in a single desktop workflow.

**Intended outcome**: A production-grade, enterprise-ready, async desktop Python application that feels premium and eliminates manual BOM sourcing research.

**Golden rule**: Deterministic retrieval first, LLM reasoning second. No hallucinated facts.

## Enterprise Readiness Note

Documents 13 to 20 are hard planning gates for full enterprise execution.
Without them, only a reduced build slice is allowed (import + normalization + storage + exact export).
