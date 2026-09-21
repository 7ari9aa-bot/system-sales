# ADR-021: Cross-Module Read Architecture

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §137

## Problem
"No cross-module repository access" (§8) was clear, but the Inbox needs data from Conversation + Customer + Last Message + Assignment. Without a read layer, modules either duplicated queries or broke the boundary.

## Decision
A dedicated Read/Query Layer reads from public read contracts, read models, approved DB views, and analytics models. InboxQuery joins across modules at the query layer, not via cross-module repository calls.

## Alternatives
- Materialized views only (rejected: hard to keep fresh)
- GraphQl federation (rejected: overkill for a modular monolith)

## Rationale
§137: "Mutation response returns canonical result directly. Read model updates asynchronously."

## Consequences
- Read models are eventually consistent (§137)
- Critical read-after-write uses authoritative read or local cache reconciliation
