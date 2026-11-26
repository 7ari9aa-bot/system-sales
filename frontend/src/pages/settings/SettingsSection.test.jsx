/**
 * A Settings Center page asks for its own home, and only its own home.
 *
 * The map gives every key exactly one canonical page. What makes that true in the UI is this
 * component passing its section+page to the settings hook, so the server returns the keys whose
 * home is that page — no control on the screen edits a setting that lives somewhere else.
 *
 * The unit environment is `node` (see vitest.config.js), so these are static-markup assertions:
 * the hook is stubbed, which is exactly the boundary worth testing here.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, test, vi } from "vitest";
import { I18nProvider } from "@/lib/i18n";

const PHONE = {
  key: "business.phone",
  domain: "business",
  type: "string",
  default: "",
  scopes: ["tenant", "branch"],
  allowed_values: null,
  min_value: null,
  max_value: null,
  max_length: 32,
  permission: "settings:write",
  audit: false,
  apply_mode: "validated",
  sensitivity: "normal",
  feature_requirement: null,
  rollback_supported: true,
  enforced: true,
  segments: [],
  section: "store",
  page: "contact-details",
  impact_level: "low",
  label_ar: "هاتف النشاط",
  label_en: "Business phone",
  description_ar: "",
  description_en: "The number the customer sees.",
};

const POLICY_DEF = {
  ...PHONE,
  key: "pos.return_max_days",
  domain: "pos",
  type: "number",
  default: 30,
  min_value: 0,
  max_value: 365,
  page: "business-policies",
  impact_level: "high",
  label_ar: "مهلة المرتجع",
  label_en: "Return window (days)",
};

/** One page's definitions, as the server would return them for that section+page. */
const DEFS_BY_PAGE = {
  "contact-details": [PHONE],
  "business-policies": [POLICY_DEF],
  "working-hours": [],
  "all-branches": [],
  "branch-data": [],
  "branch-hours": [],
  "branch-settings": [],
  "branch-staff": [],
  "operating-scopes": [],
};

const useSettingsMock = vi.fn(() => ({
  defs: [PHONE],
  defMap: { [PHONE.key]: PHONE },
  grouped: { business: [PHONE] },
  values: { [PHONE.key]: "0100" },
  original: { [PHONE.key]: "0100" },
  dirty: false,
  loading: false,
  error: "",
  saving: false,
  notice: "",
  conflict: null,
  preview: null,
  previewing: false,
  runPreview: vi.fn(),
  changeRequests: [],
  approvalRequiredKeys: [],
  changedEntries: [],
  scope: "tenant",
  scopeId: null,
  setValue: vi.fn(),
  save: vi.fn(),
  reset: vi.fn(),
  submitChangeRequest: vi.fn(),
  approveChangeRequest: vi.fn(),
  rejectChangeRequest: vi.fn(),
}));

const policyEditorMock = vi.fn(() => null);

vi.mock("@/components/settings/StorePolicyEditor", () => ({
  default: (props) => policyEditorMock(props),
}));

vi.mock("@/components/settings/DepositPolicySettings", () => ({
  default: () => null,
}));

const branchesPanelMock = vi.fn(() => null);
const branchDataMock = vi.fn(() => null);
const branchHoursMock = vi.fn(() => null);
const branchStaffMock = vi.fn(() => null);
const branchScopesMock = vi.fn(() => null);

vi.mock("@/components/settings/BranchesPanel", () => ({
  default: (props) => branchesPanelMock(props),
}));

const categoriesPanelMock = vi.fn(() => null);
const apparelPanelMock = vi.fn(() => null);

vi.mock("@/components/settings/CategoriesPanel", () => ({
  default: (props) => categoriesPanelMock(props),
}));

vi.mock("@/components/settings/ApparelOptionsPanel", () => ({
  default: (props) => apparelPanelMock(props),
}));

const returnWindowMock = vi.fn(() => null);
const inventoryRecordsMock = vi.fn(() => null);

vi.mock("@/components/settings/InventoryRecordsPanel", () => ({
  default: (props) => inventoryRecordsMock(props),
}));

vi.mock("@/components/settings/ReturnWindowPanel", () => ({
  default: (props) => returnWindowMock(props),
}));

const devicesSectionMock = vi.fn(() => null);

