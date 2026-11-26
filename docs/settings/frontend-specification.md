# Settings Frontend Specification

> **Status:** specification derived from actual frontend code.
> **Last updated:** 2026-11-26 · **Source:** `frontend/src/pages/settings/`, `frontend/src/components/settings/`, `frontend/src/cashier/components/settings/`

## 0. Purpose

This document maps every settings screen in the frontend, the navigation structure, how each
screen consumes the settings API, and the implementation status of each. It is derived from
the actual code — no screen is described as working unless the code shows it consuming the
backend settings endpoint.

---

## 1. Navigation Structure

Settings are mounted under `/settings/*` in `frontend/src/App.jsx`. The routes are:

| Route | Component | Priority |
|---|---|---|
| `/settings` | `ProfileSettings` | P1 |
| `/settings/workspace` | `WorkspaceSettings` | P1 |
| `/settings/channels` | `ChannelsSettings` | P1 |
| `/settings/channels/:channel` | `ChannelsSettings` | P1 |
| `/settings/ai` | `AI` | P2 |
| `/settings/usage` | `Usage` | P2 |
| `/settings/pos` | `PosSettings` | P1 |
| `/settings/pos/:section` | `PosSettings` | P1 |
| `/settings/policies` | `PoliciesSettings` | P1 |
| `/settings/billing` | `BillingSettings` | P3 |
| `/settings/members` | `MembersSettings` | P3 |
| `/settings/security` | `SecuritySettings` | P3 |
| `/settings/danger` | `DataSettings` (DangerZone) | P3 |
| `/settings/all` | `UnifiedSettings` | P3 |

There is also a legacy `Settings.jsx` at `/settings` (the old overview page) that has been
superseded by `ProfileSettings` as the default landing screen.

### Navigation grouping by priority

**P1 — Business Configuration (owner-facing, day-to-day):**
Profile, Workspace, Channels, POS, Policies. These are the screens a shop owner touches during
onboarding and daily operations.

**P2 — Communication & Intelligence:**
AI settings, Usage. These control the customer AI agent and analytics agent, and the tenant's
consumption of AI credits.

**P3 — Platform Management:**
Billing, Members, Security, Danger Zone. These are admin-level screens for account governance.

**Unified — All Settings:**
The `/settings/all` route (`UnifiedSettings`) is the single page that consumes the unified
`/settings/effective` endpoint for ALL domains at once, grouped by domain from the registry.
It uses the shared `useSettings` hook and replaces the need for per-domain API calls.

The `useSettings` hook (rev. 2026-11-26) now supports:
* **Scope selector** — `scope` and `scopeId` opts replace the old hardcoded `scope: "tenant"`.
  The UI renders a `ScopeSelector` dropdown (tenant, workspace, branch, warehouse, pos_profile,
  register, channel, user) and a free-text scope-id field for non-tenant scopes.
* **Segment filtering** — the active segment (retail, fnb, services, wholesale) is passed to
  both `/settings/definitions` and `/settings/effective` queries.
* **APPROVAL_REQUIRED handling** — settings whose `apply_mode` is `approval_required` show a
  badge and a "Request Change" button. Instead of silently failing in a bulk save, the hook
  calls `POST /settings/change-requests` and exposes `changeRequests` state (pending/approved/
  rejected) with inline approve/reject buttons for a second admin.
* **Preview / dry-run before save** — a `PreviewPanel` component shows each dirty key's current
  vs. new value, the active scope, and whether it needs approval — modelled on the preset
  `preview_preset` dry-run shape.
* **Optimistic concurrency (409)** — `expected_history_ids` are sent with every bulk save. A
  409 response surfaces a `conflict` banner ("someone edited before you, refresh to update").

---

## 2. API consumption patterns

The frontend has two patterns for reading settings:

### Pattern A: Per-domain API (majority of screens)

Most settings screens call domain-specific endpoints (`/pos/settings`, `/policies`, etc.)
that return pre-resolved settings bundled with other business data. These endpoints read
from the settings registry internally but expose a domain-shaped response.

