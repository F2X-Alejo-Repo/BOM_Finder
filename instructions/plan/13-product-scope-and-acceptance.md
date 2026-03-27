# 13 - Product Scope and Acceptance

## Purpose

Define execution scope, measurable acceptance criteria, and non-goals before full implementation.
This document is mandatory for enterprise execution.

## Primary Personas

1. Hardware Engineer
- Imports KiCad 9 BOM files and needs fast validation and replacement options.
2. Sourcing Specialist
- Needs stock, lifecycle, and alternate decisions with clear provenance.
3. Procurement Reviewer
- Needs export artifacts that are reproducible and audit-friendly.
4. Tool Administrator
- Manages provider setup, privacy mode, and operational guardrails.

## Problem Statement

KiCad 9 BOM workflows are fragmented across spreadsheets, supplier portals, and manual review.
The product centralizes ingestion, enrichment, replacement analysis, and controlled export in one desktop workflow.

## Scope by Slice

### Slice A (Execution Baseline)

- CSV import for KiCad 9 BOMs
- Canonical normalization + persistence
- Provider configuration scaffold
- Exact 5-column procurement export

### Slice B (Controlled Intelligence)

- Evidence retrieval and enrichment
- Row/job state machine with resumable jobs
- Confidence display and evidence inspection

### Slice C (Decision Support)

- Part finder and replacement workflow
- Side-by-side candidate comparison
- User-confirmed replacement updates

## Out of Scope (Current Program)

- Browser-first multi-tenant SaaS
- Automated supplier ordering
- Fully autonomous replacement without human confirmation
- Unvetted crawling across arbitrary domains

## Acceptance Criteria

1. Import
- Given a valid KiCad 9 CSV with header variations, import succeeds without UI blocking.
- Malformed rows are preserved and flagged, never silently dropped.

2. Enrichment
- Facts are grounded in retrieved evidence.
- Any inferred field is explicitly marked inferred with confidence.

3. Replacement
- Candidate ranking is explainable.
- No replacement is applied without explicit user confirmation.

4. Export
- Primary workbook always includes exact column order:
  `Designator`, `Comment`, `Footprint`, `LCSC LINK`, `LCSC PART #`.
- Export output is reproducible and includes metadata policy per doc 18 and 19.

5. Security and Privacy
- Secrets never appear in logs.
- Privacy mode is explicit and enforced at call-time.

## Success Metrics

- Import success rate: >= 99% on supported input set
- Time to first visible rows after import start: <= 5s for 1k-row BOM on reference machine
- Enrichment row success rate (excluding external outages): >= 97%
- Export correctness for required 5-column sheet: 100%
- Hallucinated factual assertions in eval suite: 0 blockers

## Traceability Contract

All implementation work must map to:
- one persona
- one scope slice
- one acceptance criterion
- one metric or risk control

## Open Program Decisions

- Final approved supplier source list
- Supported desktop OS matrix for first distribution
- Default policy for metadata sheet visibility
