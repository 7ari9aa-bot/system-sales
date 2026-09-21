# ADR-014: Conversation Serialization & AI Cancellation

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §126

## Problem
Multiple AI/message processors could run concurrently for the same conversation, causing race conditions, stale responses, and inconsistent state.

## Decision
Every conversation has a serialization key (`conversation_id`). Only one state-mutating processor can run at a time, enforced via a conversation lease with fencing/version.

## Alternatives
- Database-level advisory locks (rejected: not portable across all PostgreSQL deployments)
- Redis distributed lock (rejected: Redis is transport, not truth — §10)

## Rationale
A DB-backed lease with fencing token ensures correctness even across retries and crash recovery.

## Consequences
- AI runs that become stale (newer message arrived, human intervened) are marked cancelled
- The lease has an expiry; if a processor crashes, another can claim after expiry
- Conversation ownership state (AI_ACTIVE, HUMAN_ACTIVE, PAUSED, HANDOVER_PENDING, CLOSED) is explicit

## Operational Implications
Monitors must track lease hold time and alert on long-held leases.
