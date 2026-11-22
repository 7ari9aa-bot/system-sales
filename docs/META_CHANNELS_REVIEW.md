# Meta channels: deep review (linking, webhooks, monitoring)

Scope: WhatsApp, Messenger, Instagram, Facebook Pages. Every row names a file and line and
quotes the evidence. Rows marked **Unconfirmed** are NOT counted as problems until verified.
Reviewed at commit `c0617b1e`. Status column: `fixed` (this change), `open`, `retracted`.

## A. Linking (OAuth, Embedded Signup)

| # | Severity | Where | Problem | Evidence | Status |
|---|---|---|---|---|---|
| A1 | Critical | `channel_specs/facebook.py:56` vs `meta_oauth.py:600` | Facebook `verify` reads `config.page_id`; OAuth stores only `{"account_id"}`. The "verify" button always fails, then moves a healthy channel to `reauth_required` (`integrations.py:399`). | `page_id = numeric_id(config, "page_id")` vs `identity_config = {"account_id": ...}` | fixed |
| A2 | High | `meta_oauth.py:365,530` | `refreshable` is derived from `_config_id`, which is the Instagram config id, so Messenger/Facebook are marked refreshable by an unrelated setting. A short-lived token is stored if `expires_in` is missing. | `"refreshable": bool(_config_id and expires_in)` | open |
| A3 | High | `meta_oauth.py:187` | `_meta_graph_error` keeps only `code`; drops `error_subcode`, `type`, `fbtrace_id`. 190/463 (expired) and 190/460 (password changed) become the same text. | `f"{step} failed ({code}): {message}"` | fixed (fields now recorded) |
| A4 | High | `meta_token_refresh.py:72-82` | Only 190/102 and 401/403 mean "reconnect". 10, 200, 368 and subcodes 463/467 fall into a generic retry every 12 h and the channel stays `active`. | `if code in {190, 102} or status in {401, 403}` | open |
| A5 | Medium | `meta_oauth.py:205` | `POST /{page}/subscribed_apps` REPLACES the field list. Linking Messenger on a Page already linked as Facebook drops `feed`. | `"facebook": base + ",feed"` vs messenger = base | fixed (the Page subscription is merged, and on disconnect narrowed to the sibling's fields) |
| A6 | Medium | `integrations.py:446-453` | A successful verify rewrites `_connection` and wipes `granted_scopes`, so a false "reconnect" badge appears. | `config = {**identity, "_connection": _verification_metadata(...)}` | open |
| A7 | Medium | `meta_oauth.py:795` | The page-choice ticket is consumed (`getdel`) before tenant/user/page are checked; a bad or repeated request burns it. | `parked = await _take_page_choice(...)` first | open |
| A8 | Medium | `meta_oauth.py:886` | `except Exception: return _back("error","invalid_state")` logs nothing. | no logger call | open |
| A9 | Medium | `meta_oauth.py:308` | `except ValueError: return None` hides a corrupt ticket as "expired". | | open |
| A10 | Medium | `meta_oauth.py:340-415` | `.json()` is called with no status check; a 429/5xx HTML body raises `ValueError` and shows as a config error. | | open |
| A11 | Medium | `meta_oauth.py:249` | `_messaging_pages` returns ALL pages when any lacks `tasks`. | `return pages or all_pages` | fixed (a Page whose tasks exclude messaging is no longer offered) |
| A12 | Medium | `facebook_pages.py:85-96` | Reads token and page id from credentials only; OAuth keeps the page id in `config`. Whether config is merged at every call site is **Unconfirmed**. | | unconfirmed |
| A13 | Medium | `facebook.py:33,46` vs `messenger.py:57,68` | Facebook accepts fallback secrets (`meta_app_secret`, `whatsapp_verify_token`) that Messenger does not: one deployment can pass one webhook and fail the other. | | open |
| A14 | Medium | `integrations.py:70-75` | Facebook webhook status requires `messenger_*` settings only, while the adapter accepts fallbacks: false "server setup required". | | open |
| A15 | Medium | `facebook_pages.py:219` | `publish_post` can return the string `"None"`. | `str(body.get("post_id") or body.get("id"))` | open |
| A16 | Medium | `meta_token_refresh.py:212` | The failure reason (code) is never logged. | `logger.warning("...failed provider=%s")` | open |
| A17 | Low | `meta_oauth.py:335` | 6 sequential calls at 8 s each: up to ~48 s inside a browser redirect. | | open |
| A18 | Low | `ChannelsSettings.jsx:397` | Dead code: reads `meta_connected`/`meta_error` from the URL, the server never redirects with them. | | open |
| A19 | Low | `meta_oauth.py:242` | Server TTL (600 s) equals the UI timeout (10 min): a 9:50 connect is lost. | | open |
| A20 | Low | `instagram.py:411` | Unreachable branch (reaction handled at 404-410). | | open |

### WhatsApp Embedded Signup

| # | Severity | Where | Problem | Status |
|---|---|---|---|---|
| W1 | High | `ChannelsSettings.jsx:491` | `FB.login` sends no `sessionInfoVersion` while the code waits for `WA_EMBEDDED_SIGNUP` events. Meta's v5 notes say the value is ignored (always 5), so this is **not** the cause; kept only as a test gap. | retracted |
| W2 | High | `ChannelsSettings.jsx:448,507` | The code is exchanged only after `Promise.all([code, session])` with a 10 min timer. Meta's code lives 5 min. | open |
| W3 | High | `ChannelsSettings.jsx:462` | `CANCEL` and `ERROR` share one message; Meta's `error_code`/`error_message` are discarded. | fixed (`whatsappSignupInterruption` shows Meta's message, error id and session id) |
| W4 | High | `meta_whatsapp_signup.py:142` | Code-exchange failure drops Meta's error and logs nothing. | fixed (recorded) |
| W5 | High | `meta_whatsapp_signup.py:282,313` | An unknown phone status is treated as "not connected" and `/register` is called, spending one of Meta's limited attempts (133016). | open |
| W6 | High | `meta_whatsapp_signup.py:315,343` | PIN is generated before the call and stored only on success: a lost response makes the next attempt use a different PIN. | open |
| W7 | Medium | `meta_whatsapp_signup.py:326` | Only 133016 is special-cased; other register errors show a misleading "finish verifying". | fixed (`_register_error` maps the documented Meta codes) |
| W8 | Medium | `meta_whatsapp_signup.py:399-405` | App is subscribed to the WABA BEFORE registering the number; a register failure leaves an orphan subscription. | open |
| W9 | Medium | `meta_whatsapp_signup.py:427` | No `IntegrityError` handling on flush (the manual path has it). | open |
| W10 | Medium | `meta_whatsapp_signup.py` | No audit row for an embedded connect (manual connect writes one). | open |
| W11 | Medium | `ChannelsSettings.jsx:101` | `isMetaSdkOrigin` accepts any `*.facebook.com` origin and never checks `event.source`. | open |
| W12 | Medium | `whatsapp.py:197` | Status updates keep only `errors[0].message`; the numeric code (131047, 131026, 131051, 132000...) is dropped. | fixed (code, title and details kept on the stored error) |
| W13 | Medium | `whatsapp.py:325` | Any >=400 becomes one error; 429/130429 is not marked retryable. | open |
| W14 | Medium | `docs/META_SETUP.md:143` | `WHATSAPP_APP_SECRET` / `WHATSAPP_VERIFY_TOKEN` and the app-level callback URL are not documented for WhatsApp; both checks fail closed. | fixed (`META_SETUP.md` rewritten per Meta object) |
| W15 | Low | `ChannelsSettings.jsx:70` | SDK locale hardcoded `en_US`; `fbAsyncInit` overwritten per call can stall to the 15 s timeout. | open |
| W16 | Low | `meta_whatsapp_signup.py` `/complete` | Not idempotent: a retry re-sends a one-time code and shows an error for a channel that is connected. | open |
| W17 | Test gap | `loadFacebookSdk.test.js` | No test for `FB.login` options, FINISH/CANCEL/ERROR, or the timeout. | open |

