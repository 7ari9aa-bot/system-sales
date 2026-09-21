# ADR-047: Billing Metering Integration

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §171

## Problem
Provider charges (WhatsApp message categories, voice minutes, AI usage, storage) were not systematically tracked for billing. Usage was calculated at invoice time, missing intermediate usage events.

## Decision
Provider Usage Event -> Usage Meter -> Billing. Usage events: usage_event_id, tenant_id, metric, quantity, unit, occurred_at, source, idempotency_key. Metrics: messages_sent, ai_tokens, ai_requests, storage, automation_runs, campaign_messages, voice_minutes. Billing uses canonical usage events, not UI-calculated values.

## Alternatives
- Calculate at invoice time (rejected: §53 not at issuance only)
- Provider-reported usage only (rejected: no dedupe or audit)

## Rationale
§171: "Billing uses canonical usage events."

## Consequences
- UsageRecord table is the source for billing snapshots
- Idempotency key prevents double-counting
