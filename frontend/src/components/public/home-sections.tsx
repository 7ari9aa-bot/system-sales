"use client";

/** أقسام الصفحة الرئيسية + العناصر المشتركة بينها وبين صفحات المنتج. */

import Link from "next/link";
import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";
import { StepsRow, ContextGraph, FeatureList, FaqList } from "@/components/public/blocks";
import { BentoFeatures } from "@/components/public/bento-features";

/* ---------- قسم موحّد: إزاي بيشتغل + سياق العمل ---------- */
export function HowContextSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="how">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.how.title}</h2>
          <p>{t.how.sub}</p>
        </Reveal>
        <div className="fh-how-context">
          <Reveal className="fh-how-detail" stagger>
            {(t.how.steps as [string, string][]).map(([title, desc], i) => (
              <div key={title} className="fh-how-step">
                <h4><span className="fh-step-num" aria-hidden="true">{i + 1}</span>{title}</h4>
                <p>{desc}</p>
                <div className="fh-step-tags">
                  {(t.how.tags as string[][])[i].map((tag) => (
                    <span key={tag} className="fh-step-tag">{tag}</span>
                  ))}
                </div>
              </div>
            ))}
          </Reveal>
          <Reveal>
            <div className="fh-card" style={{ padding: 24 }}>
              <h4 style={{ fontSize: 14.5, fontWeight: 650, marginBottom: 14 }}>{t.graph.title}</h4>
              <ContextGraph />
              <p style={{ fontSize: 13.5, color: "var(--muted)", marginTop: 14, lineHeight: 1.65 }}>{t.graph.sub}</p>
            </div>
          </Reveal>
        </div>
        <Reveal className="fh-more-link">
          <Link href="/product">{t.how.more} ←</Link>
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
        <Reveal className="fh-more-link">
          <p style={{ marginBottom: ".6rem", color: "var(--muted)", fontSize: 14.5 }}>
            الردود دي محاكاة — جرّب النظام الحقيقي مجانًا.
          </p>
          <Link href="/auth/signup" className="fh-inline-link">
            افتح مساحتك مجانًا ←
          </Link>
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

        <Reveal>
          <img className="fh-section-img" src="https://media.base44.com/images/public/6ab00dcc41a53757c2f8a0b1/73aa727d1_generated_image.png" alt={t.automation.title} loading="lazy" />
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

/* ---------- قسم موحّد: أمان + تكاملات ---------- */
export function SecurityIntegrationsSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="security">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.securityTeaser.title}</h2>
          <p>{t.securityTeaser.sub}</p>
        </Reveal>
        <div className="fh-sec-int">
          <Reveal className="fh-sec-int-col">
            <h3>{t.securityTeaser.colTitle}</h3>
            {(t.securityTeaser.points as [string, string][]).map(([title, desc]) => (
              <div key={title} className="fh-sec-point-deep">
                <span className="fh-sec-ico" aria-hidden="true">✓</span>
                <div>
                  <b>{title}</b>
                  <small>{desc}</small>
                </div>
              </div>
            ))}
          </Reveal>
          <Reveal className="fh-sec-int-col">
            <h3>{t.integrations.title}</h3>
            <div className="fh-flow" aria-hidden="true" style={{ marginBottom: 16 }}>
              {(t.integrations.flow as string[]).map((node, i) => (
                <span key={node} style={{ display: "inline-flex", alignItems: "center", gap: ".6rem" }}>
                  {i > 0 && <span className="fh-flow-arrow" aria-hidden="true">←</span>}
                  <span className="fh-flow-node">{node}</span>
                </span>
              ))}
            </div>
            <div className="fh-integrations" style={{ gridTemplateColumns: "1fr 1fr" }}>
              {(t.integrations.items as [string, string, string, boolean][]).map(([name, desc, status, live]) => (
                <div key={name} className="fh-integration" style={{ padding: 14 }}>
                  <b style={{ fontSize: 14 }}>{name}</b>
                  <small style={{ fontSize: 12.5 }}>{desc}</small>
                  <span className={"fh-badge " + (live ? "fh-badge-primary" : "")} style={{ fontSize: 11 }}>{status}</span>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
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


/* ---------- ليه FIHRIST (المميزات) ---------- */
export function FeaturesSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="features">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.features.title}</h2>
          <p>{t.features.sub}</p>
        </Reveal>
        <Reveal>
          <img className="fh-section-img fh-section-img-wide" src="https://media.base44.com/images/public/6ab00dcc41a53757c2f8a0b1/0bc824d23_generated_image.png" alt={t.features.title} loading="lazy" />
        </Reveal>
        <Reveal stagger>
          <BentoFeatures items={t.features.items as [string, string][]} />
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- لمين FIHRIST (حالات الاستخدام) ---------- */
export function UseCasesSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="use-cases">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.useCases.title}</h2>
          <p>{t.useCases.sub}</p>
        </Reveal>
        <Reveal stagger>
          <div className="fh-bento" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            {(t.useCases.items as [string, string][]).map(([title, desc], i) => {
              const results = t.useCases.results as string[];
              return (
                <div key={title} className="fh-usecase">
                  <b>{title}</b>
                  <p>{desc}</p>
                  {results[i] && <span className="fh-usecase-result">{results[i]}</span>}
                </div>
              );
            })}
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/* ---------- أسئلة شائعة ---------- */
export function FaqSection() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="faq">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.faq.title}</h2>
          <p>{t.faq.sub}</p>
        </Reveal>
        <Reveal>
          <FaqList faq={t.faq.items as [string, string][]} />
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
