# ADR-030: Durable Scheduler

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §154

## Problem
Redis Streams was being used as a scheduler for delayed jobs. Redis is transport, not a scheduler — if Redis is flushed, scheduled jobs are lost.

## Decision
A `ScheduledJob` table in PostgreSQL with run_at, status, attempts, next_attempt_at. A scheduler poller claims due jobs via SELECT FOR UPDATE SKIP LOCKED. Supports cancel, reschedule, retry. On execution, re-checks conditions (customer may have replied, consent may have changed).

## Alternatives
- Redis delayed tasks (rejected: §10 Redis is not the database)
- APScheduler (rejected: in-process, not durable across restarts)

## Rationale
§154: "All scheduled work is durable."

## Consequences
- The scheduler_worker polls ScheduledJob on a fixed interval
- Cancelled jobs are skipped even if already due
