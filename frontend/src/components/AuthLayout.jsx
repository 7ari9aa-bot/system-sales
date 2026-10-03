import React, { useState, useEffect } from "react";
import AuthArtPanel from "@/components/AuthArtPanel";

export default function AuthLayout({ icon: Icon, title, subtitle, footer, children }) {
  const [locale, setLocale] = useState(() => {
    try { return window.localStorage.getItem("fh_locale") === "en" ? "en" : "ar" } catch { return "ar" }
  });
  const [theme] = useState(() => {
    try { const s = window.localStorage.getItem("fh_theme"); if (s) return s; return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light" } catch { return "light" }
  });

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = "ltr";
  }, [locale, theme]);

  return (
    <div className={`app ${theme === "dark" ? "theme-dark" : ""}`} data-theme={theme} data-lang={locale}>
      <div className="auth-split">
        <AuthArtPanel locale={locale} />
        <div className="auth-form-side">
          <button
            className="auth-lang-switch"
            onClick={() => setLocale(locale === "ar" ? "en" : "ar")}
          >
            {locale === "ar" ? "EN" : "عربي"}
          </button>
          <div className="auth-form-inner">
            <a className="auth-brand-mobile" href="/">
              <img src="/fihrist-mark.svg" alt="" />
              <span>FIHRIST</span>
            </a>
            {Icon && (
              <div className="auth-icon-wrap">
                <div className="auth-icon"><Icon size={22} /></div>
              </div>
            )}
            <h1 className="auth-title" dir="auto">{title}</h1>
            {subtitle && <p className="auth-subtitle" dir="auto">{subtitle}</p>}
            {children}
            {footer && <p className="auth-footer" dir="auto">{footer}</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
