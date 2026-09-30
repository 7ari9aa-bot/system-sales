import React, { createContext, useContext, useState, useCallback, useMemo, useEffect } from "react";
import en from "./en";
import ar from "./ar";

const DICTS = { en, ar };
const STORAGE_KEY = "salesos.lang";

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLang] = useState(() => {
    if (typeof window === "undefined") return "en";
    return localStorage.getItem(STORAGE_KEY) || "en";
  });

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, lang);
    document.documentElement.setAttribute("data-lang", lang);
    // Layout direction is ALWAYS LTR by product decision. Only content language changes.
    document.documentElement.setAttribute("dir", "ltr");
  }, [lang]);

  const t = useCallback(
    (key, varsOrFallback) => {
      const dict = DICTS[lang] || en;
      let str = dict[key] ?? en[key];
      if (str == null) {
        // fallback: either a plain string, or a vars object with a _fallback key
        if (varsOrFallback && typeof varsOrFallback === "object" && "_fallback" in varsOrFallback) {
          str = varsOrFallback._fallback;
        } else if (typeof varsOrFallback === "string") {
          str = varsOrFallback;
        } else {
          str = key;
        }
      }
      if (varsOrFallback && typeof varsOrFallback === "object") {
        str = str.replace(/\{(\w+)\}/g, (_, k2) => (varsOrFallback[k2] != null ? String(varsOrFallback[k2]) : `{${k2}}`));
      }
      return str;
    },
    [lang]
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within I18nProvider");
  return ctx;
}

export function useT() {
  return useI18n().t;
}