# 19 - SLOs, Observability, and Incident Runbooks

## Purpose

Define operational targets, telemetry, and response playbooks for enterprise supportability.

## Core SLIs and SLOs

| Area | SLI | SLO Target |
|---|---|---|
| App startup | time to interactive | p95 <= 8s |
| CSV import | import completion success rate | >= 99% |
| Enrichment | row enrichment success rate (excluding source outages) | >= 97% |
| Export | successful export completion rate | >= 99.5% |
| Job execution | stuck job rate (>10m no progress) | <= 1% |

## Mandatory Telemetry

- Structured logs with correlation IDs
- Job lifecycle metrics: queued, running, completed, failed, cancelled
- Per-provider call metrics: latency, retry count, timeout count
- Row-level outcome counters by state
- Export validation counters

## Alert Thresholds

- Provider timeout rate > 10% for 15 minutes
- Enrichment failure rate > 5% in active jobs
- Stuck job count >= 3
- Export failure rate > 2% over 1 hour

## Diagnostics Bundle

Bundle must include:
- redacted logs
- config snapshot (without secrets)
- environment and app version
- migration version
- recent job summaries

## Incident Severity Model

- Sev1: data integrity or security/privacy breach
- Sev2: core workflow unavailable for majority of users
- Sev3: degraded behavior with workaround

## Runbook Minimum Set

1. Provider outage
2. Corrupted local DB
3. Stuck/failed job recovery
4. Export failure diagnostics
5. Secret storage access failure

## Post-Incident Requirements

- Timeline
- Impact summary
- Root cause
- Corrective and preventive actions
- Owner and due date

## Gate Criteria

- SLI/SLO dashboards defined
- Alert tests or simulations performed
- Runbook dry-run completed for top three incidents
