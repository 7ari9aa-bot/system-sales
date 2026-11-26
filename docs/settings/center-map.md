# Settings Center — the map / خريطة مركز الإعدادات

> **Status:** live — the target information architecture for the Settings Center, and the
> build order that closes the gap between it and the code.
> **Last updated:** 2026-11-26 · **Owner's proposal:** Hamed, 2026-11-26

This document is the **navigation contract**. `frontend-specification.md` says what each screen
consumes today; this one says what the Settings Center is supposed to look like when it is
finished, section by section, so that no page is invented twice and no setting is homeless.

Twenty sections in five groups. They are **navigation groups**, not twenty sibling pages.

---

## 1. Groups and sections

### Group 1 — Account and administration

| # | Section | Pages |
|---|---|---|
| 01 | **My Account** — everything about the signed-in person, whatever workspace they are in | Profile · Sign-in · Personal security · Preferences · Personal notifications |
| 02 | **Workspace** — the organisational container, which may hold more than one business | Overview · Workspace data · Ownership and administration · Manage workspaces · Workspace settings |
| 03 | **Team & permissions** — who exists and what they may do | Members · Invitations · Roles · Permission matrix · Teams and departments · Access scope |

### Group 2 — Business and structure

| # | Section | Pages |
|---|---|---|
| 04 | **Store & business** — identity and the facts used inside the system and in front of customers | Business profile · Brand identity · Contact details · Working hours · Business policies · Legal data |
| 05 | **Locations** — the physical structure | All branches · Branch data · Branch hours · Branch settings · Branch staff · Operating scopes |

A **branch**, a **warehouse** and a **register** are three different things. A branch may own one
warehouse and several registers; they are not the same entity and must not share a page.

### Group 3 — Commerce and operations

| # | Section | Pages |
|---|---|---|
| 06 | **Products & catalog** | Product settings · Categories · Variants and options · Attributes and specs · SKU and barcode · Images and media · Product states |
| 07 | **Sales, pricing and tax** — the rules of selling, not the act of selling | Sales settings · Price lists · Pricing · Discounts and offers · Taxes and fees · Exchange and returns |
| 08 | **POS & registers** — configuring the till, not building a payment processor | POS settings · Registers and devices · Collection methods · Shifts · Cash movement · Invoices and receipts · Peripherals · Offline mode |
| 09 | **Inventory & warehousing** | Inventory settings · Warehouses · Stock states · Stock limits · Counts and adjustments · Transfers · Inventory cost |
| 10 | **Purchasing & suppliers** | Suppliers · Purchasing settings · Purchase orders · Receiving and inspection · Supplier returns · Approval limits |
| 11 | **Customers & support** — the customer relationship; the agent's behaviour lives in 13 | Customer data · Customer segments · Customer records · Inbox · Conversation routing · Reply templates · Support hours · Escalation to a human |

### Group 4 — Channels and intelligence

