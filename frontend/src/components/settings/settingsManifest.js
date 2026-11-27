import {
  BarChart3,
  Bell,
  Boxes,
  Building2,
  Code2,
  Database,
  KeyRound,
  MapPin,
  MessageSquare,
  Package,
  Receipt,
  ScanLine,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Store,
  Truck,
  User,
  UserRound,
  Users,
  Wallet,
  Workflow,
} from "lucide-react";
import { DEVELOPER_ROLES } from "@/lib/developerAccess";

/**
 * THE Settings Center manifest — the one place that says what the Center contains.
 *
 * Before this file the structure lived in four unrelated places that could each drift on
 * their own: this sidebar (`SettingsLayout`), the section tabs (`SettingsSection`'s
 * `SECTION_PAGES`), the router (`App.jsx`), and `docs/settings/center-map.md`. Adding a
 * section meant remembering all four, and the result was sections that existed in the
 * router but could not be reached from the navigation at all (team, customers, analytics,
 * automation, workspace notifications, data).
 *
 * The split of responsibility is deliberate and must stay:
 *
 *   - the BACKEND registry says what a setting IS (key, type, default, scopes, permissions,
 *     how a change is applied, which section+page owns it);
 *   - this manifest says how the Center is NAVIGATED (groups, sections, their landing route,
 *     who may see them).
 *
 * Neither may grow the other's job. A page's settings come from the registry; the entry that
 * leads to it comes from here. `settingsManifest.test.js` pins the parts a human forgets:
 * five groups, twenty sections, unique routes, every route registered in `App.jsx`, and every
 * label present in both languages.
 *
 * Group and section numbering follows `docs/settings/center-map.md`. When the map and this
 * file disagree, the map is the specification and this file is the bug.
 */

/** Five navigation groups. A group is a heading, never a page. */
export const SETTINGS_GROUP_KEYS = [
  "settings.group.admin",
  "settings.group.business",
  "settings.group.commerce",
  "settings.group.intelligence",
  "settings.group.advanced",
];

/**
 * The twenty sections, in map order.
 *
 * `to` is the section's LANDING page — the first page that is real today, never a route that
 * only redirects. `pages` lists the pages the section owns (only the live ones: a page the map
 * marks pending has nothing to edit and must not be a tab).
 */
