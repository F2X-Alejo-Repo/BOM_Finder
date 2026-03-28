---
description: "Use when choosing among the workspace custom agents, routing a task to the right specialist, deciding whether to invoke subagents, or sequencing multi-step delivery across product, architecture, implementation, QA, security, operations, and docs."
---
# Agent Routing

- Start with Enterprise Orchestrator for ambiguous, cross-functional, or multi-step tasks.
- Use Product Strategist when the user asks for outcomes, scope, priorities, acceptance criteria, or thin-slice planning.
- Use Domain Process Analyst when workflow rules, business taxonomy, compliance rules, or supply-chain logic need clarification.
- Use Solution Architect for boundaries, interfaces, ADRs, and major technical tradeoffs.
- Use Backend Services Lead for Python application logic, APIs, workflows, jobs, persistence, and backend tests.
- Use Frontend Experience Lead for user flows, UI behavior, state handling, responsiveness, and accessibility.
- Use Data AI Lead for ingestion, retrieval, ranking, prompts, evaluation, and AI workflow safety.
- Use Platform SRE Lead for CI/CD, runtime reliability, logging, metrics, traces, alerts, and runbooks.
- Use Security Compliance Lead for auth, secrets, privacy, third-party risk, and AI risk review.
- Use Quality Engineering Lead for regression analysis, test strategy, resilience, and release confidence.
- Use Release Manager for rollout, rollback, environment coordination, and launch sequencing.
- Use Technical Writer Enablement Lead for durable docs, runbooks, release notes, and handoff artifacts.
- Use Context Curator before expensive reasoning when the task mostly needs targeted repository context.
- Use Repo Cartographer when the main problem is locating code ownership, entry points, or test coverage.

## Routing Principles

- Prefer one lead agent and only the reviewers needed for the current risk.
- Pull security and quality by default for medium and large changes.
- Avoid switching agents just to repeat context. Hand off a compressed packet instead.
