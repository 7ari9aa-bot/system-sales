# conversations

CONVERSATIONS domain — conversations, messages, assignments, ai_sessions.

## Where things are

- `gateway/`
- `inbox.py`
- `media.py`
- `models.py`
- `policy.py`
- `router.py`
- `routers/`
- `service.py`
- `social_comments.py`
- `templates.py`
- `voice.py`

## HTTP

23 endpoints. Route prefixes: `/message-templates`. Registered in `app/main.py`.

## Tables

- `ai_sessions`
- `assignments`
- `attachments`
- `call_legs`
- `call_sessions`
- `calls`
- `conversations`
- `message_templates`
- `messages`
- `phone_numbers`
- `social_comments`
- `template_approvals`

## Depends on

Other modules imported from here: `customers`, `identity`, `operations`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `conversations` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
