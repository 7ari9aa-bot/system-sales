# Messenger Platform settings: greeting, Get Started, menu, ice breakers

The Page's Messenger profile (the greeting above an empty thread, the Get Started button, the
persistent menu, the ice breakers above the composer) could only be changed in Meta Business
Suite. `gateway/messenger_profile.py` had the calls and the tests, but **nothing imported it** — a
tested module with no route is not a feature, and the report listed the whole settings lifecycle
as missing for that reason.

`routers/messenger_profile.py` is the missing half.

| Route | What it does |
|---|---|
| `GET /api/v1/messenger/profile` | Reads `greeting, get_started, persistent_menu, ice_breakers` from Meta, so the screen shows the truth, including settings made outside FIHRIST |
| `PUT /api/v1/messenger/profile/{setting}` | Sets one setting: `greeting` (≤160 chars), `get_started` (payload), `persistent_menu` (≤5 items), `ice_breakers` (≤3 questions, 80 chars each) |
| `DELETE /api/v1/messenger/profile/{setting}` | Clears one field; Meta has no per-field delete endpoint, so the field name goes in `fields` |

## The three rules the routes keep

1. **Messenger stays its own function.** The writes need `pages_messaging`; a Page connection that
   only manages posts is refused with the permission named (`403`), before any Meta call. Facebook's
   Page-management permission is not borrowed to reach Messenger.
2. **Meta answers first.** A refusal from Meta is an error, never a saved setting, and the message
   Meta gave is passed through.
3. **Nothing is invented.** A read returns what Meta holds; a setting made in Business Suite shows
   up here unchanged, and a field Meta never set is `null`.

Meta's own limits (greeting length, five menu items, three ice breakers) are checked before the
call and come back as a `400` with a reason, not as a Meta refusal or a `500`.

## Capability state

`profile_settings` in `customers/capability_states.py` already declares this feature against
`pages_messaging`, so diagnostics show *Needs permission* (not a broken button) until Messenger is
linked. `inbox_labels` and `conversation_history` sit next to it the same way.

## Tests

* `tests/test_messenger_profile_routes.py` — the real route graph against a mocked Graph: a greeting
  reaches `me/messenger_profile`, an unknown setting and an over-long greeting never leave the
  server, a missing `pages_messaging` is a `403` with no Meta call, a Meta refusal is an error, the
  read returns Meta's own values, and clearing deletes exactly one field.
* `tests/test_messenger_profile_settings.py` — the gateway client's shapes and limits.
