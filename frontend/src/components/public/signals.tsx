"use client";

/** إشارات العمل — كل إشارة قابلة للاختيار وتعرض معاينة مصغرة (بيانات تجريبية). */

import { useState } from "react";

type Signal = {
  id: string;
  count: number;
  label: string;
  tone: "info" | "warn" | "danger" | "success";
  rows: { title: string; meta: string; badge?: string };
};

const SIGNALS: Signal[] = [
  {
    id: "convos", count: 12, label: "محادثة جديدة", tone: "info",
    rows: { title: "أحمد محمد — واتساب", meta: "النية: حالة طلب · منذ دقيقتين", badge: "AI يعالج" },
  },
  {
    id: "orders", count: 4, label: "طلبات تحتاج انتباه", tone: "warn",
    rows: { title: "طلب #1042 — دفع عند الاستلام", meta: "مستودع القاهرة · منذ ساعة", badge: "بانر المراجعة" },
  },
  {
    id: "automations", count: 2, label: "أتمتة فشلت", tone: "danger",
    rows: { title: "مسار: تذكير السلة المتروكة", meta: "فشل نداء المزود · محاولة 3/3", badge: "قابلة لإعادة التشغيل" },
  },
  {
    id: "leads", count: 3, label: "عملاء محتملون عالي القيمة", tone: "success",
    rows: { title: "منى خالد — من حملة الصيف", meta: "قيمة متوقعة: عالية · أول تواصل", badge: "توزيع تلقائي" },
  },
  {
    id: "sla", count: 1, label: "SLA في خطر", tone: "danger",
    rows: { title: "سارة علي — تليجرام", meta: "لم يُرد خلال 8 دقائق من أصل 10", badge: "تحويل بشري" },
  },
];

export function BusinessSignals() {
  const [active, setActive] = useState(SIGNALS[0].id);
  const current = SIGNALS.find((s) => s.id === active) ?? SIGNALS[0];

  return (
    <section className="mk-section" id="signals">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>اعرف اللي محتاج انتباهك.</h2>
          <p>النظام بيرتّب أولوياتك — مش مجرد تقارير.</p>
        </header>

        <div className="mk-demo-chip mk-demo-chip-float" aria-hidden="true">
          <span className="mk-demo-dot" /> مساحة تجريبية
        </div>

        <div className="mk-signals">
          <div className="mk-signals-list" role="tablist" aria-label="إشارات العمل">
            {SIGNALS.map((sig) => (
              <button
                key={sig.id}
                role="tab"
                aria-selected={active === sig.id}
                className={`mk-signal-row${active === sig.id ? " is-active" : ""}`}
                onClick={() => setActive(sig.id)}
              >
                <span className={`mk-signal-dot mk-dot-${sig.tone}`} aria-hidden="true" />
                <span className="mk-signal-count">{sig.count}</span>
                <span>{sig.label}</span>
              </button>
            ))}
          </div>

          <div className="card mk-signals-preview" role="tabpanel">
            <div className="mk-signals-preview-head">
              <strong>{current.label}</strong>
              <span className={`badge badge-${current.tone === "danger" ? "danger" : current.tone === "warn" ? "warning" : current.tone === "success" ? "success" : "primary"}`}>
                {current.count} عنصر
              </span>
            </div>
            <div className="mk-signals-row">
              <div>
                <strong>{current.rows.title}</strong>
                <small>{current.rows.meta}</small>
              </div>
              {current.rows.badge && <span className="badge">{current.rows.badge}</span>}
            </div>
            <p className="mk-muted-note">
              داخل التطبيق، كل إشارة بتفتح الشاشة المناسبة مع السياق الكامل — دي معاينة مبسطة.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
