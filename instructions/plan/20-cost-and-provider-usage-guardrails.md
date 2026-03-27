# 20 - Cost and Provider Usage Guardrails

## Purpose

Control token spend, provider usage, and retry behavior so enrichment remains predictable and sustainable.

## Budget Model

- Define monthly budget per environment/workspace.
- Define per-job and per-row token/cost caps.
- Define emergency stop thresholds.

## Hard and Soft Limits

### Hard limits (must enforce)

- max tokens per request
- max requests per row
- max retries per row
- max total tokens per job
- max concurrent provider calls

### Soft limits (warn and require approval)

- projected job spend above threshold
- daily spend above planned envelope
- unusual token spike per row

## Preflight Cost Estimation

Before starting enrichment:
- estimate token usage from row count and selected mode
- show user projected range
- require confirmation if above soft limit

## Circuit Breakers

Trip circuit and pause job when:
- provider returns sustained 429/5xx beyond retry budget
- observed spend exceeds hard budget cap
- policy violation detected

## Usage Logging Contract

Track per call:
- provider
- model
- prompt_version
- input_tokens
- output_tokens
- estimated_cost
- retry_attempt
- job_id and row_id

## Recovery Policy

- paused-by-budget jobs require explicit user/admin approval to continue
- failed-by-budget rows remain retryable after limit adjustment

## Gate Criteria

- Budget limits enforced in integration tests
- Cost projection visible in UI and logged
- Circuit breaker behavior validated
