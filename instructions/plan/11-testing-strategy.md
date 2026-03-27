# 11 — Testing Strategy

## Test Stack

- `pytest` + `pytest-asyncio` for async test support
- `pytest-cov` for coverage reporting
- No mocking of the database in integration tests (use in-memory SQLite)
- Mock only external HTTP calls (LLM providers) using `httpx` mock transport or `respx`
- Test fixtures in `tests/fixtures/`

## Enterprise Gate Test Suites (Docs 13 to 20)

These suites are required for enterprise signoff.

1. Scope and acceptance gates (Doc 13)
- Validate acceptance criteria tags map to implementation tests.
- Fail build if acceptance-to-test traceability is missing.

2. Source compliance and retrieval safety (Doc 14)
- Host allowlist tests
- SSRF guardrail tests (localhost/private ranges blocked)
- Parser provenance field tests

3. State machine and workflow contracts (Doc 15)
- Valid and invalid row transitions
- Valid and invalid job transitions
- `completed_with_errors` semantics tests

4. AI evaluation and review policy (Doc 16)
- Grounding precision and hallucination blocker suite
- Structured output schema validity tests
- Human review trigger tests

5. Migration and upgrade resilience (Doc 17)
- Forward migration tests from prior snapshots
- Backup/restore tests
- Interrupted migration recovery tests

6. Release and rollback readiness (Doc 18)
- Packaging smoke tests
- Rollback drill simulation tests
- Release checklist artifact validation

7. SLO and incident readiness (Doc 19)
- Telemetry contract tests (required fields and correlation IDs)
- Alert-threshold simulation tests
- Diagnostics bundle generation tests

8. Cost and usage guardrails (Doc 20)
- Per-row and per-job budget cap enforcement
- Cost preflight estimate tests
- Circuit breaker behavior tests

## Test Structure

```
tests/
├── conftest.py                         # Shared fixtures
├── unit/
│   ├── test_column_matcher.py          # 25+ test cases
│   ├── test_csv_parser.py             # 15+ test cases
│   ├── test_normalizer.py            # 15+ test cases
│   ├── test_matching_engine.py        # 20+ test cases
│   ├── test_normalization_service.py  # 10+ test cases
│   ├── test_entities.py              # 10+ test cases
│   └── test_enums.py                 # 5+ test cases
├── integration/
│   ├── test_import_pipeline.py        # 10+ test cases
│   ├── test_enrichment_pipeline.py    # 10+ test cases
│   ├── test_export_pipeline.py        # 8+ test cases
│   ├── test_job_manager.py           # 10+ test cases
│   └── test_provider_adapters.py     # 8+ test cases
├── fixtures/
│   ├── sample_bom_standard.csv
│   ├── sample_bom_weird_headers.csv
│   ├── sample_bom_missing_cols.csv
│   ├── sample_bom_extra_cols.csv
│   ├── sample_bom_quoted.csv
│   ├── sample_bom_malformed.csv
│   ├── sample_bom_utf8_bom.csv
│   └── sample_bom_large.csv
└── ui/
    └── test_smoke.py                  # 5+ test cases
```

## Key Test Cases by Module

### test_column_matcher.py — Column Regex Matching

