import React from "react";
import { ClipboardList, Repeat, RotateCcw, ShoppingCart } from "lucide-react";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** أقسام المبيعات الأربعة — نفس ترويسة التصميم الجديد (أيقونة + عنوان + شرح). */
const SECTIONS = {
  new: { icon: ShoppingCart, titleKey: "sales.new.title", hintKey: "sales.new.hint" },
  returns: { icon: RotateCcw, titleKey: "sales.returns.title", hintKey: "sales.returns.hint" },
  exchanges: { icon: Repeat, titleKey: "sales.exchanges.title", hintKey: "sales.exchanges.hint" },
  history: { icon: ClipboardList, titleKey: "sales.history.title", hintKey: "sales.history.hint" },
};

function SectionHeader({ section }) {
  const t = useT();
  const meta = SECTIONS[section] || SECTIONS.new;
  const Icon = meta.icon;
  return (
    <header className="mb-4 flex items-center gap-3">
      <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent text-accent-foreground">
        <Icon className="h-5 w-5" />
      </span>
      <div className="min-w-0">
        <h1 className="truncate font-heading text-xl font-bold">{t(meta.titleKey)}</h1>
        <p className="truncate text-xs text-muted-foreground">{t(meta.hintKey)}</p>
      </div>
    </header>
  );
}

function EmptyState({ children }) {
  return (
    <div className="grid flex-1 place-items-center px-6 py-10 text-center">
      <p className="max-w-sm text-sm text-muted-foreground">{children}</p>
    </div>
  );
}

const FIELD = "h-10 rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** بيع جديد: باركود + جدول أصناف + إجمال. الجدول فاضي عمدًا — الوحدة لسه
 *  متربطتش بـ/pos، وأي رقم هنا لازم يجي من السيرفر لا من هنا. */
function NewSalePanel() {
  const t = useT();
  return (
    <section className="flex min-h-[520px] flex-1 flex-col overflow-hidden rounded-xl border border-foreground/30 bg-card shadow-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-3">
        <input
          dir="ltr"
          aria-label={t("sales.scanLabel")}
          placeholder={t("sales.scanPlaceholder")}
          className={cn(FIELD, "min-w-0 flex-1")}
        />
        <button type="button" disabled className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground opacity-50">
          {t("sales.scanAdd")}
        </button>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] gap-3 border-b border-border px-4 py-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        <span>{t("sales.colItem")}</span>
        <span className="w-16 text-center">{t("sales.colQty")}</span>
        <span className="w-24 text-end">{t("sales.colPrice")}</span>
        <span className="w-24 text-end">{t("sales.colTotal")}</span>
      </div>
      <EmptyState>{t("sales.cartEmpty")}</EmptyState>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border p-3">
        <div className="text-sm text-muted-foreground">{t("sales.netTotal")} <span className="ms-1 font-semibold text-foreground tabular-nums">—</span></div>
        <button type="button" disabled className="h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground opacity-50">
          {t("sales.complete")}
        </button>
      </div>
    </section>
  );
}

/** المرتجعات والاستبدال: فتح الفاتورة الأصلية أولًا، ثم تحديد الكميات. */
function InvoiceLookupPanel({ actionKey, itemsKey }) {
  const t = useT();
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-card p-3 shadow-card">
        <input
          dir="ltr"
          aria-label={t("sales.lookupLabel")}
          placeholder={t("sales.lookupPlaceholder")}
          className={cn(FIELD, "min-w-0 flex-1")}
        />
        <button type="button" disabled className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground opacity-50">
          {t(actionKey)}
        </button>
      </div>
      <div className="rounded-xl border border-border bg-card p-3 shadow-card">
        <EmptyState>{t(itemsKey)}</EmptyState>
      </div>
    </section>
  );
}

export default function SalesWorkspace({ section }) {
  const t = useT();
  return (
    <div className="flex min-h-full flex-col">
      <SectionHeader section={section} />
      {section === "new" ? <NewSalePanel /> : null}
      {section === "returns" ? <InvoiceLookupPanel actionKey="sales.confirmReturn" itemsKey="sales.returnsEmpty" /> : null}
      {section === "exchanges" ? <InvoiceLookupPanel actionKey="sales.confirmExchange" itemsKey="sales.exchangesEmpty" /> : null}
      {section === "history" ? <p className="text-sm text-muted-foreground">{t("sales.history.title")}</p> : null}
    </div>
  );
}
