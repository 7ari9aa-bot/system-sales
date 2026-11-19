import React, { useMemo } from "react";
import { Link } from "react-router-dom";
import FbAvatar from "@/components/facebook/FbAvatar";
import { FB } from "@/components/facebook/fbTheme";
import { cn } from "@/lib/utils";
import { needsAnswer, useFacebookData } from "./useFacebookData";

/** /facebook/activity — Notifications, built from what the API gives: comments on the Page's posts. */
export default function FacebookActivityPage() {
  const { lang, posts, postsLoading, postsError } = useFacebookData();
  const ar = lang === "ar";
  const items = useMemo(() => {
    const out = [];
    for (const post of posts) {
      const walk = (list) => list.forEach((c) => { if (!c.isPage) out.push({ comment: c, post }); walk(c.replies || []); });
      walk(post.comments || []);
    }
    return out.sort((a, b) => new Date(b.comment.commentedAt || 0) - new Date(a.comment.commentedAt || 0));
  }, [posts]);
  return (
    <div className="h-full overflow-y-auto" data-testid="facebook-activity">
      <div className="mx-auto w-full max-w-[680px] px-3 py-4">
        <h1 className="mb-3 text-[24px] font-bold">{ar ? "الإشعارات" : "Notifications"}</h1>
        {postsError && <p role="alert" className="mb-2 text-[14px]" style={{ color: FB.red }}>{postsError}</p>}
        {postsLoading && items.length === 0 && <p role="status" style={{ color: FB.text2 }}>{ar ? "جارٍ التحميل..." : "Loading..."}</p>}
        {!postsLoading && !postsError && items.length === 0 && <p className="rounded-lg bg-white p-8 text-center text-[15px] shadow-[0_1px_2px_rgba(0,0,0,0.2)]" style={{ color: FB.text2 }}>{ar ? "عندما يعلّق أحد على منشورات الصفحة ستراه هنا." : "When someone comments on the Page's posts, you'll see it here."}</p>}
        <ul className="space-y-1">
          {items.map(({ comment, post }) => {
            const waiting = needsAnswer(comment);
            return (
              <li key={comment.id}>
                <Link to={`/facebook/posts/${encodeURIComponent(post.id)}`} className={cn("flex items-start gap-3 rounded-lg bg-white p-3 shadow-[0_1px_2px_rgba(0,0,0,0.2)] hover:bg-[#f2f2f2]", waiting && "ring-1 ring-[#0866ff]/40")}>
                  <FbAvatar src="" name={comment.author} size="h-12 w-12" />
                  <span className="min-w-0 flex-1 text-[15px]">
                    <span dir="auto"><b>{comment.author}</b> {ar ? "علّق:" : "commented:"} <span dir="auto">{comment.text}</span></span>
                    <span className="mt-0.5 block text-[13px]" style={{ color: waiting ? FB.blue : FB.text2 }}>{comment.timeLabel}{waiting ? ` · ${ar ? "بانتظار ردك" : "Waiting for your reply"}` : ""}</span>
                  </span>
                  {waiting && <span className="mt-2 h-3 w-3 shrink-0 rounded-full" style={{ background: FB.blue }} aria-hidden="true" />}
                </Link>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
