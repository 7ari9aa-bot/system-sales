/** أقسام الذكاء الاصطناعي + التكامل البشري + الأتمتة. */

const AI_STEPS = ["يفهم", "يجيب السياق", "يستنتج", "يستخدم أدوات", "يتحقق", "ينفذ", "يراجع", "يحوّل للبشر"];

export function AISection() {
  return (
    <section className="mk-section" id="ai">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>ذكاء اصطناعي بيشتغل — جوه قواعدك.</h2>
          <p>
            مش نافذة شات. عامل جوه النظام: بيشوف السياق المسموح له بس،
            وبينفذ عبر أدوات بصلاحيات محددة، وكل خطوة بتتسجل.
          </p>
        </header>

        <ol className="mk-pipeline" aria-label="مسار عمل الذكاء الاصطناعي">
          {AI_STEPS.map((label, i) => (
            <li key={label}>
              <span className="mk-pipeline-num" aria-hidden="true">{i + 1}</span>
              {label}
            </li>
          ))}
        </ol>

        <div className="mk-flow-demo">
          <span className="mk-flow-node">محادثة</span>
          <span className="mk-flow-arrow" aria-hidden="true">←</span>
          <span className="mk-flow-node">سياق العميل</span>
          <span className="mk-flow-arrow" aria-hidden="true">←</span>
          <span className="mk-flow-node mk-flow-node-ai">AI</span>
          <span className="mk-flow-arrow" aria-hidden="true">←</span>
          <span className="mk-flow-node">أداة</span>
          <span className="mk-flow-arrow" aria-hidden="true">←</span>
          <span className="mk-flow-node">طلب</span>
          <span className="mk-flow-arrow" aria-hidden="true">←</span>
          <span className="mk-flow-node">أتمتة</span>
        </div>

        <div className="mk-chip-grid">
          <span className="mk-chip">صلاحيات وأدوار محددة</span>
          <span className="mk-chip">سياسات وأدوات معتمدة</span>
          <span className="mk-chip">موافقات بشرية للخطوات الحساسة</span>
          <span className="mk-chip">حدود تكلفة لكل مستأجر</span>
          <span className="mk-chip">تدقيق كامل لكل تشغيل</span>
          <span className="mk-chip">مصادر معرفة مجمّعة بالصلاحيات</span>
        </div>
      </div>
    </section>
  );
}

export function Handoff() {
  return (
    <section className="mk-section mk-section-alt" id="handoff">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>الـAI بيشتغل مع فريقك، مش براه.</h2>
          <p>لما الحالة تعقّد، التحويل بيحصل بسطر واحد — والسياق الكامل بيوصل مع الموظف. بدون إعادة من الصفر.</p>
        </header>

        <div className="mk-handoff">
          <div className="mk-handoff-step">
            <span className="badge badge-primary">AI</span>
            <b>الـAI بيعالج المحادثة</b>
            <small>فهم النية · تنفيذ مسموح · ردود مسودة</small>
          </div>
          <span className="mk-handoff-arrow" aria-hidden="true">←</span>
          <div className="mk-handoff-step">
            <span className="badge badge-warning">اكتشاف</span>
            <b>حالة معقدة تكتشف</b>
            <small>شكوى · استرجاع · عميل غاضب</small>
          </div>
          <span className="mk-handoff-arrow" aria-hidden="true">←</span>
          <div className="mk-handoff-step">
            <span className="badge badge-danger">تحويل</span>
            <b>تحويل لحد من الفريق</b>
            <small>حسب التخصص والعبء</small>
          </div>
          <span className="mk-handoff-arrow" aria-hidden="true">←</span>
          <div className="mk-handoff-step">
            <span className="badge badge-success">إنسان</span>
            <b>الموظف يستلم جاهز</b>
            <small>الملخص + الطلب + الدفع + تاريخ العميل</small>
          </div>
        </div>

        <div className="mk-chip-grid mk-chip-grid-subtle">
          <span className="mk-chip">حالة الـAI ظاهرة دايمًا</span>
          <span className="mk-chip">ملكية بشرية واضحة</span>
          <span className="mk-chip">موافقة على الخطوات الحساسة</span>
          <span className="mk-chip">تدقيق لكل انتقال</span>
        </div>
      </div>
    </section>
  );
}

const AUTO_CHAIN = ["حدث", "شرط", "AI / منطق", "أداة", "تحقق", "موافقة", "تنفيذ", "مراجعة", "تدقيق"];
const AUTO_EXAMPLE = [
  "عميل عالي القيمة يبعت رسالة",
  "تعريف العميل من السياق",
  "فحص قيمة العميل",
  "انتظار 10 دقايق",
  "مفيش رد بشري؟",
  "الـAI يصنّف الرسالة",
  "إشعار الفريق",
  "تصعيد لو مفيش استجابة",
];

export function Automation() {
  return (
    <section className="mk-section" id="automation">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>اوصفها. ابنِها. شغّلها.</h2>
          <p>أتمتة تشغيلية حقيقية — بتنفذ إجراءات عمل جوه النظام، مش إشعارات بس.</p>
        </header>

        <ol className="mk-pipeline mk-pipeline-compact" aria-label="بنية مسار الأتمتة">
          {AUTO_CHAIN.map((label) => (
            <li key={label}>{label}</li>
          ))}
        </ol>

        <div className="mk-automation">
          <div className="card mk-automation-flow">
            <h4>مثال: مسار العملاء عالي القيمة</h4>
            <ol className="mk-auto-steps">
              {AUTO_EXAMPLE.map((step, i) => (
                <li key={step}>
                  <span className="mk-auto-num" aria-hidden="true">{i + 1}</span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
          <div className="mk-automation-caps">
            <span className="mk-chip">سجل إصدارات</span>
            <span className="mk-chip">تشغيل تجريبي</span>
            <span className="mk-chip">سجل تنفيذ</span>
            <span className="mk-chip">إعادة تشغيل</span>
            <span className="mk-chip">استرجاع بعد الفشل</span>
          </div>
        </div>
      </div>
    </section>
  );
}