export const SETTINGS_SECTIONS = [
  {
    id: "01",
    // Personal screens: they edit the signed-in person, not the shop, so no settings grant
    // gates them. A staff member with no settings code at all still changes their own password.
    personal: true,
    slug: "profile",
    labelKey: "settings.nav.profile",
    to: "/settings",
    icon: User,
    end: true,
    pages: ["profile", "sign-in", "personal-security", "preferences", "personal-notifications"],
  },
  {
    id: "02",
    slug: "workspace",
    labelKey: "settings.nav.workspace",
    to: "/settings/workspace",
    icon: Store,
    pages: ["overview", "data", "ownership", "switch", "defaults"],
  },
  {
    id: "03",
    slug: "team",
    labelKey: "settings.nav.team",
    to: "/settings/team/members",
    icon: Users,
    pages: ["members", "invitations", "roles", "matrix", "groups", "access"],
  },
  {
    id: "04",
    slug: "store",
    labelKey: "settings.nav.store",
    to: "/settings/store/business-profile",
    icon: Building2,
    pages: [
      "business-profile",
      "brand-identity",
      "contact-details",
      "working-hours",
      "business-policies",
      "legal-data",
    ],
  },
  {
    id: "05",
    slug: "locations",
    labelKey: "settings.nav.locations",
    to: "/settings/locations/all-branches",
    icon: MapPin,
    pages: [
      "all-branches",
      "branch-data",
      "branch-hours",
      "branch-settings",
      "branch-staff",
      "operating-scopes",
    ],
  },
  {
    id: "06",
    slug: "catalog",
    labelKey: "settings.nav.catalog",
    to: "/settings/catalog/product-settings",
    icon: Package,
    pages: [
      "product-settings",
      "categories",
      "variants-and-options",
      "attributes-and-specs",
      "sku-and-barcode",
      "product-states",
    ],
  },
  {
    id: "07",
    slug: "sales",
    labelKey: "settings.nav.sales",
    to: "/settings/sales/sales-settings",
    icon: Receipt,
    pages: [
      "sales-settings",
      "price-lists",
      "pricing",
      "discounts-and-offers",
      "taxes-and-fees",
      "exchange-and-returns",
    ],
  },
  {
    id: "08",
    slug: "pos",
    labelKey: "settings.nav.pos",
    to: "/settings/pos/pos-settings",
    icon: ScanLine,
    pages: [
      "pos-settings",
      "registers-and-devices",
      "collection-methods",
      "shifts",
      "cash-movement",
      "invoices-and-receipts",
    ],
  },
  {
    id: "09",
    slug: "inventory",
    labelKey: "settings.nav.inventory",
    to: "/settings/inventory/inventory-settings",
    icon: Boxes,
    pages: [
      "inventory-settings",
      "warehouses",
      "stock-states",
      "stock-limits",
      "counts-and-adjustments",
      "transfers",
      "inventory-cost",
    ],
  },
  {
    id: "10",
    slug: "purchasing",
    labelKey: "settings.nav.purchasing",
    to: "/settings/purchasing/purchasing-settings",
    icon: Truck,
    pages: [
      "suppliers",
      "purchasing-settings",
      "purchase-orders",
      "receiving-and-inspection",
      "supplier-returns",
      "approval-limits",
    ],
    // Record screens, not settings: the module that owns these rows is where they are
    // read and changed. The tab stays as a short link so an old bookmark still lands
    // somewhere true (the owner's rule: Settings configures, modules operate).
    links: {
      "suppliers": "/cashier/suppliers",
      "purchase-orders": "/cashier/purchases",
      "supplier-returns": "/cashier/supplier-returns",
    },
  },
  {
    id: "11",
    slug: "customers",
    labelKey: "settings.nav.customers",
    to: "/settings/customers/customer-data",
    icon: UserRound,
    pages: [
      // The router lands /settings/customers on customer-records, so that page is first: a
      // section's first page and its landing address are the same thing, and the manifest test
      // fails when they drift apart.
      "customer-records",
      "customer-data",
      "customer-segments",
      "inbox",
      "conversation-routing",
      "reply-templates",
      "support-hours",
      "escalation-to-human",
    ],
    // Record screens, not settings: the module that owns these rows is where they are
    // read and changed. The tab stays as a short link so an old bookmark still lands
    // somewhere true (the owner's rule: Settings configures, modules operate).
    links: {
      "customer-records": "/customers",
      "inbox": "/inbox",
    },
  },
  {
    id: "12",
    slug: "channels",
    labelKey: "settings.nav.channels",
    to: "/settings/channels",
    icon: MessageSquare,
    pages: [
      "connected-channels",
      "whatsapp",
      "facebook",
      "instagram",
      "telegram",
      "webchat",
      "data-sync",
      "external-integrations",
      "connection-health",
    ],
  },
  {
    id: "13",
    slug: "ai",
    labelKey: "settings.nav.ai",
    to: "/settings/ai",
    icon: Sparkles,
    // The nine pages the section really renders. The old four ("agents", "knowledge",
    // "provider-policies", "evaluations") were named after the ENDPOINTS, not after the pages,
    // so no tab could ever match a route: the section had no inner navigation at all.
    pages: [
      "agent-management",
      "customer-agent",
      "analytics-agent",
      "knowledge-sources",
      "models-and-routing",
      "tools-and-permissions",
      "policies-and-safety",
      "testing-and-evaluation",
      "versions-and-publishing",
    ],
  },
  {
    id: "14",
    slug: "analytics",
    labelKey: "settings.nav.analytics",
    to: "/settings/analytics/metrics-and-indicators",
    icon: BarChart3,
    // /settings/analytics/reports is the landing the router already redirects to.
    pages: ["reports", "dashboards", "metrics-and-indicators"],
    // Record screens, not settings: the module that owns these rows is where they are
    // read and changed. The tab stays as a short link so an old bookmark still lands
    // somewhere true (the owner's rule: Settings configures, modules operate).
    links: {
      "reports": "/cashier/reports",
      "dashboards": "/analytics",
    },
  },
  {
    id: "15",
    slug: "automation",
    labelKey: "settings.nav.automation",
    to: "/settings/automation/workflows",
    icon: Workflow,
    // /settings/automation/workflows is the landing the router already redirects to.
    pages: ["workflows", "rules", "triggers-and-events", "execution-attempts"],
    // Record screens, not settings: the module that owns these rows is where they are
    // read and changed. The tab stays as a short link so an old bookmark still lands
    // somewhere true (the owner's rule: Settings configures, modules operate).
    links: {
      "execution-attempts": "/automation",
    },
  },
  {
    id: "16",
    slug: "notifications",
    labelKey: "settings.nav.workspaceNotifications",
    to: "/settings/notifications/notification-channels",
    icon: Bell,
    pages: [
      "notification-channels",
      "notification-rules",
      "recipients",
      "alerts-and-escalation",
      "message-templates",
    ],
  },
  {
    id: "17",
    slug: "data",
    labelKey: "settings.nav.data",
    to: "/settings/data/data-privacy",
    icon: Database,
    // "backups-and-restore" is the offboarding screen (`DataSettings`), served by its own
    // route: the tab leads there, and /settings/danger forwards to it.
    // /settings/data/data-privacy is the landing the router already redirects to.
    pages: ["data-privacy", "import", "retention", "data-deletion", "backups-and-restore"],
  },
  {
    id: "18",
    slug: "security",
    labelKey: "settings.nav.governance",
    to: "/settings/security/security-policies",
    icon: ShieldCheck,
    pages: [
      "security-policies",
      "session-control",
      "audit-log",
      "settings-change-log",
      "approval-requests",
      "sensitive-settings",
      "emergency-procedures",
    ],
  },
  {
    id: "19",
    slug: "billing",
    labelKey: "settings.nav.billing",
    to: "/settings/billing/current-plan",
    icon: Wallet,
    pages: ["current-plan", "usage", "invoices", "billing-details"],
  },
  {
    id: "20",
    slug: "developers",
    labelKey: "settings.nav.developers",
    to: "/settings/developers/webhooks",
    icon: Code2,
    // The one section that is hidden by ROLE. The route guard in `SettingsSection` reads the
    // same list, so a typed address cannot open what the sidebar hides.
    roles: DEVELOPER_ROLES,
    pages: ["webhooks", "connected-apps", "rate-limits", "api-logs", "developer-environment"],
  },
];

