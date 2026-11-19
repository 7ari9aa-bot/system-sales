import React, { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import FbAvatar from "@/components/facebook/FbAvatar";
import FbPostCard from "@/components/facebook/FbPostCard";
import { FB } from "@/components/facebook/fbTheme";
import { FbClock } from "@/components/facebook/fbIcons";
import { fetchScheduled } from "@/lib/facebookApi";
import { useFacebookData } from "./useFacebookData";

function Scheduled({ lang, enabled }) {
  const ar = lang === "ar";
  const q = useQuery({ queryKey: ["facebook-scheduled"], queryFn: fetchScheduled, enabled, retry: 1 });
  const items = q.data || [];
  if (!items.length) return null;
  const when = (s) => (s ? new Date(Number(s) * 1000 || s).toLocaleString(ar ? "ar-EG" : "en-GB", { dateStyle: "medium", timeStyle: "short" }) : "");
  return (
    <section aria-label={ar ? "منشورات مجدولة" : "Scheduled posts"} className="rounded-lg bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.2)]">
      <h2 className="mb-2 flex items-center gap-2 text-[17px] font-bold"><FbClock size={18} />{ar ? "منشورات مجدولة" : "Scheduled posts"}</h2>
      <ul className="space-y-2">
        {items.map((p) => (
          <li key={p.id} className="rounded-lg p-3 text-[15px]" style={{ background: FB.bg }}>
            <p dir="auto" className="line-clamp-3 whitespace-pre-wrap">{p.message || (ar ? "(بدون نص)" : "(no text)")}</p>
            <p className="mt-1 text-[13px]" style={{ color: FB.text2 }}>{when(p.scheduled_for)}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The Page's feed: its real posts, newest first, with comments under each. */
export default function FacebookPostsPage() {
  const { lang, live, posts, postsLoading, pageName, pageAvatar, page, canAct } = useFacebookData();
  const { postId } = useParams();
  const [insights, setInsights] = useState(null);
  const ar = lang === "ar";
  const shown = useMemo(() => (postId ? posts.filter((p) => p.id === postId) : posts), [posts, postId]);
  const actions = live;
  return (
    <div className="h-full overflow-y-auto overscroll-contain" data-testid="facebook-posts">
      <div className="mx-auto w-full max-w-[680px] space-y-4 px-3 py-4">
        <section className="flex items-center gap-3 rounded-lg bg-white p-4 shadow-[0_1px_2px_rgba(0,0,0,0.2)]">
          <FbAvatar src={pageAvatar} name={pageName} size="h-14 w-14" />
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-[20px] font-bold">{pageName || (ar ? "الصفحة" : "Page")}</h1>
            <p className="text-[13px]" style={{ color: FB.text2 }}>
              {page?.followers_count != null ? `${page.followers_count.toLocaleString(ar ? "ar-EG" : "en-GB")} ${ar ? "متابع" : "followers"}` : page?.about || ""}
            </p>
          </div>
          {canAct && <button type="button" onClick={live.refresh} disabled={postsLoading} className="rounded-md bg-[#e4e6eb] px-3 py-1.5 text-[14px] font-semibold hover:bg-[#d8dadf] disabled:opacity-60">{postsLoading ? (ar ? "جارٍ التحديث..." : "Refreshing...") : (ar ? "تحديث" : "Refresh")}</button>}
        </section>
        <Scheduled lang={lang} enabled={canAct} />
        {shown.map((post) => (
          <FbPostCard key={post.id} post={post} pageName={pageName} pageAvatar={pageAvatar} lang={lang} actions={actions} onOpenInsights={setInsights} />
        ))}
        {!postsLoading && shown.length === 0 && (
          <p className="rounded-lg bg-white p-8 text-center text-[15px] shadow-[0_1px_2px_rgba(0,0,0,0.2)]" style={{ color: FB.text2 }}>
            {canAct ? (ar ? "لا توجد منشورات بعد. اضغط + لإنشاء أول منشور." : "No posts yet. Press + to create the first one.") : (ar ? "الحساب التجريبي لا يملك صفحة فيسبوك متصلة." : "The demo account has no connected Facebook Page.")}
          </p>
        )}
        {postsLoading && shown.length === 0 && <p role="status" className="p-8 text-center text-[15px]" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
      </div>
      {insights && <FbPostInsightsDialog post={insights} lang={lang} onClose={() => setInsights(null)} />}
    </div>
  );
}

function FbPostInsightsDialog({ post, lang, onClose }) {
  const ar = lang === "ar";
  const q = useQuery({ queryKey: ["facebook-post-insights", post.id], queryFn: () => import("@/lib/facebookApi").then((m) => m.fetchFacebookPostInsights(post.id)), retry: 0 });
  const rows = (q.data || []).map((m) => ({ name: m.name, value: m.values?.[0]?.value }));
  const label = {
    post_media_view: ar ? "مرات العرض" : "Views",
    post_reactions_like_total: ar ? "إعجاب" : "Like",
    post_reactions_love_total: ar ? "حب" : "Love",
    post_reactions_wow_total: ar ? "واو" : "Wow",
    post_reactions_haha_total: ar ? "هاها" : "Haha",
    post_reactions_sorry_total: ar ? "حزين" : "Sad",
    post_reactions_anger_total: ar ? "غاضب" : "Angry",
  };
  return (
    <div role="dialog" aria-modal="true" aria-label={ar ? "إحصاءات المنشور" : "Post insights"} dir={ar ? "rtl" : "ltr"} className="fixed inset-0 z-50 grid place-items-center bg-white/80 p-3" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="w-full max-w-[420px] rounded-xl bg-white p-4 shadow-[0_12px_28px_rgba(0,0,0,0.2),0_2px_4px_rgba(0,0,0,0.1)]">
        <div className="mb-3 flex items-center justify-between"><h2 className="text-[18px] font-bold">{ar ? "إحصاءات المنشور" : "Post insights"}</h2><button type="button" onClick={onClose} aria-label={ar ? "إغلاق" : "Close"} className="grid h-8 w-8 place-items-center rounded-full bg-[#e4e6eb] text-[18px] leading-none">×</button></div>
        {q.isLoading && <p role="status" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
        {q.error && <p role="alert" style={{ color: FB.red }}>{q.error.message || (ar ? "تعذّر تحميل الإحصاءات" : "Could not load insights")}</p>}
        {q.data && rows.length === 0 && <p style={{ color: FB.text2 }}>{ar ? "لا توجد بيانات بعد. قد تتأخر الأرقام حتى 48 ساعة." : "No data yet. Numbers can take up to 48 hours."}</p>}
        <dl className="divide-y" style={{ borderColor: FB.divider }}>
          {rows.map((r) => <div key={r.name} className="flex justify-between py-2 text-[15px]"><dt>{label[r.name] || r.name}</dt><dd className="font-semibold">{r.value == null ? "—" : Number(r.value).toLocaleString(ar ? "ar-EG" : "en-GB")}</dd></div>)}
        </dl>
      </div>
    </div>
  );
}
