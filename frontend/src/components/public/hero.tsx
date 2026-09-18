"use client";

import { useI18n } from "@/components/public/i18n";
import { DemoChat } from "@/components/public/demo-chat";
import { Reveal } from "@/components/public/reveal";

export function Hero() {
  const { t } = useI18n();
  return (
    <section className="fh-hero" id="product">
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