/**
 * Section 01 is the signed-in person, so its five pages are navigation targets of their own:
 * a cashier looks for "my password" without knowing that "My account" is a section. Every
 * other section is one entry that lands on its first real page, and the section's own tabs
 * carry the rest — that is how the Center stays twenty sections instead of thirty siblings.
 */
export const ACCOUNT_PAGE_ITEMS = [
  { to: "/settings", icon: User, labelKey: "settings.nav.profile", end: true, personal: true },
  { to: "/settings/login", icon: KeyRound, labelKey: "settings.nav.login", personal: true },
  { to: "/settings/security", icon: ShieldCheck, labelKey: "settings.nav.security", personal: true },
  { to: "/settings/preferences", icon: SlidersHorizontal, labelKey: "settings.nav.preferences", personal: true },
  { to: "/settings/notifications", icon: Bell, labelKey: "settings.nav.notifications", personal: true },
];

const byId = (id) => SETTINGS_SECTIONS.find((section) => section.id === id);

/** The sidebar, generated. Group headings are the map's five; items are sections (01 expands). */
export const SETTINGS_NAV_GROUPS = [
  { key: "settings.group.admin", items: [...ACCOUNT_PAGE_ITEMS, byId("02"), byId("03")] },
  { key: "settings.group.business", items: [byId("04"), byId("05")] },
  {
    key: "settings.group.commerce",
    items: [byId("06"), byId("07"), byId("08"), byId("09"), byId("10"), byId("11")],
  },
  {
    key: "settings.group.intelligence",
    items: [byId("12"), byId("13"), byId("14"), byId("15"), byId("16"), byId("17")],
  },
  { key: "settings.group.advanced", items: [byId("18"), byId("19"), byId("20")] },
];

/** Every route the Center links to, in one list — the set the router must be able to serve. */
export const SETTINGS_NAV_ROUTES = SETTINGS_NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => item.to)
);

