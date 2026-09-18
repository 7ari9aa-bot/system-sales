"use client";

/** i18n + theme (spec §109-§112).
 *
 * Language: ar/en toggle. The LAYOUT NEVER FLIPS — direction stays RTL per
 * directive; only strings change. `t` is a Proxy over the active dictionary
 * so every existing `import { t }` consumer picks the language automatically.
 * Theme: light (default) / dark via the .dark class on <html>.
 */

export type Lang = "ar" | "en";

const LS_LANG = "sales_os_lang";
const LS_THEME = "sales_os_theme";

export function getLang(): Lang {
  if (typeof window === "undefined") return "ar";
  return (window.localStorage.getItem(LS_LANG) as Lang) || "ar";
}

export function setLang(lang: Lang) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LS_LANG, lang);
}

export function getTheme(): "light" | "dark" {
  if (typeof window === "undefined") return "light";
  return (window.localStorage.getItem(LS_THEME) as "light" | "dark") || "light";
}

export function applyTheme(theme: "light" | "dark") {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(LS_THEME, theme);
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function toggleTheme() {
  const dark = document.documentElement.classList.contains("dark");
  applyTheme(dark ? "light" : "dark");
  return dark ? "light" : "dark";
}

/** Proxy-based t: resolves keys against the active language at access time. */
export function makeT<T extends object>(dictionaries: Record<Lang, T>): T {
  return new Proxy({} as T, {
    get(_target, key: string) {
      const lang = getLang();
      const dict = dictionaries[lang] ?? dictionaries.ar;
      const en = dictionaries.en as Record<string, unknown>;
      const ar = dictionaries.ar as Record<string, unknown>;
      return (dict as Record<string, unknown>)[key] ?? en[key] ?? ar[key] ?? key;
    },
  }) as T;
}
