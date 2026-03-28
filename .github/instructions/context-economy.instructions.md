---
description: "Use when planning, exploring, implementing, or reviewing complex work and you want to minimize token usage without losing robustness. Covers compressed handoffs, minimal context gathering, and memory-efficient task execution."
---
# Context Economy

- Prefer targeted search over broad file reads.
- Read the smallest code slice that can support the next decision.
- Reuse prior findings instead of re-reading the same files.
- Use Context Curator or Repo Cartographer before escalating to stronger agents when the task is mostly discovery.
- Keep handoffs to objective, scope, constraints, assumptions, risks, target files, and next action.
- Do not dump large plans unless the user asked for depth.
- Prefer a single recommended path plus explicit assumptions over many speculative options.
- When reviewing, list only actionable findings and the residual risk.
- When implementing, keep change sets thin so future context stays small.

## Compact Handoff Template

- Objective
- Scope
- Constraints
- Assumptions
- Relevant files
- Risks
- Next action

Target 120 to 220 tokens for internal handoffs unless the task genuinely requires more.