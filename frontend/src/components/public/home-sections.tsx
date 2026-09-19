"use client";

/** أقسام الصفحة الرئيسية + العناصر المشتركة بينها وبين صفحات المنتج. */

import Link from "next/link";
import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";
import { StepsRow, ContextGraph } from "@/components/public/blocks";

/* ---------- إزاي بيشتغل (3 خطوات) ---------- */
export function HowItWorks() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="how">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.how.title}</h2>
          <p>{t.how.sub}</p>
        </Reveal>
        <Reveal stagger>
          <StepsRow steps={t.how.steps as [string, string][]} />
        </Reveal>
        <Reveal className="fh-more-link">
          <Link href="/product">{t.how.more} ←</Link>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- سياق العمل ---------- */
export function ContextSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="context">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.graph.title}</h2>
          <p>{t.graph.sub}</p>
        </Reveal>
        <Reveal>
          <ContextGraph />
        </Reveal>
        <Reveal className="fh-more-link">
          <Link href="/context">{t.nav.context} ←</Link>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- قسم الشات التفاعلي (في عمق الصفحة) ---------- */
export function TrySection({ children }: { children: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="try">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.chat.title}</h2>
          <p>{t.chat.sub}</p>
        </Reveal>
        <Reveal>{children}</Reveal>
        <Reveal className="fh-more-link" >
          <p style={{ marginBottom: ".6rem", color: "var(--muted)", fontSize: 14.5 }}>
            {t.final.title}
          </p>
          <Link href="/auth/signup" className="fh-btn">{t.final.start}</Link>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- الأتمتة ---------- */
export function AutomationSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="automation">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.automation.title}</h2>
          <p>{t.automation.sub}</p>
        </Reveal>

        <Reveal className="fh-pipeline fh-pipeline-compact" stagger aria-label={t.automation.title}>
          {t.automation.chain.map((label) => <li key={label}>{label}</li>)}
        </Reveal>

        <Reveal className="fh-automation" stagger>
          <div className="fh-card fh-automation-flow">
            <h4>{t.automation.example}</h4>
            <ol className="fh-auto-steps">
              {(t.automation.steps as string[]).map((step, i) => (
                <li key={step}>
                  <span className="fh-auto-num" aria-hidden="true">{i + 1}</span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
          <div className="fh-automation-caps">
            {(t.automation.caps as string[]).map((c) => (
              <span key={c} className="fh-cap">✓ {c}</span>
            ))}
          </div>
        </Reveal>

        <Reveal className="fh-more-link">
          <Link href="/automation">{t.automation.more} ←</Link>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- التكاملات ---------- */
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
          {(t.integrations.flow as string[]).map((node, i) => (
            <span key={node} style={{ display: "inline-flex", alignItems: "center", gap: ".6rem" }}>
              {i > 0 && <span className="fh-flow-arrow" aria-hidden="true">←</span>}
              <span className="fh-flow-node">{node}</span>
            </span>
          ))}
        </Reveal>

        <Reveal className="fh-integrations" stagger>
          {(t.integrations.items as [string, string, string, boolean][]).map(([name, desc, status, live]) => (
            <div key={name} className="fh-integration">
              <b>{name}</b>
              <small>{desc}</small>
              <span className={`fh-badge ${live ? "fh-badge-primary" : ""}`}>{status}</span>
            </div>
          ))}
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- شريط الأمان ---------- */
export function SecurityTeaser() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="security">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.securityTeaser.title}</h2>
          <p>{t.securityTeaser.sub}</p>
        </Reveal>
        <Reveal className="fh-more-link">
          <Link href="/security">{t.securityTeaser.more} ←</Link>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- ملخص الأسعار ---------- */
export function PricingPreview() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="pricing">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.pricing.title}</h2>
          <p>{t.pricing.sub}</p>
        </Reveal>

        <Reveal className="fh-pricing-grid" stagger>
          {(t.pricing.tiers as { name: string; desc: string; features: string[] }[]).map((tier, i) => (
            <div key={tier.name} className={`fh-tier${i === 1 ? " is-popular" : ""}`}>
              {i === 1 && <span className="fh-tier-badge">{t.pricing.popular}</span>}
              <h3>{tier.name}</h3>
              <p className="fh-tier-desc">{tier.desc}</p>
              <div className="fh-tier-price">
                <b>{t.pricing.free}</b>
                <small>{t.pricing.freeNote}</small>
              </div>
              <ul className="fh-tier-features">
                {tier.features.map((f) => <li key={f}>{f}</li>)}
              </ul>
              <Link href="/auth/signup" className={`fh-btn ${i === 1 ? "" : "fh-btn-secondary"}`}>
                {t.pricing.cta}
              </Link>
            </div>
          ))}
        </Reveal>

        <Reveal as="p" className="fh-pricing-note">
          {t.pricing.note}{" "}
          <Link href="/pricing" className="fh-inline-link">{t.pricing.more} ←</Link>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- CTA ختامي ---------- */
export function FinalCTA() {
  const { t } = useI18n();
  return (
    <section className="fh-final">
      <div className="fh-container fh-final-inner">
        <Reveal>
          <h2>{t.final.title}</h2>
          <p>{t.final.sub}</p>
          <div className="fh-hero-cta fh-hero-cta-center">
            <Link href="/auth/signup" className="fh-btn fh-btn-lg">{t.final.start}</Link>
            <Link href="/product" className="fh-btn fh-btn-secondary fh-btn-lg">{t.final.explore}</Link>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
