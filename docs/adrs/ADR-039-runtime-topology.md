# ADR-039: Runtime Topology / Redis Failure

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §162-163

## Problem
If Redis goes down, the system must continue to function for synchronous operations. Events must not be lost.

## Decision
API instances are stateless. Realtime state is externalized. Redis persistence is enabled but Redis failure does not mean data loss — Outbox/EventLog/DB are the recovery source. On Redis recovery, Outbox Relay republishes pending events, consumers dedupe and continue.

## Alternatives
- Redis as primary (rejected: §10 Redis is not the database)
- No Redis (rejected: need a stream transport)

## Rationale
§163: "Redis failure != data loss."

## Consequences
- Redis outage test is in the pre-production gate (§176)
- The Outbox accumulates events during Redis downtime
