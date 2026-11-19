import React, { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FB } from "@/components/facebook/fbTheme";
import FacebookReelStoryDialog from "@/components/facebook/FacebookReelStoryDialog";
import { fbAge, fetchFacebookReels, fetchFacebookStories, publishFacebookReel, publishFacebookStory } from "@/lib/facebookApi";
import { useFacebookData } from "./useFacebookData";

const card = "rounded-lg bg-white shadow-[0_1px_2px_rgba(0,0,0,0.2)]";

function Empty({ children }) {
  return <p className={`${card} p-8 text-center`} style={{ color: FB.text2 }}>{children}</p>;
}

/** Unix seconds (as Meta sends them) or an ISO time, as a short age. */
function ageOf(value, lang) {
  if (!value) return "";
  const n = Number(value);
  return fbAge(Number.isFinite(n) && n > 1e9 ? new Date(n * 1000).toISOString() : value, lang);
}

/** /facebook/reels — the Page's Reels and Stories from Meta, and the way to publish a new one. */
export default function FacebookReelsPage() {
  const { lang, canAct } = useFacebookData();
  const ar = lang === "ar";
  const qc = useQueryClient();
  const [tab, setTab] = useState("reels");
  const [creating, setCreating] = useState(null);
  const reels = useQuery({ queryKey: ["facebook-reels"], queryFn: () => fetchFacebookReels(), enabled: canAct, retry: 0, staleTime: 60 * 1000 });
  const stories = useQuery({ queryKey: ["facebook-stories"], queryFn: fetchFacebookStories, enabled: canAct, retry: 0, staleTime: 60 * 1000 });
  const q = tab === "reels" ? reels : stories;
  const items = q.data || [];
  const tabBtn = (id, label) => (
    <button key={id} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)} className={`h-10 flex-1 rounded-lg text-[15px] font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff] ${tab === id ? "bg-[#e7f3ff] text-[#0866ff]" : "text-[#65676b] hover:bg-[#f2f2f2]"}`}>{label}</button>
  );
  return (
    <div className="h-full overflow-y-auto" data-testid="facebook-reels">
      <div className="mx-auto w-full max-w-[680px] px-3 py-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <h1 className="text-[24px] font-bold">{ar ? "الريلز والستوري" : "Reels and Stories"}</h1>
          {canAct && (
            <button type="button" onClick={() => setCreating(tab === "reels" ? "reel" : "story")} className="h-9 rounded-md px-4 text-[15px] font-semibold text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff] focus-visible:ring-offset-2" style={{ background: FB.blue }}>
              {tab === "reels" ? (ar ? "ريل جديد" : "New reel") : (ar ? "ستوري جديد" : "New story")}
            </button>
          )}
        </div>
        <div role="tablist" aria-label={ar ? "النوع" : "Type"} className={`${card} mb-3 flex gap-1 p-1`}>
          {tabBtn("reels", ar ? "الريلز" : "Reels")}
          {tabBtn("stories", ar ? "الستوري" : "Stories")}
        </div>
        {!canAct && <Empty>{ar ? "الحساب التجريبي لا يملك صفحة فيسبوك متصلة." : "The demo account has no connected Facebook Page."}</Empty>}
        {canAct && q.isLoading && <p role="status" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
        {canAct && q.error && <p role="alert" className={`${card} p-4 text-[14px]`} style={{ color: FB.red }}>{q.error.message || (ar ? "تعذّر التحميل" : "Could not load")}</p>}
        {canAct && !q.isLoading && !q.error && items.length === 0 && <Empty>{tab === "reels" ? (ar ? "لا ريلز منشورة بعد." : "No Reels yet.") : (ar ? "لا ستوري حاليًا." : "No Stories right now.")}</Empty>}
        <ul className="space-y-3">
          {tab === "reels" && items.map((r) => (
            <li key={r.id} className={`${card} flex gap-3 p-3`}>
              {r.picture ? <img src={r.picture} alt="" className="h-[96px] w-[54px] shrink-0 rounded-md object-cover" /> : <span className="h-[96px] w-[54px] shrink-0 rounded-md" style={{ background: FB.bg }} />}
              <div className="min-w-0 flex-1">
                <p className="line-clamp-3 text-[15px]" dir="auto">{r.description || r.title || (ar ? "ريل بلا وصف" : "Reel without a description")}</p>
                <p className="mt-1 text-[12px]" style={{ color: FB.text2 }}>{ageOf(r.updated_at, lang)}{r.length ? ` · ${Math.round(r.length)} ${ar ? "ث" : "s"}` : ""}</p>
                {r.permalink && <a href={r.permalink.startsWith("http") ? r.permalink : `https://www.facebook.com${r.permalink}`} target="_blank" rel="noopener noreferrer" className="mt-1 inline-block text-[13px] font-semibold text-[#0866ff] hover:underline">{ar ? "فتح على فيسبوك" : "Open on Facebook"}</a>}
              </div>
            </li>
          ))}
          {tab === "stories" && items.map((s) => (
            <li key={s.id} className={`${card} flex items-center justify-between gap-3 p-3`}>
              <div className="min-w-0">
                <p className="text-[15px] font-semibold">{s.type === "video" ? (ar ? "ستوري فيديو" : "Video story") : (ar ? "ستوري صورة" : "Photo story")}</p>
                <p className="text-[12px]" style={{ color: FB.text2 }}>{ageOf(s.created_at, lang)} · {s.status === "ARCHIVED" ? (ar ? "في الأرشيف" : "Archived") : (ar ? "منشور" : "Live")}</p>
              </div>
              {s.url && <a href={s.url} target="_blank" rel="noopener noreferrer" className="shrink-0 text-[13px] font-semibold text-[#0866ff] hover:underline">{ar ? "فتح" : "Open"}</a>}
            </li>
          ))}
        </ul>
      </div>
      {creating && canAct && (
        <FacebookReelStoryDialog
          kind={creating}
          lang={lang}
          onPublishReel={async (input) => {
            const out = await publishFacebookReel(input);
            qc.invalidateQueries({ queryKey: ["facebook-reels"] });
            return out;
          }}
          onPublishStory={async (input) => {
            const out = await publishFacebookStory(input);
            qc.invalidateQueries({ queryKey: ["facebook-stories"] });
            return out;
          }}
          onClose={() => setCreating(null)}
        />
      )}
    </div>
  );
}