| # | Section | Pages |
|---|---|---|
| 11 Customer data | done | `/settings/customers/customer-data` — the real contact-quality work queue from `GET /customers/contact-data-issues` (name, phone, phone state); the fix happens on the customer's own record, which the page says |
| 11 Customer segments | done | `/settings/customers/customer-segments` — the segments in force from `GET /segments`; a segment is its rule set, so the page shows them and points at the screen that creates them |
| 11 Customer records | done | `/settings/customers/customer-records` — the real customer list from `GET /customers` with state and contact number |
| 11 Inbox | done | `/settings/customers/inbox` — the live inbox read model (`GET /conversations`: channel, state, unread), so the page answers "what is the load" rather than pretending to configure it |
| 11 Conversation routing | done | `/settings/customers/conversation-routing` — the response-time policies routing works to (`GET /sla/policies`, optionally per channel); assigning staff stays on `/settings/team/access` |
| 11 Reply templates | done | `/settings/customers/reply-templates` — the real templates from `GET /message-templates` with their language and approval state |
| 11 Support hours | done | `/settings/customers/support-hours` — reads the published `hours` store policy and LINKS to its single editor on `/settings/store/working-hours`; a second editor here would be the duplicate the Center exists to prevent |
| 11 Escalation to a human | done | `/settings/customers/escalation-to-human` — edits the real `sla_policies` rows through `GET`/`PUT /sla/policies` (first response, resolution, per channel). The agent's own handover behaviour stays in section 13 and is linked |
| 12 Connected channels | done | `/settings/channels` — the existing channels screen, unchanged: one row per channel, its connect state and the manual actions. A channel's identity is its `integrations` row, never its warehouse |
| 12 WhatsApp Business | done | `/settings/channels/whatsapp` — the same screen focused on one channel (`/settings/channels/:channel` already existed), with its diagnostics, reconnect plan and the WhatsApp roadmap endpoint behind it |
| 12 Facebook | done | `/settings/channels/facebook` — one channel, its page permissions (`missing_scopes`) and diagnostics; a non-empty list means "connect again", which the screen says |
| 12 Instagram | done | `/settings/channels/instagram` — one channel, same diagnostics, plus the Instagram login path the module already implements |
| 12 Data sync | done | `/settings/channels/data-sync` — what each channel is receiving: webhook state and the timestamp of the last event that really arrived (`GET /integrations`) |
| 12 External integrations | done | `/settings/channels/external-integrations` — the integrations whose kind is not `channel`, with state and credential verification. Credentials never leave the server: the list returns `credentials_verified`, never the secret |
| 12 Connection health | done | `/settings/channels/connection-health` — every channel's state, verification and missing scopes in one place, reusing `ChannelDiagnostics` rather than a second check |
| 12 | **Channels & integrations** | Connected channels · WhatsApp Business · Facebook · Instagram · Data sync · External integrations · Connection health |
| 13 Agent management | done | `/settings/ai/agent-management` — every agent from `GET /ai/agents`: kind, model, version. Editing and publishing stay on the agents screen; this is the governance view |
| 13 Customer Agent | done | `/settings/ai/customer-agent` — the customer agent row only (`kind === "customer"`), with the boundary written as design: answers enquiries, reads text/images/voice, finds products, shows pictures, hands over to a human; it does NOT add to cart, create an order or take payment. Handover behaviour stays in section 11 and is linked |
| 13 Analytics Agent | done | `/settings/ai/analytics-agent` — the analytics agent row only, with the rule that every figure it reports is backed by evidence, never a model guess. Report settings stay in section 14 |
| 13 Knowledge sources | done | `/settings/ai/knowledge-sources` — the real knowledge rows from `GET /ai/knowledge` (title, source type, state, visibility); store policies are the same store and keep their editor in section 04 |
| 13 Models and routing | done | `/settings/ai/models-and-routing` — the provider egress policy from `GET /ai/provider-policies`: allowed/denied, allowed models, data classification, whether redaction is required |
| 13 Tools and permissions | done | `/settings/ai/tools-and-permissions` — each agent's execution ceiling (max output tokens, run limit). Tools are declared per agent kind in code rather than a table edited from a screen, which the page says instead of showing an empty editor; agent permissions stay independent of staff permissions |
| 13 Policies and safety | done | `/settings/ai/policies-and-safety` — the safety envelope per agent: temperature, max output tokens, `run_limits` (the real ceiling on every execution) and the `is_active` kill switch |
| 13 Testing and evaluation | done | `/settings/ai/testing-and-evaluation` — the evaluations from `GET /ai/evaluations` with prompt version, status and rollout state (canary/full/rolled back), which is what gates publishing |
| 13 Versions and publishing | done | `/settings/ai/versions-and-publishing` — each agent's version and state; the version is the concurrency token that stops one edit overwriting another, and publishing runs on the publish path after a passing evaluation |
| 13 | **AI & agents** | Agent management · Customer Agent · Analytics Agent · Knowledge sources · Models and routing · Tools and permissions · Policies and safety · Testing and evaluation · Versions and publishing |
| 14 Dashboards | done | `/settings/analytics/dashboards` — the live overview from `GET /analytics/overview`, rendered as the figures the engine returned rather than a hand-written tile list |
| 14 Metrics and indicators | done | `/settings/analytics/metrics-and-indicators` — the metric definitions the engine actually computes (`GET /analytics/metrics/definitions`), so no indicator is computed twice in two ways |
| 14 Reports | done | `/settings/analytics/reports` — the revenue summary from `GET /analytics/revenue/summary`, produced from the real order and invoice rows |
| 14 Scheduled reports | pending | No report scheduler exists: the repo has no scheduler module and no stored report job, so a schedule editor here would write rows nothing reads. Needs a report job table plus a worker before the page is real |
| 14 Analysis settings | pending | There is no analysis configuration to edit: periods, groupings and thresholds are arguments of the analytics calls, not stored settings. `GET /analytics/retention` and its per-class policies are real but belong to section 17 |
| 14 Report permissions | pending | Report visibility is not modelled: there is no per-report or per-dashboard grant, so the page would be a second, weaker copy of the team roles in section 02 |
| 14 | **Analytics & reports** | Dashboards · Metrics and indicators · Reports · Scheduled reports · Analysis settings · Report permissions |
| 15 Rules | done | `/settings/automation/rules` — a rule IS a workflow with a trigger event, so the page reads `GET /automation` (name, trigger event, state) instead of inventing a second rule table computed alongside the engine |
| 15 Workflows | done | `/settings/automation/workflows` — every workflow with its state and current version; a running execution stays on the version it started with |
| 15 Triggers and events | done | `/settings/automation/triggers-and-events` — the trigger events the engine really fires (`trigger_event`, e.g. `order.created`), not a list of theoretical events |
| 15 Schedules | pending | The engine triggers on events only: there is no time-based trigger and no stored schedule, so a schedule editor here would write rows no worker reads. Needs a scheduled trigger type in the engine first |
| 15 Approvals | pending | The automation engine has no approval step: a workflow's definition is steps and conditions, with no gate that waits for a person. The approvals that DO exist are the settings change workflow's, and they belong to section 18 |
| 15 Execution attempts | done | `/settings/automation/execution-attempts` — `GET /automation/{id}/executions` per workflow: state, version, start time and the stored `error`, because "it failed" without the reason is not an attempt record |
| 15 | **Automation & workflows** | Rules · Workflows · Triggers and events · Schedules · Approvals · Execution attempts |
| 16 Notification channels | done | `/settings/notifications/notification-channels` — `notifications.email_enabled` and `notifications.push_enabled`, the two switches `notifications/service.py::dispatch` and the delivery worker actually read |
| 16 Notification rules | done | `/settings/notifications/notification-rules` — `notifications.order_received` (orders/service.py) and `notifications.low_stock_alert` (the scheduler worker), the two rules that fire without a person asking |
| 16 Message templates | done | `/settings/notifications/message-templates` — links to the single template editor in section 11. The wording is the shop's voice, not workspace notification policy, so this page refuses to open a second editor |
| 16 Recipients | done | `/settings/notifications/recipients` — links to each person's own notification preferences in section 01. Who receives what is that person's choice, and the dispatcher already honours it, so a workspace-level recipient list would override a person with a setting |
| 16 Alerts and escalation | done | `/settings/notifications/alerts-and-escalation` — `quiet_hours_start`, `quiet_hours_end` and `digest_mode`, the three terms `notifications/digest.py::should_send_immediately` reads |
| 16 | **Notifications** — workspace rules, where 01 holds the person's preferences | Notification channels · Notification rules · Message templates · Recipients · Alerts and escalation |

