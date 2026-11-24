# What WhatsApp Coexistence does and does not bring into FIHRIST

Coexistence links a number that already runs on the WhatsApp Business app, so the merchant keeps
their phone and their app while FIHRIST answers alongside them. That is not the same as "everything
in the app is now in FIHRIST". This page is the honest list, written for the merchant and for
support, so nobody promises a feature Meta's API does not expose.

## Synced

| What | Where it comes from | Notes |
| --- | --- | --- |
| One-to-one customer chats | `messages` webhook | Both directions, with media |
| Replies typed in the Business app | `smb_message_echoes` | Stored as a HUMAN message, and the thread is handed to a person so the AI cannot answer over it |
| The app's contact list | `smb_app_state_sync` | Imported as customers, no conversations opened. Carries later add/update/remove as well as the first snapshot |
| Up to 6 months of chat history | `history` | Only if the merchant taps "share" in the app during linking. Declining is a valid answer, not a failure |
| Delivery and read state | `statuses` webhook | Per message |
| The number being disconnected | `account_update` (PARTNER_REMOVED) | The channel is blocked from sending immediately |

## Not synced

Meta's coexistence API does not carry these, so FIHRIST cannot show them no matter what the app does:

* **Groups** — group chats stay in the Business app only.
* **Calls** — voice and video calls, including call history and missed-call records.
* **Status / stories** — the merchant's own status posts.
* **Catalog, orders and shop tools** — the Business app's commerce surfaces.
* **Broadcast lists and labels** — the app's own organisation of chats.
* **Chats on unsupported companion devices** — WhatsApp for Windows, WearOS watches and other
  companion clients do not take part in coexistence. Messages sent from them can arrive as
  `131060` "unsupported" notices instead, which FIHRIST shows as a system note in the thread.
* **Messages older than the shared window** — history older than the 6 months Meta offers.
* **Anything the merchant deleted before linking** — the transfer starts from what the app holds at
  that moment.

## What the merchant should expect

1. Their number keeps working in the Business app; FIHRIST is a second pair of hands.
2. When they answer from the phone, the AI stops for that conversation. A person owns it.
3. The first contact list arrives in batches; FIHRIST says "initial contacts received" and stops
   claiming more than that. The 24-hour window closing means "nothing more is coming", not "the
   list was complete".
4. Group and call activity will simply be absent. That is the API, not a bug.
