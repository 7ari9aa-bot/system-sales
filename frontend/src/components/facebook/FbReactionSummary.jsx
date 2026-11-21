import React, { useRef, useState } from "react";
import { FB } from "@/components/facebook/fbTheme";
import { FbReactionBadge } from "@/components/facebook/fbIcons";
import { REACTION_KINDS, REACTION_LABEL, fetchReactionBreakdown, topReactions } from "@/lib/facebookApi";

/**
 * The reactions beside a post: the most used kinds as small overlapping badges and the total, as on
 * Facebook. Hovering or focusing it opens the count of each kind. The breakdown is read from Meta
 * once, on first use, never while the feed loads. A Page can read every kind but send only a like.
 *
 * `kinds` and `open` can be given (they are what the box shows), otherwise it loads and tracks them.
 */
export default function FbReactionSummary({ objectId, total, lang = "ar", kinds: given, open: openGiven }) {
  const ar = lang === "ar";
  const [loaded, setLoaded] = useState(null);
  const [openState, setOpen] = useState(false);
  const asked = useRef(false);
  const kinds = given || loaded;
  const open = openGiven ?? openState;
  if (!(total > 0)) return null;

  const show = () => {
    setOpen(true);
    if (asked.current || given || !objectId) return;
    asked.current = true;
    fetchReactionBreakdown(objectId).then((r) => setLoaded(r.kinds)).catch(() => { asked.current = false; });
  };
  const badges = kinds ? topReactions(kinds) : [{ kind: "LIKE", count: total }];
  const present = kinds ? REACTION_KINDS.filter((k) => (kinds[k] || 0) > 0) : [];

  return (
    <span className="relative inline-flex" onMouseEnter={show} onMouseLeave={() => setOpen(false)}>
      <button type="button" aria-haspopup="true" aria-expanded={open} onFocus={show} onBlur={() => setOpen(false)} className="inline-flex items-center gap-1.5 rounded-sm hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#0866ff]">
        <span className="flex -space-x-1 rtl:space-x-reverse">{badges.map((b) => <FbReactionBadge key={b.kind} kind={b.kind} />)}</span>
        <span>{total}</span>
      </button>
      {open && (
        <span role="tooltip" className="absolute start-0 top-full z-20 mt-1 min-w-[130px] rounded-lg bg-[#242526] px-3 py-2 text-[13px] text-white shadow-lg" style={{ fontFamily: FB.font }}>
          {kinds ? (
            present.length ? present.map((k) => (
              <span key={k} className="flex items-center justify-between gap-4 py-0.5">
                <span className="flex items-center gap-1.5"><FbReactionBadge kind={k} size={14} />{REACTION_LABEL[k][ar ? "ar" : "en"]}</span>
                <span>{kinds[k]}</span>
              </span>
            )) : <span>{total}</span>
          ) : <span>{ar ? "جارٍ التحميل..." : "Loading..."}</span>}
        </span>
      )}
    </span>
  );
}
