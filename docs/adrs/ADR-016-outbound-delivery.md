# ADR-016: Outbound Message Delivery State Machine

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §129-130

## Problem
Message delivery was treated as "POST provider -> done", leaving UNKNOWN states (connection interrupted) and out-of-order provider events unhandled.

## Decision
Full delivery state machine: QUEUED -> SENDING -> SENT -> DELIVERED -> READ, with FAILED and UNKNOWN branches. UNKNOWN triggers reconciliation via provider status lookup, not blind retry.

## Alternatives
- Fire-and-forget (rejected: no audit trail, no reconciliation)
- Synchronous confirmation (rejected: provider webhooks are async)

## Rationale
Provider events can arrive late or out of order. State transition rules + provider_event_id + provider_timestamp handle this correctly.

## Consequences
- Each outbound message has an idempotency_key
- Reconciliation worker resolves UNKNOWN states via provider API
- Out-of-order events are stored and reconciled, not discarded