**Status:** ✅ working — but this means the frontend does NOT use the unified
`/settings/effective` endpoint for most screens. A change to a setting key requires a
matching change in the domain API, creating drift risk.

### Pattern B: `/settings/effective` (unified settings API)

A growing number of components consume the unified endpoint directly:

| Component | Call | Keys/Domain |
|---|---|---|
| `components/settings/useSettings.js` | `api("/settings/definitions")` + `api("/settings/effective")` + `api("/settings/change-requests")` | ALL domains (shared hook) |
| `components/settings/BrandColorCard.jsx` | `api("/settings/effective/organization.brand_color")` | Single key |
| `components/settings/AnalyticsAgentCard.jsx` | `api("/settings/effective?domain=analytics_agent")` | Domain |
| `components/settings/OrganizationBranchCard.jsx` | `api("/settings/effective?domain=organization")` + `?domain=branch` | Two domains |
| `cashier/components/settings/ShopPolicySettings.jsx` | `api("/settings/definitions?domain=...")` + `api("/settings/effective?domain=...")` | Domain (definitions + effective) |
| `cashier/api/useShifts.js` | `api("/settings/effective?keys=pos.variance_reason_required,pos.variance_approval_threshold")` | Multiple keys |

**Status:** 🟡 growing — 6 consumers use `/settings/effective`. The `useSettings` shared hook
is the canonical way for new screens to consume settings; it fetches all definitions and
effective values in two calls, groups by domain, and exposes a save function. The P3 goal is
to unify all settings screens to consume `/settings/effective` via this hook.

---

## 3. Screen-by-screen status

### P1 — Business Configuration

#### ProfileSettings (`/settings`)
**Status:** ✅ working

Manages the business profile: legal name, trade name, tax ID, address, phone, email, website.
Consumes per-domain APIs for business profile data. The `BrandColorCard` sub-component
reads `organization.brand_color` via `/settings/effective/organization.brand_color`.

Keys consumed: `business.*` (11 keys), `organization.brand_color`.

#### WorkspaceSettings (`/settings/workspace`)
**Status:** ✅ working

Manages workspace-level configuration: multi-branch toggle, max branches, fiscal year start,
default language. The `OrganizationBranchCard` sub-component reads `organization` and `branch`
domains via `/settings/effective?domain=...`.

Keys consumed: `organization.*` (5 keys), `branch.*` (4 keys).

#### ChannelsSettings (`/settings/channels`)
**Status:** ✅ working

Manages channel connections (WhatsApp, Instagram, Messenger, Telegram, web chat). Does not
read from the settings registry — channel state is managed through the integrations API
(`/integrations`). The `ChannelCapabilities` sub-component reads capability settings.

Keys consumed: `capability.*` (8 keys, via the capabilities API).

#### PosSettings (`/settings/pos`)
**Status:** ✅ working

The POS settings screen. Has sub-sections (`/settings/pos/:section`) for devices, receipt
format, and payment methods. The cashier app has its own settings components under
`cashier/components/settings/` that consume `/settings/effective?domain=pos` and
`/settings/definitions?domain=pos`.

Keys consumed: `pos.*` (16 keys), `print.*` (8 keys), `einvoice.*` (15 keys).

#### PoliciesSettings (`/settings/policies`)
**Status:** ✅ working

Manages inventory and order policies: auto-reserve, FIFO, return windows, purchasing rules.
Consumes per-domain APIs.

Keys consumed: `inventory.*` (12 keys), `orders.*` (3 keys), `purchasing.*` (5 keys),
`catalog.*` (5 keys).

### P2 — Communication & Intelligence

#### AI Settings (`/settings/ai`)
**Status:** ✅ working

Controls the customer AI agent and analytics agent. The `AnalyticsAgentCard` sub-component
reads `analytics_agent` domain via `/settings/effective?domain=analytics_agent`. The dialect
setting (`customer_agent.dialect`) is managed via a dedicated `dialectSetting.js` helper.

