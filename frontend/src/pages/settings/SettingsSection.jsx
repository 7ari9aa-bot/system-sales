/** One page of the Settings Center, rendered from the registry.
 *
 * The map (docs/settings/center-map.md) gives every key exactly ONE canonical home: a section
 * and a page. This component asks the server for the keys whose home is `section/page`, so a
 * page shows only the controls it owns — nothing borrowed from a neighbouring page, and no
 * control that edits a key living somewhere else.
 *
 * What every page gets for free, because the anatomy in the map asks for it on all of them:
 *   - one line saying what the page configures;
 *   - controls grouped by the registry domain that owns them;
 *   - the effective value AND its source, and whether it is inherited or overridden;
 *   - a warning when the page holds high-impact keys;
 *   - validation and preview from the server, not a client guess;
 *   - direct save for ordinary keys, a change request for approval-required ones;
 *   - the "not active yet" mark on any key no code reads.
 */
import React, { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, RotateCcw, Save, ShieldAlert } from "lucide-react";
import { useI18n, useT } from "@/lib/i18n";
import SettingsShell, { SettingCard } from "@/components/settings/SettingsShell";
import { SettingField } from "@/components/settings/SettingField";
import StorePolicyEditor from "@/components/settings/StorePolicyEditor";
import BranchesPanel from "@/components/settings/BranchesPanel";
import ApparelOptionsPanel from "@/components/settings/ApparelOptionsPanel";
import CategoriesPanel from "@/components/settings/CategoriesPanel";
import ReturnWindowPanel from "@/components/settings/ReturnWindowPanel";
import InventoryRecordsPanel from "@/components/settings/InventoryRecordsPanel";
import DevicesSection from "@/pages/settings/pos/DevicesSection";
import PriceListsPanel from "@/components/settings/PriceListsPanel";
import DiscountRulesPanel from "@/components/settings/DiscountRulesPanel";
import {
  EscalationSection,
  SupportHoursLink,
} from "@/components/settings/CustomerSupportPanels";
import {
  BranchDataPanel,
  BranchHoursPanel,
  BranchScopesPanel,
  BranchStaffPanel,
} from "@/components/settings/BranchPanels";
import DepositPolicySettings from "@/components/settings/DepositPolicySettings";
import { useSettings } from "@/components/settings/useSettings";
import ScopeSelector from "@/components/settings/ScopeSelector";
import PreviewPanel from "@/components/settings/PreviewPanel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/dashboard/ui";

/** Human names for the registry domains a page may group its keys by. */
const DOMAIN_LABELS_AR = {
  business: "بيانات النشاط",
  organization: "المؤسسة",
  capability: "قدرات النشاط",
  branch: "الفروع",
  catalog: "الكتالوج",
  pos: "نقطة البيع",
  print: "الطباعة والمستندات",
  einvoice: "الفاتورة الإلكترونية",
  inventory: "المخزون",
  purchasing: "المشتريات",
  orders: "الطلبات",
  notifications: "الإشعارات",
  customer_agent: "وكيل العملاء",
  analytics_agent: "وكيل التحليلات",
  team: "الفريق",
  security: "الأمان",
  billing: "الفوترة",
  imports: "الاستيراد",
};

const DOMAIN_LABELS_EN = {
  business: "Business facts",
  organization: "Organisation",
  capability: "What the business can do",
  branch: "Branches",
  catalog: "Catalog",
  pos: "Point of sale",
  print: "Print & documents",
  einvoice: "E-invoice",
  inventory: "Inventory",
  purchasing: "Purchasing",
  orders: "Orders",
  notifications: "Notifications",
  customer_agent: "Customer agent",
  analytics_agent: "Analytics agent",
  team: "Team",
  security: "Security",
  billing: "Billing",
  imports: "Imports",
};

/** The pages of each section, in the order the map lists them. A section is a navigation group
 * with its own pages, not one long screen: the tab strip below is how a merchant moves inside
 * it without the sidebar growing to twenty siblings. */
