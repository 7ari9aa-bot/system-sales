"use client";

/** بلوكات مشتركة بين الصفحة الرئيسية وصفحات المنتج الداخلية. */

import Link from "next/link";
import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";

/** ترويسة صفحة داخلية */
export function PageHero({
  eyebrow,
  title,
  sub,
}: {
  eyebrow?: string;
  title: string;
  sub: string;
}) {
  return (
    <section className="fh-hero fh-hero-page">
      <div className="fh-container fh-hero-inner">
        <Reveal className="fh-hero-copy">
          {eyebrow && <span className="fh-eyebrow">{eyebrow}</span>}
          <h1>{title}</h1>
          <p className="fh-hero-sub">{sub}</p>
        </Reveal>
      </div>
    </section>
  );
}

/** مخطط سياق العمل — بيئة عمل، مش أزرار */
export function ContextGraph() {
  const { t } = useI18n();
  return (
    <div className="fh-graph" role="img" aria-label={t.graph.hub}>
      <div className="fh-graph-row">
        {t.graph.nodes.slice(0, 3).map((n) => <span key={n} className="fh-node">{n}</span>)}
      </div>
      <div className="fh-graph-link" aria-hidden="true" />
      <div className="fh-graph-hub">{t.graph.hub}</div>
      <div className="fh-graph-link" aria-hidden="true" />
      <div className="fh-graph-row">
        {t.graph.nodes.slice(3, 6).map((n) => <span key={n} className="fh-node">{n}</span>)}
      </div>
      <div className="fh-graph-tail" aria-hidden="true" />
      <span className="fh-node">{t.graph.nodes[6]}</span>
    </div>
  );
}

/** قائمة مميزات [عنوان، وصف] — محتوى مقروء مش أزرار */
export function FeatureList({
  items,
  cols = 2,
}: {
  items: [string, string][];
  cols?: 1 | 2 | 3;
}) {
  return (
    <div className={`fh-feat-grid cols-${cols}`}>
      {items.map(([title, desc]) => (
        <div key={title} className="fh-feat">
          <b>{title}</b>
          <p>{desc}</p>
        </div>
      ))}
    </div>
  );
}

/** صف قصصي مرقّم (How it works) */
export function StepsRow({ steps }: { steps: [string, string][] }) {
  return (
    <div className="fh-steps">
      {steps.map(([title, desc], i) => (
        <div key={title} className="fh-step">
          <span className="fh-step-num" aria-hidden="true">{i + 1}</span>
          <b>{title}</b>
          <p>{desc}</p>
        </div>
      ))}
    </div>
  );
}

/** سيكشن كامل بعنوان + محتوى */
export function Section({
  id,
  title,
  sub,
  children,
  alt = false,
}: {
  id?: string;
  title?: string;
  sub?: string;
  children: React.ReactNode;
  alt?: boolean;
}) {
  return (
    <section className={`fh-section${alt ? " fh-section-alt" : ""}`} id={id}>
      <div className="fh-container">
        {title && (
          <Reveal className="fh-section-head">
            <h2>{title}</h2>
            {sub && <p>{sub}</p>}
          </Reveal>
        )}
        {children}
      </div>
    </section>
  );
}

/** نداء ختامي لصفحة داخلية */
export function PageCTA({ title }: { title: string }) {
  const { t } = useI18n();
  return (
    <section className="fh-final">
      <div className="fh-container fh-final-inner">
        <Reveal>
          <h2>{title}</h2>
          <div className="fh-hero-cta">
            <Link href="/auth/signup" className="fh-btn fh-btn-lg">{t.final.start}</Link>
            <Link href="/pricing" className="fh-btn fh-btn-secondary fh-btn-lg">{t.nav.pricing}</Link>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

/** قائمة أسئلة شائعة */
export function FaqList({ faq }: { faq: [string, string][] }) {
  return (
    <div className="fh-faq">
      {faq.map(([q, a]) => (
        <details key={q} className="fh-faq-item">
          <summary>{q}</summary>
          <p>{a}</p>
        </details>
      ))}
    </div>
  );
}

/** صفحة سياسة (خصوصية/شروط) — نص قانوني منظم */
export function PolicyBody({
  updated,
  intro,
  sections,
}: {
  updated: string;
  intro: string;
  sections: [string, string][];
}) {
  return (
    <div className="fh-prose">
      <Reveal>
        <p className="fh-prose-updated">{updated}</p>
        <p className="fh-prose-intro">{intro}</p>
      </Reveal>
      {sections.map(([h, body]) => (
        <Reveal key={h}>
          <h2>{h}</h2>
          <p>{body}</p>
        </Reveal>
      ))}
    </div>
  );
}
