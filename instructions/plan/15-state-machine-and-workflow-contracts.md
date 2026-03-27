# 15 - State Machine and Workflow Contracts

## Purpose

Unify row and job lifecycle behavior across import, enrichment, review, and export.
This document is the single state contract for UI, application, and persistence.

## Row State Model

Allowed states:
- `imported`
- `pending`
- `queued`
- `enriching`
- `enriched`
- `warning`
- `failed`
- `cancelled`
- `skipped_by_user`
- `user_reviewed`

## Row Transition Rules

| From | To | Trigger |
|---|---|---|
| imported | pending | row accepted for processing |
| pending | queued | job queued |
| queued | enriching | worker starts row |
| enriching | enriched | enrichment success |
| enriching | warning | partial success or low-confidence critical field |
| enriching | failed | hard failure or policy rejection |
| pending/queued/enriching | cancelled | user cancellation |
| pending/queued | skipped_by_user | manual approval denied |
| warning/failed/enriched | user_reviewed | reviewer marks complete |
| failed/warning/cancelled | pending | retry action |

Invalid transitions must raise domain errors and be logged.

## Job State Model

Allowed states:
- `pending`
- `queued`
- `running`
- `paused`
- `completed`
- `completed_with_errors`
- `failed`
- `cancelled`

## Job Transition Rules

| From | To | Trigger |
|---|---|---|
| pending | queued | submit job |
| queued | running | scheduler starts job |
| running | paused | user pause |
| paused | running | user resume |
| running | completed | all rows successful |
| running | completed_with_errors | at least one row failed/warned and job ended |
| running/queued/paused | cancelled | user cancellation |
| running/queued | failed | unrecoverable systemic failure |

## Workflow Ownership

- UI owns user intents only.
- Application layer owns transitions and policy checks.
- Repository persists every transition with timestamp and reason.

## Required Event Contract

Events must include:
- `entity_type` (`row` or `job`)
- `entity_id`
- `previous_state`
- `next_state`
- `reason_code`
- `correlation_id`
- `timestamp`

## Invariants

- No row can be `enriched` without at least one evidence record.
- No job can be `completed` if failed row count > 0.
- `completed_with_errors` must expose failed row IDs.
- Any manual approval denial must map to `skipped_by_user`.

## Gate Criteria

- State transition unit tests pass
- Cross-page workflow tests pass
- Invalid transitions are rejected and observable
