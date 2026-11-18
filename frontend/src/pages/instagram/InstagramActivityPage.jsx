import React, { useMemo } from "react";
import { Link } from "react-router-dom";
import IgAvatar from "@/components/instagram/IgAvatar";
import { IG, igShortTime } from "@/components/instagram/igTheme";
import { IgHeart } from "@/components/instagram/igIcons";
import { cn } from "@/lib/utils";
import { needsAnswer, useInstagramData } from "./useInstagramData";

const DAY = 24 * 3600 * 1000;

/** /instagram/activity — Instagram's Notifications, built from what the API gives: comments on the shop's posts. */
export default function InstagramActivityPage() {
  const { lang, posts, postsLoading, postsError } = useInstagramData();
  const isArabic = lang === "ar";
  const items = useMemo(() => {
    const out = [];
    for (const post of posts) {
      const walk = (list) => list.forEach((c) => { if (!c.isPage) out.push({ comment: c, post }); walk(c.replies || []); });
      walk(post.comments || []);
    }
    return out.sort((a, b) => new Date(b.comment.commentedAt || 0) - new Date(a.comment.commentedAt || 0));
  }, [posts]);
  const groups = [
    [isArabic ? "اليوم" : "Today", (age) => age < DAY],
    [isArabic ? "هذا الأسبوع" : "This week", (age) => age >= DAY && age < 7 * DAY],
    [isArabic ? "هذا الشهر" : "This month", (age) => age >= 7 * DAY && age < 30 * DAY],
    [isArabic ? "أقدم" : "Earlier", (age) => age >= 30 * DAY],
  ];
  const ageOf = (item) => Date.now() - new Date(item.comment.commentedAt || 0).getTime();

  return (
    <div className="flex h-full min-h-0">
      <div className="h-full w-full shrink-0 overflow-y-auto border-e py-6 md:w-[397px]" style={{ borderColor: IG.border }}>
        <h1 className="px-6 pb-4 text-[24px] font-bold">{isArabic ? "الإشعارات" : "Notifications"}</h1>
        {postsError && <p role="alert" className="px-6 text-[14px]" style={{ color: IG.error }}>{postsError}</p>}
        {postsLoading && items.length === 0 && <p role="status" className="px-6 text-[14px]" style={{ color: IG.secondary }}>{isArabic ? "جارٍ التحميل…" : "Loading…"}</p>}
        {!postsLoading && !postsError && items.length === 0 && (
          <div className="px-6 py-16 text-center">
            <span className="mx-auto grid h-16 w-16 place-items-center rounded-full border-2 border-[#0c1014]"><IgHeart size={32} /></span>
            <p className="mt-4 text-[14px]">{isArabic ? "عندما يعلّق أحد على منشوراتك ستراه هنا." : "When someone comments on your posts, you'll see it here."}</p>
          </div>
        )}
        {groups.map(([title, test]) => {
          const list = items.filter((item) => test(ageOf(item)));
          if (!list.length) return null;
          return (
            <section key={title} aria-label={title} className="border-b py-2" style={{ borderColor: IG.border }}>
              <h2 className="px-6 py-2 text-[16px] font-bold">{title}</h2>
              {list.map(({ comment, post }) => {
                const waiting = needsAnswer(comment);
                return (
                  <Link key={comment.id} to={`/instagram/p/${encodeURIComponent(post.id)}`} data-testid="ig-activity-row" className="flex items-center gap-3 px-6 py-2 hover:bg-[#f3f5f7]">
                    <IgAvatar src={comment.avatarUrl} size={44} />
                    <p className="min-w-0 flex-1 text-[14px] leading-[18px]">
                      <bdi dir="auto" className="font-semibold">{comment.handle || comment.author}</bdi>{" "}
                      {isArabic ? "علّق:" : "commented:"} <span dir="auto" className="[unicode-bidi:isolate]">{comment.text}</span>{" "}
                      <span style={{ color: IG.secondary }}>{igShortTime(comment.commentedAt, lang)}</span>
                      {waiting && <span className={cn("ms-2 inline-block rounded px-1.5 text-[11px] font-semibold text-white")} style={{ background: IG.blue }}>{isArabic ? "بدون رد" : "Needs reply"}</span>}
                    </p>
                    <span className="h-11 w-11 shrink-0 overflow-hidden rounded-[4px] bg-[#f3f5f7]">{post.mediaUrl && post.mediaType !== "video" && <img src={post.mediaUrl} alt="" className="h-full w-full object-cover" />}</span>
                  </Link>
                );
              })}
            </section>
          );
        })}
      </div>
      <div className="hidden min-w-0 flex-1 md:block" aria-hidden="true" />
    </div>
  );
}