/**
 * Legacy addresses that must keep working but must NOT be a second front door.
 *
 * `/settings/members` was the old combined members-and-invitations screen while
 * `/settings/team/*` holds the six real pages. Two editors of the same thing is exactly what
 * the Center exists to prevent, so the old address forwards to the section and the sidebar
 * only ever points at the section.
 */
export const SETTINGS_LEGACY_REDIRECTS = [
  { from: "/settings/members", to: "/settings/team/members" },
];

/**
 * Screens that stay reachable by address but are NOT a section, with the reason — so the next
 * person does not "fix" their absence from the sidebar by adding a twenty-first entry.
 */
export const SETTINGS_UNLISTED_SCREENS = [
  {
    to: "/settings/all",
    why: "The unified editor that lists every key at once. It is a working screen, not a place in the map: the map's twenty sections are how a person is meant to arrive.",
  },
];

/**
 * Where a page's own label comes from, when the page does not follow the section convention.
 *
 * The convention is `settings.<section>.pages.<page>.title`. Six groups cannot follow it and
 * never could, because their labels were written before the Center had sections: the two
 * hand-built wrappers (workspace, team) name their tabs `workspace.tab.*` / `team.tab.*`, and
 * the AI, notifications and channel pages were named after their endpoints in camelCase. The
 * override map is the whole list, so "which pages have a label nobody can find" is answerable
 * by reading one object instead of grepping four components.
 */
const PAGE_LABEL_OVERRIDES = {
  "workspace/overview": "workspace.tab.overview",
  "workspace/data": "workspace.tab.data",
  "workspace/ownership": "workspace.tab.ownership",
  "workspace/switch": "workspace.tab.switch",
  "workspace/defaults": "workspace.tab.defaults",
  "team/members": "team.tab.members",
  "team/invitations": "team.tab.invitations",
  "team/roles": "team.tab.roles",
  "team/matrix": "team.tab.matrix",
  "team/groups": "team.tab.groups",
  "team/access": "team.tab.access",
  "ai/agent-management": "settings.ai.agents.title",
  "ai/customer-agent": "settings.ai.customerAgent.title",
  "ai/analytics-agent": "settings.ai.analyticsAgent.title",
  "ai/knowledge-sources": "settings.ai.knowledge.title",
  "ai/models-and-routing": "settings.ai.models.title",
  "ai/tools-and-permissions": "settings.ai.tools.title",
  "ai/policies-and-safety": "settings.ai.safety.title",
  "ai/testing-and-evaluation": "settings.ai.evaluations.title",
  "ai/versions-and-publishing": "settings.ai.versions.title",
  "customers/customer-data": "settings.customers.customerData.title",
  "customers/customer-segments": "settings.customers.segments.title",
  "customers/customer-records": "settings.customers.customerRecords.title",
  "customers/inbox": "settings.customers.inbox.title",
  "customers/conversation-routing": "settings.customers.routing.title",
  "customers/reply-templates": "settings.customers.templates.title",
  "customers/support-hours": "settings.customers.supportHours.title",
  "customers/escalation-to-human": "settings.customers.escalation.title",
  "channels/connected-channels": "settings.channels.pages.connected-channels.title",
  "channels/whatsapp": "settings.channels.pages.whatsapp.title",
  "channels/facebook": "settings.channels.pages.facebook.title",
  "channels/instagram": "settings.channels.pages.instagram.title",
  "channels/telegram": "settings.channels.pages.telegram.title",
  "channels/webchat": "settings.channels.pages.webchat.title",
  "channels/data-sync": "settings.channels.dataSync.title",
  "channels/external-integrations": "settings.channels.external.title",
  "channels/connection-health": "settings.channels.health.title",
  "analytics/dashboards": "settings.analytics.overview.title",
  "analytics/metrics-and-indicators": "settings.analytics.metrics.title",
  "analytics/reports": "settings.analytics.reports.title",
  "automation/rules": "settings.automation.rules.title",
  "automation/workflows": "settings.automation.workflows.title",
  "automation/triggers-and-events": "settings.automation.triggers.title",
  "automation/execution-attempts": "settings.automation.executions.title",
  "notifications/notification-channels": "settings.notifications.pages.notification-channels.title",
  "notifications/notification-rules": "settings.notifications.pages.notification-rules.title",
  "notifications/alerts-and-escalation": "settings.notifications.pages.alerts-and-escalation.title",
  "notifications/recipients": "settings.notifications.recipients.title",
  "notifications/message-templates": "settings.notifications.templates.title",
  "data/import": "settings.data.import.title",
  "data/retention": "settings.data.retention.title",
  "data/data-privacy": "settings.data.privacy.title",
  "data/data-deletion": "settings.data.deletion.title",
  "data/backups-and-restore": "settings.data.backups.title",
};

