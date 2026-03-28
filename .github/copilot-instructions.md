# GitHub Copilot Instructions

This repository uses a shared AI operating system in `/.ai`.

Before generating large changes, review:

1. `/.ai/README.md`
2. `/.ai/operating-model.md`
3. `/.ai/delivery-workflow.md`
4. `/.ai/agent-roster.md`

Then follow the specialist guidance in `/.ai/agents/`.

## Expectations

- Align with the shared enterprise workflow.
- Prefer secure, testable, maintainable solutions.
- Keep outputs compatible with Codex and Claude Code workflows.
- Make assumptions explicit when repository context is incomplete.
- Suggest small, reviewable increments instead of large unstructured rewrites.

## Copilot agent battery

Workspace custom agents are defined in `.github/agents/`.

- Start with `Enterprise Orchestrator` for ambiguous, cross-functional, or multi-step work.
- Use the specialist agents for focused execution, review, release, and documentation tasks.
- Use `Context Curator` or `Repo Cartographer` before stronger specialists when the main need is discovery or context compression.

## Context budget

- Keep active context intentionally small.
- Prefer targeted search and narrow reads over broad file loading.
- Use compact handoffs with objective, scope, constraints, assumptions, risks, relevant files, and next action.
- Avoid repeating repository background that is already captured in `.ai/` or earlier handoffs.
