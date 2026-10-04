# Architecture (Canonical)

This is the in-repo canonical version of the approved blueprint. If a diagram
and this file disagree, this file wins.

## Layers

```
EXPERIENCE  →  APPLICATION  →  DOMAIN  →  DATA  →  INFRASTRUCTURE
```

AI runtimes and channel adapters are actors **above** the Domain — they consume it,
they never define business logic.

## Golden rule

```
PostgreSQL + Domain/Business Rules = SOURCE OF TRUTH
```

LLM, Redis, conversation history, and the frontend do **not** own base truth.

## Component responsibilities

| Component | Responsibility |
|---|---|
| FastAPI Core | Application layer: tenancy, auth, RBAC, all domain APIs, business rule orchestration |
| Domain Layer | The business brain: CreateOrder, Inventory, Payment, Campaign, Attribution services; validation; transactions |
| Channel Gateway | Per-platform details: webhook verification, payload parsing, normalization, media, retries, rate limits, outbound delivery |
| Redis | Cache, rate limits, locks, temp state, idempotency, queues, streams — **never** source of truth |
| Event Bus | `EventBus` interface over Redis Streams; swappable for Kafka/Redpanda later without touching the Domain |
| Outbox | Business transactions commit their events atomically; a relay publishes them after COMMIT |
| Workers | Separate pools: message / AI / notification / integration / analytics / embedding / sync / report |
| AI Platform | Gateway, model router, agents, runtime, tools + tool policies, memory, knowledge, usage & cost |
| Workflow engine | Internal automation runs in FastAPI workers from versioned definitions and durable Postgres events |
| Realtime | Event bus → realtime gateway → WebSocket/SSE → frontend |

## Key flows

**Messaging hot path**

Message → Channel Gateway → verify → normalize → idempotency → **durable write to
Postgres** → Redis Stream → Message Worker → Conversation Core → AI → Domain → DB →
Outbound queue → Channel Gateway → customer.

For WhatsApp, Meta calls `GET` and `POST /api/v1/webhooks/whatsapp` on FastAPI.
The POST route verifies the raw-body signature, persists the delivery, and queues
`webhook.ingest`; the platform worker normalizes it off the request path. Outbound
messages are queued as `message.outbound` and the message worker calls the WhatsApp
Cloud API directly using the tenant's encrypted integration credentials.

Durable ingestion is explicit: the raw inbound message is persisted first; the
stream entry is a trigger. If Redis is lost, we replay from Postgres.

**AI tool call**

```
LLM → tool request → permission → tenant context → policy
    → Application Service → Domain → DB
```

There is no `LLM → SQL` path. Ever.

**Outbox**

```
BEGIN; business writes; INSERT outbox_event; COMMIT;
Outbox Relay → Event Bus → consumers
```

Prevents "order created / event lost".

## Multi-tenancy

- Every tenant-scoped table carries `tenant_id`, and it leads its indexes/PKs
  (sharding-ready: a tenant can later move to a dedicated DB/cluster).
- Isolation enforced twice: application-layer authorization **and** PostgreSQL RLS
  (`app.tenant_id` GUC, `SET LOCAL` per transaction for pooler compatibility).

## Hot vs cold path

Hot: inbound/outbound messages, conversation, AI replies.
Cold (workers only): analytics, reports, embeddings, CRM/ad sync, bulk
messages, exports, long jobs. Cold work never blocks the messaging path.

## Reliability baseline (from day one)

Idempotency · retries · exponential backoff + jitter · DLQ · circuit breaker ·
audit logs · concurrency control · outbox · tenant isolation.

Failure isolation: AI provider down → core still works; WhatsApp down → queue +
retry; workflow failures are recorded and retried by the worker runtime.

## Stack

Frontend: Vite SPA (React 18 + TS) · Core: FastAPI + Python · DB: PostgreSQL (Supabase,
pgvector) · Cache/Queue/Streams: Redis (Railway) · Workers: Python runtime ·
Storage: S3-compatible · Vectors: pgvector · AI: gateway + model router ·
Automation: FastAPI + worker runtime · Realtime: WebSocket/SSE · Observability: OpenTelemetry ·
Deployment: containers (Railway) + horizontal scaling.

## Construction principle

Modular monolith first. The Channel Gateway, AI runtime, analytics, and worker
pools are modules/worker processes inside one deployable core; they get extracted
into standalone services only when scale demands it — without rebuilding the
business domain.