/** The section whose route segment is `slug`, or undefined. */
export function sectionBySlug(slug) {
  return SETTINGS_SECTIONS.find((section) => section.slug === slug);
}

/**
 * The pages of a section, as navigation entries: `{ slug, labelKey }`.
 *
 * This is the ONLY answer to "which tabs does this section have". `SettingsSection` used to
 * keep its own `SECTION_PAGES` copy, which is how the AI section ended up with four manifest
 * pages, nine real routes and no tabs at all.
 */
export function sectionPages(slug) {
  const section = sectionBySlug(slug);
  if (!section) return [];
  return section.pages.map((page) => ({
    slug: page,
    labelKey: PAGE_LABEL_OVERRIDES[`${slug}/${page}`] ?? `settings.${slug}.pages.${page}.title`,
  }));
}

/** The route of one page inside a section. */
export function pagePath(slug, page) {
  return `/settings/${slug}/${page}`;
}

/** Every page route the Center can open, section by section — the router's must-serve set. */
export const SETTINGS_PAGE_ROUTES = SETTINGS_SECTIONS.filter(
  (section) => section.id !== "01" && section.pages.length > 0
).flatMap((section) => section.pages.map((page) => pagePath(section.slug, page)));

/**
 * The section a pathname belongs to, for the route guard.
 *
 * Longest prefix wins, so `/settings/workspace/data` is the workspace section and
 * `/settings/data/import` is the data section — the two names collide and a naive
 * `startsWith` on `/settings/data` would put the workspace's page under the wrong rule. The
 * account pages (`/settings/profile`, `/settings/sign-in`, …) are section 01 and answer `null`
 * from `permission`-gated lookups only because they are personal screens, never shop settings.
 */
export function sectionByPath(pathname) {
  const path = (pathname || "").replace(/\/+$/, "");
  // The personal addresses are checked FIRST, because three of them are also a section slug:
  // /settings/security is the person's own password screen while /settings/security/audit-log
  // is section 18, and /settings/notifications is personal while
  // /settings/notifications/notification-channels is section 16. A slug-prefix match alone
  // would put a staff member's own security page behind a settings grant they do not hold.
  const personal = ACCOUNT_PAGE_ITEMS.find((item) => (item.end ? path === item.to : path === item.to));
  if (personal) return byId("01");
  const candidates = SETTINGS_SECTIONS.filter(
    (section) =>
      section.id !== "01" &&
      (path === `/settings/${section.slug}` || path.startsWith(`/settings/${section.slug}/`))
  );
  if (candidates.length === 0) return null;
  return candidates.sort((a, b) => b.slug.length - a.slug.length)[0];
}

/**
 * Where a page's real screen lives, when it is not the Center.
 *
 * The Settings Center configures how the system works. A screen whose job is to show RECORDS
 * (a supplier list, a purchase order, an inbox, a report, a run log) belongs to the module that
 * owns those rows: duplicating it here gave two editors for one table, and the copy in Settings
 * was always the staler one. The page keeps its address as a short link, so a bookmark still
 * lands somewhere true.
 *
 * Returns `null` for a page the Center itself renders.
 */
export function pageLink(section, page) {
  if (!section || !page) return null;
  return section.links?.[page] || null;
}

/** Every module link in the Center, for the tests and the generated docs. */
export function allPageLinks() {
  return SETTINGS_SECTIONS.flatMap((section) =>
    Object.entries(section.links || {}).map(([page, to]) => ({
      sectionId: section.id,
      sectionSlug: section.slug,
      page,
      to,
    }))
  );
}
