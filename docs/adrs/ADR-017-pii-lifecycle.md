# ADR-017: PII Data Lifecycle / Deletion Propagation

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §131, §172

## Problem
PII exists in multiple stores (DB, outbox, event log, audit, logs, n8n, search index, vector store, analytics, object storage, backups). Deleting a customer only touched the primary DB.

## Decision
A Data Classification Map and Deletion Propagation Policy cover every store. Customer deletion triggers: primary records -> search index -> vector chunks -> analytics -> memory -> n8n retained data -> other derived stores.

## Alternatives
- Soft-delete only (rejected: derived stores still contain PII)
- Full DB wipe (rejected: §164 tenant-scoped restore)

## Rationale
Privacy compliance requires complete deletion across all derived data stores. Backups have separate retention.

## Consequences
- DeletionJob orchestrates the full propagation chain
- Each derived store must implement a deletion hook
- Backups expire on their own retention schedule
