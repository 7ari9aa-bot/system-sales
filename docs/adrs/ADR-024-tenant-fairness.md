# ADR-024: Tenant Fairness / Queue Governance

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §144

## Problem
A large campaign from Tenant A could monopolize worker capacity, starving Tenant B's customer messages (noisy neighbor).

## Decision
Each tenant has concurrency, queue, rate, AI, and campaign throughput budgets. Priority: Human Response > AI Response > Critical System > Customer Webhooks > Normal Automation > Bulk/Campaign.

## Alternatives
- Equal sharing (rejected: human responses must always be fast)
- Per-tenant isolation (rejected: too expensive at scale)

## Rationale
§144: "Campaign from Tenant A must not starve Tenant B."

## Consequences
- The fairness module enforces budgets at the queue/consumer level
- Bulk work is throttled; human-facing work is prioritized
