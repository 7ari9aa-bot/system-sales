import React from "react";
import { useI18n } from "@/lib/i18n";

/**
 * A page the manifest names but nobody has written yet.
 *
 * It exists so a manifest entry can never be silently dropped from the tab strip by a wrapper
 * that has no body for it: the tab appears, opens, and says the screen is not built. The
 * manifest test asserts this never happens — every manifest page must have a view — so seeing
 * this in the app means the manifest and the wrapper drifted, which is the bug worth showing.
 */
export default function MissingPage({ slug }) {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-4 text-[13px] text-muted-foreground">
      {isAr
        ? `الصفحة «${slug}» معرَّفة في خريطة المركز لكن شاشتها لم تُبنَ بعد.`
        : `The page “${slug}” is declared in the Center map but its screen is not built yet.`}
    </div>
  );
}