const SECTION_PAGES = {
  store: [
    "business-profile",
    "brand-identity",
    "contact-details",
    "working-hours",
    "business-policies",
    "legal-data",
  ],
  locations: [
    "all-branches",
    "branch-data",
    "branch-hours",
    "branch-settings",
    "branch-staff",
    "operating-scopes",
  ],
  // Only pages that are live get a tab: a page the map still marks pending has nothing to edit
  // yet, and a tab that lands on an empty screen is worse than no tab at all. The pending pages
  // stay named in the map's Build status table, with the reason.
  catalog: [
    "product-settings",
    "categories",
    "variants-and-options",
    "attributes-and-specs",
    "sku-and-barcode",
    "product-states",
  ],
  sales: [
    "sales-settings",
    "price-lists",
    "pricing",
    "discounts-and-offers",
    "taxes-and-fees",
    "exchange-and-returns",
  ],
  pos: [
    "pos-settings",
    "registers-and-devices",
    "collection-methods",
    "shifts",
    "cash-movement",
    "invoices-and-receipts",
  ],
  inventory: [
    "inventory-settings",
    "warehouses",
    "stock-states",
    "stock-limits",
    "counts-and-adjustments",
    "transfers",
    "inventory-cost",
  ],
  purchasing: [
    "suppliers",
    "purchasing-settings",
    "purchase-orders",
    "receiving-and-inspection",
    "supplier-returns",
    "approval-limits",
  ],
};

/** Pages that also publish store policies — the promises the customer agent answers from.
 *
 * A policy is not a registry key: it is a knowledge item the agent quotes. It still has exactly
 * one home, and that home is here. `business-policies` also carries the deposit rules, which are
 * the same kind of promise (what the shop asks for before it will hold an order).
 */
const POLICY_KEYS_BY_PAGE = {
  "store/working-hours": ["hours"],
  "store/business-policies": ["exchange", "return", "warranty", "cancellation", "shipping", "ordering"],
};

/** Pages whose body is a panel over real records rather than a list of registry keys. */
const PANEL_PAGES = new Set([
  "locations/all-branches",
  "locations/branch-data",
  "locations/branch-hours",
  "locations/branch-staff",
  "locations/operating-scopes",
  // Section 11: the customer relationship. These pages carry records or link to a policy that
  // already has a home, so none of them may show "this page has no settings yet".
  "customers/customer-data",
  "customers/customer-records",
  "customers/customer-segments",
  "customers/inbox",
  "customers/conversation-routing",
  "customers/reply-templates",
  "customers/support-hours",
  "customers/escalation-to-human",
  "sales/price-lists",
  "sales/discounts-and-offers",
  // Section 13: every page here reads the AI module's own rows (agents, knowledge, provider
  // policies, evaluations) rather than inventing a switch the runtime does not read.
  "ai/agent-management",
  "ai/customer-agent",
  "ai/analytics-agent",
  "ai/knowledge-sources",
  "ai/models-and-routing",
  "ai/tools-and-permissions",
  "ai/policies-and-safety",
  "ai/testing-and-evaluation",
  "ai/versions-and-publishing",
]);

/** Domains whose keys may be set below the workspace, so the scope picker is worth showing. */
const SCOPED_DOMAINS = new Set(["business", "organization", "branch", "pos", "print", "orders"]);

