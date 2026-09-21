# ADR-045: AI Evaluation & Rollout

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §169

## Problem
AI agent/prompt changes were deployed directly to production without evaluation, risking quality regressions.

## Decision
Pipeline: Prompt/Agent Version -> Evaluation Dataset -> Offline Evaluation -> Safety/Policy Checks -> Regression Comparison -> Approve -> Canary (5% -> 25% -> 50% -> 100%) -> Production -> Monitor -> Rollback if needed. Canary ramp uses CANARY_METRIC_THRESHOLD; rollback is automated.

## Alternatives
- Direct production deploy (rejected: quality regression risk)
- A/B test only (rejected: canary is safer for AI)

## Rationale
§169: "Production rollout requires evaluation, observability, and rollback."

## Consequences
- The evaluation pipeline is a gate before production
- Rollback is automatic if canary metrics drop below threshold
