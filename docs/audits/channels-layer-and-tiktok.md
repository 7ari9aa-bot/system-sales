# Channels layer audit and TikTok plan

Working audit, 2026-11-17, written before any TikTok code. Sources: repo at `d9f5abb7` and the TikTok Business Messaging API docs (v1.3).

Fihrist · channels layer · code read on main d9f5abb7

## Adding TikTok exposed five gaps

The channels layer is clean for Meta-style channels. TikTok is not Meta-style, and four things the guide calls "automatic" are not. None is fixed yet. I wrote no code until you rule on them.

Places that name a channel

30 backend files

Plus about 20 frontend files. The guide says "one file and one line". The real list is a spec, a registry line, an adapter, a policy row, a webhook allow-list, a schema literal, a breaker name, settings, a SQL function and a unique index.

## What TikTok is, from its own docs

- **Product:** Business Messaging API, Open Beta in METAP (includes Egypt)

- **Access:** Needs TikTok's data security and privacy review before sending works

- **Webhook level:** One URL per developer app, not per merchant

- **Merchant id:** user_openid at the top of the payload

- **Signature:** TikTok-Signature: t=,s=, HMAC-SHA256 of t.body with the app secret

- **Access token:** Lives 1 day. Refresh token lives 1 year

- **Send:** Needs the conversation_id from the inbound webhook

- **Limits:** 10 replies per 48 hours after each customer message. The business cannot start a chat

- **Payload:** content is a JSON string inside the JSON

## The five gaps

- 1 Webhooks would be dropped silently resolve_channel_tenant is a SQL function with a fixed list of providers and ELSE NULL . A TikTok message would match no merchant and be acknowledged and discarded. The guide says no migration is needed. That is wrong for this function.

- 2 Two merchants could connect one account The unique index on channel identity also lists providers by name. TikTok is not in it, so uniqueness would not be enforced.

- 3 Sending is impossible as built TikTok replies need the thread's conversation_id . The inbound message has a conversation_ref field, but nothing stores it and the outbound message has nowhere to carry it.

- 4 Tokens would die every day Nothing in the code refreshes a channel token. Meta tokens last about 60 days and the rest are pasted once. TikTok would silently stop sending after 24 hours.

- 5 The webhook is not per merchant The generic route authenticates with one app-wide secret and resolves the merchant from the body. That fits TikTok, but the signature check must use TikTok's timestamp rule, and a 5-second window (their sample) would reject real deliveries.

### Smaller finds in the existing layer

- The SQL function maps Telegram to public_key , but the guide says bot_id . One of them is stale.

- Replay protection hashes the raw body. TikTok sends a fresh timestamp per delivery, so a retried event may not collapse.

- The policy table models a 24-hour window. TikTok is 48 hours with a 10-message cap, which the policy type cannot express.

Decision for you
Two paths. A: build TikTok properly (a migration, a stored conversation id, a token refresher, a message quota in policy). That is the safe route and touches the shared layer. B: ship only the connection screen and inbound reading now, and leave sending off until TikTok approves your app. B is smaller, but replies from the inbox would not work.

Sources: TikTok API for Business, Business Messaging API v1.3 docs (webhooks, verification, send, authentication); Fihrist repo at main d9f5abb7. Nothing here has been run against a live TikTok account.
