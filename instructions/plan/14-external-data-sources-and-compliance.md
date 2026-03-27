# 14 - External Data Sources and Compliance

## Purpose

Define authoritative external sources, legal constraints, and safety controls for retrieval.
No enrichment execution is allowed without this contract.

## Approved Source Policy

Only explicitly approved sources may be queried.
Default deny for all other domains.

## Source Registry (Initial)

| Source | Domain(s) | Access Method | Allowed Data | Notes |
|---|---|---|---|---|
| JLCPCB/LCSC listing pages | `jlcpcb.com`, `lcsc.com` | HTTP GET with parser | stock, lifecycle text, links, part metadata | subject to ToS review |
| Provider APIs (LLM) | provider endpoints | official SDK/API | synthesis only, no source-of-truth facts | governed by privacy mode |

Any source addition requires update to this table and legal approval note.

## Legal and Policy Requirements

- Respect robots and terms where applicable.
- Add explicit legal decision for each non-API source.
- Keep an audit field indicating source, retrieval time, and parser version.

## Retrieval Safety Controls

1. Host allowlist
- Permit requests only to approved domains.

2. SSRF guardrails
- Block localhost, private subnets, link-local, and file schemes.
- Reject redirects to disallowed hosts.

3. Request budgets
- Enforce per-host concurrency caps and per-job request caps.
- Enforce timeout and retry ceilings.

4. Caching
- Cache by normalized key and parser version.
- Include TTL per source type.

5. Parsing
- Parser outputs observed facts only.
- Any uncertainty must be explicit in parser result.

## Fallback Strategy

- If source unavailable: mark row as warning/failed with reason code.
- Do not fabricate values.
- Permit retry with exponential backoff within configured budget.

## Mandatory Evidence Fields

- `source_name`
- `source_url`
- `retrieved_at`
- `parser_version`
- `evidence_type` (`observed`, `inferred`, `estimated`, `unknown`)

## Compliance Gate (Must Pass)

- Source domain in allowlist
- Legal note present for source
- Retrieval policy tests passing
- SSRF tests passing
- Provenance fields present in persisted evidence
