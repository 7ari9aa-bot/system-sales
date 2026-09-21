# ADR-044: SLO / Alerting

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §168

## Problem
Operations relied on metrics without targets. Without SLOs, there was no way to know if the system was healthy or if alerts should fire.

## Decision
SLO catalog: API availability, webhook processing latency, outbox lag, queue depth, DLQ size, AI fallback rate, AI failure rate, realtime disconnect rate, provider error rate, search latency, job failure rate. Each SLO has warning threshold, critical threshold, alert destination, owner, runbook.

## Alternatives
- Ad-hoc alerts (rejected: no systematic coverage)
- External monitoring only (rejected: needs domain-specific SLOs)

## Rationale
§168: "The framework itself must exist from the beginning."

## Consequences
- SLO violations trigger alerts to the assigned owner
- Runbooks are linked for each SLO
