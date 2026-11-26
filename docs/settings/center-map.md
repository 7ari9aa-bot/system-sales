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
| 12 | **Channels & integrations** | Connected channels · WhatsApp Business · Facebook · Instagram · Data sync · External integrations · Connection health |
| 13 | **AI & agents** | Agent management · Customer Agent · Analytics Agent · Knowledge sources · Models and routing · Tools and permissions · Policies and safety · Testing and evaluation · Versions and publishing |
| 14 | **Analytics & reports** | Dashboards · Metrics and indicators · Reports · Scheduled reports · Analysis settings · Report permissions |
| 15 | **Automation & workflows** | Rules · Workflows · Triggers and events · Schedules · Approvals · Execution attempts |
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
| 04 Working hours | pending | no key exists yet: opening/closing time and closed days need a consumer before they can be offered |
| 04 Business policies | pending | no key exists yet: exchange, return and warranty policy need the orders/returns path to read them first |
| 05–20 | pending | see the tables above |

The remaining sections are built one at a time, each with the page anatomy in §3, its bilingual
copy, its tests, and the gates in [runtime-testing-specification.md](runtime-testing-specification.md).

**How a page is produced.** Every key declares its home in the registry (`section` + `page`, with
a domain default in `_DOMAIN_HOME` and per-key overrides where a domain spans pages). A Settings
Center page asks the server for `GET /settings/definitions?section=…&page=…` and renders exactly
those keys, so a control can only ever edit a setting whose canonical home is that page — the §4
"no duplicated setting" rule is enforced by construction rather than by review. `tests/test_settings_registry_homes.py`
fails if a registered key has no home, names a section outside the twenty, or could appear on two pages.
