# Enterprise Operating Model

## Mission

Build this product with the discipline of a top-tier enterprise team while keeping startup speed where possible.

## Core principles

1. Business outcomes first. Every change should connect to user value, operational value, risk reduction, or learning.
2. Thin slices over big-bang delivery. Prefer small increments that can be validated quickly.
3. Architecture with intent. Use explicit boundaries, documented decisions, and reversible choices when uncertainty is high.
4. Security by default. Identity, access, secrets, dependencies, and supply chain risks are part of normal engineering.
5. Quality is designed in. Testing, monitoring, and documentation are part of the feature, not follow-up work.
6. Observable systems win. Logs, metrics, traces, dashboards, alerts, and operational runbooks matter from the start.
7. AI features require governance. Prompts, model choices, evaluations, grounding sources, and failure modes must be explicit.
8. Shared context beats heroics. Decisions should be documented so any of the supported AI tools can continue the work.

## Non-negotiable engineering standards

- Use clear acceptance criteria before implementation.
- Prefer short-lived branches or tightly scoped change sets.
- Keep architecture decisions in lightweight ADR style notes when a choice has lasting impact.
- Require test coverage proportional to risk.
- Treat dependency health, code scanning, and secret handling as standard practice.
- Design for rollback and safe release.
- Capture assumptions whenever domain knowledge is missing.

## Standard artifacts

For important work, the team should leave behind some or all of these artifacts:

- Problem statement
- Scope and non-goals
- Acceptance criteria
- Architecture notes or ADR
- Threats and controls
- Test strategy
- Observability notes
- Release and rollback notes
- Follow-up backlog

## Enterprise quality gates

No change is considered complete until it is:

- Functionally correct
- Reviewed for security and privacy impact
- Tested at the right level
- Observable in production or staging as appropriate
- Documented enough for another engineer or AI tool to continue

## AI-specific controls

For any AI-assisted or model-driven feature:

- Define the model purpose and failure modes.
- Prefer grounded outputs over free-form generation when accuracy matters.
- Maintain evaluation examples for core user journeys.
- Track prompt and workflow changes like code.
- Redact or isolate sensitive data.
- Add fallback behavior for low-confidence outcomes.
