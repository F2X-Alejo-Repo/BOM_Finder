# BOM Intelligence Workbench — Prompt Pack

## 1) Main build prompt

```text
You are a principal software architect and staff-level Python engineer building a production-grade desktop BOM intelligence platform for KiCad 9 users only.

Your task is to DESIGN AND IMPLEMENT a world-class, enterprise-ready, async, non-blocking, modern desktop Python application called:

“KICAD BOM Intelligence Workbench”

This is not a prototype, demo, mock, or toy. Build it like a real commercial internal tool that could ship to engineering, sourcing, and procurement teams inside a serious company.

======================================================================
0. PRIMARY GOAL
======================================================================

Build a robust desktop application that:

1. Imports KiCad 9 BOM CSV files via:
   - drag-and-drop
   - file picker
   - folder import for batch ingestion

2. Accepts CSVs with varying column order, formatting, casing, spaces, punctuation, or minor naming variations, but normalizes them into a canonical schema.

3. Displays the parsed BOM in a professional, modern, minimal, dark-mode-first UI.

4. Lets the user configure LLM providers and models:
   - OpenAI
   - Anthropic / Claude
   - provider-specific auth methods supported by their official platforms
   - API-key mode must be fully supported
   - runtime model discovery, not hardcoded model lists
   - provider/model selection
   - reasoning / thinking intensity controls where supported
   - concurrency / batch controls
   - timeout / retry controls

5. Enriches BOM rows with market intelligence and sourcing metadata:
   - stock quantity
   - stock status
   - lifecycle status
   - EOL / NRND / active / unknown
   - recommended alternates
   - sourcing confidence
   - notes and evidence links
   - timestamp of last check

6. Allows the user to search for candidate replacement parts using criteria such as:
   - footprint
   - value
   - tolerance
   - voltage rating
   - dielectric
   - package
   - manufacturer preference
   - LCSC availability
   - long-life preference
   - high-stock preference
   - lifecycle safety
   - pricing / MOQ preference if available

7. Lets the user accept a suggested replacement and update the row inside the same table.

8. Exports a clean .xlsx containing exactly these five columns:
   - Designator
   - Comment
   - Footprint
   - LCSC LINK
   - LCSC PART #

9. Must feel premium, polished, and efficient for daily use.

======================================================================
1. REQUIRED ENGINEERING STANDARD
======================================================================

The application must be:

- Python-first
- async and non-blocking
- highly modular
- strongly typed
- observable
- testable
- secure by default
- enterprise-ready
- maintainable by a real engineering team
- resilient to malformed inputs and network instability
- explicit about uncertainty
- hostile to hallucinations

Do not generate a simplistic CRUD app.
Do not generate a monolithic script.
Do not generate placeholder architecture.
Do not generate pseudo-enterprise fluff.

Generate a real software system.

======================================================================
2. PREFERRED TECHNICAL STACK
======================================================================

Use this stack unless there is a compelling engineering reason to improve it:

Frontend/Desktop:
- Python 3.12+
- PySide6 (Qt 6)
- qasync for asyncio + Qt event loop integration
- QSS styling and/or QML only if needed for superior UX
- dark mode first
- table virtualization or efficient table rendering for larger BOMs

Backend / Core:
- asyncio
- httpx for async HTTP
- pydantic v2 for schemas and validation
- pandas for CSV/XLSX data handling
- openpyxl for styled Excel export
- SQLite for local persistence
- SQLModel or SQLAlchemy 2.x for persistence layer
- tenacity or equivalent for retries
- structlog or standard structured logging
- keyring or OS-native secure secret storage for API keys if feasible
- dependency injection friendly design
- pytest + pytest-asyncio for testing

Packaging:
- PyInstaller, Nuitka, or Briefcase if justified
- produce a desktop-distributable build path

Architecture:
- clean architecture / hexagonal architecture
- service layer + provider adapters + repository layer
- no provider logic mixed directly into UI code

======================================================================
3. MANDATORY SUBAGENT STRATEGY
======================================================================

You are allowed to spawn subagents. Use them.

Spawn specialized subagents for:
1. Desktop UX / Qt architecture
2. CSV ingestion and normalization
3. Provider integrations
4. BOM enrichment / sourcing pipeline
5. Export and spreadsheet formatting
6. Testing / QA
7. Security / secrets / compliance
8. Packaging / deployment

Each subagent must return:
- scope
- decisions
- risks
- implementation output
- open questions

Then integrate all outputs into one coherent codebase.

======================================================================
4. USER EXPERIENCE REQUIREMENTS
======================================================================

The UI must be beautiful, minimal, modern, and professional.

Design goals:
- dark theme by default
- excellent spacing and typography
- restrained accent color usage
- subtle elevation, not flashy
- keyboard-friendly workflows
- drag-and-drop affordances
- enterprise-grade data density with clarity
- polished loading states
- empty states
- retry states
- partial failure states
- status chips / pills
- responsive resizing
- non-blocking progress indicators
- searchable, sortable tables
- pinned summary metrics at top

Required primary tabs/pages:
1. BOM Import
2. BOM Table / Enrichment
3. Part Finder / Replacement Search
4. LLM Providers & Models
5. Jobs / Activity / Logs
6. Export / Reports
7. Settings

Suggested visual structure:
- top app bar with workspace and theme
- left navigation rail or clean tab system
- central data workspace
- right-side inspector panel for selected row details
- bottom status / job panel for async operations

======================================================================
5. CANONICAL DATA MODEL
======================================================================

Define a canonical internal row schema.

At minimum:

Core imported fields:
- source_file
- row_id
- designator
- comment
- value_raw
- footprint
- lcsc_link
- lcsc_part_number

Derived / normalized:
- designator_list
- quantity
- manufacturer
- mpn
- package
- category
- param_summary

Availability / sourcing:
- stock_qty
- stock_status
- lifecycle_status
- eol_risk
- lead_time
- moq
- last_checked_at
- source_url
- source_name
- source_confidence
- sourcing_notes

Replacement workflow:
- replacement_candidate_part_number
- replacement_candidate_link
- replacement_candidate_mpn
- replacement_rationale
- replacement_match_score
- replacement_status
- user_accepted_replacement

Auditability:
- enrichment_provider
- enrichment_model
- enrichment_job_id
- enrichment_version
- evidence_blob
- raw_provider_response
- created_at
- updated_at

======================================================================
6. CSV INGESTION REQUIREMENTS
======================================================================

This system will be used with KiCad 9 BOM CSV exports only, but exported CSV formatting may vary.

Build a robust ingestion pipeline that:
- detects encoding
- detects delimiter
- handles quoted cells
- handles missing columns gracefully
- handles extra columns
- handles repeated commas inside quoted fields
- handles multiline cell text if present
- preserves original source columns
- normalizes to canonical schema

Column matching must be regex-driven and case-insensitive.
Ignore:
- capitalization
- leading/trailing spaces
- underscores
- hyphens
- repeated spaces
- punctuation variation

Match these canonical fields using robust aliases:

1. designator
Accepted header aliases should include patterns like:
- reference
- references
- ref
- designator
- designators

2. comment
Accepted header aliases should include patterns like:
- value
- comment
- val

3. footprint
Accepted header aliases should include patterns like:
- footprint
- package
- pcb footprint

4. lcsc_link
Accepted header aliases should include patterns like:
- lcsc link
- lcsc url
- supplier link
- part link

5. lcsc_part_number
Accepted header aliases should include patterns like:
- lcsc part #
- lcsc part number
- lcsc no
- lcsc pn
- part #
- part number

Important:
- If only “Value” exists, map it into internal comment while preserving value_raw.
- If multiple URLs or multiple part numbers appear in a cell, preserve all raw data, but compute a primary best candidate and flag ambiguity.
- If a row is partially malformed, do not drop it silently; mark it with validation warnings.

Create:
- import validator
- column mapping preview dialog
- warnings panel
- import report

======================================================================
7. LLM / PROVIDER CONFIGURATION REQUIREMENTS
======================================================================

Build a provider abstraction layer.

Support at minimum:
- OpenAI provider adapter
- Anthropic provider adapter

Provider UI must include:
- provider enable/disable
- auth method selection
- secure credential entry
- test connection
- runtime model refresh / discovery
- selected model dropdown
- provider-specific advanced options
- timeout
- retry policy
- max parallel jobs
- token / cost awareness where available
- temperature if supported and appropriate
- reasoning / thinking effort where supported
- structured output enforcement
- batch mode controls

Rules:
- Never hardcode a static model list as the only source of truth.
- Fetch provider model lists dynamically where possible.
- Cache model lists locally with refresh controls.
- Fail gracefully if provider model discovery is unavailable.
- All secrets must stay out of logs.
- No secrets in plaintext config files unless explicitly allowed by user.

Create a provider capability matrix so the UI adapts by provider:
- supports model discovery?
- supports reasoning control?
- supports JSON / structured output?
- supports tool use?
- supports batch?
- supports streaming?

======================================================================
8. ENRICHMENT PHILOSOPHY: NO HALLUCINATED FACTS
======================================================================

This is critical.

The LLM must NEVER invent:
- stock quantity
- lifecycle status
- EOL status
- source URLs
- lead times
- part numbers
- compatibility claims

Design the application so that:
1. deterministic retrieval gets supplier/market data first
2. LLM reasoning interprets and summarizes retrieved evidence second
3. every asserted fact includes provenance
4. uncertain fields are marked unknown, estimated, or inferred
5. the user can inspect evidence

All enrichment results must include:
- source URL
- source name
- retrieval timestamp
- confidence level
- raw evidence snippet or structured evidence record
- whether the value is observed vs inferred

Use the LLM for:
- synthesis
- matching
- ranking
- alternate suggestion reasoning
- parsing messy vendor text
- mapping candidate replacements
- explaining tradeoffs
- classifying lifecycle risk from evidence

Do not use the LLM as the sole source of supplier truth.

======================================================================
9. SOURCING / ENRICHMENT PIPELINE
======================================================================

Implement an async enrichment job pipeline.

For each BOM row:
1. normalize the row
2. determine search keys
   - LCSC part number if available
   - MPN if derivable
   - URL if present
   - value + footprint + category as fallback
3. retrieve market / supplier evidence using provider-specific or tool-based retrieval
4. parse evidence into structured fields
5. optionally use LLM to summarize / classify / rank
6. store evidence and normalized results
7. update UI incrementally without blocking

The UI must show per-row state:
- pending
- queued
- running
- complete
- warning
- failed
- user-reviewed

Use soft red highlighting for:
- out of stock
- EOL
- invalid / ambiguous supplier mapping

Use amber highlighting for:
- low stock
- NRND / near EOL
- ambiguous match
- missing critical evidence

Use green highlighting for:
- healthy stock
- active lifecycle
- validated alternate

======================================================================
10. DEFINE THE EXTRA FIELDS THE USER ASKED FOR
======================================================================

In addition to stock and out-of-stock, the application must track and display:

- lifecycle_status: Active / NRND / Last Time Buy / EOL / Unknown
- eol_risk: Low / Medium / High
- stock_qty
- stock_bucket: Out / Low / Medium / High
- lead_time
- moq
- manufacturer
- mpn
- package
- category
- alternate_count
- best_alternate
- match_score
- sourcing_confidence
- source_name
- source_url
- last_checked_at
- last_changed_at if derivable
- warnings
- evidence_available
- review_required
- notes

Also compute summary dashboard metrics:
- total BOM rows
- total unique parts
- rows enriched
- rows failed
- out-of-stock rows
- low-stock rows
- EOL/NRND rows
- rows with alternates
- rows needing manual review

======================================================================
11. PART FINDER / REPLACEMENT SEARCH
======================================================================

Build a dedicated Part Finder tab.

Capabilities:
- search for a part manually
- search by existing selected BOM row
- search by footprint + value + constraints
- search by lifecycle-safe replacements
- search by high-stock replacements
- search by long-life / industrial preference
- search by exact LCSC availability
- show ranked candidates
- let user compare candidates side-by-side
- let user apply selected candidate back into BOM table

Candidate result card/table should include:
- manufacturer
- MPN
- footprint / package
- value / electrical summary
- LCSC link
- LCSC part #
- stock qty
- lifecycle status
- confidence
- match score
- why it matches
- what may differ
- warnings about risky substitutions

Critical rule:
Never silently replace a component.
Always require explicit user confirmation.

======================================================================
12. MATCHING LOGIC
======================================================================

Build a tiered matching engine.

Priority order:
1. exact LCSC part #
2. exact manufacturer part number
3. exact URL-resolved part
4. strong parametric match
5. heuristic match
6. LLM-ranked candidate set

Compute a transparent match score based on:
- exact value match
- footprint/package match
- voltage rating compatibility
- tolerance compatibility
- temperature rating if available
- dielectric / technology compatibility
- manufacturer preference
- lifecycle safety
- stock health
- confidence in parsed evidence

Expose why the score was assigned.

======================================================================
13. EXPORT REQUIREMENTS
======================================================================

At every major step the user should be able to export.

Export targets:
- current visible filtered table
- full canonical table
- final clean procurement BOM

Primary required export:
.xlsx with EXACT columns and order:
1. Designator
2. Comment
3. Footprint
4. LCSC LINK
5. LCSC PART #

Export rules:
- Comment should map from normalized comment field
- Designator should preserve multi-designator grouping if intended
- one workbook, professionally formatted
- bold header row
- autofilter
- freeze top row
- sensible column widths
- consistent alignment
- optional color cues on status sheets
- include metadata sheet with export timestamp, source files, provider/model used, and warnings summary
- preserve hyperlinks correctly
- no corrupted formula-like text
- UTF-8 safe handling

======================================================================
14. JOBS / CONCURRENCY / ASYNC
======================================================================

Everything network-bound must be async and non-blocking.

Requirements:
- task queue for enrichment jobs
- bounded concurrency via semaphores
- cancellation support
- retry with backoff
- per-job timeout
- partial completion persistence
- resumable jobs where practical
- responsive UI during long operations
- progress reporting at row and batch level

Build a job manager capable of:
- enqueue selected rows
- enqueue full BOM
- pause
- resume
- cancel
- retry failed only
- clear completed
- export failures report

======================================================================
15. SECURITY REQUIREMENTS
======================================================================

Implement production-grade security hygiene.

Required:
- API keys never logged
- secrets masked in UI
- secure storage when possible
- no secret leakage into tracebacks
- redaction filters in logging
- clear trust boundaries
- user confirmation before any destructive action
- local-first data handling
- explicit privacy notes if external providers receive row data
- opt-in sending of BOM data to LLMs
- dry-run mode if possible

Add a privacy setting:
- “Send full row context to LLM”
- “Send minimized row context”
- “Do not send supplier URLs”
- “Manual approval before external calls”

======================================================================
16. RELIABILITY / ERROR HANDLING
======================================================================

This app must behave like enterprise software, not a hackathon demo.

Implement:
- graceful startup checks
- corrupted settings recovery
- provider unavailable handling
- malformed CSV handling
- partial network failure handling
- per-row error isolation
- global error boundary
- actionable user-facing error messages
- developer logs separate from user-friendly alerts

No silent failures.
No swallowed exceptions.
No unexplained disabled UI states.

======================================================================
17. TESTING REQUIREMENTS
======================================================================

Create a meaningful test suite.

Include:
- unit tests for CSV normalization
- regex header matching tests
- parser robustness tests
- provider adapter contract tests
- async job manager tests
- export format tests
- BOM replacement workflow tests
- UI smoke tests where practical
- malformed file tests
- edge-case regression tests

Test cases must include:
- different header capitalization
- extra spaces
- underscores and dashes in headers
- missing optional columns
- duplicated URLs
- duplicated part numbers
- quoted commas
- ambiguous mapping
- partial row corruption

======================================================================
18. OBSERVABILITY / LOGGING
======================================================================

Implement structured logging and diagnostics.

Required:
- app log
- provider log
- job log
- import log
- export log
- error log
- redacted request/response summaries
- correlation IDs / job IDs
- optional debug mode

Build a Jobs / Activity panel that shows:
- started time
- finished time
- duration
- status
- row counts
- failures
- retry count
- provider used
- model used

======================================================================
19. DELIVERABLES
======================================================================

Produce output in this order:

1. Executive architecture summary
2. Technology choices with rationale
3. Folder structure
4. Domain model definitions
5. UI information architecture
6. Provider abstraction design
7. CSV normalization strategy
8. Enrichment pipeline design
9. Replacement workflow design
10. Export design
11. Error handling strategy
12. Testing strategy
13. Step-by-step implementation plan
14. Then generate the actual codebase files
15. Then generate tests
16. Then generate sample config and sample data fixtures
17. Then generate run instructions
18. Then generate packaging instructions

======================================================================
20. OUTPUT QUALITY RULES
======================================================================

- No pseudo-code unless explicitly marked as design-only.
- Prefer complete code.
- Prefer explicit types.
- Prefer composable modules.
- Prefer readable production code.
- Avoid overengineering, but do not underspecify critical systems.
- Use docstrings where they add value.
- Add comments only where logic is non-obvious.
- Make the code look like it came from a top-tier professional team.

======================================================================
21. NON-NEGOTIABLE PRODUCT DECISIONS
======================================================================

- Desktop app, not browser-only
- Python-first
- KiCad 9 BOM workflow only
- Modern dark UI
- Async non-blocking architecture
- Robust CSV normalization
- LLM provider abstraction
- Runtime model discovery
- Evidence-based sourcing enrichment
- Replace-in-table workflow
- Enterprise-grade Excel export

======================================================================
22. BUILD NOW
======================================================================

Now begin by:
1. presenting the architecture
2. identifying risks and design tradeoffs
3. proposing the final folder structure
4. then implementing the codebase in phases
5. after each phase, briefly state what was completed and what remains
6. continue until a runnable MVP-plus production-grade foundation exists

Do not stop at design notes.
Do not stop at mockups.
Do not stop at a partial scaffold.

Build the system.
```

