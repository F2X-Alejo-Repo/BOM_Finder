# Agent Roster

This is the default enterprise-grade AI team for this repository.

Detailed operating guidance is grouped into the specialist files under `/.ai/agents/`.
Some related leads share a file so the system stays compact and easy to maintain.

## Executive layer

### 1. Orchestrator

- Owns task intake, routing, sequencing, and final coherence
- Activates the smallest set of specialists needed
- Prevents overlapping or contradictory work

## Product and business layer

### 2. Product Strategist

- Converts requests into business outcomes, scope, and measurable value
- Owns acceptance criteria and prioritization logic

Subagents:

- Business Analyst
- User Journey Mapper
- KPI and Success Metrics Analyst

### 3. Domain and Process Analyst

- Models the target business workflow and domain language
- Identifies regulatory, supply chain, or operational constraints

Subagents:

- Domain Taxonomy Curator
- Process Mapper
- Rules and Policy Analyst

## Architecture and platform layer

### 4. Solution Architect

- Owns system boundaries, interfaces, major tradeoffs, and ADRs

Subagents:

- API Designer
- Integration Architect
- Data Contract Reviewer

### 5. Platform and SRE Lead

- Owns environments, CI/CD, reliability, and observability

Subagents:

- Infrastructure Engineer
- Observability Engineer
- Incident and Runbook Engineer

## Engineering layer

### 6. Backend and Services Lead

- Owns service logic, APIs, jobs, and backend quality

Subagents:

- API Engineer
- Workflow and Automation Engineer
- Persistence and Performance Engineer

### 7. Frontend and Experience Lead

- Owns UX implementation, accessibility, and client behavior

Subagents:

- UI Engineer
- Accessibility Specialist
- Design System Steward

### 8. Data and AI Lead

- Owns data pipelines, retrieval, model workflows, and evaluation quality

Subagents:

- Data Engineer
- ML and Prompt Engineer
- Evaluation and Grounding Specialist

## Risk and quality layer

### 9. Security and Compliance Lead

- Owns threat modeling, secure defaults, secrets, and compliance controls

Subagents:

- Application Security Engineer
- Supply Chain Security Analyst
- Privacy and Compliance Analyst

### 10. Quality Engineering Lead

- Owns test strategy, failure analysis, and release confidence

Subagents:

- Test Automation Engineer
- Exploratory QA Analyst
- Performance and Resilience Tester

## Delivery enablement layer

### 11. Release Manager

- Owns rollout readiness, release notes, and operational coordination

Subagents:

- Change Manager
- Environment Coordinator
- Rollback Planner

### 12. Technical Writer and Enablement Lead

- Owns docs, onboarding, operational guides, and knowledge continuity

Subagents:

- Developer Documentation Writer
- User Documentation Writer
- Runbook Editor

## Default pod compositions

### Feature pod

- Product Strategist
- Solution Architect
- Relevant implementation lead
- Quality Engineering Lead

### AI feature pod

- Product Strategist
- Solution Architect
- Data and AI Lead
- Security and Compliance Lead
- Quality Engineering Lead

### Platform pod

- Solution Architect
- Platform and SRE Lead
- Security and Compliance Lead
- Release Manager

## Routing guidance

- Start with Orchestrator for multi-step or ambiguous tasks.
- Start with Product Strategist for unclear user value or scope.
- Start with Solution Architect for new system design.
- Start with Backend, Frontend, or Data and AI leads for direct implementation work.
- Pull Security and Quality in by default for medium and large changes.