## B. Webhooks and monitoring

| # | Severity | Where | Problem | Status |
|---|---|---|---|---|
| M1 | Critical | `webhooks.py:171`, `health.py:72`, `diagnostics.py:610` | `consecutive_failures` is only ever written as 0. The health surface can never turn degraded from webhook failures; the `>= 3` branch is unreachable. | open (next) |
| M2 | Critical | `webhooks.py:79` | A bad signature was refused with no log, count or row. | fixed |
| M3 | High | `webhooks.py:56` | A failed verify handshake was refused silently. | fixed |
| M4 | High | `webhooks.py:120` | An unknown account got one `info` line and a 200. | fixed (counted + row) |
| M5 | High | `observability.py:81-92` | Most logs (stdlib) skip structlog: raw text, no JSON, level, timestamp or request id. | open |
| M6 | High | repo-wide | No error aggregation (no Sentry) and no alert channel. | open |
| M7 | High | `diagnostics.py:49-73` | No check on `webhook_events` in `failed`/`dead`; a dead inbound message is invisible. | open (next) |
| M8 | High | `health.py:64-77` | `last_webhook_at` is never compared with now: "never arrived" and "stopped" both read healthy. | open (next) |
| M9 | Medium | `webhooks.py:138` | `last_webhook_at` is only written for `active`/`connected`. | open |
| M10 | Medium | `message_worker.py:509` | A phase-1 `PermanentError` does not notify the owner (media read failure leaves the customer waiting). | open |
| M11 | Medium | `ingest.py:327` | A failed template resync is swallowed in a warning. | open |
| M12 | Medium | `webhooks.py:96-107` | In a multi-account batch the digest is of re-serialised JSON, not the signed bytes. | open |
| M13 | Low | `diagnostics.py:421` vs `health.py:29` | Two definitions of the same DLQ list. | open |
| M14 | Low | `diagnostics.py:637` | `check_integrations` returns `error: None` while degraded. | open |
| M15 | Low | `webhooks.py:36` | A production monkeypatch shim in the request path. | open |
| M16 | Low | `observability.py:139` | `request_failed` has no counter. | open |
| M17 | Retracted | `webhooks.py:171` | "ON CONFLICT needs a unique index": `uq_webhook_events_provider_external` exists (`b2c3d4e5f6a7`). | retracted |
| M18 | Unconfirmed | `webhooks.py:69` | No body size cap before `request.body()`; a middleware may cover it. | unconfirmed |
| M19 | Unconfirmed | grep | Nothing found that sets `restricted` or handles `account_update` / `phone_number_quality_update`. | unconfirmed |

