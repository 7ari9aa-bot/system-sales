# WhatsApp: the four features Meta gates

The report's WhatsApp gaps (a) and (g): coexistence, and Calls / Groups / Marketing Messages shown
as buttons FIHRIST cannot press. Both are now declared facts, not wishes.

`app/modules/customers/whatsapp_roadmap.py` holds one entry per gated feature: its state, **who
decides**, the evidence, and what the owner would have to do.

| Feature | State | Who decides |
|---|---|---|
| Coexistence (Business app + Cloud API on one number) | `account_ineligible` until a connection records it | Meta, per number; signup ends with `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` |
| Calls | `region_restricted` | calling must be enabled on the number and supported in the country |
| Groups | `account_ineligible` | the business account must be approved for the Groups API |
| Marketing Messages | `needs_app_review` | opt-in per customer plus approval per business |

`GET /api/v1/integrations/{id}/whatsapp-roadmap` returns them with the connection's recorded
`onboarding_mode`, and refuses a non-WhatsApp channel.

## Two bugs this closed

* **A false green.** `coexistence` was declared plain `available` in the capability report while
  nothing in signup handled the coexistence step at all. It now reports `account_ineligible` with
  Meta's rule as the reason, and only a connection that recorded `onboarding_mode=coexistence`
  reports `available` — because Meta already allowed it for that number.
* **A silent choice.** Embedded Signup now always requests the Business App coexistence flow,
  and the server verifies `is_on_biz_app` + `platform_type` from Meta before accepting the link.
  Cloud API-only numbers are refused rather than silently connected as a different product.

The state words are literals in the roadmap module rather than imported from `capability_states`,
because `capability_states` reads the registry while it is being defined; importing back would be a
circular import.

## Tests

`tests/test_whatsapp_roadmap_and_coexistence.py` — every gated feature carries evidence and an
action, none claims to be available out of the box, the capability report carries the roadmap states
(and still reports `flows` and `catalog_messages` as available), a measured state only replaces a
known one, an unknown feature is a `KeyError`, signup records coexistence, defaults to coexistence
and refuses Cloud API-only and made-up modes.
