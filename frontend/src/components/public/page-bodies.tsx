"use client";

/** أجسام صفحات الموقع العام — كلها client لأنها بتقرأ القاموس.
 *  ملفات الـpage.tsx (server) بتصدر metadata وتستدعي الجسم من هنا. */

import Link from "next/link";
import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";
import {
  PageHero,
  FeatureList,
  StepsRow,
  ContextGraph,
  FaqList,
  PolicyBody,
  PageCTA,
} from "@/components/public/blocks";
import { DemoChat } from "@/components/public/demo-chat";

function CtaLink({ href, label }: { href: string; label: string }) {
  return (
    <Reveal className="fh-more-link">
      <Link href={href}>{label} ←</Link>
    </Reveal>
  );
}

/* ---------- /product ---------- */
export function ProductBody() {
  const { t } = useI18n();
  const p = t.pages.product;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
          <Reveal stagger>
            <FeatureList items={p.features as [string, string][]} />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.forWho.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.forWho.items as [string, string][]} cols={3} />
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /context ---------- */
export function ContextBody() {
  const { t } = useI18n();
  const p = t.pages.context;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.problem.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.problem.items as [string, string][]} cols={3} />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal>
            <ContextGraph />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.solution.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.solution.items as [string, string][]} cols={3} />
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /conversations ---------- */
export function ConversationsBody() {
  const { t } = useI18n();
  const p = t.pages.conversations;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.channels.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.channels.items as [string, string][]} cols={2} />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.inbox.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.inbox.items as [string, string][]} />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.handoff.title}</h2>
          </Reveal>
          <Reveal className="fh-handoff" stagger>
            {(p.handoff.steps as [string, string, string][]).map(([badge, title, detail], i) => (
              <span key={title} style={{ display: "contents" }}>
                {i > 0 && <span className="fh-handoff-arrow" aria-hidden="true">←</span>}
                <div className="fh-handoff-step">
                  <span className={`fh-badge ${["fh-badge-primary", "fh-badge-warning", "fh-badge-danger", "fh-badge-success"][i]}`}>{badge}</span>
                  <b>{title}</b>
                  <small>{detail}</small>
                </div>
              </span>
            ))}
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /ai ---------- */
export function AiBody() {
  const { t } = useI18n();
  const p = t.pages.ai;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.loop.title}</h2>
          </Reveal>
          <Reveal className="fh-pipeline" stagger>
            {(p.loop.steps as string[]).map((label, i) => (
              <li key={label}>
                <span className="fh-pipeline-num" aria-hidden="true">{i + 1}</span>
                {label}
              </li>
            ))}
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.can.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.can.items as [string, string][]} cols={2} />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.guard.title}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.guard.items as [string, string][]} cols={3} />
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /automation ---------- */
export function AutomationBody() {
  const { t } = useI18n();
  const p = t.pages.automationPage;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.chainTitle}</h2>
          </Reveal>
          <Reveal className="fh-pipeline fh-pipeline-compact" stagger>
            {(t.automation.chain as string[]).map((label) => <li key={label}>{label}</li>)}
          </Reveal>
          <Reveal>
            <div className="fh-card fh-automation-flow">
              <h4>{p.exampleTitle}</h4>
              <ol className="fh-auto-steps">
                {(t.automation.steps as string[]).map((step, i) => (
                  <li key={step}>
                    <span className="fh-auto-num" aria-hidden="true">{i + 1}</span>
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.capsTitle}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.caps as [string, string][]} cols={3} />
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.guardTitle}</h2>
          </Reveal>
          <Reveal stagger>
            <FeatureList items={p.guardItems as [string, string][]} cols={3} />
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /pricing ---------- */
export function PricingBody() {
  const { t } = useI18n();
  const p = t.pages.pricingPage;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
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
            {t.pricing.note}
          </Reveal>
        </div>
      </section>
      <section className="fh-section">
        <div className="fh-container">
          <Reveal className="fh-section-head">
            <h2>{p.faqTitle}</h2>
          </Reveal>
          <Reveal>
            <FaqList faq={p.faq as [string, string][]} />
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /security ---------- */
export function SecurityBody() {
  const { t } = useI18n();
  const p = t.pages.securityPage;
  return (
    <main>
      <PageHero title={p.title} sub={p.sub} />
      <section className="fh-section">
        <div className="fh-container">
          <Reveal stagger>
            <FeatureList items={p.areas as [string, string][]} />
          </Reveal>
          <Reveal>
            <p className="fh-note" style={{ maxWidth: 720, marginTop: "2rem" }}>{p.honest}</p>
          </Reveal>
        </div>
      </section>
      <PageCTA title={p.cta} />
    </main>
  );
}

/* ---------- /privacy ---------- */
export function PrivacyBody() {
  const { t } = useI18n();
  const p = t.pages.privacy;
  return (
    <main>
      <PageHero title={p.title} sub={p.intro} />
      <section className="fh-section">
        <div className="fh-container">
          <PolicyBody updated={p.updated} intro={p.intro} sections={p.sections as [string, string][]} />
          <CtaLink href="/security" label={t.securityTeaser.more} />
        </div>
      </section>
    </main>
  );
}

/* ---------- /terms ---------- */
export function TermsBody() {
  const { t } = useI18n();
  const p = t.pages.terms;
  return (
    <main>
      <PageHero title={p.title} sub={p.intro} />
      <section className="fh-section">
        <div className="fh-container">
          <PolicyBody updated={p.updated} intro={p.intro} sections={p.sections as [string, string][]} />
          <CtaLink href="/auth/signup" label={p.cta} />
        </div>
      </section>
    </main>
  );
}