Agent boundaries are part of the design, not a prompt detail:

- **Customer Agent** answers enquiries, understands text, images and voice, finds products and
  shows their pictures, and may hand over to a human. It does **not** add to cart, create orders,
  take payment or sell.
- **Analytics Agent** analyses and reports, and every figure it gives is backed by evidence — it
  never presents an LLM guess as an account.
- Agent permissions are **independent of staff permissions** and are declared per agent type.

### Group 5 — Advanced administration

| # | Section | Pages |
|---|---|---|
| 17 Import | done | `/settings/data/import` — the real import sessions from `GET /imports/sessions` (state, where each got to), plus `imports.legacy_csv_endpoint`, the one import setting the registry carries |
| 17 Export | pending | No export engine exists: an export is a job that must be generated and run, and there is no export job table and no worker reading one. The page says so plainly instead of offering a button that does nothing |
| 17 Retention | done | `/settings/data/retention` — `GET /analytics/retention`, the position the retention worker runs on; the policy is written through `PUT /analytics/retention/policies/{data_class}`, the same endpoint the worker reads |
| 17 Backups and restore | pending | No backup or restore system exists in the product: backup belongs to the database and host layer, restore is a catastrophic procedure needing approval and a record, and there is no backup table or restore path to drive |
| 17 Data privacy | done | `/settings/data/data-privacy` — the consents actually recorded (`GET /privacy/consents`); withdrawal is an event on the record, not an erasure of history |
| 17 Data deletion | done | `/settings/data/data-deletion` — the data requests and their state (`GET /privacy/data-requests`); execution runs on `POST /privacy/data-requests/{id}/execute` after review, never from a click on the settings page |
| 17 | **Data & privacy** | Import · Export · Retention · Backups and restore · Data privacy · Data deletion |
| 18 | **Security & governance** | Security policies · Session control · Audit log · Settings change log · Approval requests · Sensitive settings · Emergency procedures |
| 19 | **Plan & billing** | Current plan · Usage · Invoices · Payment methods · Billing details · Renewal and upgrade |
| 20 | **Developers & API** — hidden from ordinary users; shown only to developer/integration roles | API keys · Webhooks · Connected apps · Rate limits · API logs · Developer environment |

