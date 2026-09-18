"use client";

/** الذكاء الاصطناعي + التكامل البشري + الأتمتة — كلها من القاموس. */

import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";

export function AISection() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="ai">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.ai.title}</h2>
          <p>{t.ai.sub}</p>
        </Reveal>

        <Reveal className="fh-pipeline" stagger aria-label={t.ai.title}>
          {t.ai.steps.map((label, i) => (
            <li key={label}>
              <span className="fh-pipeline-num" aria-hidden="true">{i + 1}</span>
              {label}
            </li>
          ))}
        </Reveal>

        <Reveal className="fh-flow" aria-hidden="true">
          {t.ai.flow.map((node, i) => (
            <span key={node} style={{ display: "inline-flex", alignItems: "center", gap: ".6rem" }}>
              {i > 0 && <span className="fh-flow-arrow" aria-hidden="true">←</span>}
              <span className={`fh-flow-node${node === "AI" ? " is-ai" : ""}`}>{node}</span>
            </span>
          ))}
        </Reveal>

        <Reveal className="fh-chip-grid" stagger>
          {t.ai.chips.map((c) => <span key={c} className="fh-chip">{c}</span>)}
        </Reveal>
      </div>
    </section>
  );
}

export function Handoff() {
  const { t } = useI18n();
  const badges = ["fh-badge-primary", "fh-badge-warning", "fh-badge-danger", "fh-badge-success"];
  return (
    <section className="fh-section fh-section-alt" id="handoff">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.handoff.title}</h2>
          <p>{t.handoff.sub}</p>
        </Reveal>

        <Reveal className="fh-handoff" stagger>
          {(t.handoff.steps as [string, string, string][]).map(([badge, title, detail], i) => (
            <span key={title} style={{ display: "contents" }}>
              {i > 0 && <span className="fh-handoff-arrow" aria-hidden="true">←</span>}
              <div className="fh-handoff-step">
                <span className={`fh-badge ${badges[i]}`}>{badge}</span>
                <b>{title}</b>
                <small>{detail}</small>
              </div>
            </span>
          ))}
        </Reveal>

        <Reveal className="fh-chip-grid subtle" stagger>
          {t.handoff.chips.map((c) => <span key={c} className="fh-chip">{c}</span>)}
        </Reveal>
      </div>
    </section>
  );
}

export function Automation() {
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
              {t.automation.steps.map((step, i) => (
                <li key={step}>
                  <span className="fh-auto-num" aria-hidden="true">{i + 1}</span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
          <div className="fh-automation-caps">
            {t.automation.caps.map((c) => <span key={c} className="fh-chip">{c}</span>)}
          </div>
        </Reveal>
      </div>
    </section>
  );
}
