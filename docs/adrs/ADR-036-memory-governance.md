# ADR-036: AI Memory Governance

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §158

## Problem
AI was writing customer memory freely, blurring the line between "customer said X" and "system verified X". Memory could contain hallucinations stated as fact.

## Decision
Memory write policy determines: allowed memory types, source, verification level, confidence, retention. Clear distinction between "customer said X" and "system verified X". Staff can review, edit, delete, invalidate memory.

## Alternatives
- Free-form memory (rejected: no governance, hallucination risk)
- No persistent memory (rejected: poor AI quality)

## Rationale
§158: "AI does not write customer memory freely."

## Consequences
- Each memory claim has source, actor, created_at, verified_at, confidence
- Unverified memory is marked as such in the AI context
