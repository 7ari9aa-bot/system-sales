# ADR-029: Durable Event Log vs Outbox

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §152

## Problem
The Outbox was being used as both a publication buffer and a permanent event archive. Cleaning the outbox after publication meant losing replay capability.

## Decision
Separate the two: Outbox is a temporary reliable publication buffer. EventLog is an append-only durable event history. Both are written in the same transaction. Outbox is cleaned after publication; EventLog is retained for replay.

## Alternatives
- Outbox only with long retention (rejected: table bloat)
- EventLog only without outbox (rejected: no reliable publication mechanism)

## Rationale
§152: "Outbox is not the permanent event archive. EventLog is durable replay history."

## Consequences
- Replays source from EventLog, not Outbox
- Outbox can be aggressively trimmed
