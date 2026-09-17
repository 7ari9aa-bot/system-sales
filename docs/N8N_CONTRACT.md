# n8n Integration Contract

n8n is automation glue, OUTSIDE the core. The core never depends on n8n for
business truth: `FastAPI → DB → Event → n8n`, never `FastAPI → n8n → DB`.

## How n8n consumes core events

1. Deploy an n8n instance (Railway) with `N8N_BASIC_AUTH` set.
2. Create a workflow whose trigger is an **n8n Redis Trigger / custom poller**
   reading from the core's event bus streams, OR (simpler) register an
   outbound webhook endpoint (below) pointing at the n8n webhook node.

## Outbound webhooks (recommended)

The core delivers signed, retried webhooks for business events:

- Register: `POST /webhook-endpoints` (settings:write permission)
  `{ "url": "https://n8n.example.com/webhook/sales-os", "events": ["order.created", "message.received"] }`
- Delivery: `POST` JSON `{ "event": "order.created", "data": {...} }`
- Signature header: `X-SalesOS-Signature: sha256=<HMAC-SHA256(endpoint_secret, raw_body)>`
- Retries: exponential backoff (2s base, 5 attempts) → then `dead`.
- The secret is shown once at registration — store it in n8n credentials.

## Core callbacks (inbound n8n → core)

n8n workflows that must WRITE data call application endpoints with a service
token (JWT issued for the service account) — never direct DB writes. Endpoints
require the same RBAC permissions as human actors.

## Events catalog (outbox → bus → consumers)

| Stream            | event_type            | payload keys                              |
|-------------------|-----------------------|-------------------------------------------|
| message.events    | message.received      | conversation_id, customer_id, channel, body |
| message.events    | message.outbound      | message_id, conversation_id               |
| order.events      | order.created         | order_id, number, customer_id, grand_total |
| order.events      | order.cancelled       | order_id                                   |
| order.events      | order.status_changed  | order_id, to_status                        |
| order.events      | order.refunded        | order_id, payment_id, amount               |
| platform.events   | notification.queued   | notification_id                            |
| platform.events   | webhook.deliver       | delivery_id                                |

Envelope metadata always carries `tenant_id`.
