# Customer Commerce — Architecture Fit and Current Scope

Updated 2026-11-05 for the working tree on `feat/commerce-deposit-foundation`. The first
survey measured `1fb9ae4`; the implementation described here is still uncommitted. This is
not a CI, deployment, or production-readiness report.

## Scope decision

The current priority is merchant settings and reliable customer-agent facts. Payment
providers and collection are deferred, and the customer agent stays read-only with staff
handover for operational actions. Publishing a deposit rule does **not** enable order
creation, confirmation, stock reservation, cancellation, refund, or collection.

## Reuse instead of parallel services

| Concern | Existing owner | Constraint on commerce work |
|---|---|---|
| Orders and item snapshots | `backend/app/modules/orders/models.py`, `service.py` | Extend the existing order; `order_items` snapshots products, not deposit quotes. |
| Status history and transitions | `orders/models.py` + `backend/app/core/transitions.py` | Reuse the guards; no second state machine. |
| Payments and refunds | `OrderPayment`, `Refund`, `orders/money.py` | Reuse the ledger. `authorized` blocks overcollection but is not money received. |
| Stock holds and expiry | inventory reservations + `expire_reservations` worker | Existing mechanisms still need commerce-specific concurrency tests before execution. |
| Authorization | identity RBAC, `authority`, `decisions`, `ai/approvals`, `core/risk.py` | No parallel policy/authorization service. |
| Money | `orders/money.py`, `core/currency.py`, `core/model_kit.py` | Storage stays `NUMERIC(14,2)`; minor units belong at the provider edge. |
| Events | `core/events/writer.py` + transactional outbox | No direct transport publish from a service. |
| Tenant isolation | application predicates + FORCE RLS + `bind_tenant` | Tests must run as a role that is neither superuser nor BYPASSRLS. |
| Published merchant text | `ai/policies.py` + `KnowledgeItem` | Extend the existing surface; do not open a second knowledge store. |

`Numeric(14,2)` capacity is not the application's input limit: policy amounts are capped at
`999999999.99`, the same cap manually entered order money uses. Percentage points keep two
decimals regardless of currency; money uses the currency's exponent, and three-decimal
currencies are refused at storage.

## In this branch

**Merchant deposit rules**

- Versioned `DepositPolicy`: one active row per tenant, unique `(tenant_id, version)`,
  per-tenant advisory lock on save, and an unchanged retry that reuses the active version.
- Reads need `settings:read`, writes need `settings:read`+`settings:write` and order
  previews need `orders:read`; audit row and outbox event land in the caller's transaction.
- NONE / PERCENTAGE / FIXED with calculation base, minimum and maximum, capped at the
  order's grand total. The items-after-discounts base is floored at zero, and the minimum
  is applied before the final currency rounding.
- Cross-currency fixed amounts and bands are refused rather than reinterpreted.
- The order preview recomputes from stored order amounts and subtracts only money that
  actually arrived (captured/partially-refunded/refunded minus non-rejected refunds).

A preview is **not** a frozen quote and must never be presented as a price a customer
already accepted. Missing policy and an explicit NONE policy stay distinguishable; NONE
does not itself select cash on delivery.

**Published policies and the customer agent**

- The existing exchange/return/shipping/hours fields gained ordering and cancellation.
- `get_store_info` takes a closed topic enum plus an optional question. Exact topics read
  published, customer-facing policy rows deterministically, without embeddings; general
  questions keep bounded relevance retrieval and report `ranking: "unavailable"` when the
  retrieval model is down.
- Structured deposit output exposes only type, value, currency, base and band. Internal
  names, ids and versions stay out of the grounding facts, and an absent rule is `null`
  instead of an invented zero deposit.
- Prompts and tool descriptions separate *published fact* from *permission to act*: the
  agent explains the deposit rule, never computes an order amount or claims that an order,
  reservation, refund or payment happened. Tool text is data, not instructions.
- The settings screen uses the existing authenticated `api()` client. Money units come from
  the tenant's own currency setting (`GET /tenants/{id}/currency`), because `auth/me`
  answers with a tenant list and no currency. A rule saved in another currency is flagged
  with both codes, its absolute amounts are cleared for re-entry, and saving requires an
  explicit acknowledgement. Load failures fail closed instead of guessing, and the UI
  shows localized reasons for permission, validation and transient failures without
  echoing backend internals.

## What is still missing

1. **Frozen quote and consent** — persist the exact order/deposit payload, bind confirmation
   to authenticated customer identity plus that payload hash, with expiry, replay and
   concurrency rules. A token is the mechanism; consent is still a claim to verify.
2. **Order execution** — any reversal of the 2026-10-18 language-only scope cut needs the
   identity, ownership, consent and authorization checks above, not only an allowlist edit.
3. **`get_my_orders`** is a tenant-scoped invoice-number lookup. It must not be described as
   proof that the invoice belongs to the bound customer.
4. **Text-policy publishing integrity** — duplicate keyed rows, concurrent publication and
   the missing audit/outbox on `ai/policies.py` remain a separate pass.
5. **Provider integration, ledger liability, refundability wording, and rounding policy** —
   deferred decisions, unchanged from the first survey.
6. **Verification gaps** — the deposit-policy "atomic audit" test asserts the rows exist; it
   does not inject a rollback failure. Live API browser coverage of these screens requires
   `E2E_LIVE_API=1`; the deposit UI tests mock HTTP transport and prove UI behavior only.

## Local verification safety

`backend/.env` may point at production. Local database tests use an explicit process
environment derived from `backend/.env.kasher`: localhost-only DSN, the `sales_app` role,
`ENVIRONMENT=test`, dotenv loading disabled, and a live check that the connected role is
neither superuser nor BYPASSRLS. Never print credential values.

Never run `scripts/provision.py` from a checkout holding production settings —
`provision.main()` writes the app DSN into `backend/.env`. Migrations carry their own RLS
half and guard grants with `pg_roles`, because CI runs `alembic upgrade head` before the
role exists. Route or schema changes require regenerating `desktop/openapi.lock.json`, and
`tests/test_module_boundaries.py` must not have its baseline raised to make this work fit.

## Official-platform research

Shopify separates authenticated customer-account capabilities from catalog and cart work,
and treats cart values as estimates rather than finalized purchase commitments. Intercom
documents explicit connector-failure handling and distinguishes procedure simulations from
end-to-end tests. Gorgias documents action conditions, confirmation for irreversible
operations, and cases where a platform action does not reach external fulfillment. All three
support the shape used here: small typed read-only tools, server-owned identity and facts,
explicit failure states, and execution gated behind checks the model cannot assert.

Sources checked 2026-11-05:

- [Shopify Customer Accounts MCP](https://shopify.dev/docs/apps/build/customer-accounts-mcp)
- [Shopify cart MCP](https://shopify.dev/docs/agents/carts-and-checkout/cart-mcp)
- [Shopify Ask](https://shopify.dev/docs/agents/ask)
- [Intercom data connectors FAQ](https://www.intercom.com/help/en/articles/9916507-data-connectors-faqs)
- [Intercom procedure simulations](https://www.intercom.com/help/en/articles/12599517-run-simulations-for-fin-procedures)
- [Gorgias AI actions](https://docs.gorgias.com/en-US/allow-ai-agent-to-perform-actions-567325)
- [Gorgias Shopify order changes](https://docs.gorgias.com/en-US/ai-agent-actions-make-changes-to-shopify-orders-757792)
