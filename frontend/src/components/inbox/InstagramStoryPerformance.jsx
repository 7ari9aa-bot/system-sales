import React from "react";
import { storyRows } from "@/lib/socialApi";

/**
 * How the account's stories performed, in Meta's own numbers.
 *
 * A story lives 24 hours and its metrics arrive afterwards, so three states are shown honestly:
 * «لسه موصلناش» for a metric Meta has not delivered, «أقل من ٥» for Meta's -1 sentinel, and the
 * number itself. Nothing is rounded up, shown as 0, or hidden because it is small.
 */
export default function InstagramStoryPerformance({ stories = [], lang = "ar", className = "" }) {
  const isAr = lang === "ar";
  const list = stories.filter((s) => s && (s.isStory || s.insights));

  if (!list.length) {
    return (
      <div data-testid="ig-story-performance" className={className}>
        <h3 className="text-[15px] font-semibold">{isAr ? "أداء الستوري" : "Story performance"}</h3>
        <p className="mt-1 text-[13px] text-[#737373]">
          {isAr
            ? "لا توجد ستوري لها أرقام حتى الآن. ميتا ترسل أرقام الستوري بعد انتهاء الـ24 ساعة."
            : "No story has numbers yet. Meta sends a story's metrics after its 24 hours end."}
        </p>
      </div>
    );
  }

  return (
    <div data-testid="ig-story-performance" className={className}>
      <h3 className="text-[15px] font-semibold">{isAr ? "أداء الستوري" : "Story performance"}</h3>
      <ul className="mt-2 space-y-3">
        {list.map((story) => {
          const rows = storyRows(story.insights, isAr);
          return (
            <li key={story.id} data-testid={`ig-story-${story.id}`} className="flex gap-3">
              {story.mediaUrl ? (
                <img src={story.mediaUrl} alt="" className="h-16 w-12 shrink-0 rounded-md object-cover" />
              ) : (
                <div className="h-16 w-12 shrink-0 rounded-md bg-[#efefef]" aria-hidden="true" />
              )}
              <div className="min-w-0">
                <div className="text-[12.5px] text-[#737373]">{story.timeLabel || ""}</div>
                {rows.length === 0 ? (
                  <p className="text-[13px] text-[#737373]">{isAr ? "لم تصلنا أرقامها بعد" : "No numbers delivered yet"}</p>
                ) : (
                  <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                    {rows.map((row) => (
                      <div key={row.key} className="text-[13px]">
                        <dt className="text-[#737373]">{row.label}</dt>
                        <dd className={`font-semibold ${row.belowThreshold ? "text-[#737373]" : "text-[#262626]"}`}>{row.text}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
