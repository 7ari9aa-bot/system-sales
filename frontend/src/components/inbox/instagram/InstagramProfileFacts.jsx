import React from "react";

const W = {
  en: { verified: "Verified", followers: "followers", followsYou: "Follows you", youFollow: "You follow them", notFollowing: "Not following each other" },
  ar: { verified: "حساب موثّق", followers: "متابع", followsYou: "يتابعك", youFollow: "أنت تتابعه", notFollowing: "لا يتابع أحدكما الآخر" },
};

/** 12500 -> "12.5K", 1200000 -> "1.2M", 950 -> "950". */
export function compactCount(n) {
  if (!Number.isFinite(n) || n < 0) return "";
  const fmt = (v, unit) => `${(Math.round(v * 10) / 10).toString().replace(/\.0$/, "")}${unit}`;
  if (n >= 1_000_000) return fmt(n / 1_000_000, "M");
  if (n >= 1_000) return fmt(n / 1_000, "K");
  return String(Math.trunc(n));
}

/** The blue tick Instagram puts after a verified account's name. */
export function VerifiedBadge({ lang = "ar", className = "" }) {
  const label = W[lang === "ar" ? "ar" : "en"].verified;
  return (
    <svg data-testid="ig-verified" role="img" aria-label={label} viewBox="0 0 24 24" width="14" height="14" className={`inline-block shrink-0 align-[-2px] ${className}`}>
      <title>{label}</title>
      <path fill="#0095f6" d="M12 1.5l2.6 1.9 3.2-.1 1 3.1 2.6 1.9-1 3.1 1 3.1-2.6 1.9-1 3.1-3.2-.1L12 22.5l-2.6-1.9-3.2.1-1-3.1-2.6-1.9 1-3.1-1-3.1 2.6-1.9 1-3.1 3.2.1z" />
      <path fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" d="M7.8 12.3l3 3 5.4-6" />
    </svg>
  );
}

/** What Instagram told us about the person. Draws only what is known; nothing is guessed. */
export function InstagramProfileFacts({ conversation, lang = "ar" }) {
  const w = W[lang === "ar" ? "ar" : "en"];
  const count = Number.isFinite(conversation?.followerCount) ? compactCount(conversation.followerCount) : "";
  const { followsYou, youFollow } = conversation || {};
  let relation = "";
  if (followsYou != null || youFollow != null) {
    if (followsYou && youFollow) relation = `${w.followsYou} · ${w.youFollow}`;
    else if (followsYou) relation = w.followsYou;
    else if (youFollow) relation = w.youFollow;
    else relation = w.notFollowing;
  }
  if (!count && !relation) return null;
  return (
    <div data-testid="ig-profile-facts" dir="auto" className="mt-1 space-y-0.5 text-[12.5px] text-[#737373]">
      {count && <div data-testid="ig-follower-count"><span className="font-semibold text-[#262626]">{count}</span> {w.followers}</div>}
      {relation && <div data-testid="ig-relation">{relation}</div>}
    </div>
  );
}
