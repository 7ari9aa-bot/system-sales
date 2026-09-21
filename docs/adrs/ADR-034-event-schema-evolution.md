# ADR-034: Event Schema Evolution

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §153

## Problem
Event payloads evolve over time. Consumers that were written for an old schema break when the payload changes.

## Decision
Every event has schema_version and aggregate_version. Backward-compatible changes are allowed. Breaking changes require a new schema version. Consumer-driven contract tests and producer contract tests verify compatibility. Old events remain consumable via versioned consumer/adapter.

## Alternatives
- No versioning (rejected: breaks consumers)
- Proto/AVRO with schema registry (rejected: too heavy for current scale)

## Rationale
§153: "Old event must remain consumable via versioned consumer/adapter."

## Consequences
- Event schema documentation is maintained
- Consumer tests cover all schema versions in production
