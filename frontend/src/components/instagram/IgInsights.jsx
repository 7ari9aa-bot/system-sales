import React, { useEffect, useState } from "react";
import { fetchPostInsights } from "@/lib/socialApi";
import { IG } from "./igTheme";

// Likes and comments are already on the post, so only what Instagram adds is shown here.
const LABELS = {
  reach: { en: "Reach", ar: "الوصول" },
  views: { en: "Views", ar: "المشاهدات" },
  saved: { en: "Saves", ar: "الحفظ" },
  shares: { en: "Shares", ar: "المشاركات" },
  replies: { en: "Replies", ar: "الردود" },
  total_interactions: { en: "Interactions", ar: "التفاعلات" },
};

/** One row of post statistics from Instagram. "No data yet" (null) is shown as a dash, never as a 0. */
export default function IgInsights({ postId, lang = "ar" }) {
  const ar = lang === "ar";
  const [state, setState] = useState({ loading: true, metrics: null, error: "" });
  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, metrics: null, error: "" });
    fetchPostInsights(postId)
      .then((metrics) => { if (!cancelled) setState({ loading: false, metrics, error: "" }); })
      .catch((e) => { if (!cancelled) setState({ loading: false, metrics: null, error: e?.message || "error" }); });
    return () => { cancelled = true; };
  }, [postId]);

  if (state.loading) return null;
  if (state.error) {
    return <p data-testid="ig-insights-error" role="alert" className="mt-2 text-[12px]" style={{ color: IG.error }}>{ar ? "تعذّر تحميل إحصائيات المنشور." : "Couldn't load this post's insights."}</p>;
  }
  const shown = Object.keys(LABELS).filter((k) => k in (state.metrics || {}));
  if (!shown.length) return null;
  const empty = shown.every((k) => state.metrics[k] === null);
  return (
    <div data-testid="ig-insights" className="mt-2">
      <dl className="flex flex-wrap gap-x-5 gap-y-1">
        {shown.map((k) => (
          <div key={k} className="flex items-baseline gap-1.5">
            <dd data-testid={`ig-insight-${k}`} className="text-[14px] font-semibold">{state.metrics[k] === null ? "—" : Number(state.metrics[k]).toLocaleString(ar ? "ar-EG" : "en-US")}</dd>
            <dt className="text-[12px]" style={{ color: IG.secondary }}>{LABELS[k][ar ? "ar" : "en"]}</dt>
          </div>
        ))}
      </dl>
      {empty && <p className="mt-1 text-[12px] leading-4" style={{ color: IG.secondary }}>{ar ? "لم تصل أرقام هذا المنشور بعد. قد تتأخر حتى 48 ساعة." : "No numbers for this post yet. They can take up to 48 hours."}</p>}
    </div>
  );
}
