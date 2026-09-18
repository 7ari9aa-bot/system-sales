"use client";

/** إشارات العمل — كل الإشارات مجردة بالكامل: بدون أسماء أو بيانات شخصية. */

import { useState } from "react";
import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";

const TONES = ["info", "warn", "danger", "success", "danger"] as const;

export function BusinessSignals() {
  const { t } = useI18n();
  const [active, setActive] = useState(0);
  const item = t.signals.items[active];

  return (
    <section className="fh-section" id="signals">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.signals.title}</h2>
          <p>{t.signals.sub}</p>
        </Reveal>

        <div className="fh-demo-chip" style={{ marginInlineStart: "auto", marginBottom: ".8rem" }}>
          <span className="fh-demo-dot" /> {t.signals.demo}
        </div>

        <Reveal className="fh-signals" stagger>
          <div className="fh-signal-list" role="tablist" aria-label={t.signals.title}>
            {t.signals.items.map((sig, i) => (
              <button
                key={sig.label}
                role="tab"
                aria-selected={active === i}
                className={`fh-signal-row${active === i ? " is-active" : ""}`}
                onClick={() => setActive(i)}
              >
                <span className={`fh-signal-dot fh-dot-${TONES[i]}`} aria-hidden="true" />
                <span className="fh-signal-count">{t.signals.counts[i]}</span>
                <span>{sig.label}</span>
              </button>
            ))}
          </div>

          <div className="fh-card fh-signal-preview" role="tabpanel">
            <div className="fh-signal-preview-head">
              <strong>{item.label}</strong>
              <span className={`fh-badge ${TONES[active] === "danger" ? "fh-badge-danger" : TONES[active] === "warn" ? "fh-badge-warning" : TONES[active] === "success" ? "fh-badge-success" : "fh-badge-primary"}`}>
                {t.signals.counts[active]} {t.signals.element}
              </span>
            </div>
            <div className="fh-signal-detail">
              <div>
                <strong>{item.label}</strong>
                <small>{item.detail}</small>
              </div>
              <span className="fh-badge">{item.badge}</span>
            </div>
            <p className="fh-note">{t.signals.note}</p>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
