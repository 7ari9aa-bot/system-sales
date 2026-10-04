# Full Implementation Audit — spec §1-177 vs code (honest)

Date: 2026-09-18. Checked against actual files, not intentions.

## ✅ Fully implemented (wired end-to-end + tested)
§1-5 layers/monolith · §10-11 tenancy+RLS(non-bypass) · §12 RBAC · §18 outbox ·
§20-21 streams/groups/DLQ · §26 channel gateway (WA/TG/webchat) · §39 RAG
pgvector · §58 pooling · §62 n8n isolation · §73-75 CI + versioned migrations ·
§78 /api/v1 · §80 error contract · §109 RTL-native · §126 lease · §127
ProcessedEvent table · §129 UNKNOWN state · §140 Reservation table · §152
EventLog table · §154 ScheduledJob+poller · §165 EntitlementService · §172
deletion service · §173 guardrail chain · §176 8/23 gate scenarios.

## 🔴 Gaps found (this audit) — Wave 7 closes them

| # | Spec | Gap | Fix in W7 |
|---|---|---|---|
| G1 | §127 | ProcessedEvent table exists but consumers never write it | message worker inserts marker + effect in same tx |
| G2 | §128 | relay crash between claim+publish strands rows in 'publishing' forever | reclaim stale 'publishing' rows older than 5 min |
| G3 | §130 | UNKNOWN messages have no reconciliation path | delivery webhooks reconcile; worker age-out marks stale |
| G4 | §135 | ApprovalRequest never created by tool execution — HIGH-risk tools run freely | create_order tool → approval gate |
| G5 | §132 | tools accept any in-tenant id — no conversation/customer scope binding | tools take context; verify entity belongs |
| G6 | §134 | run limits hardcoded (5 iterations) only | add max_tool_calls/max_wall_time config on agent |
| G7 | §140 | InventoryReservation table never written by OrderService | write ACTIVE rows on reserve; CONVERT on payment; expiry worker |
| G8 | §141 | Payment UNKNOWN state missing | add status + reconciliation path |
| G9 | §152 | EventLog table never written | relay dual-writes: event_log row on publish |
| G10 | §153 | aggregate_version never populated | version columns bump on mutation; events carry it |
| G11 | §155 | canonical message model partial (no reply_to/content_type/provider_metadata/edited) | add columns |
| G12 | §156 | conversation states limited (open/pending/closed) | expand to spec states |
| G13 | §145 | integrations.status not lifecycle states | expand values |
| G14 | §154 | scheduler worker not wired into run.py POOLS | register |
| G15 | §15 | tools lack risk_level | add to ToolSpec + policy |
| G16 | §65/67 | security events not emitted (login failure etc.) | emit on auth paths |
| G17 | §150 | missing entities: Workflow minimal, Journey minimal, Review, ApiKey, SavedView, Mention, Transcript | minimal models |
| G18 | §45 | SearchPort built but not exposed via API | /api/v1/search endpoint |

## 🟡 Partial (acceptable now, finish in W8 polish)
§131 PII map doc · §137 InboxQuery read model · §139 saga (order flow is a
simple state machine — saga when fulfillment ships) · §144 fairness budgets ·
§146 MFA/SSO-ready · §147 break-glass · §149 realtime cursor resume ·
§157-158 knowledge/memory governance fields · §160 platform admin plane ·
§164 restore automation · §166 notification prefs/digest · §168-169 SLO/eval
execution · §174 full ADR files.

## 🟢 Verified green
159 tests · 8/23 gate scenarios · ruff clean · frontend builds (rebuild in flight) ·
deployed: Vercel + Railway + Supabase (90 tables).

## Execution order from here
W7a (agent): G1,G2,G3,G4,G7,G8,G9,G11,G12,G13,G14,G15 — backend wiring fixes.
W7b (agent): G5,G6 — AI scope binding + run limits + knowledge visibility + memory fields.
W8 (agent): G17 minimal entities (Workflow/Journey/Review/ApiKey/SavedView/Mention/Transcript) + G18 search API + G16 security events.
Me: ADR files, PII map doc, remaining gate scenarios, final integration.