vi.mock("@/pages/settings/pos/DevicesSection", () => ({
  default: (props) => devicesSectionMock(props),
}));

const priceListsMock = vi.fn(() => null);
const offersMock = vi.fn(() => null);

vi.mock("@/components/settings/PriceListsPanel", () => ({
  default: (props) => priceListsMock(props),
}));

vi.mock("@/components/settings/DiscountRulesPanel", () => ({
  default: (props) => offersMock(props),
}));

const supportHoursMock = vi.fn(() => null);
const escalationMock = vi.fn(() => null);

vi.mock("@/components/settings/CustomerSupportPanels", () => ({
  SupportHoursLink: (props) => supportHoursMock(props),
  EscalationSection: (props) => escalationMock(props),
}));


vi.mock("@/components/settings/BranchPanels", () => ({
  BranchDataPanel: (props) => branchDataMock(props),
  BranchHoursPanel: (props) => branchHoursMock(props),
  BranchStaffPanel: (props) => branchStaffMock(props),
  BranchScopesPanel: (props) => branchScopesMock(props),
}));

vi.mock("@/components/settings/useSettings", () => ({
  useSettings: (opts) => {
    const defs = DEFS_BY_PAGE[opts.page] ?? [];
    const grouped = {};
    for (const d of defs) (grouped[d.domain] ||= []).push(d);
    return {
      ...useSettingsMock(opts),
      defs,
      grouped,
      defMap: Object.fromEntries(defs.map((d) => [d.key, d])),
    };
  },
}));

vi.mock("@/components/settings/ScopeSelector", () => ({
  default: () => null,
}));

// Imported after the mocks so the component picks them up.
const { default: SettingsSection } = await import("./SettingsSection");

function renderAt(path) {
  return renderToStaticMarkup(
    <I18nProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/settings/store/:page" element={<SettingsSection section="store" />} />
          <Route path="/settings/locations/:page" element={<SettingsSection section="locations" />} />
          <Route path="/settings/catalog/:page" element={<SettingsSection section="catalog" />} />
          <Route path="/settings/sales/:page" element={<SettingsSection section="sales" />} />
          <Route path="/settings/inventory/:page" element={<SettingsSection section="inventory" />} />
          <Route path="/settings/pos/:page" element={<SettingsSection section="pos" />} />
          <Route path="/settings/purchasing/:page" element={<SettingsSection section="purchasing" />} />
          <Route path="/settings/customers/:page" element={<SettingsSection section="customers" />} />
        </Routes>
      </MemoryRouter>
    </I18nProvider>,
  );
}

