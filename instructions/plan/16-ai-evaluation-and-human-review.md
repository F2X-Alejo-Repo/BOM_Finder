# 16 - AI Evaluation and Human Review

## Purpose

Define measurable AI quality gates and mandatory human review controls.
No production-ready enrichment without this evaluation framework.

## Evaluation Scope

- Enrichment summary quality
- Factual grounding compliance
- Replacement candidate ranking quality
- Safety and privacy policy adherence

## Versioning Contract

Every enrichment result must reference:
- `provider`
- `model`
- `prompt_version`
- `evidence_schema_version`
- `evaluation_suite_version`

## Eval Dataset Buckets

1. Standard BOM set
- clean rows, known parts
2. Ambiguous source set
- conflicting stock/lifecycle evidence
3. Adversarial text set
- noisy or malformed supplier descriptions
4. Privacy-sensitive set
- rows where minimization policy changes context
5. Failure-path set
- source unavailable, partial evidence, timeout

## Core Metrics and Thresholds

- Grounded factual fields precision: >= 0.99
- Hallucinated factual assertions: 0 blocker tolerance
- Replacement top-3 relevance: >= 0.90 on golden set
- Structured output validity: >= 0.995
- Policy violations (privacy/approval bypass): 0 blocker tolerance

## Blocking Failure Conditions

- Any fabricated stock, lifecycle, lead time, MOQ, source URL, or part number
- Missing provenance for asserted observed fact
- Response accepted when structured schema validation fails

## Human Review Policy

Mandatory manual review if any of:
- confidence below configured threshold
- conflicting evidence across sources
- lifecycle status in `NRND`, `LAST_TIME_BUY`, or `EOL`
- replacement match score below acceptance threshold
- policy decision requires approval

## Evaluation Cadence

- Baseline run before feature merge
- Full suite run before release candidate
- Regression run on provider/model/prompt changes

## Gate Criteria

- Eval suite thresholds pass
- Human-review trigger tests pass
- Versioning fields persisted and exportable for audits
