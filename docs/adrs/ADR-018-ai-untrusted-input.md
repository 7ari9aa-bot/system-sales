# ADR-018: AI Untrusted Input & Tool Scope Security

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §132

## Problem
AI input from customers, messages, attachments, transcripts, knowledge documents, and tool results is untrusted. Without separation, prompt injection could modify system instructions or escalate tool scope.

## Decision
Strict separation between SYSTEM/POLICY instructions and UNTRUSTED CONTEXT. Tool argument binding is server-side: `get_order(order_id)` verifies the order belongs to the allowed customer/conversation/tenant scope.

## Alternatives
- Trust AI output (rejected: prompt injection risk)
- Client-side scope validation (rejected: §12 backend is the final authority)

## Rationale
§132: "AI does not determine authorization scope from prompt."

## Consequences
- Tool implementations must validate ownership/scope server-side
- System prompts are never in the same context as untrusted data
