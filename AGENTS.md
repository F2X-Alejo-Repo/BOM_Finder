# AI Team Entry Point for Codex and Other Agentic Tools

This repository uses a shared AI operating system stored in `/.ai`.

Read these files in order before starting substantial work:

1. `/.ai/README.md`
2. `/.ai/operating-model.md`
3. `/.ai/delivery-workflow.md`
4. `/.ai/agent-roster.md`

Then choose the most relevant specialist file under `/.ai/agents/`.

## Primary rule

All tools should behave as one enterprise delivery team, not as isolated assistants. Prefer reusing the same vocabulary, workflow, handoff artifacts, and quality bar across Codex, Claude Code, and GitHub Copilot.

## Current repository state

- Product context is still incomplete.
- The current known description is: "AI BOM Finder for PCB making."
- Until more context is added, optimize for discovery, low-risk scaffolding, and explicit assumptions.

## Cross-tool behavior contract

- Use `/.ai` as the source of truth.
- Keep plans, assumptions, and tradeoffs explicit.
- Favor small, reviewable changes.
- Treat security, testing, observability, and documentation as first-class work.
- For larger features, produce or update the relevant architecture, workflow, and handoff notes.

## If the task is ambiguous

- Default to the Orchestrator agent in `/.ai/agents/orchestrator.md`.
- Route work through the appropriate specialist agents.
- Record assumptions in the final response or changed docs.
