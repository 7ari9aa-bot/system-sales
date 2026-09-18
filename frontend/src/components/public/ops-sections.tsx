"use client";

/** التحليلات + مركز التحكم + الأسعار + التكاملات + الأمان + الختامي. */

import { useI18n } from "@/components/public/i18n";
import { useEffect, useRef } from "react";
import { Reveal } from "@/components/public/reveal";

/** رسم بياني بأعمدة بتكبر أول ما يدخل الشاشة */
function ChartBars() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.classList.add("fh-in");
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          el.classList.add("fh-in");
          io.disconnect();
        }
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <div ref={ref} className="fh-chart" aria-hidden="true">
      <div className="fh-bar" />
      <div className="fh-bar" />
      <div className="fh-bar" />
      <div className="fh-bar" />
      <div className="fh-bar" />
      <div className="fh-bar" />
    </div>
  );
}

export function Analytics() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="analytics">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.analytics.title}</h2>
          <p>{t.analytics.sub}</p>
        </Reveal>

        <div className="fh-demo-chip" style={{ marginInlineStart: "auto", marginBottom: ".8rem" }}>
          <span className="fh-demo-dot" /> {t.analytics.demo}
        </div>

        <Reveal className="fh-snapshot" >
          <div className="fh-panel">
            <div className="fh-panel-label">{t.analytics.chartLabel}</div>
            <ChartBars />
            <div className="fh-chart-foot">
              <span>{t.analytics.chartStart}</span>
              <span>{t.analytics.chartEnd}</span>
            </div>
          </div>
          <div className="fh-panel">
            <div className="fh-panel-label">{t.analytics.insightTag}</div>
            <p style={{ fontSize: 16, marginBottom: "1.1rem" }}>
              {t.analytics.insight[0]}<b>{t.analytics.insight[1]}</b>{t.analytics.insight[2]}
            </p>
            <div className="fh-insight-actions" style={{ marginTop: "auto" }}>
              <span className="fh-chip">{t.analytics.inspect}</span>
              <span className="fh-chip">{t.analytics.act}</span>
            </div>
          </div>
        </Reveal>

        <Reveal className="fh-metrics" stagger>
          {(t.analytics.metrics as [string, string, string][]).map(([label, delta, tone]) => (
            <div key={label} className="fh-card fh-card-hover fh-metric">
              <small>{label}</small>
              <b className={`fh-delta-${tone}`} dir="ltr">{delta}</b>
            </div>
          ))}
        </Reveal>

        {/* الكارت القديم اتدمج في الـsnapshot فوق */}
      </div>
    </section>
  );
}

export function ControlCenter() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-band" id="control">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.control.title}</h2>
          <p>{t.control.sub}</p>
        </Reveal>

        <div className="fh-demo-chip" style={{ marginInlineStart: "auto", marginBottom: ".8rem" }}>
          <span className="fh-demo-dot" /> {t.control.demo}
        </div>

        <Reveal className="fh-controls" stagger>
          {(t.control.counters as [string, string][]).map(([value, label]) => (
            <div key={label} className="fh-card fh-card-hover fh-control">
              <b>{value}</b>
              <small>{label}</small>
            </div>
          ))}
        </Reveal>

        <Reveal className="fh-chip-grid" stagger>
          {t.control.chips.map((c) => <span key={c} className="fh-chip">{c}</span>)}
        </Reveal>
      </div>
    </section>
  );
}

export function Pricing() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="pricing">
      <div className="fh-container">
        <Reveal className="fh-section-head" >
          <span className="fh-eyebrow">{t.pricing.badge}</span>
          <h2>{t.pricing.title}</h2>
          <p>{t.pricing.sub}</p>
        </Reveal>

        <Reveal className="fh-pricing-grid" stagger>
          {t.pricing.tiers.map((tier, i) => (
            <div key={tier.name} className={`fh-card fh-card-hover fh-tier${i === 1 ? " is-popular" : ""}`}>
              {i === 1 && <span className="fh-badge fh-badge-primary fh-tier-badge">{t.pricing.popular}</span>}
              <h3>{tier.name}</h3>
              <p className="fh-tier-desc">{tier.desc}</p>
              <div className="fh-tier-price">
                <b>{t.pricing.free}</b>
                <small>{t.pricing.freeNote}</small>
              </div>
              <ul className="fh-tier-features">
                {tier.features.map((f) => <li key={f}>{f}</li>)}
              </ul>
              <a href="/auth/signup" className={`fh-btn ${i === 1 ? "" : "fh-btn-secondary"}`}>
                {t.pricing.cta}
              </a>
            </div>
          ))}
        </Reveal>

        <Reveal as="p" className="fh-pricing-note">
          {t.pricing.note}
        </Reveal>
      </div>
    </section>
  );
}

export function Integrations() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="integrations">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.integrations.title}</h2>
          <p>{t.integrations.sub}</p>
        </Reveal>

        <Reveal className="fh-flow" aria-hidden="true">
          {t.integrations.flow.map((node, i) => (
            <span key={node} style={{ display: "inline-flex", alignItems: "center", gap: ".6rem" }}>
              {i > 0 && <span className="fh-flow-arrow" aria-hidden="true">←</span>}
              <span className="fh-flow-node">{node}</span>
            </span>
          ))}
        </Reveal>

        <Reveal className="fh-integrations" stagger>
          {(t.integrations.items as [string, string, string, boolean][]).map(([name, desc, status, live]) => (
            <div key={name} className="fh-card fh-card-hover fh-integration">
              <b>{name}</b>
              <small>{desc}</small>
              <span className={`fh-badge ${live ? "fh-badge-success" : ""}`}>{status}</span>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

export function SecuritySection() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="security">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.security.title}</h2>
          <p>{t.security.sub}</p>
        </Reveal>

        <Reveal className="fh-security" stagger>
          {(t.security.items as [string, string][]).map(([title, desc]) => (
            <div key={title} className="fh-card fh-card-hover fh-security-item">
              <b>{title}</b>
              <p>{desc}</p>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

export function FinalCTA() {
  const { t } = useI18n();
  return (
    <section className="fh-final" id="start">
      <div className="fh-container fh-final-inner">
        <Reveal>
          <h2>{t.final.title}</h2>
          <p>{t.final.sub}</p>
          <div className="fh-hero-cta">
            <a href="/auth/signup" className="fh-btn fh-btn-lg">{t.final.start}</a>
            <a href="#product" className="fh-btn fh-btn-secondary fh-btn-lg">{t.final.explore}</a>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
