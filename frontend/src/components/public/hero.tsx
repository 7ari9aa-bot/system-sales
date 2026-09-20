"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useI18n } from "@/components/public/i18n";

/** الشكل الهندسي الدوّار — ديكور بطيء جدًا (دورة كل 100 ثانية) */
function HeroShape() {
  return (
    <div className="fh-hero-shape" aria-hidden="true">
      <svg viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="200" cy="200" r="190" strokeOpacity=".35" />
        <circle cx="200" cy="200" r="150" strokeOpacity=".5" strokeDasharray="4 10" />
        <circle cx="200" cy="200" r="110" strokeOpacity=".65" />
        <circle cx="200" cy="200" r="70" strokeOpacity=".45" strokeDasharray="2 8" />
        <circle cx="200" cy="10" r="5" fill="var(--forest)" stroke="none" />
        <circle cx="350" cy="200" r="4" fill="var(--forest)" stroke="none" />
        <circle cx="90" cy="310" r="3" fill="var(--forest)" stroke="none" />
      </svg>
    </div>
  );
}

/** معاينة المنتج التفاعلية — دوس على أي محادثة وشوف اقتراح الـ AI المتعلق بيها */
function HeroMock() {
  const { t } = useI18n();
  const rows = t.hero.mockRows as [string, string, string][];
  const aiRows = t.hero.mockAiRows as string[];
  const variants = ["fh-badge-warning", "fh-badge", "fh-badge-success"];
  const [active, setActive] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setActive((a) => (a + 1) % rows.length), 4500);
    return () => clearInterval(id);
  }, [rows.length]);

  return (
    <div className="fh-hero-mock" role="img" aria-label="FIHRIST inbox">
      <div className="fh-hero-mock-head">
        <span className="fh-chat-avatar" aria-hidden="true"><span>F</span></span>
        <span className="fh-chat-title">
          <strong>FIHRIST · Inbox</strong>
          <small><span className="fh-status-dot" /> {t.hero.mockBadge}</small>
        </span>
      </div>
      <div className="fh-hero-mock-body">
        {rows.map(([name, badge, meta], i) => (
          <button
            key={name}
            type="button"
            className={`fh-hero-mock-row${i === active ? " is-active" : ""}`}
            onClick={() => setActive(i)}
            aria-pressed={i === active}
          >
            <span className="fh-status-dot" />
            <b>{name}</b>
            <span className={`fh-badge ${variants[i] || ""}`}>{badge}</span>
            <small>{meta}</small>
          </button>
        ))}
        <div className="fh-hero-mock-ai" key={active}>
          <b>AI:</b> {aiRows[active] || t.hero.mockAi}
        </div>
      </div>
    </div>
  );
}

export function Hero() {
  const { t } = useI18n();
  return (
    <section className="fh-hero" id="product">
      <HeroShape />
      <div className="fh-container fh-hero-inner">
        <div className="fh-hero-grid">
          <div className="fh-hero-copy">
            <span className="fh-eyebrow">{t.hero.eyebrow}</span>
            <h1>{t.hero.h1}</h1>
            <p className="fh-hero-sub">{t.hero.sub}</p>
            <div className="fh-hero-cta">
              <Link href="/auth/signup" className="fh-btn fh-btn-lg">{t.hero.start}</Link>
              <Link href="/product" className="fh-btn fh-btn-secondary fh-btn-lg">{t.hero.explore}</Link>
            </div>
            <p className="fh-hero-trust">{t.hero.trust}</p>
          </div>
          <div className="fh-hero-visual">
            <HeroMock />
          </div>
        </div>
      </div>
    </section>
  );
}
