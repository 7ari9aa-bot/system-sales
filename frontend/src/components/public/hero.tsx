"use client";

import { useI18n } from "@/components/public/i18n";
import { DemoChat } from "@/components/public/demo-chat";
import { Reveal } from "@/components/public/reveal";

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

export function Hero() {
  const { t } = useI18n();
  return (
    <section className="fh-hero" id="product">
      <HeroShape />
      <div className="fh-container fh-hero-inner">
        <Reveal className="fh-hero-copy">
          <span className="fh-eyebrow">{t.hero.eyebrow}</span>
          <h1>{t.hero.h1}</h1>
          <p className="fh-hero-sub">{t.hero.sub}</p>
          <div className="fh-hero-cta">
            <a href="/auth/signup" className="fh-btn fh-btn-lg">{t.hero.start}</a>
            <a href="#context" className="fh-btn fh-btn-secondary fh-btn-lg">{t.hero.explore}</a>
          </div>
        </Reveal>
        <Reveal className="fh-hero-env">
          <DemoChat />
        </Reveal>
      </div>
    </section>
  );
}
