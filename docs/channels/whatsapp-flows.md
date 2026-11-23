# WhatsApp Flows: the lifecycle, from FIHRIST

A Flow is a form Meta hosts inside WhatsApp (order status, appointment booking, a return request).
FIHRIST could already SEND a flow message and read the `nfm_reply` that came back, but a Flow could
only be created and published in Meta's own console: `WhatsAppFlowsClient` had no caller anywhere.
That is the recurring shape of this whole effort — a tested module nothing imports.

`routers/whatsapp_flows.py` is the missing half.

| Route | What it does |
|---|---|
| `GET /api/v1/whatsapp/flows` | the Flows on this WhatsApp Business Account, as Meta lists them |
| `POST /api/v1/whatsapp/flows` | create a Flow — it is a **DRAFT** until published, which is Meta's rule |
| `POST /api/v1/whatsapp/flows/{id}/assets` | attach the Flow JSON (Meta validates it here) |
| `POST /api/v1/whatsapp/flows/{id}/publish` | publish it so it can be sent |

## Two error paths that must stay different

* **Meta refused the Flow JSON** (a missing screen title, a bad routing model): the author is the only
  person who can fix it, so the route answers `400` with Meta's own words. Answering `502` would send
  them hunting for an outage.
* **Meta is down or the token is dead**: that is an upstream failure and stays a `502`.

A missing token or WABA id is a `409` ("WhatsApp is not connected"), never a `500`.

## Sending and receiving

Sending a flow message is the interactive builder's job (`build_flow_message`), and the answer
arrives as `interactive.type == "nfm_reply"` with the answers in `response_json`, stored on the
conversation like any other inbound message. The two halves together are the lifecycle the report
asked for: create → upload → publish → send → receive → store.

## Tests

`tests/test_whatsapp_flows_routes.py` — creation returns Meta's id as a draft, the JSON is uploaded to
the Flow, Meta's validation error comes back as `400` with its text, publishing hits the publish
endpoint, listing reads the WABA, a disconnected channel is `409`, and an empty Flow JSON never
leaves the server.