## 2) Memory-efficient checkpoint prompt

```text
ADDITIONAL EXECUTION DIRECTIVE: COMPACT MEMORY, CHECKPOINTS, AND HANDOFFS

You must maintain a compact, durable PROJECT MEMORY during the build.

GOAL:
Preserve only implementation-critical context while minimizing token use.

RULES:

1. Keep memory short, structured, and cumulative.
Use fixed sections only:
- Objective
- Current Phase
- Done
- Next
- Decisions
- Risks
- Blockers
- Open Questions
- Active Files
- Resume Point

2. Hard memory limits:
- Total memory target: <= 250-400 words
- Each section: 1-5 bullets max
- Each bullet: one line, compact wording
- Prefer fragments over prose
- No repetition
- No motivational text
- No long explanations

3. Only store durable information:
Keep:
- hard requirements
- architectural decisions
- file/module ownership
- unresolved bugs
- active risks
- provider/API constraints
- next exact actions
Discard:
- redundant reasoning
- obsolete alternatives
- verbose summaries
- already-implemented low-risk details
- conversational filler

4. Use 3 memory layers:

A. LONG-TERM MEMORY
Store only stable facts:
- product scope
- architecture choices
- key constraints
- accepted tradeoffs
- required outputs

B. WORKING MEMORY
Store only current execution state:
- active task
- files being edited
- current dependency chain
- immediate next steps

C. HANDOFF MEMORY
Store only what another agent needs to resume:
- what is done
- what remains
- where to continue
- known issues
- validation status

5. Compress aggressively after each major phase:
- merge duplicates
- remove stale items
- collapse completed low-risk details
- keep only facts that affect future correctness
- rewrite verbose bullets into dense engineering shorthand

6. Mandatory checkpoints:
Create a checkpoint at:
- architecture
- data model
- CSV ingestion
- provider integration
- UI shell
- enrichment pipeline
- replacement workflow
- export
- tests
- packaging

7. Each checkpoint must contain only:
- Name
- Done
- Decisions
- Risks
- Validation
- Next
Limit checkpoint summary to <= 120 words.

8. Decision log:
Only record non-trivial decisions.
Format:
- Decision
- Why
- Impact
Maximum 1-2 lines per decision.

9. Subagent handoff format:
Each subagent returns only:
- Scope
- Output
- Dependencies
- Risks
- Next Handoff
Maximum 80-120 words.

10. Before each new phase:
Restate only:
- relevant constraints
- prior decisions that matter now
- exact next task
Maximum 80 words.

11. End every major phase with:
- Updated Long-Term Memory
- Updated Working Memory
- Updated Handoff Memory
- Decision Log delta
- Exact Resume Point

12. Never allow memory to bloat.
When memory grows, compress instead of append.
Prefer:
- canonical bullets
- IDs
- filenames
- short labels
- status tags like [done], [risk], [blocked], [next]

Use memory as an engineering control surface, not as narration.
```