export default function SettingsSection({ section }) {
  const { page } = useParams();
  const { lang } = useI18n();
  const t = useT();
  const isAr = lang === "ar";

  const [scope, setScope] = useState("tenant");
  const [scopeId, setScopeId] = useState(null);

  const s = useSettings({ section, page, scope, scopeId });
  const domainLabels = isAr ? DOMAIN_LABELS_AR : DOMAIN_LABELS_EN;

  const domains = useMemo(() => Object.keys(s.grouped).sort(), [s.grouped]);
  const highImpact = useMemo(
    () => (s.defs || []).filter((d) => d.impact_level === "high"),
    [s.defs],
  );
  const scoped = useMemo(
    () => (s.defs || []).some((d) => SCOPED_DOMAINS.has(d.domain)),
    [s.defs],
  );

  const pages = SECTION_PAGES[section] || [];
  const title = t(`settings.${section}.pages.${page}.title`) || t(`settings.${section}.title`);
  const desc = t(`settings.${section}.pages.${page}.desc`) || t(`settings.${section}.subtitle`);

  const hasApprovalChanges = s.approvalRequiredKeys.length > 0;
  const hasDirectChanges = s.changedEntries.some((e) => !e.needsApproval);
  // The preview panel renders the diff the server just confirmed, so it appears only while the
  // page has unsaved edits — exactly as /settings/all does.
  const showPreview = Boolean(s.preview) && s.dirty;

  if (s.loading) {
    return (
      <SettingsShell title={title} subtitle={desc}>
        <div className="py-8 text-center text-[13px] text-muted-foreground">
          {s.error || (isAr ? "جارٍ التحميل…" : "Loading…")}
        </div>
      </SettingsShell>
    );
  }

  return (
    <SettingsShell
      title={title}
      subtitle={desc}
      actions={
        <div className="flex items-center gap-2">
          {s.dirty && (
            <Button variant="outline" size="sm" onClick={s.reset} disabled={s.saving}>
              <RotateCcw className="h-3.5 w-3.5" />
              {isAr ? "تراجع" : "Reset"}
            </Button>
          )}
          {s.dirty && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => s.runPreview()}
              disabled={s.previewing}
            >
              {isAr ? "معاينة" : "Preview"}
            </Button>
          )}
          {hasApprovalChanges && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => s.submitChangeRequest()}
              disabled={s.saving}
            >
              <ShieldAlert className="h-3.5 w-3.5" />
              {s.saving ? "…" : isAr ? "طلب تغيير" : "Request change"}
            </Button>
          )}
          {hasDirectChanges && (
            <Button size="sm" onClick={s.save} disabled={!s.dirty || s.saving}>
              <Save className="h-3.5 w-3.5" />
              {s.saving ? "…" : isAr ? "حفظ" : "Save"}
            </Button>
          )}
        </div>
      }
    >
      {pages.length > 1 && (
        <nav className="flex flex-wrap items-center gap-1 border-b border-border pb-2">
          {pages.map((p) => {
            const active = p === page;
            return (
              <Link
                key={p}
                to={`/settings/${section}/${p}`}
                className={
                  active
                    ? "rounded-md bg-primary/10 px-2.5 py-1.5 text-[12.5px] font-medium text-primary"
                    : "rounded-md px-2.5 py-1.5 text-[12.5px] text-muted-foreground hover:bg-muted hover:text-foreground"
                }
              >
                {t(`settings.${section}.pages.${p}.title`) || p}
              </Link>
            );
          })}
        </nav>
      )}

      {scoped && (
        <div className="flex flex-wrap items-center gap-3">
          <ScopeSelector
            scope={scope}
            scopeId={scopeId}
            onScopeChange={(v) => {
              setScope(v);
              setScopeId(null);
            }}
            onScopeIdChange={setScopeId}
            isAr={isAr}
          />
        </div>
      )}

      {highImpact.length > 0 && (
        <div className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-[12.5px]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <span>{t("settings.store.impact.high")}</span>
        </div>
      )}

      {s.notice && (
        <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-[12.5px]">
          {s.notice === "saved"
            ? isAr
              ? "تم الحفظ"
              : "Saved"
            : s.notice === "saved_with_pending"
              ? isAr
                ? "تم حفظ التعديلات المباشرة، والباقي اتحول لطلب تغيير بانتظار الموافقة"
                : "Direct edits saved; the rest became a change request awaiting approval"
              : s.notice === "change_request_submitted"
                ? isAr
                  ? "تم إرسال طلب التغيير"
                  : "Change request submitted"
                : s.notice}
        </div>
      )}

      {s.conflict && (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-[12.5px]">
          {isAr
            ? "حد تاني عدّل نفس الإعداد. راجع القيم وحدّث الصفحة قبل الحفظ."
            : "Someone else changed these settings. Review the values and reload before saving."}
        </div>
      )}

      {showPreview && (
        <PreviewPanel changedEntries={s.changedEntries} scope={scope} isAr={isAr} />
      )}

      {domains.length === 0 &&
        !POLICY_KEYS_BY_PAGE[`${section}/${page}`] &&
        !PANEL_PAGES.has(`${section}/${page}`) && (
        <div className="py-8 text-center text-[13px] text-muted-foreground">
          {t("settings.store.empty")}
        </div>
      )}

      {domains.map((domain) => (
        <SettingCard key={domain} title={domainLabels[domain] || domain}>
          {s.grouped[domain].map((defn) => (
            <SettingField
              key={defn.key}
              defn={defn}
              value={s.values[defn.key]}
              onChange={s.setValue}
              isAr={isAr}
            />
          ))}
        </SettingCard>
      ))}

      {`${section}/${page}` === "locations/all-branches" && <BranchesPanel />}

      {`${section}/${page}` === "catalog/categories" && <CategoriesPanel />}

      {`${section}/${page}` === "catalog/attributes-and-specs" && <ApparelOptionsPanel />}

      {`${section}/${page}` === "sales/exchange-and-returns" && <ReturnWindowPanel />}

      {/* A price list and an offer are documents, not switches: the panel lists and edits the
          rows, and the registry keys above it decide whether they are used at all. */}
      {`${section}/${page}` === "sales/price-lists" && <PriceListsPanel />}

      {`${section}/${page}` === "sales/discounts-and-offers" && <DiscountRulesPanel />}

      {/* Section 11: the customer relationship. These are records the customers, segments and
          conversations modules already own, so each page shows the real rows and says where they
          are created. The two things that ARE policy — support hours and escalation clocks —
          link to their single homes instead of growing a second editor. */}
      {`${section}/${page}` === "customers/customer-data" && (
        <InventoryRecordsPanel
          endpoint="/customers/contact-data-issues"
          titleKey="settings.customers.customerData.title"
          descKey="settings.customers.customerData.desc"
          emptyKey="settings.customers.customerData.empty"
          loadingKey="settings.customers.customerData.loading"
          loadErrorKey="settings.customers.customerData.loadError"
          footerKey="settings.customers.customerData.whereToEdit"
          columns={[
            { key: "name" },
            { key: "phone", kind: "num" },
            { key: "phone_state", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "customers/customer-records" && (
        <InventoryRecordsPanel
          endpoint="/customers"
          titleKey="settings.customers.customerRecords.title"
          descKey="settings.customers.customerRecords.desc"
          emptyKey="settings.customers.customerRecords.empty"
          loadingKey="settings.customers.customerRecords.loading"
          loadErrorKey="settings.customers.customerRecords.loadError"
          footerKey="settings.customers.customerRecords.whereToEdit"
          columns={[
            { key: "name" },
            { key: "phone", kind: "num" },
            { key: "status", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "customers/customer-segments" && (
        <InventoryRecordsPanel
          endpoint="/segments"
          titleKey="settings.customers.segments.title"
          descKey="settings.customers.segments.desc"
          emptyKey="settings.customers.segments.empty"
          loadingKey="settings.customers.segments.loading"
          loadErrorKey="settings.customers.segments.loadError"
          footerKey="settings.customers.segments.whereToEdit"
          columns={[
            { key: "name" },
            { key: "status", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "customers/inbox" && (
        <InventoryRecordsPanel
          endpoint="/conversations"
          titleKey="settings.customers.inbox.title"
          descKey="settings.customers.inbox.desc"
          emptyKey="settings.customers.inbox.empty"
          loadingKey="settings.customers.inbox.loading"
          loadErrorKey="settings.customers.inbox.loadError"
          footerKey="settings.customers.inbox.whereToEdit"
          columns={[
            { key: "channel", kind: "badge" },
            { key: "status", kind: "badge" },
            { key: "unread_count", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "customers/conversation-routing" && (
        <InventoryRecordsPanel
          endpoint="/sla/policies"
          titleKey="settings.customers.routing.title"
          descKey="settings.customers.routing.desc"
          emptyKey="settings.customers.routing.empty"
          loadingKey="settings.customers.routing.loading"
          loadErrorKey="settings.customers.routing.loadError"
          footerKey="settings.customers.routing.whereToEdit"
          columns={[
            { key: "name" },
            { key: "applies_to_channel", kind: "badge" },
            { key: "first_response_minutes", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "customers/reply-templates" && (
        <InventoryRecordsPanel
          endpoint="/message-templates"
          titleKey="settings.customers.templates.title"
          descKey="settings.customers.templates.desc"
          emptyKey="settings.customers.templates.empty"
          loadingKey="settings.customers.templates.loading"
          loadErrorKey="settings.customers.templates.loadError"
          footerKey="settings.customers.templates.whereToEdit"
          columns={[
            { key: "name" },
            { key: "language", kind: "num" },
            { key: "status", kind: "badge" },
          ]}
        />
      )}

      {`${section}/${page}` === "customers/support-hours" && <SupportHoursLink />}

      {`${section}/${page}` === "customers/escalation-to-human" && <EscalationSection />}
      {/* Section 13: AI and agents. The boundaries are design, not prompt detail, and every row
          below is the AI module's own record — an agent, a knowledge item, a provider policy, an
          evaluation — so no page here offers a control the runtime does not read. Editing happens
          in the AI console the pages link to; this is the governance view of it. */}
      {`${section}/${page}` === "ai/agent-management" && (
        <InventoryRecordsPanel
          endpoint="/ai/agents"
          titleKey="settings.ai.agents.title"
          descKey="settings.ai.agents.desc"
          emptyKey="settings.ai.agents.empty"
          loadingKey="settings.ai.agents.loading"
          loadErrorKey="settings.ai.agents.loadError"
          footerKey="settings.ai.agents.whereToEdit"
          columns={[
            { key: "name" },
            { key: "kind", kind: "badge" },
            { key: "model", kind: "num" },
            { key: "version", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/customer-agent" && (
        <InventoryRecordsPanel
          endpoint="/ai/agents"
          titleKey="settings.ai.customerAgent.title"
          descKey="settings.ai.customerAgent.desc"
          emptyKey="settings.ai.customerAgent.empty"
          loadingKey="settings.ai.customerAgent.loading"
          loadErrorKey="settings.ai.customerAgent.loadError"
          footerKey="settings.ai.customerAgent.whereToEdit"
          filter={(r) => r.kind === "customer"}
          columns={[
            { key: "name" },
            { key: "model", kind: "num" },
            { key: "temperature", kind: "num" },
            { key: "is_active", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/analytics-agent" && (
        <InventoryRecordsPanel
          endpoint="/ai/agents"
          titleKey="settings.ai.analyticsAgent.title"
          descKey="settings.ai.analyticsAgent.desc"
          emptyKey="settings.ai.analyticsAgent.empty"
          loadingKey="settings.ai.analyticsAgent.loading"
          loadErrorKey="settings.ai.analyticsAgent.loadError"
          footerKey="settings.ai.analyticsAgent.whereToEdit"
          filter={(r) => r.kind === "analytics"}
          columns={[
            { key: "name" },
            { key: "model", kind: "num" },
            { key: "temperature", kind: "num" },
            { key: "is_active", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/knowledge-sources" && (
        <InventoryRecordsPanel
          endpoint="/ai/knowledge"
          titleKey="settings.ai.knowledge.title"
          descKey="settings.ai.knowledge.desc"
          emptyKey="settings.ai.knowledge.empty"
          loadingKey="settings.ai.knowledge.loading"
          loadErrorKey="settings.ai.knowledge.loadError"
          footerKey="settings.ai.knowledge.whereToEdit"
          columns={[
            { key: "title" },
            { key: "source_type", kind: "badge" },
            { key: "status", kind: "badge" },
            { key: "visibility", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/models-and-routing" && (
        <InventoryRecordsPanel
          endpoint="/ai/provider-policies"
          titleKey="settings.ai.models.title"
          descKey="settings.ai.models.desc"
          emptyKey="settings.ai.models.empty"
          loadingKey="settings.ai.models.loading"
          loadErrorKey="settings.ai.models.loadError"
          footerKey="settings.ai.models.whereToEdit"
          columns={[
            { key: "provider" },
            { key: "status", kind: "badge" },
            { key: "data_classification", kind: "badge" },
            { key: "pii_redaction_required", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/tools-and-permissions" && (
        <InventoryRecordsPanel
          endpoint="/ai/agents"
          titleKey="settings.ai.tools.title"
          descKey="settings.ai.tools.desc"
          emptyKey="settings.ai.tools.empty"
          loadingKey="settings.ai.tools.loading"
          loadErrorKey="settings.ai.tools.loadError"
          footerKey="settings.ai.tools.whereToEdit"
          columns={[
            { key: "name" },
            { key: "kind", kind: "badge" },
            { key: "max_output_tokens", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/policies-and-safety" && (
        <InventoryRecordsPanel
          endpoint="/ai/agents"
          titleKey="settings.ai.safety.title"
          descKey="settings.ai.safety.desc"
          emptyKey="settings.ai.safety.empty"
          loadingKey="settings.ai.safety.loading"
          loadErrorKey="settings.ai.safety.loadError"
          footerKey="settings.ai.safety.whereToEdit"
          columns={[
            { key: "name" },
            { key: "kind", kind: "badge" },
            { key: "temperature", kind: "num" },
            { key: "max_output_tokens", kind: "num" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/testing-and-evaluation" && (
        <InventoryRecordsPanel
          endpoint="/ai/evaluations"
          titleKey="settings.ai.evaluations.title"
          descKey="settings.ai.evaluations.desc"
          emptyKey="settings.ai.evaluations.empty"
          loadingKey="settings.ai.evaluations.loading"
          loadErrorKey="settings.ai.evaluations.loadError"
          footerKey="settings.ai.evaluations.whereToEdit"
          columns={[
            { key: "agent_id", kind: "num" },
            { key: "prompt_version", kind: "num" },
            { key: "status", kind: "badge" },
            { key: "rollout_status", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "ai/versions-and-publishing" && (
        <InventoryRecordsPanel
          endpoint="/ai/agents"
          titleKey="settings.ai.versions.title"
          descKey="settings.ai.versions.desc"
          emptyKey="settings.ai.versions.empty"
          loadingKey="settings.ai.versions.loading"
          loadErrorKey="settings.ai.versions.loadError"
          footerKey="settings.ai.versions.whereToEdit"
          columns={[
            { key: "name" },
            { key: "version", kind: "num" },
            { key: "is_active", kind: "badge" },
          ]}
        />
      )}

      {`${section}/${page}` === "inventory/warehouses" && (
        <InventoryRecordsPanel
          endpoint="/inventory/warehouses"
          titleKey="settings.inventory.warehouses.title"
          descKey="settings.inventory.warehouses.desc"
          emptyKey="settings.inventory.warehouses.empty"
          loadingKey="settings.inventory.warehouses.loading"
          loadErrorKey="settings.inventory.warehouses.loadError"
          footerKey="settings.inventory.warehouses.whereToEdit"
          columns={[
            { key: "name" },
            { key: "code", kind: "num" },
            { key: "address" },
          ]}
        />
      )}

      {`${section}/${page}` === "inventory/transfers" && (
        <InventoryRecordsPanel
          endpoint="/inventory/transfers"
          titleKey="settings.inventory.transfers.title"
          descKey="settings.inventory.transfers.desc"
          emptyKey="settings.inventory.transfers.empty"
          loadingKey="settings.inventory.transfers.loading"
          loadErrorKey="settings.inventory.transfers.loadError"
          footerKey="settings.inventory.transfers.whereToEdit"
          columns={[
            { key: "from_warehouse_id", kind: "num" },
            { key: "to_warehouse_id", kind: "num" },
            { key: "status", kind: "badge" },
            { key: "created_at", kind: "num" },
          ]}
        />
      )}

      {`${section}/${page}` === "inventory/counts-and-adjustments" && (
        <InventoryRecordsPanel
          endpoint="/inventory/stocktakes"
          titleKey="settings.inventory.stocktakes.title"
          descKey="settings.inventory.stocktakes.desc"
          emptyKey="settings.inventory.stocktakes.empty"
          loadingKey="settings.inventory.stocktakes.loading"
          loadErrorKey="settings.inventory.stocktakes.loadError"
          footerKey="settings.inventory.stocktakes.whereToEdit"
          columns={[
            { key: "warehouse_id", kind: "num" },
            { key: "status", kind: "badge" },
            { key: "created_at", kind: "num" },
          ]}
        />
      )}

      {/* The till's devices screen is the real implementation; this page reuses it rather than
          growing a second register editor beside it. */}
      {`${section}/${page}` === "pos/registers-and-devices" && <DevicesSection />}

      {/* Suppliers, orders and returns are documents, not settings. Each page shows the rows the
          purchasing module already reports and leaves the rules to the registry. */}
      {`${section}/${page}` === "purchasing/suppliers" && (
        <InventoryRecordsPanel
          endpoint="/purchasing/suppliers"
          titleKey="settings.purchasing.suppliers.title"
          descKey="settings.purchasing.suppliers.desc"
          emptyKey="settings.purchasing.suppliers.empty"
          loadingKey="settings.purchasing.suppliers.loading"
          loadErrorKey="settings.purchasing.suppliers.loadError"
          footerKey="settings.purchasing.suppliers.whereToEdit"
          columns={[
            { key: "name" },
            { key: "phone", kind: "num" },
            { key: "city", kind: "num" },
            { key: "status", kind: "badge" },
          ]}
        />
      )}

      {`${section}/${page}` === "purchasing/purchase-orders" && (
        <InventoryRecordsPanel
          endpoint="/purchasing/purchase-orders"
          titleKey="settings.purchasing.orders.title"
          descKey="settings.purchasing.orders.desc"
          emptyKey="settings.purchasing.orders.empty"
          loadingKey="settings.purchasing.orders.loading"
          loadErrorKey="settings.purchasing.orders.loadError"
          footerKey="settings.purchasing.orders.whereToEdit"
          columns={[
            { key: "number" },
            { key: "order_date", kind: "num" },
            { key: "total", kind: "num" },
            { key: "status", kind: "badge" },
            { key: "payment_status", kind: "badge" },
          ]}
        />
      )}

      {`${section}/${page}` === "purchasing/supplier-returns" && (
        <InventoryRecordsPanel
          endpoint="/purchasing/supplier-returns"
          titleKey="settings.purchasing.returns.title"
          descKey="settings.purchasing.returns.desc"
          emptyKey="settings.purchasing.returns.empty"
          loadingKey="settings.purchasing.returns.loading"
          loadErrorKey="settings.purchasing.returns.loadError"
          footerKey="settings.purchasing.returns.whereToEdit"
          columns={[
            { key: "number" },
            { key: "return_date", kind: "num" },
            { key: "total", kind: "num" },
            { key: "status", kind: "badge" },
          ]}
        />
      )}
      {`${section}/${page}` === "locations/branch-data" && <BranchDataPanel />}
      {`${section}/${page}` === "locations/branch-hours" && <BranchHoursPanel />}
      {`${section}/${page}` === "locations/branch-staff" && <BranchStaffPanel />}
      {`${section}/${page}` === "locations/operating-scopes" && <BranchScopesPanel />}

      {POLICY_KEYS_BY_PAGE[`${section}/${page}`] && (
        <div className="space-y-2 pt-2">
          <div className="border-b border-border pb-2">
            <h2 className="font-display text-[14px] font-semibold leading-5">
              {t("settings.store.policies.title")}
            </h2>
            <p className="mt-0.5 text-[12.5px] text-muted-foreground">
              {t("settings.store.policies.desc")}
            </p>
          </div>
          <StorePolicyEditor keys={POLICY_KEYS_BY_PAGE[`${section}/${page}`]} />
        </div>
      )}

      {`${section}/${page}` === "store/business-policies" && <DepositPolicySettings />}

      {s.defs && s.defs.length > 0 && (
        <div className="flex items-center gap-2 pt-2">
          <Badge tone="muted">
            {isAr
              ? `${s.defs.length} إعدادًا في هذه الصفحة`
              : `${s.defs.length} ${s.defs.length === 1 ? "setting" : "settings"} on this page`}
          </Badge>
        </div>
      )}
    </SettingsShell>
  );
}
