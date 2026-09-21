# ADR-015: Event Consumer Idempotency

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §127

## Problem
"Consumers must be idempotent" is a requirement, not an implementation. Without a concrete mechanism, duplicate events cause duplicate side effects.

## Decision
Use a `processed_events` inbox table with a unique constraint on `(consumer_name, event_id)`. The processing marker and business effect are committed in the same transaction.

## Alternatives
- Redis SETNX dedupe (rejected: Redis is not the database — §10)
- Application-level dedupe set (rejected: not durable across restarts)

## Rationale
Same-transaction dedupe guarantees that if the business effect happened, the marker exists, and vice versa.

## Consequences
- Each consumer must check and insert into `processed_events` before applying its effect
- The table grows; retention policy periodically cleans old entries
