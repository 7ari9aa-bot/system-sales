# ADR-035: Knowledge Visibility

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §157

## Problem
Knowledge chunks were retrieved without checking whether the requesting agent/user was allowed to see them. Internal-only documents could leak to customer-facing AI responses.

## Decision
Every KnowledgeDocument/Chunk has a visibility field: CUSTOMER_FACING, STAFF_ONLY, INTERNAL, ADMIN_ONLY. Retrieval pipeline: retrieve candidates -> tenant filter -> permission filter -> visibility filter -> agent policy filter -> context.

## Alternatives
- No visibility (rejected: information leakage)
- Post-retrieval filtering only (rejected: wastes retrieval budget)

## Rationale
§157: "Not enough to put permissions and then inject chunks into context."

## Consequences
- Indexing includes visibility metadata
- Agent type (customer-facing vs staff) determines which chunks are eligible