## C. What developers hit, and how it was solved (official sources read)

* **Embedded Signup versions.** v5 released 20 Oct 2026, v4 8 Oct 2025; v2/v3 deprecated 15 Oct 2026
  (served as v4). WhatsApp Business app onboarding is on by default in v5. `sessionInfoVersion`
  is ignored. https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/versions
* **Window closed vs cancelled.** Closing on the final screen is a success; the code returns only on
  Finish. CANCEL carries `current_step`; ERROR carries `error_code`/`error_message`.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/errors
* **"Partner can't set up new WhatsApp Business accounts right now" (3441142)** and **2655111**
  (partner app lacks advanced WhatsApp Business Management/messaging permissions: request it in App Review).
  Same source as above.
* **Exchange the code in 5 minutes**, server to server; subscribe the WABA to the app afterwards.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation
* **Page domain must be in Allowed Domains and Valid OAuth Redirect URIs** or the ids never return to the opener.
* **133016** = too many register/deregister attempts; **133005** wrong PIN; **133006** verify first;
  **131047** 24 h window passed, send a template; **131026** undeliverable; **131051** unsupported type;
  **132000** template parameter mismatch; **130429** throughput; **80007** WABA rate limit.
  https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes
* **Token error 190 subcodes**: 458 app not installed, 459 checkpoint, 460 password changed, 463 expired,
  464 unconfirmed user, 467 invalid token. https://developers.facebook.com/docs/graph-api/guides/error-handling
* **System user tokens need BOTH the WhatsApp account and the Messaging account assigned**; Business Suite does
  not cascade the grant (error 200 otherwise).
* **Not researched (no source found, so nothing is claimed):** Instagram linking rules and review needs,
  Messenger tags after 2025, signature-with-raw-body pitfalls, Meta disabling a failing webhook, development
  mode behaviour for testers, Graph version sunset dates, the numeric limit behind 133016, codes 32 and 613.

## E. Webhook architecture rework (branch `feat/meta-channels-unified`)

Meta gives an app one callback URL per object type, so Messenger and Facebook (both the `Page`
object) could not each own a path, and Instagram's fields were being sent to the Page subscription,
which does not configure them.

| # | Severity | Problem | Status |
|---|---|---|---|
| E1 | Critical | Messenger and Facebook shared one Meta object but had two callback paths; events landed on whichever path was registered. | fixed: `POST /webhooks/meta/page` splits `messaging` to Messenger and `changes` to Facebook |
| E2 | Critical | `comments`, `message_reactions`, `messaging_seen` were sent to `/{page}/subscribed_apps` for Instagram; they are not Page fields. | fixed: only Page fields are sent; Instagram's are set on the Instagram object |
| E3 | Critical | The setup guide registered every channel under the Page object. | fixed: three independent setups |
| E4 | Critical | "Connected" proved nothing about delivery. | fixed: `GET /integrations/{id}/diagnostics` and the "Diagnose channel" button (app-level dashboard setup still cannot be read from the server; it is inferred from traffic) |
| E5 | High | Disconnect only changed a row; Meta kept delivering. | fixed: removes (or narrows, when a sibling channel stays) the subscription, records the outcome, retry route |
| E6 | High | Postbacks, referrals, reads, deliveries, reactions, echoes, handovers and albums were dropped by Messenger. | fixed |
| E7 | High | A human reply after 24 h had no `HUMAN_AGENT` tag. | fixed |
| E8 | High | Ad-opened conversations (Click-to-Messenger / Click-to-Direct) got the 24 h window, not 7 days. | fixed (marker kept in `messaging_policy_state`, no migration) |
| E9 | Medium | Instagram reactions had no dedupe id; mentions were ignored; referrals were not parsed. | fixed |
| E10 | Medium | Messenger customers had no name. | fixed (Graph lookup, cached, never fails ingest) |
| E11 | Medium | Instagram permissions were never checked for what the channel needs. | fixed (`missing_scopes` for Instagram) |
| E12 | Medium | No history backfill for Messenger conversations. | open |
| E13 | Medium | Page mentions (`mention`) on Facebook and Page comments do not open a conversation. | open (design decision: comments stay a separate surface) |
| E14 | Medium | WABA account, quality and template update events are not handled. | open |
| E15 | Medium | The unified route is tested against fakes. It has not been run against a live Meta app. | open: needs the dashboard setup in `META_SETUP.md` and a test Page |

