"use client";

/** سياق العمل + ملف العميل الموحد (مجرد بالكامل — بدون أسماء) + الـInbox. */

import { useI18n } from "@/components/public/i18n";
import { Reveal } from "@/components/public/reveal";

function PersonIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c1.5-3.5 4.5-5 8-5s6.5 1.5 8 5" />
    </svg>
  );
}

export function ContextGraph() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="context">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.context.title}</h2>
          <p>{t.context.sub}</p>
        </Reveal>
        <Reveal className="fh-graph" role="img" aria-label={t.context.hub}>
          <div className="fh-graph-row">
            {t.context.nodes.slice(0, 3).map((n) => <span key={n} className="fh-node">{n}</span>)}
          </div>
          <div className="fh-graph-link" aria-hidden="true" />
          <div className="fh-graph-hub">{t.context.hub}</div>
          <div className="fh-graph-link" aria-hidden="true" />
          <div className="fh-graph-row">
            {t.context.nodes.slice(3, 6).map((n) => <span key={n} className="fh-node">{n}</span>)}
          </div>
          <div className="fh-graph-tail" aria-hidden="true" />
          <span className="fh-node">{t.context.nodes[6]}</span>
        </Reveal>
      </div>
    </section>
  );
}

export function Customer360() {
  const { t } = useI18n();
  return (
    <section className="fh-section" id="customer">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.c360.title}</h2>
          <p>{t.c360.sub}</p>
        </Reveal>

        <div className="fh-demo-chip" style={{ marginInlineStart: "auto", marginBottom: ".8rem" }}>
          <span className="fh-demo-dot" /> {t.c360.demo}
        </div>

        <Reveal className="fh-card fh-record">
          <div className="fh-record-head">
            <span className="fh-record-avatar" aria-hidden="true"><PersonIcon /></span>
            <div className="fh-record-id">
              <strong>{t.c360.name}</strong>
              <div className="fh-record-badges">
                <span className="fh-badge fh-badge-primary">{t.c360.vip}</span>
                <span className="fh-badge fh-badge-success">{t.c360.active}</span>
              </div>
            </div>
            <div className="fh-record-stats">
              <div><small>{t.c360.revenue}</small><b>8,420</b></div>
              <div><small>{t.c360.orders}</small><b>14</b></div>
              <div><small>{t.c360.last}</small><b>{t.c360.demo}</b></div>
            </div>
          </div>

          <div className="fh-record-tabs" aria-hidden="true">
            {t.c360.tabs.map((tab, i) => (
              <span key={tab} className={i === 0 ? "is-active" : ""}>{tab}</span>
            ))}
          </div>

          <div className="fh-record-body">
            <div className="fh-record-panel">
              <h4>{t.c360.info}</h4>
              <div className="fh-kv"><span>{t.c360.phone}</span><b>{t.c360.masked}</b></div>
              <div className="fh-kv"><span>{t.c360.email}</span><b>{t.c360.masked}</b></div>
              <div className="fh-kv"><span>{t.c360.tags}</span><b>{t.c360.vip}</b></div>
              <div className="fh-kv"><span>{t.c360.owner}</span><b>{t.c360.demo}</b></div>
            </div>
            <div className="fh-record-panel">
              <h4>{t.c360.work}</h4>
              <div className="fh-kv"><span>{t.c360.openOrders}</span><b>2</b></div>
              <div className="fh-kv"><span>{t.c360.payments}</span><b>14</b></div>
              <div className="fh-kv"><span>{t.c360.issues}</span><b>—</b></div>
              <div className="fh-kv"><span>{t.c360.channel}</span><b>{t.inbox.channels[1]}</b></div>
            </div>
            <div className="fh-record-panel is-ai">
              <h4>{t.c360.aiCtx}</h4>
              <div className="fh-kv"><span>{t.c360.intent}</span><b>{t.inbox.intentVal}</b></div>
              <div className="fh-kv"><span>{t.c360.value}</span><b>{t.c360.vip}</b></div>
              <div className="fh-kv"><span>{t.c360.risk}</span><b>—</b></div>
              <div className="fh-kv"><span>{t.c360.next}</span><b>{t.inbox.nextVal}</b></div>
            </div>
          </div>
        </Reveal>

        <Reveal className="fh-timeline-wrap">
          <h3>{t.c360.timelineTitle}</h3>
          <ol className="fh-timeline">
            {(t.c360.timeline as [string, string][]).map(([label, detail]) => (
              <li key={label}><b>{label}</b><small>{detail}</small></li>
            ))}
          </ol>
        </Reveal>
      </div>
    </section>
  );
}

export function InboxPreview() {
  const { t } = useI18n();
  return (
    <section className="fh-section fh-section-alt" id="inbox">
      <div className="fh-container">
        <Reveal className="fh-section-head">
          <h2>{t.inbox.title}</h2>
          <p>{t.inbox.sub}</p>
        </Reveal>

        <Reveal className="fh-channels" stagger>
          {t.inbox.channels.map((ch, i) => (
            <span key={ch} className={`fh-channel${i === 0 ? " is-live" : ""}`}>
              {ch}
              <small>{i === 0 ? t.inbox.live : t.inbox.soon}</small>
            </span>
          ))}
        </Reveal>

        <div className="fh-demo-chip" style={{ marginInlineStart: "auto", marginBottom: ".8rem" }}>
          <span className="fh-demo-dot" /> {t.inbox.demo}
        </div>

        <Reveal className="fh-card fh-inboxp">
          <div className="fh-inboxp-col">
            <div className="fh-col-title">{t.inbox.list}</div>
            {(t.inbox.convos as [string, string][]).map(([title, meta], i) => (
              <div key={title} className={`fh-convo${i === 0 ? " is-active" : ""}`}>
                <span className="fh-convo-avatar" aria-hidden="true"><PersonIcon /></span>
                <span className="fh-convo-meta">
                  <strong>{title}</strong>
                  <small>{meta}</small>
                </span>
              </div>
            ))}
          </div>
          <div className="fh-inboxp-col fh-thread">
            <div className="fh-col-title">{t.inbox.thread}</div>
            <div className="fh-thread-msgs">
              <div className="fh-bubble">{t.inbox.m1}<span className="fh-bubble-tag">· 10m</span></div>
              <div className="fh-bubble fh-bubble-user">{t.inbox.m2}<span className="fh-bubble-tag">{t.inbox.agent} · 8m</span></div>
              <div className="fh-bubble">{t.inbox.m3}<span className="fh-bubble-tag">· 2m</span></div>
            </div>
            <div className="fh-inbox-suggest">
              <span className="fh-badge fh-badge-primary">{t.inbox.suggestTag}</span>
              <small>{t.inbox.suggest}</small>
            </div>
          </div>
          <div className="fh-inboxp-col">
            <div className="fh-col-title">{t.inbox.ctx}</div>
            <div className="fh-kv"><span>{t.c360.name}</span><b>{t.inbox.newCustomer}</b></div>
            <div className="fh-kv"><span>{t.inbox.orders}</span><b>1</b></div>
            <div className="fh-kv"><span>{t.inbox.intent}</span><b>{t.inbox.intentVal}</b></div>
            <div className="fh-kv"><span>{t.inbox.next}</span><b>{t.inbox.nextVal}</b></div>
          </div>
        </Reveal>
      </div>
    </section>
  );
}