Section 18 is where the existing Settings Engine (approvals, change history, sensitive keys,
restore) becomes visible to the merchant. Section 20 is the only section that may be hidden by
role rather than by plan.

---

## 2. Scope model — every setting declares where it may live

The one failure mode a centre of this size must not have: a value changed in one place that
silently changes a branch, a register or a channel.

```
Platform · Workspace/Tenant · Store · Branch · Register · Channel · Agent · User
```

This is a **set of allowed paths per setting**, not one inheritance tree. Each setting declares:

- may it be set at workspace level?
- may it be overridden per store?
- per branch? per register?
- is it channel- or agent-specific?
- is it personal, and therefore unaffected by the workspace?

Example: receipt layout defaults at the business level, with an exception for one branch or one
register. The person's own language must never change because they moved to another branch.

---

## 3. Anatomy of a settings page

Every page, whatever it configures, answers the same questions in the same order:

1. what this setting does, in one line;
2. grouped, comprehensible controls;
3. the current effective value **and where it comes from**;
4. inherited or overridden — visibly;
5. who may read it and who may change it;
6. validation before saving;
7. the impact of the change when it is not obvious;
8. immediate save, or a change request when the change is risky;
9. history and restore where supported;
10. clear success and error messages.

## 4. Rules that bind every section

1. **No duplicated setting.** One canonical home; another page may link to it, never edit it.
2. **Settings vs operational data.** The low-stock *rule* is a setting; the stock *quantity* is
   operational data. The barcode *format* is a setting; a product's barcode is product data.
3. **Per-section permissions.** Reading, writing and approving are three different rights.
4. **High-risk settings need extra protection** — tax, return policy, cash limits, sensitive
   permissions, channel credentials, agent knowledge sources.
5. **No single inheritance path.** POS settings, inventory settings and personal preferences each
   have their own valid scope paths.
6. **Merchant surface and platform surface stay apart.** Plans, central model settings,
   infrastructure and tenant administration belong to a separate Platform Admin control plane,
   never to a store's settings.

## 5. One engine, many screens

```
Settings Center (frontend: sections, search, forms, visibility)
        ↓
Settings API & application services (read/write, validation, change requests, approvals)
        ↓
Registry · Scope resolver · Policy engine · Validation engine · History & audit · Change workflow
        ↓
Postgres configuration store  →  outbox/events  →  workers, caches, consumers
```

The **registry is the source of truth**: `key`, `section`, `page`, `type`, `default_value`,
`allowed_scopes`, `validation`, `permission`, `sensitive`, `approval_policy`, `dependencies`,
`impact_level`, `status`. A key with no owner, or a control on a screen that changes nothing, is a
defect. See [registry-specification.md](registry-specification.md) for the keys that exist today.