Keys consumed: `customer_agent.*` (8 keys), `analytics_agent.*` (4 keys).

#### Usage (`/settings/usage`)
**Status:** ✅ working

Shows AI credit consumption, conversation counts, and team seat usage. Reads from the
usage API (`/usage`), not the settings registry.

### P3 — Platform Management

#### BillingSettings (`/settings/billing`)
**Status:** ✅ working

Manages billing preferences: auto-renew, currency, renewal reminders. Consumes per-domain
billing API.

Keys consumed: `billing.*` (3 keys).

#### MembersSettings (`/settings/members`)
**Status:** ✅ working

Manages team members and roles. Reads `team.*` settings (default role, allow invites) via
the members API. The session timeout and 2FA settings are enforced backend-side.

Keys consumed: `team.*` (4 keys).

#### SecuritySettings (`/settings/security`)
**Status:** ✅ working

Manages security policies: strong passwords, API key rotation period, IP allowlist, audit
retention. Reads from the security domain API.

Keys consumed: `security.*` (4 keys).

#### DangerZoneSettings (`/settings/danger`)
**Status:** ✅ working

Archive/workspace deletion. Does not read from the settings registry.

---

## 4. `/settings/effective` endpoint usage

The unified settings endpoint (`GET /settings/effective`) resolves settings through the
hierarchical scope chain and returns effective values. It supports:

* `?domain=pos` — all keys in a domain
* `?keys=key1,key2` — specific keys
* `/settings/effective/{key}` — a single key

### Current adoption

| Component | Pattern | Keys/Domain |
|---|---|---|
| BrandColorCard | single key | `organization.brand_color` |
| AnalyticsAgentCard | domain | `analytics_agent` |
| OrganizationBranchCard | domain × 2 | `organization`, `branch` |
| ShopPolicySettings (cashier) | definitions + effective | `pos` domain |
| useShifts (cashier) | multiple keys | `pos.variance_reason_required`, `pos.variance_approval_threshold` |

### Migration target (P3)

All settings screens should migrate from per-domain APIs to `/settings/effective` so a
settings key change does not require a matching API change. The migration is incremental:
each screen switches its read path, and the per-domain API is retired once no frontend
code references it.

---

## 5. i18n

Settings labels are maintained in `frontend/src/lib/i18n/ar.js` and `en.js`. The registry
itself carries `label_ar` and `label_en` on every `SettingDef`, but the frontend does not
yet render from registry labels — it uses its own i18n strings. Keeping both in step is a
manual responsibility (no CI guard yet).

---

## 6. Gaps

| Gap | Priority | Status |
|---|---|---|
| Most screens use per-domain APIs, not `/settings/effective` | P3 | 🟡 partial — `useSettings` hook + `UnifiedSettings` page now exist |
| Frontend i18n labels not synced with registry labels | P3 | 🟡 partial — `UnifiedSettings` renders from registry labels |
| No CI guard for frontend settings API consumption | P3 | ❌ missing |
| `security.audit_retention_days` has no frontend screen | P3 | ✅ resolved — visible on `/settings/all` |
| No frontend screen for `notifications.email_enabled` / `push_enabled` toggles | P3 | ✅ resolved — visible on `/settings/all` |
| Settings page hardcoded to `scope: "tenant"` | P3 | ✅ resolved — `ScopeSelector` component added (2026-11-26) |
| No segment filtering in unified settings | P3 | ✅ resolved — segment dropdown added to `UnifiedSettings` (2026-11-26) |
| APPROVAL_REQUIRED settings silently rejected in bulk save | P3 | ✅ resolved — "Request Change" button + `ChangeRequestList` with approve/reject (2026-11-26) |
| No preview before save | P3 | ✅ resolved — `PreviewPanel` shows current/new values, scope, approval flag (2026-11-26) |
| No 409 conflict handling | P3 | ✅ resolved — `conflict` banner with refresh prompt (2026-11-26) |
| Component tests for settings UI | P3 | ✅ resolved — 14 tests across 3 files (2026-11-26) |
