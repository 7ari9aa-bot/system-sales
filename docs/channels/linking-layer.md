# The shared linking layer

One Meta Page is ONE object with several FIHRIST functions hanging off it: Facebook Page management,
Messenger, Instagram. `app/modules/customers/meta_linking.py` is the single owner of that connection.
It does **not** merge the functions: each keeps its own permission and its own state, exactly as
Meta keeps them.

## `MetaPageConnection`

Built from an integration row by `from_integration()`. It carries the Page id, whether a token
exists (never its value), granted scopes, Page tasks, the subscribed field set, the fields Meta has
actually delivered, and the onboarding mode. A fact nobody measured stays `None` and is reported as
unverified — never as a failure, because an unreachable Graph is not a missing permission.

`capability_states()` returns one honest state per function from `capability_states.evaluate`;
`working_capabilities()` returns only those genuinely `available`.

## `PageSubscriptionManager`

The subscription had its field set computed in one place and merged in another, with nothing
stopping two requests from overwriting each other. The manager fixes three things:

* **union, never intersection** — subscribing only what the newest capability wants would silently
  unsubscribe the older one;
* **a failed read never becomes a write** — `current=None` produces `write: False`, because writing
  a guessed set is how a failed GET turns into lost fields on the next POST (P0-3);
* **one lock per Page** — concurrent updates for the same Page are serialised; different Pages never
  wait for each other.

A field Meta added that this build does not know about is kept, not dropped.

## Reconnect: four failures, four answers

`reconnect_plan(connection, capability)` distinguishes what a channel screen shows as one thing:

| Action | Meaning |
|---|---|
| `connect` | the channel is not linked |
| `reconnect_account` | linked, but no usable token |
| `request_scopes` | token fine, scope missing — asks only for that capability's scopes |
| `fix_subscription` | scope granted, webhook field not subscribed |
| `wait_for_event` | subscribed but never delivered (Meta review, or no such event yet) |
| `none` | it works |

Exposed as `GET /api/v1/integrations/{id}/reconnect-plan?capability=messenger`.

## Backfill: one shape, per-provider bounds

`BackfillBounds` (max pages, max items, max days, rate limit) per provider. Messenger walks its
Conversation API; Instagram backfills comments; **WhatsApp returns `supported: False`** because Meta
exposes no history API at all — a platform limit, recorded as one, not a missing job.

## Event registry

`EVENT_REGISTRY` lists every webhook event the system claims to handle with its class, what it
persists, its domain effect, and its diagnostic state. An event that is parsed but not persisted is
the "silently ignored" bug the report kept finding, so `persist` and `effect` are required fields.

## Tests

`tests/test_meta_linking_layer.py` (20) — the row is read without invention, Facebook management
needs no Messenger scope, the field set is a stable union, a failed read never writes, an unknown
field is kept, a no-op update never calls Meta, one Page's updates are serialised, reconnect asks
only for the missing scopes, a dead token is not a missing permission, a webhook problem is not a
token problem, WhatsApp has no backfill, every provider's bounds are finite, and every registered
event says what it persists and what it does.