---

## 6. Build status

| Section | State | Where |
|---|---|---|
| 01 Profile | done | `/settings` — photo, name, email, phone, job title, verification, account closure |
| 01 Sign-in | done | `/settings/login` — password change, sign-in method, recovery |
| 01 Personal security | done | `/settings/security` — two-step verification, signed-in devices |
| 01 Preferences | done | `/settings/preferences` — language, appearance, the person's own timezone, date format, landing page; stored on the account (migration fe2026112610) |
| 01 Personal notifications | done | `/settings/notifications` — email/push switches (in-app locked as the record), quiet hours as real times read in the person's own zone; `GET`/`PUT /users/me/notification-preferences`; one row per person (migration fe2026112611) and the dispatcher now honours it |
| 02 Workspace overview | done | `/settings/workspace` — the container, its state, your role in it, member count, region |
| 02 Workspace data | done | `/settings/workspace/data` — name (editable), identifier (read-only: other systems address it), country/currency/timezone; brand logo stays in Store & business, where the identity belongs |
| 02 Ownership and administration | done | `/settings/workspace/ownership` — owner and administrators from `GET /workspaces/current/admins` (settings read); transfer is explained, not offered, because no transfer endpoint exists behind it |
| 02 Manage workspaces | done | `/settings/workspace/switch` — every membership from `GET /workspaces`, entering one through `POST /auth/switch-tenant` |
| 02 Workspace settings | done | `/settings/workspace/defaults` — the inherited values read-only, each with a link to the single page that owns it |
| 03 Members | done | `/settings/team/members` (and `/settings/members`) — the real roster with a working role change (`PUT /tenants/{id}/members/{user_id}`, rank-guarded) and removal (`DELETE`, refused for the owner and for yourself) |
| 03 Invitations | done | `/settings/team/invitations` — create through `POST /tenants/{id}/invitations`, copy the one-time link, list and revoke; seat limits still enforced server-side |
| 03 Roles | done | `/settings/team/roles` — the seeded roles and the permission count each actually carries, from `GET /roles/matrix`; read-only because the guards are written against these codes |
| 03 Permission matrix | done | `/settings/team/matrix` — every real permission row against every role, read/write/approve shown as distinct actions; ticks come from `role_permissions`, so no cell can promise an unchecked action |
| 03 Teams and departments | done | `/settings/team/groups` — real teams (migration fe2026112612, tenant RLS on both tables) with add/remove members; a team grants nothing by design and the page says so |
| 03 Access scope | done | `/settings/team/access` — per-branch grants through `/hierarchy/locations/{id}/access`; warehouses and tills stay on their own pages |
| 04 Business profile | done | `/settings/store/business-profile` — trade name, business type, vertical, setup state, the shop's default language and the capability switches, rendered from the registry |
| 04 Brand identity | done | `/settings/store/brand-identity` — the brand colour (`organization.brand_color`) |
| 04 Contact details | done | `/settings/store/contact-details` — phone, email, website and address lines, tenant and branch scoped |
| 04 Legal data | done | `/settings/store/legal-data` — legal name, tax ID, commercial register, terms acceptance; all four already reach the receipt read model |
| 04 Working hours | done | `/settings/store/working-hours` — publishes the `hours` store policy, the text the customer agent answers "when are you open" from. Not a registry key: the promise is prose the agent quotes, and it lives in one row of `knowledge_items` |
| 04 Business policies | done | `/settings/store/business-policies` — the enforced windows (`pos.return_max_days`, `pos.exchange_max_days`, both high impact) plus the published exchange, return, warranty, cancellation, shipping and ordering policies and the deposit rules |
| 05 All branches | done | `/settings/locations/all-branches` — the branches that exist, read from the hierarchy (`workspaces` → `locations`) beside the keys that limit how many there may be |
| 05 Branch settings | done | `/settings/locations/branch-settings` — the four `branch.*` keys at branch scope |
| 05 Branch data | done | `/settings/locations/branch-data` — name, code and "this branch trades", written through `PATCH /hierarchy/locations/{id}` |
| 05 Branch hours | done | `/settings/locations/branch-hours` — the branch's own week in the new `locations.hours` column (migration `fe2026112613`); empty means "follows the store", which is what every existing row says |
| 05 Branch staff | done | `/settings/locations/branch-staff` — the real grants: list, grant with a per-branch role override, revoke, over `user_location_access` |
| 05 Operating scopes | done | `/settings/locations/operating-scopes` — read-only: every key that accepts a branch value, its resolved value and whether it was inherited, set for the branch, or is the default |
| 06 Product settings | done | `/settings/catalog/product-settings` — `catalog.default_tax_rate` (high impact: it lands on every new product) |
| 06 Categories | done | `/settings/catalog/categories` — the real category list from `GET /catalog/categories`, with add; ordering and linking stay in the catalogue screen, which is where shop data belongs |
| 06 Variants and options | done | `/settings/catalog/variants-and-options` — `catalog.max_variants_per_product` |
| 06 Attributes and specs | done | `/settings/catalog/attributes-and-specs` — the shop's own size sets and colours (`GET/PUT/DELETE /catalog/apparel/options`), the apparel case: defined once, used by thousands of products |
| 06 SKU and barcode | done | `/settings/catalog/sku-and-barcode` — `catalog.sku_format` and `catalog.barcode_auto_generate`: the FORMAT, never a product's own barcode |
| 06 Product states | done | `/settings/catalog/product-states` — `catalog.show_out_of_stock` |
| 06 Images and media | pending | no media rule exists to edit (limits, ordering, placeholders are per-product data today); a page here would be switches wired to nothing |
| 07 Sales settings | done | `/settings/sales/sales-settings` — `orders.reserve_on`, `orders.deduct_stock_on`, `orders.allow_backorder` |
| 07 Taxes and fees | done | `/settings/sales/taxes-and-fees` — the fifteen `einvoice.*` keys, with `vat_category` and `prices_include_vat` marked high impact because they change what the customer is charged |
| 07 Exchange and returns | done | `/settings/sales/exchange-and-returns` — reads the windows in force (`GET /settings/effective`) and LINKS to their single home on `/settings/store/business-policies`; it offers no second editor |
| 07 Price lists | done | `/settings/sales/price-lists` — `pricing.price_lists_enabled` plus a panel over the new `price_lists` / `price_list_items` tables (`GET/POST /pricing/price-lists`, archive, items). Migration `fe2026112614` |
| 07 Pricing | done | `/settings/sales/pricing` — `pricing.quantity_tiers_enabled`, `pricing.round_prices_to`, `pricing.allow_price_below_cost` (high impact), all read by `PricingService.resolve` |
| 07 Discounts and offers | done | `/settings/sales/discounts-and-offers` — `pricing.auto_apply_offers`, `pricing.stacked_discounts`, `pricing.max_order_discount_pct` (high impact) plus a panel over `discount_rules` (`GET/POST /pricing/discount-rules`, pause/resume). The till's own cap stays in section 08 |
| 07 Pricing engine | done | `app/modules/pricing/` — `PricingService.resolve` (which list wins, tier, rounding) and `.quote` (which offers run, stacking, both caps), `POST /pricing/quote`. Migration `fe2026112614` adds `price_lists`, `price_list_items`, `discount_rules` with CHECK constraints for the shapes that cannot mean anything |
| 08 POS settings | done | `/settings/pos/pos-settings` — customer required, hold cart, restock default, cash-only refunds, return reasons, record-only sales; `pos.max_discount_pct` is here and now high impact |
| 08 Registers and devices | done | `/settings/pos/registers-and-devices` — reuses the till's existing `DevicesSection` (profiles, registers, warehouses, members) rather than growing a second register editor |
| 08 Collection methods | done | `/settings/pos/collection-methods` — `take_payments`, `settle_payment_methods` (high impact), `allow_sale_on_account`, `reference_required_methods` |
| 08 Shifts | done | `/settings/pos/shifts` — `variance_reason_required`, `variance_approval_threshold` (high impact) |
| 08 Cash movement | done | `/settings/pos/cash-movement` — `cash_movement_limit` (high impact) |
| 08 Invoices and receipts | done | `/settings/pos/invoices-and-receipts` — the eight `print.*` keys |
| 08 Peripherals | pending | no peripheral configuration is stored anywhere: the printer and drawer are driven by the print keys and the device's own settings |
| 08 Offline mode | pending | the till has no offline queue or offline policy in the codebase, so a page would be a switch wired to nothing |
| 09 Inventory settings | done | `/settings/inventory/inventory-settings` — `inventory.track_locations`, `inventory.show_channel_allocation`, `inventory.show_units_of_measure` |
| 09 Warehouses | done | `/settings/inventory/warehouses` — the active warehouses from `GET /inventory/warehouses`, with where they are really created and edited stated on the page |
| 09 Stock states | done | `/settings/inventory/stock-states` — `auto_reserve`, `reserve_ttl_minutes`, `expiry_alert_days`, `dead_stock_days`: how stock is classified, which is not the same question as how it is costed |
| 09 Stock limits | done | `/settings/inventory/stock-limits` — `inventory.safety_stock_default`, the rule behind a low-stock warning (the quantities themselves stay operational data) |
| 09 Counts and adjustments | done | `/settings/inventory/counts-and-adjustments` — `inventory.stocktake_approval_required` (high impact) over the real stocktake list from `GET /inventory/stocktakes` |
| 09 Transfers | done | `/settings/inventory/transfers` — `show_warehouse_transfers`, `quality_check_on_receipt` over the real transfer list from `GET /inventory/transfers` |
| 09 Inventory cost | done | `/settings/inventory/inventory-cost` — `inventory.fifo_enabled` (high impact: it decides how the cost of goods sold is worked out) |
| 10 Suppliers | done | `/settings/purchasing/suppliers` — reads `GET /purchasing/suppliers` (the real list) and says where a supplier is created |
| 10 Purchasing settings | done | `/settings/purchasing/purchasing-settings` — `purchasing.centralized` |
| 10 Purchase orders | done | `/settings/purchasing/purchase-orders` — reads `GET /purchasing/purchase-orders` with number, date, total, status and the DERIVED payment state |
| 10 Receiving and inspection | done | `/settings/purchasing/receiving-and-inspection` — `allow_partial_receipt`, `allow_over_receipt` |
| 10 Supplier returns | done | `/settings/purchasing/supplier-returns` — reads `GET /purchasing/supplier-returns` with number, date, total and status |
| 10 Approval limits | done | `/settings/purchasing/approval-limits` — `approval_required` and `approval_threshold`, both high impact: one removes approval entirely, the other sets the amount above which it applies |
| 18 Security policies | done | `/settings/security/security-policies` — the four `security.*` keys at their registry home: strong passwords, API key rotation, audit retention and the IP allowlist. All four are read by real code (`identity/services/auth.py`, `core/api_key_rotation.py`, the audit sweep, `identity/deps.py`), so none of them is a switch wired to nothing |
| 18 Session control | done | `/settings/security/session-control` — `GET /settings/security-posture`: the resolved `security.*` values plus the access and refresh token lifetimes the running process was started with. Read-only by design: the lifetimes are deployment configuration, and the page says so and links to the page that owns the editable half |
| 18 Audit log | done | `/settings/security/audit-log` — `GET /platform/audit-logs`, the tenant's audited actions with lineage and a bounded page |
| 18 Settings change log | done | `/settings/security/settings-change-log` — `GET /settings/history`, every value change with the old value, the new one and who wrote it |
| 18 Approval requests | done | `/settings/security/approval-requests` — `GET /settings/change-requests` with the engine's own approve/reject paths (`settings:approve`), so a high-impact key is reviewed where it already lives instead of on a second workflow invented here |
| 18 Sensitive settings | done | `/settings/security/sensitive-settings` — the keys the registry marks `sensitive`, whether each needs approval, and whether any module reads it (`enforced`). Read-only: the value is edited at the key's home, and the allowlist is never echoed |
| 18 Emergency procedures | done | `/settings/security/emergency-procedures` — `POST /settings/restore`, the tenant-wide snapshot restore that already existed: it writes forward-only history rows and audits itself. Branch and register overrides are deliberately out of scope, which the page states |
| 19 Current plan | done | `/settings/billing/current-plan` — the subscription row with its plan (name, price, currency, interval), status and period bounds from `GET /billing/subscription`, plus the three `billing.*` keys at their registry home. `auto_renew`, `currency` and `notify_before_renewal_days` are read by `billing/services/trial_expiry.py`, so they are switches with a reader |
| 19 Usage | done | `/settings/billing/usage` — `GET /billing/usage/summary`: every entitlement the plan granted, what this period used, and the limit. The number comes from `used_this_period`, the same call the entitlement gate refuses on, so a seat limit is counted from live rows rather than summed from usage |
| 19 Invoices | done | `/settings/billing/invoices` — `GET /billing/invoices`, bounded and validated (a negative limit is a 400, not "every row"). A closed period's frozen snapshot and an ordinary invoice are both listed: to the shop they are the same document |
| 19 Billing details | done | `/settings/billing/billing-details` — a link page, not an editor: the legal name, tax number, commercial register and address that print on an invoice are section 04's legal data, and a second copy here would be two tax numbers that can disagree |
| 19 Payment methods | pending | No payment instrument is stored anywhere: `invoices.provider` records who billed, never a card, and no provider is configured. A page of payment methods would be a form writing rows nothing charges |
| 19 Renewal and upgrade | pending | An upgrade is a checkout session, and the billing module has no checkout path until a payment provider is configured. What does exist — the auto-renew switch and the reminder window — is on `current-plan`, so this page would only repeat it |
| 20 API keys | pending | There is no key store: nothing in the schema issues, lists or revokes a developer API key, so the page would show a button that mints nothing. What DOES exist is the rotation policy (`security.api_key_rotation_days`, edited in section 18) and provider credentials rotated from the integration screen, so the page names both instead of inventing a third place |
| 20 Webhooks | done | `/settings/developers/webhooks` — the tenant's own outbound endpoints (`GET /webhook-endpoints`) plus a new delivery log (`GET /webhook-endpoints/deliveries`: status, attempts, response code, last error; the payload is never echoed back) |
| 20 Connected apps | done | `/settings/developers/connected-apps` — a link page: the connected services are the integration rows owned by section 12, and a second editor here would be the duplicate the map forbids |
| 20 Rate limits | done | `/settings/developers/rate-limits` — new `GET /platform/rate-limits` reports the middleware's own bucket table and window, and whether enforcement is on; a shop cannot raise its own ceiling, so the page reads and never edits |
| 20 API logs | done | `/settings/developers/api-logs` — `GET /platform/audit-logs?source=integration`: what changed without a person clicking. Request-level HTTP logs are not stored, and the page says so rather than presenting audit rows as traffic |
| 20 Developer environment | done | `/settings/developers/developer-environment` — the live API contract: the base URL this deployment serves and a link to its OpenAPI schema. There is no separate sandbox environment, and the page does not pretend there is |

The remaining sections are built one at a time, each with the page anatomy in §3, its bilingual
copy, its tests, and the gates in [runtime-testing-specification.md](runtime-testing-specification.md).

**Where the return promise lives.** A return is two objects, not one: the *window* the system
enforces (`pos.return_max_days`, read by `pos/service.py::return_policy` and printed on the receipt)
and the *wording* the customer agent quotes (the `return` policy row). Both are owned by
`04 Business policies` so the promise is read and written in one place. Section 07's
`exchange-and-returns` page links here; it must not offer a second editor for either.

**How a page is produced.** Every key declares its home in the registry (`section` + `page`, with
a domain default in `_DOMAIN_HOME` and per-key overrides where a domain spans pages). A Settings
Center page asks the server for `GET /settings/definitions?section=…&page=…` and renders exactly
those keys, so a control can only ever edit a setting whose canonical home is that page — the §4
"no duplicated setting" rule is enforced by construction rather than by review. `tests/test_settings_registry_homes.py`
fails if a registered key has no home, names a section outside the twenty, or could appear on two pages.
