import React, { useCallback, useEffect } from "react";
import { PageHeader } from "@/components/dashboard/ui";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import PendingPurchase from "./PendingPurchase";
import SiteControl from "./SiteControl";
import TemplateGallery from "./TemplateGallery";

/**
 * «My Website» (§206) — the in-house website builder.
 * One page, three merchant states driven by GET /website/overview:
 *  - none:    the template gallery (choose a design -> purchase)
 *  - pending: payment instructions + the payment-reference bookkeeping
 *  - active:  the website control page (identity, content, publish)
 */

export default function MyWebsite() {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const L = (ar, en) => (isAr ? ar : en);

  const [overview, setOverview] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const initialLoad = React.useRef(true);
  const [error, setError] = React.useState("");
  const [attempt, setAttempt] = React.useState(0);
  const refresh = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api("/website/overview")
      .then((data) => {
        if (alive) setOverview(data);
      })
      .catch((err) => {
        if (alive) setError(err?.message || L("تعذر تحميل حالة الموقع", "Could not load website status"));
      })
      .finally(() => {
        if (alive) {
          setLoading(false);
          initialLoad.current = false;
        }
      });
    return () => {
      alive = false;
    };
     
  }, [attempt]);

  return (
    <div className="space-y-6">
      <PageHeader
        title={L("موقعي", "My Website")}
        subtitle={L(
          "اختر تصميمًا لموقع متجرك، ادفعه، وخصصه وانشره. منتجاتك من الكتالوج تظهر عليه تلقائيًا.",
          "Pick a design for your store's website, pay for it, then customize and publish. Your catalog products appear automatically.",
        )}
      />

      {error ? (
        <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>
      ) : null}

      {loading && initialLoad.current ? (
        <div className="rounded-xl border bg-card p-6">
          <div className="animate-pulse space-y-3">
            <div className="h-4 w-1/3 rounded bg-muted" />
            <div className="h-24 rounded bg-muted" />
          </div>
        </div>
      ) : !overview ? null : overview.state === "active" ? (
        <SiteControl overview={overview} onMutate={refresh} />
      ) : overview.state === "pending" ? (
        <PendingPurchase overview={overview} onMutate={refresh} />
      ) : (
        <TemplateGallery onPurchased={refresh} />
      )}
    </div>
  );
}
