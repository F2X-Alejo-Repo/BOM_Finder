# Delivery Workflow

## Default lifecycle

1. Discover
   - Clarify the business problem, user, constraints, and success metrics.
   - Identify missing product or technical context.
   - Record assumptions.

2. Frame
   - Turn the request into a thin vertical slice.
   - Define acceptance criteria, risks, and non-goals.
   - Choose the lead agent and required subagents.

3. Design
   - Sketch the target architecture and interfaces.
   - Document major tradeoffs.
   - Add security, data, and observability considerations early.

4. Build
   - Implement in small increments.
   - Keep code, tests, and docs moving together.
   - Prefer simple, reversible designs unless scale requirements are known.

5. Verify
   - Run tests and static checks.
   - Perform security and failure-mode review.
   - Validate logs, metrics, and debugging paths.

6. Release
   - Prepare rollout notes.
   - Define rollback or mitigation steps.
   - Capture feature flags, migrations, and dependency concerns.

7. Learn
   - Summarize outcomes, gaps, and follow-ups.
   - Feed insights back into docs, prompts, and architecture notes.

## Agent handoff rules

- Every task should have one lead agent.
- Supporting agents advise, review, or produce scoped deliverables.
- Handoffs should include:
  - objective
  - assumptions
  - constraints
  - open risks
  - expected outputs

## Change sizing

- Small: one concern, one lead agent, direct implementation
- Medium: one lead agent with one to three specialist reviews
- Large: Orchestrator plus a pod of specialists with explicit handoffs

## Default pull request checklist

- What business problem does this solve?
- What assumptions were made?
- What changed in behavior?
- What tests prove it?
- What could fail in production?
- How do we observe and roll it back?

## Definition of done

A task is done when:

- The change meets acceptance criteria.
- Risks were evaluated and documented.
- Tests and checks were run or the gap was stated clearly.
- Operational considerations were addressed.
- Another engineer or AI tool could pick up the thread without guessing.
