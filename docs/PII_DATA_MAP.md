# PII / Data Lifecycle Map (spec §131)

Every location where customer data lives, its classification, and its
deletion/retention behavior. Deletion propagation order follows §172.

| Store | Data | Classification | Retention | Deletion behavior |
|---|---|---|---|---|
| PostgreSQL `customers` | name, phone, email, address | PII primary | life of tenant | tombstone (deleted_at/by/reason) + merged redirect |
| `customer_identities` | channel handles | PII | life of tenant | cascade on customer delete; remapped on merge |
| `messages` | conversation content | PII | policy (default 365d) | retention worker; content_type provider_metadata kept minimal |
| `attachments` | media (S3 keys) | PII (media) | policy | storage delete + row delete |
| `memories` | AI memory content | PII (derived) | policy/expires_at | HARD DELETE on customer deletion (DeletionService step 2) |
| `knowledge_items/chunks` | business knowledge | internal | until superseded | re-index on version change; tenant-scoped delete |
| `orders/payments` | transactional | financial (keep) | legal retention | never hard-delete; tombstone/refund state |
| `audit_logs` | before/after minimum | sensitive | policy (§66 minimum-necessary) | never deletes identity beyond need |
| `ai_usage` | tokens/cost — NO content | metrics | 13 months | retention worker |
| EventLog | IDs + minimal payload | minimal | policy | retention worker |
| Outbox | transient payload | minimal | cleaned after publish + window | relay cleanup |
| Redis Streams | transport only | none persisted | maxlen + TTL | loss is harmless (§163) |
| Search index | derived fields | derived | rebuildable | deletable per customer (§131) |
| Vector store | embeddings | derived | rebuildable | deletable per customer |
| n8n | minimal payload via webhook | minimal | per workflow policy | §62 isolation; credentials via SecretReference |
| Backups | full DB copy | full | declared window (§70) | expires with backup rotation — documented, not individually editable |
| Logs (structlog) | no raw PII by default | minimal | short | request_id correlation only |

## Deletion propagation order (§172)
1. customers tombstone (this service)
2. memories hard delete
3. messages retention path
4. derived: search/vector (rebuildable — flagged)
5. audit: minimum-necessary entries preserved
6. events: privacy.customer_deleted (n8n/automation react)
7. backups: covered by rotation window (documented RPO)

## Rules
- Events carry IDs + minimal metadata, never full PII payloads.
- Logs: structlog emits request ids and statuses; message bodies are never
  logged by default.
- Any NEW store added to the system MUST be appended to this map + wired into
  DeletionService (ADR-017).
