# ADR-031: Provider Event Ordering

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §130

## Problem
Provider events (delivery status, read receipts) can arrive out of order. A READ event might arrive before SENT due to provider batching or network delays.

## Decision
Store out-of-order events and reconcile using provider_timestamp + provider_event_id + state transition rules. Do not rely on received_at alone.

## Alternatives
- Ignore out-of-order events (rejected: loses information)
- Sort by received_at (rejected: incorrect ordering)

## Rationale
§130: "Provider events can arrive late/out of order."

## Consequences
- The reconciliation worker processes out-of-order events
- State transitions follow a strict state machine
