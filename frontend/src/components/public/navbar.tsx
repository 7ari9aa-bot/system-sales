"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useI18n, useTheme, type Theme } from "@/components/public/i18n";

const LINKS = [
  { href: "#product", key: "product" },
  { href: "#context", key: "context" },
  { href: "#inbox", key: "inbox" },
  { href: "#ai", key: "ai" },
  { href: "#automation", key: "automation" },
  { href: "#pricing", key: "pricing" },
  { href: "#security", key: "security" },
] as const;

function ThemeIcon({ theme }: { theme: Theme }) {
  if (theme === "dark") {
    return (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4m11.4-11.4 1.4-1.4" />
      </svg>
    );
  }
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  );
}

export function PublicNavbar() {
  const { t, locale, setLocale } = useI18n();
  const { theme, toggle } = useTheme();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    setAuthed(Boolean(window.localStorage.getItem("sales_os_tokens")));
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`fh-nav${scrolled ? " is-scrolled" : ""}`}>
      <div className="fh-container fh-nav-inner">
        <Link href="/" className="fh-brand" aria-label="FIHRIST">
          <span className="fh-brand-mark" aria-hidden="true">F</span>
          <span className="fh-brand-name">FIHRIST</span>
          <span className="fh-brand-tag">{t.brandTag}</span>
        </Link>

        <nav className="fh-nav-links" aria-label={t.nav.menu}>
          {LINKS.map((l) => (
            <a key={l.href} href={l.href}>{t.nav[l.key]}</a>
          ))}
        </nav>

        <div className="fh-nav-actions">
          <button
            className="fh-icon-btn"
            onClick={toggle}
            aria-label={theme === "light" ? t.nav.toDark : t.nav.toLight}
            title={theme === "light" ? t.nav.toDark : t.nav.toLight}
          >
            <ThemeIcon theme={theme} />
          </button>
          <button
            className="fh-icon-btn fh-lang-btn"
            onClick={() => setLocale(locale === "ar" ? "en" : "ar")}
            aria-label={t.nav.lang}
            title={t.nav.lang}
            style={{ width: "auto", padding: "0 .7rem", fontSize: 13, fontWeight: 700 }}
          >
            {t.nav.lang}
          </button>
          {authed ? (
            <Link href="/inbox" className="fh-btn">{t.nav.openApp}</Link>
          ) : (
            <>
              <Link href="/auth/login" className="fh-nav-login">{t.nav.login}</Link>
              <Link href="/auth/signup" className="fh-btn">{t.nav.start}</Link>
            </>
          )}
          <button
            className="fh-icon-btn fh-burger"
            aria-label={t.nav.menu}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              {open ? <path d="M6 6l12 12M18 6 6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <div className="fh-mobile-menu">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={() => setOpen(false)}>{t.nav[l.key]}</a>
          ))}
          <div className="fh-mobile-actions">
            {authed ? (
              <Link href="/inbox" className="fh-btn" onClick={() => setOpen(false)}>{t.nav.openApp}</Link>
            ) : (
              <>
                <Link href="/auth/login" className="fh-btn fh-btn-secondary" onClick={() => setOpen(false)}>{t.nav.login}</Link>
                <Link href="/auth/signup" className="fh-btn" onClick={() => setOpen(false)}>{t.nav.start}</Link>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