| # | Input Header | Expected Canonical Field | Scenario |
|---|-------------|------------------------|----------|
| 1 | `"Designator"` | `designator` | Standard |
| 2 | `"DESIGNATOR"` | `designator` | All caps |
| 3 | `"designators"` | `designator` | Plural |
| 4 | `"Reference"` | `designator` | Alias |
| 5 | `"  Reference  "` | `designator` | Leading/trailing spaces |
| 6 | `"Ref_Des"` | `designator` | Underscore |
| 7 | `"ref-des"` | `designator` | Hyphen + lowercase |
| 8 | `"Value"` | `comment` | Value→comment mapping |
| 9 | `"COMMENT"` | `comment` | All caps |
| 10 | `"Footprint"` | `footprint` | Standard |
| 11 | `"PCB Footprint"` | `footprint` | Multi-word alias |
| 12 | `"pcb_footprint"` | `footprint` | Underscore variant |
| 13 | `"Package"` | `footprint` | Alias |
| 14 | `"LCSC Part #"` | `lcsc_part_number` | Hash sign |
| 15 | `"LCSC Part Number"` | `lcsc_part_number` | Full name |
| 16 | `"lcsc pn"` | `lcsc_part_number` | Abbreviation |
| 17 | `"LCSC_PN"` | `lcsc_part_number` | Underscore + caps |
| 18 | `"LCSC Link"` | `lcsc_link` | Standard |
| 19 | `"Supplier URL"` | `lcsc_link` | Alias |
| 20 | `"Part Link"` | `lcsc_link` | Alias |
| 21 | `"Random Column"` | `None` (unmapped) | Unknown column |
| 22 | `""` | `None` (unmapped) | Empty header |
| 23 | `"Qty"` | `quantity` | Optional column |
| 24 | `"Manufacturer"` | `manufacturer` | Optional column |
| 25 | `"MPN"` | `mpn` | Optional column |

### test_csv_parser.py — CSV Parsing

| # | Fixture | Test |
|---|---------|------|
| 1 | standard.csv | Parses correctly, all rows present |
| 2 | standard.csv | Correct header detection |
| 3 | standard.csv | Correct row count |
| 4 | weird_headers.csv | Headers normalized before matching |
| 5 | missing_cols.csv | Missing optional columns handled gracefully |
| 6 | extra_cols.csv | Extra columns preserved, not errored |
| 7 | quoted.csv | Commas inside quoted fields don't split |
| 8 | quoted.csv | Multiline quoted text preserved |
| 9 | malformed.csv | Partial rows not dropped, marked with warnings |
| 10 | utf8_bom.csv | UTF-8 BOM marker detected and stripped |
| 11 | (generated) | Latin-1 encoding detected correctly |
| 12 | (generated) | Semicolon delimiter detected |
| 13 | (generated) | Tab delimiter detected |
| 14 | (generated) | Empty file produces empty result, no crash |
| 15 | (generated) | File with only headers, no data rows |

### test_normalizer.py — Row Normalization

| # | Test |
|---|------|
| 1 | Single designator "R1" → designator_list=["R1"], quantity=1 |
| 2 | Multi-designator "R1, R2, R3" → designator_list=["R1","R2","R3"], quantity=3 |
| 3 | Designator with spaces "R1 , R2" → cleaned properly |
| 4 | Value "100K" stored in both comment and value_raw |
| 5 | Empty LCSC link → empty string, no error |
| 6 | Multiple URLs in cell → primary extracted, warning generated |
| 7 | Multiple part numbers → primary extracted, warning generated |
| 8 | Completely empty row → stored with validation warnings |
| 9 | Whitespace-only fields → cleaned to empty string |
| 10 | Very long field values → truncated at reasonable limit |

### test_matching_engine.py — Part Matching

| # | Test |
|---|------|
| 1 | Exact LCSC match → score ~1.0 |
| 2 | Same value + footprint, different manufacturer → score ~0.85 |
| 3 | Same value, different footprint → score ~0.6 |
| 4 | Different value, same footprint → score ~0.4 |
| 5 | EOL candidate penalized in lifecycle score |
| 6 | Out-of-stock candidate penalized in stock score |
| 7 | Higher voltage rating candidate scores well on voltage_compat |
| 8 | Lower voltage rating candidate scores 0 on voltage_compat |
| 9 | Score breakdown contains all expected keys |
| 10 | Explanation string is non-empty |
| 11 | Unknown fields default to conservative scores |

### test_export_pipeline.py — Excel Export

| # | Test |
|---|------|
| 1 | Output file is valid .xlsx (openpyxl can read it) |
| 2 | Exactly 5 columns: Designator, Comment, Footprint, LCSC LINK, LCSC PART # |
| 3 | Header row is bold |
| 4 | Autofilter is applied |
| 5 | Top row is frozen |
| 6 | LCSC LINK cells contain hyperlinks |
| 7 | Metadata sheet present when option enabled |
| 8 | Formula-injection text is sanitized |

