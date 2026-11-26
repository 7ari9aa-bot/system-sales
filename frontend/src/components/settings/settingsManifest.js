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
    labelKey: "settings.nav.profile",
    to: "/settings",
    icon: User,
    end: true,
    pages: ["profile", "sign-in", "personal-security", "preferences", "personal-notifications"],
  },
  {
    id: "02",
    labelKey: "settings.nav.workspace",
    to: "/settings/workspace",
    icon: Store,
    pages: ["overview", "data", "ownership", "switch", "defaults"],
  },
  {
    id: "03",
    labelKey: "settings.nav.team",
    to: "/settings/team/members",
    icon: Users,
    pages: ["members", "invitations", "roles", "permissions", "groups", "access"],
  },
  {
    id: "04",
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
    labelKey: "settings.nav.purchasing",
    to: "/settings/purchasing/suppliers",
    icon: Truck,
    pages: [
      "suppliers",
      "purchasing-settings",
      "purchase-orders",
      "receiving-and-inspection",
      "supplier-returns",
      "approval-limits",
    ],
  },
  {
    id: "11",
    labelKey: "settings.nav.customers",
    to: "/settings/customers/customer-records",
    icon: UserRound,
    pages: [
      "customer-data",
      "customer-segments",
      "customer-records",
      "inbox",
      "conversation-routing",
      "reply-templates",
      "support-hours",
      "escalation-to-human",
    ],
  },
  {
    id: "12",
    labelKey: "settings.nav.channels",
    to: "/settings/channels",
    icon: MessageSquare,
    pages: ["connected-channels", "whatsapp", "facebook", "instagram", "telegram", "webchat"],
  },
  {
    id: "13",
    labelKey: "settings.nav.ai",
    to: "/settings/ai",
    icon: Sparkles,
    pages: ["agents", "knowledge", "provider-policies", "evaluations"],
  },
  {
    id: "14",
    labelKey: "settings.nav.analytics",
    to: "/settings/analytics/reports",
    icon: BarChart3,
    pages: ["dashboards", "metrics-and-indicators", "reports"],
  },
  {
    id: "15",
    labelKey: "settings.nav.automation",
    to: "/settings/automation/workflows",
    icon: Workflow,
    pages: ["rules", "workflows", "triggers-and-events", "execution-attempts"],
  },
  {
    id: "16",
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
    labelKey: "settings.nav.data",
    to: "/settings/data/data-privacy",
    icon: Database,
    // "backups-and-restore" is the offboarding screen (`DataSettings`), served by its own
    // route: the tab leads there, and /settings/danger forwards to it.
    pages: ["import", "retention", "data-privacy", "data-deletion", "backups-and-restore"],
  },
  {
    id: "18",
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
    labelKey: "settings.nav.billing",
    to: "/settings/billing/current-plan",
    icon: Wallet,
    pages: ["current-plan", "usage", "invoices", "billing-details"],
  },
  {
    id: "20",
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
  { to: "/settings", icon: User, labelKey: "settings.nav.profile", end: true },
  { to: "/settings/login", icon: KeyRound, labelKey: "settings.nav.login" },
  { to: "/settings/security", icon: ShieldCheck, labelKey: "settings.nav.security" },
  { to: "/settings/preferences", icon: SlidersHorizontal, labelKey: "settings.nav.preferences" },
  { to: "/settings/notifications", icon: Bell, labelKey: "settings.nav.notifications" },
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
