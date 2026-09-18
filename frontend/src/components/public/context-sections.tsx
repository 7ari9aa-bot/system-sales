/** سياق العمل الواحد + Customer 360 + الـInbox الموحد — أقسام ثابتة (Server Components). */

export function ContextGraph() {
  return (
    <section className="mk-section mk-section-alt" id="context">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>شركتك مش المفروض تعيش في أدوات مفككة.</h2>
          <p>
            مش CRM قاعدة بيانات لوحدها + Inbox قاعدة بيانات لوحدها + AI لوحده.
            سياق واحد بيلمع في كل مكان — نفس العميل بنفس التاريخ والقيمة في كل شاشة.
          </p>
        </header>

        <div className="mk-graph" role="img" aria-label="مخطط: العميل في المركز متصل بالمحادثة والطلب والتسويق والدفع والأتمتة والذكاء الاصطناعي والتحليلات">
          <div className="mk-graph-row">
            <span className="mk-node">محادثة</span>
            <span className="mk-node">طلب</span>
            <span className="mk-node">تسويق</span>
          </div>
          <div className="mk-graph-link" aria-hidden="true" />
          <div className="mk-graph-hub">العميل — سياق واحد</div>
          <div className="mk-graph-link" aria-hidden="true" />
          <div className="mk-graph-row">
            <span className="mk-node">دفع</span>
            <span className="mk-node">أتمتة</span>
            <span className="mk-node">AI</span>
          </div>
          <div className="mk-graph-tail" aria-hidden="true" />
          <span className="mk-node mk-node-wide">تحليلات</span>
        </div>
      </div>
    </section>
  );
}

export function Customer360() {
  return (
    <section className="mk-section" id="customer">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>كل عميل بيجي معاه السياق الكامل.</h2>
          <p>سجل عميل حقيقي من النظام — المحادثة والطلب والدفع والتاريخ في مكان واحد.</p>
        </header>

        <div className="mk-demo-chip mk-demo-chip-float" aria-hidden="true">
          <span className="mk-demo-dot" /> بيانات تجريبية
        </div>

        <div className="card mk-c360">
          <div className="mk-c360-head">
            <span className="mk-env-avatar mk-avatar-lg" aria-hidden="true">أ م</span>
            <div className="mk-c360-id">
              <strong>أحمد محمد</strong>
              <div className="mk-c360-badges">
                <span className="badge badge-primary">VIP</span>
                <span className="badge badge-success">نشط</span>
              </div>
            </div>
            <div className="mk-c360-stats">
              <div><small>الإيرادات</small><b>8,420 ج.م</b></div>
              <div><small>الطلبات</small><b>14</b></div>
              <div><small>آخر نشاط</small><b>منذ 5 د</b></div>
            </div>
          </div>

          <div className="mk-c360-tabs" aria-hidden="true">
            <span className="is-active">نظرة عامة</span>
            <span>الخط الزمني</span>
            <span>المحادثات</span>
            <span>الطلبات</span>
            <span>المدفوعات</span>
            <span>التسويق</span>
            <span>المهام</span>
            <span>AI</span>
          </div>

          <div className="mk-c360-body">
            <div className="mk-c360-panel">
              <h4>معلومات العميل</h4>
              <div className="mk-kv"><span>الهاتف</span><b dir="ltr">+20 100 123 4567</b></div>
              <div className="mk-kv"><span>البريد</span><b dir="ltr">ahmed@example.com</b></div>
              <div className="mk-kv"><span>الوسوم</span><b>تجزئة · عميل دائم</b></div>
              <div className="mk-kv"><span>المسؤول</span><b>نورا — فريق المبيعات</b></div>
            </div>
            <div className="mk-c360-panel">
              <h4>سياق العمل</h4>
              <div className="mk-kv"><span>طلبات مفتوحة</span><b>2</b></div>
              <div className="mk-kv"><span>مدفوعات</span><b>14 مكتملة</b></div>
              <div className="mk-kv"><span>مشاكل مفتوحة</span><b>لا يوجد</b></div>
              <div className="mk-kv"><span>قناة مفضلة</span><b>واتساب</b></div>
            </div>
            <div className="mk-c360-panel mk-c360-panel-ai">
              <h4>سياق AI</h4>
              <div className="mk-kv"><span>النية</span><b>حالة طلب · مرتفعة</b></div>
              <div className="mk-kv"><span>قيمة العميل</span><b>مرتفعة</b></div>
              <div className="mk-kv"><span>الخطر</span><b>منخفض</b></div>
              <div className="mk-kv"><span>الإجراء التالي</span><b>متابعة بعد التوصيل</b></div>
            </div>
          </div>
        </div>

        <div className="mk-timeline-wrap">
          <h3 className="mk-h3">خط زمني مترابط — مش سجلات متفرقة</h3>
          <ol className="mk-timeline">
            <li><b>محادثة</b><small>سأل على الطلب على واتساب</small></li>
            <li><b>عميل محتمل</b><small>اتسجل من حملة إنستجرام</small></li>
            <li><b>طلب</b><small dir="ltr">#1042 · 1,250 ج.م</small></li>
            <li><b>دفعة</b><small>دفع عند الاستلام · مؤكدة</small></li>
            <li><b>حملة</b><small>كود خصم للعميل الدائم</small></li>
            <li><b>أتمتة</b><small>إشعار الشحن تلقائي</small></li>
            <li><b>تفاعل AI</b><small>ملخص + إجراء مقترح</small></li>
          </ol>
        </div>
      </div>
    </section>
  );
}

