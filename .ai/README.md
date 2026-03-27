# AI Operating System

This folder defines a shared operating model for AI-assisted development in this repository.

The goal is to let Codex, Claude Code, and GitHub Copilot collaborate with the same team structure, delivery standards, and handoff language.

## Start here

Read in this order:

1. `operating-model.md`
2. `delivery-workflow.md`
3. `agent-roster.md`
4. The most relevant file in `agents/`

## Design goals

- One shared source of truth across AI tools
- Enterprise-grade delivery discipline
- Clear ownership and handoffs
- Strong defaults for security, quality, and observability
- Easy adaptation once the product context is better defined

## Current assumptions

- The repo is early-stage and mostly empty.
- The only current product signal is: AI BOM Finder for PCB making.
- The first priority is setting a durable operating foundation.

## Recommended usage pattern

- Use the Orchestrator to classify the task.
- Pull in one lead specialist and only the subagents needed for the task.
- Keep artifacts lightweight at first, then deepen them as the product matures.
- Update these docs when the product scope, architecture, or delivery model becomes clearer.
