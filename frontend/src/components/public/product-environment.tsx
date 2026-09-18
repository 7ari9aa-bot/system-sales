"use client";

/** معاينة تفاعلية لبيئة المنتج — نفس مكونات واجهة التطبيق ببيانات تجريبية.
 *  قصة من 7 مراحل: رسالة توصل → سياق العميل → AI يفهم → AI ينفذ →
 *  حدث عمل يتغير → أتمتة تتفاعل → إشارة جديدة.
 *  مع prefers-reduced-motion: تُعرض الحالة النهائية ثابتة بدون حركة. */

import { useEffect, useRef, useState } from "react";

const STEP_MS = 2600;
const STEPS = [
  "محادثة جديدة توصل",
  "سياق العميل يظهر",
  "الـAI يفهم المحادثة",
  "الـAI ينفذ إجراء مسموحًا",
  "حدث عمل يتغير",
  "الأتمتة تتفاعل",
  "إشارة عمل جديدة",
];

export function ProductEnvironment() {
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  const [reduced, setReduced] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = () => setReduced(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => setRunning(entry.isIntersecting),
      { threshold: 0.35 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    if (reduced || !running) return;
    const id = setInterval(() => setStep((s) => (s + 1) % STEPS.length), STEP_MS);
    return () => clearInterval(id);
  }, [reduced, running]);

  const s = reduced ? STEPS.length - 1 : step;
  const at = (n: number) => s >= n;

  return (
    <div className="mk-env-wrap" ref={ref}>
      <div className="mk-demo-chip" aria-hidden="true">
        <span className="mk-demo-dot" /> مساحة تجريبية — مثال توضيحي
      </div>

      <div className="mk-env" role="img" aria-label="معاينة تفاعلية لبيئة المنتج: محادثة مع عميل يعالجها الذكاء الاصطناعي ضمن سياق الطلب والأتمتة">
        {/* شريط الأوامر العالمي — معاينة بصرية فقط */}
        <div className="mk-env-command" aria-hidden="true">
          <span className="mk-env-command-icon">⌘</span>
          <span className="mk-env-command-hint">ابحث، اسأل، أنشئ، حلّل…</span>
          <span className="mk-kbd">K</span>
        </div>

        <div className="mk-env-body">
          {/* قائمة المحادثات */}
          <div className="mk-env-col mk-env-convos">
            <div className="mk-env-col-title">المحادثات</div>
            <div className={`mk-env-convo${at(1) ? " is-active" : ""}`}>
              <span className="mk-env-avatar">أ م</span>
              <span className="mk-env-convo-meta">
                <strong>أحمد محمد</strong>
                <small>أهلًا، بسال على الطلب…</small>
              </span>
              {at(1) && <span className="mk-env-unread" aria-hidden="true" />}
            </div>
            <div className="mk-env-convo">
              <span className="mk-env-avatar">س ع</span>
              <span className="mk-env-convo-meta">
                <strong>سارة علي</strong>
                <small>هل المتوفر مقاسات؟</small>
              </span>
            </div>
            <div className="mk-env-convo">
              <span className="mk-env-avatar">و ح</span>
              <span className="mk-env-convo-meta">
                <strong>عمر حسن</strong>
                <small>تمام، أشكرك</small>
              </span>
            </div>
          </div>

          {/* المحادثة الحالية */}
          <div className="mk-env-col mk-env-thread">
            <div className="mk-env-col-title">المحادثة الحالية</div>
            <div className="mk-env-msgs">
              {at(1) && (
                <div className="bubble mk-env-anim">
                  أهلًا، بسال على الطلب رقم <span dir="ltr">#1042</span> — وصل فين؟
                  <span className="time">منذ دقيقتين</span>
                </div>
              )}
              {at(3) && !at(5) && (
                <div className="mk-env-typing mk-env-anim" aria-hidden="true">
                  <span /><span /><span />
                </div>
              )}
              {at(4) && (
                <div className="mk-env-tool mk-env-anim">
                  <span className="mk-env-tool-tag">أداة</span>
                  فحص حالة الطلب <span dir="ltr">#1042</span>
                </div>
              )}
              {at(5) && (
                <div className="bubble outbound mk-env-anim">
                  مسودة AI: طلبك <span dir="ltr">#1042</span> اتشحن النهاردة من مستودع القاهرة — التوصيل يوم الأحد.
                  <span className="time">مسودة AI · بمراجعة الفريق</span>
                </div>
              )}
              {at(6) && (
                <div className="bubble outbound mk-env-anim">
                  تم إرسال إشعار الشحن تلقائيًا على واتساب ✓
                  <span className="time">أتمتة · سياسة: إشعارات الشحن</span>
                </div>
              )}
            </div>
            {at(6) && (
              <div className="mk-env-handoff mk-env-anim">
                جاهزة للتحويل البشري في أي وقت — السياق محفوظ بالكامل
              </div>
            )}
          </div>

          {/* سياق العميل */}
          <div className="mk-env-col mk-env-context">
            <div className="mk-env-col-title">سياق العميل</div>
            {!at(2) ? (
              <div className="mk-env-context-empty">يظهر تلقائيًا مع المحادثة…</div>
            ) : (
              <div className="mk-env-context-body mk-env-anim">
                <div className="mk-env-cust">
                  <strong>أحمد محمد</strong>
                  <span className="badge badge-primary">VIP</span>
                  <span className="badge badge-success">نشط</span>
                </div>
                <div className="mk-env-cust-stats">
                  <div><small>الإيرادات</small><b>8,420 ج.م</b></div>
                  <div><small>الطلبات</small><b>14</b></div>
                  <div><small>آخر نشاط</small><b>منذ 5 د</b></div>
                </div>
                <div className="mk-env-order">
                  <div className="mk-env-order-head">
                    <span dir="ltr">طلب #1042</span>
                    {at(5)
                      ? <span className="badge badge-success mk-env-anim">تم الشحن</span>
                      : <span className="badge badge-warning">قيد التجهيز</span>}
                  </div>
                  <small>مستودع القاهرة · الدفع: دفع عند الاستلام</small>
                </div>
                <div className="mk-env-ai">
                  <div className="mk-env-ai-head">سياق AI</div>
                  {at(3) && <div className="mk-env-ai-row mk-env-anim"><span>النية</span><b>حالة طلب</b></div>}
                  <div className="mk-env-ai-row"><span>الإجراء التالي</span><b>متابعة بعد التوصيل</b></div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* شريط المؤشرات */}
        <div className="mk-env-strip">
          <div className="mk-env-stat"><small>الإيرادات (الشهر)</small><b>48,300 ج.م</b></div>
          <div className="mk-env-stat"><small>الطلبات اليوم</small><b>{at(5) ? "127" : "126"}</b></div>
          <div className="mk-env-stat"><small>نشاط AI</small><b>34 مهمة</b></div>
          <div className="mk-env-stat"><small>الأتمتة</small><b>9 شغالة</b></div>
          <div className="mk-env-stat mk-env-signal">
            <small>إشارة</small>
            {at(7)
              ? <b className="mk-env-anim mk-signal-ok">تم حل خطر SLA</b>
              : <b className="mk-signal-warn">SLA في خطر</b>}
          </div>
        </div>
      </div>

      {/* مؤشر مراحل القصة */}
      <div className="mk-env-steps" aria-hidden="true">
        {STEPS.map((label, i) => (
          <span key={label} className={`mk-env-step${i === s ? " is-on" : ""}`} />
        ))}
        <span className="mk-env-step-label">{STEPS[s]}</span>
      </div>
    </div>
  );
}
