# ADR-023: High-Volume Identity & Dedupe Strategy

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §142

## Problem
Messages table is high-volume and potentially partitioned by time. A unique constraint on (tenant_id, channel_account_id, external_message_id) tied to the partition key is fragile.

## Decision
A dedicated `InboundMessageDedupe` table with unique constraint on (tenant_id, channel_account_id, external_message_id). This separates dedupe from retention/partition lifecycle.

## Alternatives
- Rely on message table unique constraint (rejected: partition key interference)
- Redis SET for dedupe (rejected: not durable, §10)

## Rationale
§142: "This separates dedupe from retention/partition lifecycle."

## Consequences
- Dedupe table can be cleaned independently of message retention
- UUIDv7 used for time-sortable IDs on high-volume tables
