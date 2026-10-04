# WhatsApp Cloud API in FastAPI

## Purpose

The former n8n workflows had two responsibilities:

1. answer Meta's verification handshake and receive signed inbound events;
2. send approved outbound payloads to the WhatsApp Cloud API.

Both responsibilities now run inside FastAPI and its worker runtime. There is no
separate n8n callback or outbound proxy in the application path.

## Public callback

Set the callback URL in the Meta app to:

```text
https://api-production-81629.up.railway.app/api/v1/webhooks/whatsapp
```

FastAPI exposes both methods at that address:

| Request | FastAPI responsibility |
| --- | --- |
| `GET` | Validates `hub.mode=subscribe` and `hub.verify_token` against `WHATSAPP_VERIFY_TOKEN`, then returns `hub.challenge`. |
| `POST` | Validates `X-Hub-Signature-256` using `WHATSAPP_APP_SECRET` over the exact raw request body. |

The callback URL is versioned under `/api/v1`. The old n8n path
`/webhook/whatsapp` must not remain configured at Meta after the FastAPI release.

## Inbound delivery flow

```text
Meta
  -> POST /api/v1/webhooks/whatsapp
  -> signature verification + tenant resolution by phone_number_id
  -> webhook_events (raw durable ingress + replay key)
  -> outbox: webhook.ingest
  -> PlatformWorker
  -> normalize customer, conversation, message, and delivery receipts
  -> outbox: message.received
```

The HTTP route acknowledges a valid, attributed delivery after the durable ingress
record and outbox event are staged. The worker retries failed processing from the
stored event; a Meta retry or Redis replay cannot create duplicate messages.

## Outbound delivery flow

```text
API / automation creates an outbound Message
  -> outbox: message.outbound
  -> MessageWorker claims queued Message
  -> policy and consent checks
  -> decrypt tenant integration credentials
  -> POST https://graph.facebook.com/v21.0/{phone_number_id}/messages
  -> persist provider id and delivery attempt
```

`WhatsAppAdapter` is the only code that calls the Graph API. It runs behind the
process-wide WhatsApp circuit breaker, records failed or unknown delivery states,
and does not retry an unknown provider result by blindly sending the customer a
second message.

## Required configuration

Configure these environment variables in the API and worker Railway services:

```text
WHATSAPP_APP_SECRET=<Meta app secret>
WHATSAPP_VERIFY_TOKEN=<random callback verification token>
```

For every tenant's WhatsApp channel integration, create or update
`POST /api/v1/integrations` with:

```json
{
  "provider": "whatsapp",
  "kind": "channel",
  "config": { "phone_number_id": "<Meta phone-number id>" },
  "credentials": {
    "phone_number_id": "<Meta phone-number id>",
    "access_token": "<Meta system-user access token>"
  },
  "status": "connected"
}
```

`config.phone_number_id` lets an inbound event resolve its tenant without exposing
credentials. `credentials` are envelope-encrypted before they are stored, decrypted
only by the message worker when it sends, and every decryption is audited. Do not use
a shared `WHATSAPP_ACCESS_TOKEN` or `WHATSAPP_PHONE_NUMBER_ID` environment variable:
outbound credentials are tenant-scoped.

## Release checklist

1. Deploy the API and worker code together.
2. Confirm `/healthz` and `/readyz` on the API service.
3. Set `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN` in both services.
4. Configure the tenant integration with its phone number id and access token.
5. Change the Meta callback URL to the FastAPI URL above and complete Meta's GET handshake.
6. Send one inbound test message and confirm a `webhook_events` row, a conversation,
   and a received message.
7. Send a template or in-window reply through the Sales OS inbox and confirm its
   `DeliveryAttempt` and provider message id.
