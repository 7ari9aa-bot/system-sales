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
  locations: ["all-branches", "branch-settings"],
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

      {domains.length === 0 && !POLICY_KEYS_BY_PAGE[`${section}/${page}`] && (
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
