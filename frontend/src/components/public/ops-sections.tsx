/** التحليلات + مركز التحكم + التكاملات + الأمان + الـCTA الختامي. */

const METRICS = [
  { label: "الإيرادات", delta: "+12%", tone: "up" },
  { label: "الطلبات", delta: "+8%", tone: "up" },
  { label: "التحويل", delta: "−3%", tone: "down" },
  { label: "العملاء", delta: "+6%", tone: "up" },
  { label: "نشاط AI", delta: "↑", tone: "up" },
  { label: "العمليات", delta: "!", tone: "alert" },
];

const CONTROLS = [
  { label: "وكلاء AI", value: "24 نشط" },
  { label: "أتمتة", value: "182 شغالة" },
  { label: "موافقات معلقة", value: "7" },
  { label: "مهام فاشلة", value: "2" },
  { label: "SLA في خطر", value: "4" },
  { label: "استخدام AI", value: "$184" },
  { label: "تحويلات بشرية", value: "31" },
];

export function Analytics() {
  return (
    <section className="mk-section mk-section-alt" id="analytics">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>اعرف اللي بيحصل. واعرف اللي محتاج فعل.</h2>
          <p>مقياس → استنتاج → السجلات اللي وراه → إجراء. مش رسومات على الفاضي.</p>
        </header>

        <div className="mk-demo-chip mk-demo-chip-float" aria-hidden="true">
          <span className="mk-demo-dot" /> بيانات تجريبية
        </div>

        <div className="mk-metrics">
          {METRICS.map((m) => (
            <div key={m.label} className="card mk-metric">
              <small>{m.label}</small>
              <b className={`mk-delta mk-delta-${m.tone}`} dir="ltr">{m.delta}</b>
            </div>
          ))}
        </div>

        <div className="card mk-insight">
          <div className="mk-insight-badge">استنتاج</div>
          <p>
            نسبة التحويل انخفضت أساسًا لدى <b>العملاء العائدين</b> —
            بعد تغيير سياسة الشحن الأسبوع الماضي.
          </p>
          <div className="mk-insight-actions" aria-hidden="true">
            <span className="btn btn-secondary">فحص السجلات</span>
            <span className="btn">تعامل مع الأمر</span>
          </div>
        </div>
      </div>
    </section>
  );
}

export function ControlCenter() {
  return (
    <section className="mk-section" id="control">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>كل حاجة النظام بيعملها ظاهرة وقابلة للتحكم.</h2>
          <p>قوي، لكنه مش صندوق أسود: تراقب، تتحكم، تحقق، توافق، تراجع، تسترجع.</p>
        </header>

        <div className="mk-demo-chip mk-demo-chip-float" aria-hidden="true">
          <span className="mk-demo-dot" /> بيانات تجريبية
        </div>

        <div className="mk-controls">
          {CONTROLS.map((c) => (
            <div key={c.label} className="card mk-control">
              <b>{c.value}</b>
              <small>{c.label}</small>
            </div>
          ))}
        </div>

        <div className="mk-chip-grid">
          <span className="mk-chip">سياسات</span>
          <span className="mk-chip">صلاحيات</span>
          <span className="mk-chip">تدقيق</span>
          <span className="mk-chip">أمان</span>
          <span className="mk-chip">صحة النظام</span>
        </div>
      </div>
    </section>
  );
}

const INTEGRATIONS = [
  { name: "Gemini", desc: "النماذج اللغوية", status: "شغّال", live: true },
  { name: "n8n", desc: "الأتمتة والتكاملات", status: "شغّال", live: true },
  { name: "شات الموقع", desc: "قناة مباشرة بدون اعتماديات", status: "شغّال", live: true },
  { name: "WhatsApp", desc: "القناة الأهم للتجارة", status: "قريبًا", live: false },
  { name: "Telegram", desc: "محادثات ومجتمعات", status: "قريبًا", live: false },
  { name: "Instagram · Messenger", desc: "التواصل الاجتماعي", status: "قريبًا", live: false },
];

export function Integrations() {
  return (
    <section className="mk-section" id="integrations">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>شغلك عايش فعلًا في أماكن كتير.</h2>
          <p>وصّل الأنظمة اللي بتستخدمها — النظام يستقبلها في نفس السياق الواحد.</p>
        </header>

        <div className="mk-flow-demo" aria-hidden="true">
          <span className="mk-flow-node">وصّل</span>
          <span className="mk-flow-arrow">←</span>
          <span className="mk-flow-node">زامن</span>
          <span className="mk-flow-arrow">←</span>
          <span className="mk-flow-node">نفّذ</span>
        </div>

        <div className="mk-integrations">
          {INTEGRATIONS.map((i) => (
            <div key={i.name} className="card mk-integration">
              <div className="mk-integration-name">{i.name}</div>
              <small>{i.desc}</small>
              <span className={`badge ${i.live ? "badge-success" : ""}`}>{i.status}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

const SECURITY_ITEMS = [
  { title: "عزل بيانات لكل مستأجر", desc: "فصل على مستوى قاعدة البيانات (RLS) — بيانات كل شركة معزولة فعليًا، مش على مستوى الواجهة بس." },
  { title: "صلاحيات وأدوار", desc: "كل مستخدم يشوف ويعمل اللي دوره يسمح بيه فقط — على مستوى الـAPI مش الواجهة." },
  { title: "مصادقة بجلسات آمنة", desc: "توكنات قصيرة العمر + تدوير تلقائي + خروج آمن." },
  { title: "سجلات تدقيق", desc: "كل تغيير مهم مسجل: مين، إمتى، وإيه اللي حصل." },
  { title: "صلاحيات منفصلة للـAI", desc: "الذكاء الاصطناعي بينفذ عبر أدوات بصلاحيات محددة مسبقًا — ومفيش وصول مباشر لقاعدة البيانات." },
  { title: "حماية نداءات النظام", desc: "التحقق من توقيع الـwebhooks ومنع الطلبات المكررة (idempotency)." },
];

export function SecuritySection() {
  return (
    <section className="mk-section mk-section-alt" id="security">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>مبني للتحكم والخصوصية والمساءلة.</h2>
          <p>اللي تحت دي قدرات مبنية فعلًا في النظام — بنكتب بس اللي شغال.</p>
        </header>

        <div className="mk-security">
          {SECURITY_ITEMS.map((s) => (
            <div key={s.title} className="mk-security-item">
              <b>{s.title}</b>
              <p>{s.desc}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function FinalCTA() {
  return (
    <section className="mk-final" id="start">
      <div className="mk-container mk-final-inner">
        <h2>سياق عمل واحد. نظام تشغيل واحد.</h2>
        <p>
          اجمع العملاء والمحادثات والتجارة والأتمتة والذكاء الاصطناعي والعمليات
          في نظام واحد متصل.
        </p>
        <div className="mk-hero-cta mk-hero-cta-center">
          <a href="/auth/signup" className="btn mk-btn-lg">ابدأ الآن</a>
          <a href="#product" className="btn btn-secondary mk-btn-lg">استعرض المنتج</a>
        </div>
      </div>
    </section>
  );
}