### test_provider_adapters.py — Provider Contract Tests

| # | Test |
|---|------|
| 1 | OpenAI adapter implements all IProviderAdapter methods |
| 2 | Anthropic adapter implements all IProviderAdapter methods |
| 3 | Capabilities are valid for each provider |
| 4 | Test connection with invalid key returns failure, not exception |
| 5 | Model discovery returns list[ModelInfo] |
| 6 | Chat returns ProviderResponse with expected fields |
| 7 | Timeout is respected |
| 8 | Rate limit (429) triggers retry |

### test_job_manager.py — Job Lifecycle

| # | Test |
|---|------|
| 1 | Submit job → state transitions: PENDING → QUEUED → RUNNING → COMPLETED |
| 2 | Cancel running job → state = CANCELLED |
| 3 | Pause/resume works correctly |
| 4 | Failed rows counted correctly |
| 5 | Concurrency bounded by semaphore |
| 6 | Job persisted to repository at each state change |
| 7 | Events emitted at each state transition |

## Test Fixtures

### sample_bom_standard.csv
```csv
Designator,Comment,Footprint,LCSC Part #,LCSC Link
"R1, R2, R3, R4",100K,R_0402_1005Metric,C25744,https://jlcpcb.com/parts/C25744
"C1, C2",100nF,C_0402_1005Metric,C1525,https://jlcpcb.com/parts/C1525
U1,STM32F405RGT6,LQFP-64_10x10mm_P0.5mm,C15742,https://jlcpcb.com/parts/C15742
```

### sample_bom_weird_headers.csv
```csv
REFERENCE ,  VALUE  , PCB_FOOTPRINT , LCSC Part Number , Supplier URL
R1,100K,0402,C25744,https://jlcpcb.com/parts/C25744
```

### sample_bom_quoted.csv
```csv
Designator,Comment,Footprint,LCSC Part #
"R1, R2","100K, 1%","R_0402_1005Metric",C25744
```

## Coverage Target

- **Unit tests**: > 90% line coverage on domain + infrastructure/csv + domain/matching
- **Integration tests**: Cover all happy paths and primary error paths
- **UI smoke tests**: Verify widgets instantiate without crash
- **Enterprise gate tests**: All doc-13-to-doc-20 gate suites passing with zero blocker failures

## Gate Signoff Matrix

| Gate Area | Source Doc | Required Test Evidence |
|---|---|---|
| Scope and acceptance | `13-product-scope-and-acceptance.md` | Acceptance traceability report |
| Source compliance and safety | `14-external-data-sources-and-compliance.md` | Allowlist + SSRF + provenance tests |
| State contracts | `15-state-machine-and-workflow-contracts.md` | Transition and invariant tests |
| AI quality and review | `16-ai-evaluation-and-human-review.md` | Eval suite report and blocker summary |
| Migration and upgrade | `17-data-migration-and-upgrade.md` | Migration + backup/restore test report |
| Release and rollback | `18-release-rollout-and-rollback.md` | Rollback drill and packaging smoke report |
| SLO and incident readiness | `19-slos-observability-and-incident-runbooks.md` | Metrics/alerts/runbook simulation report |
| Cost controls | `20-cost-and-provider-usage-guardrails.md` | Budget and circuit-breaker test report |

## Blocker Policy

- Any hallucinated factual assertion in eval suite is a blocker.
- Any state-machine invariant violation is a blocker.
- Any missing provenance for observed claims is a blocker.
- Any budget hard-limit bypass is a blocker.

## Running Tests

```bash
# All tests
pytest tests/ -v --cov=src/bom_workbench --cov-report=term-missing

# Unit only
pytest tests/unit/ -v

# Integration only
pytest tests/integration/ -v

# With async support
pytest tests/ -v --asyncio-mode=auto
```