export function InboxPreview() {
  return (
    <section className="mk-section mk-section-alt" id="inbox">
      <div className="mk-container">
        <header className="mk-section-head">
          <h2>كل محادثة بتوصل ومعاها السياق.</h2>
          <p>
            الموظف مش بيخرج من المحادثة عشان يدور على العميل أو الطلب أو الدفع —
            كل ده ظاهر جنب شغله.
          </p>
        </header>

        <div className="mk-channels" aria-label="القنوات المدعومة">
          <span className="mk-channel is-live">شات الموقع<span>شغّال</span></span>
          <span className="mk-channel">واتساب<span>قريبًا</span></span>
          <span className="mk-channel">إنستجرام<span>قريبًا</span></span>
          <span className="mk-channel">ماسنجر<span>قريبًا</span></span>
          <span className="mk-channel">تليجرام<span>قريبًا</span></span>
        </div>

        <div className="mk-demo-chip mk-demo-chip-float" aria-hidden="true">
          <span className="mk-demo-dot" /> بيانات تجريبية
        </div>

        <div className="card mk-inbox-preview">
          <div className="mk-inbox-col">
            <div className="mk-env-col-title">المحادثات</div>
            <div className="mk-env-convo is-active">
              <span className="mk-env-avatar">أ م</span>
              <span className="mk-env-convo-meta">
                <strong>أحمد محمد</strong>
                <small>واتساب · منذ دقيقتين</small>
              </span>
            </div>
            <div className="mk-env-convo">
              <span className="mk-env-avatar">س ع</span>
              <span className="mk-env-convo-meta">
                <strong>سارة علي</strong>
                <small>تليجرام · منذ 12 د</small>
              </span>
            </div>
            <div className="mk-env-convo">
              <span className="mk-env-avatar">و ح</span>
              <span className="mk-env-convo-meta">
                <strong>عمر حسن</strong>
                <small>شات الموقع · منذ ساعة</small>
              </span>
            </div>
          </div>
          <div className="mk-inbox-col mk-inbox-col-thread">
            <div className="mk-env-col-title">المحادثة</div>
            <div className="mk-env-msgs">
              <div className="bubble">
                هل الطلب هيتوصل قبل الجمعة؟
                <span className="time">منذ 10 د</span>
              </div>
              <div className="bubble outbound">
                أيوه، مجدول يوم الخميس — وابعتلك التتبع أول ما يتحرك.
                <span className="time">رد الفريق · منذ 8 د</span>
              </div>
              <div className="bubble">
                ممكن أغير العنوان لبيت والدتي؟
                <span className="time">منذ دقيقتين</span>
              </div>
              <div className="mk-env-typing" aria-hidden="true"><span /><span /><span /></div>
            </div>
            <div className="mk-inbox-suggest">
              <span className="badge badge-primary">مسودة AI</span>
              <small>«أكيد — ابعت العنوان الجديد وهحدّث الشحنة فورًا.»</small>
            </div>
          </div>
          <div className="mk-inbox-col">
            <div className="mk-env-col-title">سياق العميل</div>
            <div className="mk-env-cust">
              <strong>سارة علي</strong>
              <span className="badge">عميل جديد</span>
            </div>
            <div className="mk-kv"><span>الطلبات</span><b>1 مكتمل</b></div>
            <div className="mk-kv"><span>القيمة</span><b>690 ج.م</b></div>
            <div className="mk-kv"><span>النية</span><b>تعديل شحنة</b></div>
            <div className="mk-kv"><span>الإجراء التالي</span><b>تحديث العنوان</b></div>
          </div>
        </div>
      </div>
    </section>
  );
}
