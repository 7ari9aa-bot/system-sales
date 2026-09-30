import { useCallback } from "react";
import { useI18n } from "@/lib/i18n";

const LOCALES = { en: "en-US", ar: "ar-EG-u-nu-latn" };

// Locale-aware relative time ("2m ago") and short day ("Sep 28") formatters.
export function useFormatters() {
  const { lang } = useI18n();
  const loc = LOCALES[lang] || LOCALES.en;

  const ago = useCallback(
    (iso) => {
      if (!iso) return "—";
      const diff = (new Date(iso).getTime() - Date.now()) / 1000;
      const rtf = new Intl.RelativeTimeFormat(loc, { numeric: "auto", style: "short" });
      const abs = Math.abs(diff);
      if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
      return rtf.format(Math.round(diff / 86400), "day");
    },
    [loc]
  );

  const day = useCallback(
    (iso) => (iso ? new Intl.DateTimeFormat(loc, { month: "short", day: "numeric" }).format(new Date(iso)) : "—"),
    [loc]
  );

  return { ago, day };
}