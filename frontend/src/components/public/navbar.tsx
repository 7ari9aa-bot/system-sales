"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getTokens } from "@/lib/api";

/** روابط الـnav تشير لأقسام الصفحة الحقيقية — صفحات /product و/solutions تجي في مرحلة لاحقة */
const LINKS = [
  { href: "#product", label: "المنتج" },
  { href: "#context", label: "سياق العمل" },
  { href: "#inbox", label: "المحادثات" },
  { href: "#ai", label: "الذكاء الاصطناعي" },
  { href: "#automation", label: "الأتمتة" },
  { href: "#security", label: "الأمان" },
];

export function PublicNavbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    setAuthed(Boolean(getTokens()));
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`mk-nav${scrolled ? " is-scrolled" : ""}`}>
      <div className="mk-container mk-nav-inner">
        <Link href="/" className="mk-brand" aria-label="سيلز أو إس — الصفحة الرئيسية">
          <span className="mk-brand-mark" aria-hidden="true">س</span>
          <span className="mk-brand-name">سيلز أو إس</span>
        </Link>

        <nav className="mk-nav-links" aria-label="التنقل الرئيسي">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href}>{l.label}</a>
          ))}
        </nav>

        <div className="mk-nav-cta">
          <span className="mk-lang" title="اللغة الحالية">العربية</span>
          {authed ? (
            <Link href="/inbox" className="btn mk-btn-primary">افتح التطبيق</Link>
          ) : (
            <>
              <Link href="/auth/login" className="mk-nav-login">تسجيل الدخول</Link>
              <Link href="/auth/signup" className="btn mk-btn-primary">ابدأ الآن</Link>
            </>
          )}
          <button
            className="mk-nav-burger"
            aria-label={open ? "إغلاق القائمة" : "فتح القائمة"}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
          >
            <span /><span /><span />
          </button>
        </div>
      </div>

      {open && (
        <div className="mk-nav-mobile">
          {LINKS.map((l) => (
            <a key={l.href} href={l.href} onClick={() => setOpen(false)}>{l.label}</a>
          ))}
          <div className="mk-nav-mobile-cta">
            {authed ? (
              <Link href="/inbox" className="btn" onClick={() => setOpen(false)}>افتح التطبيق</Link>
            ) : (
              <>
                <Link href="/auth/login" className="btn btn-secondary" onClick={() => setOpen(false)}>تسجيل الدخول</Link>
                <Link href="/auth/signup" className="btn" onClick={() => setOpen(false)}>ابدأ الآن</Link>
              </>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