## 3) Code review and quality-gate prompt

```text
ADDITIONAL EXECUTION DIRECTIVE: CODE REVIEW GATES AND QUALITY SIGNOFF

You must enforce formal quality gates throughout the build.

1. No phase is complete until it passes a QUALITY GATE.

2. For each major phase, perform:
- architecture review
- correctness review
- async/non-blocking review
- typing review
- error-handling review
- security/privacy review
- test coverage review
- UX consistency review
- maintainability review

3. At each quality gate, output only:
- Scope Reviewed
- Pass/Fail
- Critical Issues
- Non-Critical Issues
- Required Fixes
- Validation Performed
- Signoff Status

4. Severity rules:
- Blocker: must fix before proceeding
- Major: fix before phase signoff
- Minor: can defer if logged
- Nice-to-have: optional

5. Minimum gate criteria:
- no secret leakage
- no UI-blocking network work
- async paths use proper cancellation/timeouts
- provider logic separated from UI
- imports, models, and services are coherent
- failures are surfaced clearly
- tests exist for critical paths
- exported XLSX matches required schema exactly
- CSV normalization handles header variance robustly

6. Required review lenses:
- Staff Engineer review
- Security review
- QA review
- UX review
- Maintainability review

7. For every failed gate:
- identify root cause
- specify exact fix
- re-run validation
- do not mark complete until passing

8. At the end of the project, run FINAL SIGNOFF with:
- architecture status
- core workflow status
- provider integration status
- export validation status
- test status
- packaging status
- known limitations
- production readiness verdict

9. Final verdict values:
- Ready
- Ready with noted limitations
- Not ready

10. Be strict.
Do not self-approve weak code, incomplete flows, or untested critical behavior.
```