describe("SettingsSection", () => {
  beforeEach(() => {
    useSettingsMock.mockClear();
    policyEditorMock.mockClear();
    branchesPanelMock.mockClear();
    categoriesPanelMock.mockClear();
    apparelPanelMock.mockClear();
    returnWindowMock.mockClear();
    inventoryRecordsMock.mockClear();
    devicesSectionMock.mockClear();
    priceListsMock.mockClear();
    offersMock.mockClear();
    supportHoursMock.mockClear();
    escalationMock.mockClear();
    branchDataMock.mockClear();
    branchHoursMock.mockClear();
    branchStaffMock.mockClear();
    branchScopesMock.mockClear();
  });

  test("asks the settings hook for its own section and page", () => {
    renderAt("/settings/store/contact-details");
    expect(useSettingsMock).toHaveBeenCalled();
    const opts = useSettingsMock.mock.calls[0][0];
    expect(opts.section).toBe("store");
    expect(opts.page).toBe("contact-details");
  });

  test("renders the controls the registry says this page owns", () => {
    const html = renderAt("/settings/store/contact-details");
    expect(html).toContain("Business phone");
  });

  test("the tab strip reaches every page the map lists for the section", () => {
    const html = renderAt("/settings/store/contact-details");
    for (const page of ["business-profile", "brand-identity", "contact-details", "legal-data"]) {
      expect(html).toContain(`href="/settings/store/${page}"`);
    }
  });

  test("the heading names the page, not the section", () => {
    const html = renderAt("/settings/store/contact-details");
    // The tab strip names every page, so the heading is what must name only this one.
    expect(html).toContain(">Contact details</h1>");
    expect(html).not.toContain(">Legal data</h1>");
  });

  test("working hours publishes only the opening-times policy", () => {
    renderAt("/settings/store/working-hours");
    expect(policyEditorMock).toHaveBeenCalled();
    expect(policyEditorMock.mock.calls[0][0].keys).toEqual(["hours"]);
  });

  test("business policies publishes the promise texts and the windows the system enforces", () => {
    const html = renderAt("/settings/store/business-policies");
    expect(policyEditorMock.mock.calls[0][0].keys).toEqual([
      "exchange",
      "return",
      "warranty",
      "cancellation",
      "shipping",
      "ordering",
    ]);
    // The window is a high-impact key, so the page warns before anything is changed.
    expect(html).toContain("Return window (days)");
    expect(html).toContain("high impact");
  });

  test("a page with no registry keys still shows its policy block, not an empty notice", () => {
    const html = renderAt("/settings/store/working-hours");
    expect(html).not.toContain("No settings on this page yet");
    expect(html).toContain("Published promises");
  });

  test("a different page of the same section asks for that page instead", () => {
    renderAt("/settings/store/legal-data");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.page).toBe("legal-data");
  });

  test("all branches shows the real branches, not a second editor for them", () => {
    renderAt("/settings/locations/all-branches");
    expect(branchesPanelMock).toHaveBeenCalled();
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("locations");
    expect(opts.page).toBe("all-branches");
  });

  test("branch settings asks for the branch page of the locations section", () => {
    renderAt("/settings/locations/branch-settings");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("locations");
    expect(opts.page).toBe("branch-settings");
    // The branches list belongs to the page that owns the branch count, not this one.
    expect(branchesPanelMock).not.toHaveBeenCalled();
  });

  test.each([
    ["branch-data", branchDataMock],
    ["branch-hours", branchHoursMock],
    ["branch-staff", branchStaffMock],
    ["operating-scopes", branchScopesMock],
  ])("%s renders its own panel and nothing else", (page, panel) => {
    renderAt(`/settings/locations/${page}`);
    expect(panel).toHaveBeenCalled();
    // Only the page's own panel runs; the others are not mounted beside it.
    const others = [branchDataMock, branchHoursMock, branchStaffMock, branchScopesMock].filter(
      (m) => m !== panel,
    );
    for (const other of others) expect(other).not.toHaveBeenCalled();
    expect(branchesPanelMock).not.toHaveBeenCalled();
    expect(policyEditorMock).not.toHaveBeenCalled();
  });

  test("the catalogue section has its own seven pages", () => {
    renderAt("/settings/catalog/sku-and-barcode");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("catalog");
    expect(opts.page).toBe("sku-and-barcode");
  });

  test("categories shows the real catalogue list, not a setting", () => {
    renderAt("/settings/catalog/categories");
    expect(categoriesPanelMock).toHaveBeenCalled();
  });

  test("attributes and specs edits the shop's own sizes and colours", () => {
    renderAt("/settings/catalog/attributes-and-specs");
    expect(apparelPanelMock).toHaveBeenCalled();
    // The two panels belong to their own pages only.
    expect(categoriesPanelMock).not.toHaveBeenCalled();
  });

  test("the sales section owns the rules of selling", () => {
    renderAt("/settings/sales/taxes-and-fees");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("sales");
    expect(opts.page).toBe("taxes-and-fees");
  });

  test("exchange and returns shows the windows instead of a second editor", () => {
    renderAt("/settings/sales/exchange-and-returns");
    expect(returnWindowMock).toHaveBeenCalled();
  });

  test("the returns panel is only on its own page", () => {
    renderAt("/settings/sales/sales-settings");
    expect(returnWindowMock).not.toHaveBeenCalled();
  });

  test("the till section owns the cash pages", () => {
    renderAt("/settings/pos/cash-movement");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("pos");
    expect(opts.page).toBe("cash-movement");
  });

  test("registers and devices reuses the till's own devices screen", () => {
    renderAt("/settings/pos/registers-and-devices");
    expect(devicesSectionMock).toHaveBeenCalled();
  });

  test("the devices screen is not drawn on the plain settings page", () => {
    renderAt("/settings/pos/pos-settings");
    expect(devicesSectionMock).not.toHaveBeenCalled();
  });

  test("the inventory section routes to its own pages", () => {
    renderAt("/settings/inventory/stock-limits");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("inventory");
    expect(opts.page).toBe("stock-limits");
  });

  test.each([
    ["warehouses", "/inventory/warehouses"],
    ["transfers", "/inventory/transfers"],
    ["counts-and-adjustments", "/inventory/stocktakes"],
  ])("%s shows the real records it governs", (page, endpoint) => {
    renderAt(`/settings/inventory/${page}`);
    const props = inventoryRecordsMock.mock.calls.at(-1)[0];
    expect(props.endpoint).toBe(endpoint);
  });

  test("a page with no records panel does not grow one", () => {
    renderAt("/settings/inventory/inventory-cost");
    expect(inventoryRecordsMock).not.toHaveBeenCalled();
  });

  test("the purchasing section owns the approval limits", () => {
    renderAt("/settings/purchasing/approval-limits");
    const opts = useSettingsMock.mock.calls.at(-1)[0];
    expect(opts.section).toBe("purchasing");
    expect(opts.page).toBe("approval-limits");
  });

  test("suppliers reads the real supplier list, not a setting", () => {
    renderAt("/settings/purchasing/suppliers");
    expect(inventoryRecordsMock).toHaveBeenCalled();
    expect(inventoryRecordsMock.mock.calls.at(-1)[0].endpoint).toBe("/purchasing/suppliers");
  });

  test("orders and returns read their own documents", () => {
    renderAt("/settings/purchasing/purchase-orders");
    expect(inventoryRecordsMock.mock.calls.at(-1)[0].endpoint).toBe("/purchasing/purchase-orders");
    inventoryRecordsMock.mockClear();
    renderAt("/settings/purchasing/supplier-returns");
    expect(inventoryRecordsMock.mock.calls.at(-1)[0].endpoint).toBe("/purchasing/supplier-returns");
  });

  test("a page with keys does not also pull a document list", () => {
    renderAt("/settings/purchasing/approval-limits");
    expect(inventoryRecordsMock).not.toHaveBeenCalled();
  });

  test("price lists and offers render the documents they govern", () => {
    renderAt("/settings/sales/price-lists");
    expect(priceListsMock).toHaveBeenCalled();
    renderAt("/settings/sales/discounts-and-offers");
    expect(offersMock).toHaveBeenCalled();
  });

  test("the pricing page is keys only, with no document panel", () => {
    renderAt("/settings/sales/pricing");
    expect(priceListsMock).not.toHaveBeenCalled();
    expect(offersMock).not.toHaveBeenCalled();
  });

  test.each([
    ["catalog", "sku-and-barcode", ["product-settings", "categories", "attributes-and-specs", "product-states"]],
    ["sales", "taxes-and-fees", ["sales-settings", "price-lists", "pricing", "exchange-and-returns"]],
    ["pos", "shifts", ["pos-settings", "collection-methods", "cash-movement", "invoices-and-receipts"]],
    ["inventory", "transfers", ["inventory-settings", "warehouses", "stock-limits", "inventory-cost"]],
    ["purchasing", "approval-limits", ["suppliers", "purchase-orders", "receiving-and-inspection"]],
  ])("the %s tab strip reaches its live pages", (section, page, siblings) => {
    const html = renderAt(`/settings/${section}/${page}`);
    for (const sibling of siblings) {
      expect(html).toContain(`href="/settings/${section}/${sibling}"`);
    }
  });

  test("a page the map still marks pending gets no tab", () => {
    // Images and media and offline mode have nothing to edit yet, so the strip must not offer a
    // link that lands on an empty screen.
    expect(renderAt("/settings/catalog/product-states")).not.toContain(
      'href="/settings/catalog/images-and-media"',
    );
    expect(renderAt("/settings/pos/pos-settings")).not.toContain(
      'href="/settings/pos/offline-mode"',
    );
  });

  test("support hours and escalation render the two policy surfaces", () => {
    renderAt("/settings/customers/support-hours");
    expect(supportHoursMock).toHaveBeenCalled();
    renderAt("/settings/customers/escalation-to-human");
    expect(escalationMock).toHaveBeenCalled();
  });

  test("the support-hours page is a link, never a second hours editor", () => {
    renderAt("/settings/customers/support-hours");
    // The store's working hours own the promise; a textarea here would be the duplicate.
    expect(escalationMock).not.toHaveBeenCalled();
    expect(priceListsMock).not.toHaveBeenCalled();
  });
});
