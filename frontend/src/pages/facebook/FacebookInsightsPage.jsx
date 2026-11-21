import React from "react";
import { useQuery } from "@tanstack/react-query";
import { FB } from "@/components/facebook/fbTheme";
import FbSparkline from "@/components/facebook/FbSparkline";
import { dailySeries, fetchFacebookInsights } from "@/lib/facebookApi";
import { useFacebookData } from "./useFacebookData";

// Only the metrics Meta still serves (the old reach, impressions and fan metrics were removed).
const LABELS = {
  page_follows: { ar: "المتابعون", en: "Followers" },
  page_media_view: { ar: "مرات عرض المحتوى", en: "Content views" },
  page_post_engagements: { ar: "التفاعلات مع المنشورات", en: "Post engagements" },
};

/** /facebook/insights — the Page's numbers for the last days, from Meta. */
export default function FacebookInsightsPage() {
  const { lang, canAct } = useFacebookData();
  const ar = lang === "ar";
  const q = useQuery({ queryKey: ["facebook-insights"], queryFn: fetchFacebookInsights, enabled: canAct, retry: 0, staleTime: 5 * 60 * 1000 });
  const cards = (q.data || []).map((m) => {
    const values = (m.values || []).map((v) => v.value).filter((v) => typeof v === "number");
    return { name: m.name, series: dailySeries(m), total: values.reduce((a, b) => a + b, 0), last: values.at(-1), days: values.length, has: values.length > 0 };
  });
  const fmt = (n) => Number(n).toLocaleString(ar ? "ar-EG" : "en-GB");
  return (
    <div className="h-full overflow-y-auto" data-testid="facebook-insights">
      <div className="mx-auto w-full max-w-[680px] px-3 py-4">
        <h1 className="mb-1 text-[24px] font-bold">{ar ? "الإحصاءات" : "Insights"}</h1>
        <p className="mb-3 text-[13px]" style={{ color: FB.text2 }}>{ar ? "أرقام يومية من فيسبوك. قد تتأخر حتى 48 ساعة." : "Daily numbers from Facebook. They can lag up to 48 hours."}</p>
        {!canAct && <p className="rounded-lg bg-white p-8 text-center shadow-[0_1px_2px_rgba(0,0,0,0.2)]" style={{ color: FB.text2 }}>{ar ? "الحساب التجريبي لا يملك صفحة فيسبوك متصلة." : "The demo account has no connected Facebook Page."}</p>}
        {q.isLoading && <p role="status" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
        {q.error && <p role="alert" className="rounded-lg bg-white p-4 text-[14px] shadow-[0_1px_2px_rgba(0,0,0,0.2)]" style={{ color: FB.red }}>{q.error.message || (ar ? "تعذّر تحميل الإحصاءات" : "Could not load insights")}</p>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {cards.map((c) => (
            <div key={c.name} className="rounded-lg bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.2)]">
              <p className="text-[13px]" style={{ color: FB.text2 }}>{LABELS[c.name]?.[ar ? "ar" : "en"] || c.name}</p>
              <p className="mt-1 text-[28px] font-bold leading-none">{c.has ? fmt(c.name === "page_follows" ? c.last : c.total) : "—"}</p>
              <p className="mt-1 text-[12px]" style={{ color: FB.text2 }}>{c.has ? (c.name === "page_follows" ? (ar ? "الآن" : "Now") : ar ? `آخر ${c.days} أيام` : `Last ${c.days} days`) : (ar ? "لا بيانات بعد" : "No data yet")}</p>
              <FbSparkline series={c.series} lang={lang} label={LABELS[c.name]?.[ar ? "ar" : "en"] || c.name} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
