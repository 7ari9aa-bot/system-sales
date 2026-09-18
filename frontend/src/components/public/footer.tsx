import Link from "next/link";

/** الفوتر: الأعمدة كاملة حسب الخطة، لكن العناصر اللي ملهاش صفحات فعلية بعد
 *  تظهر كنص ثابت مش لينكات — لا روابط وهمية. */
export function PublicFooter() {
  return (
    <footer className="mk-footer">
      <div className="mk-container mk-footer-grid">
        <div className="mk-footer-brand">
          <span className="mk-brand">
            <span className="mk-brand-mark" aria-hidden="true">س</span>
            <span className="mk-brand-name">سيلز أو إس</span>
          </span>
          <p className="mk-footer-tag">
            سياق عمل واحد. نظام تشغيل واحد.
          </p>
        </div>

        <nav aria-label="المنتج">
          <h4>المنتج</h4>
          <a href="#product">نظرة عامة</a>
          <a href="#context">سياق العمل</a>
          <a href="#inbox">المحادثات</a>
          <a href="#ai">الذكاء الاصطناعي</a>
          <a href="#automation">الأتمتة</a>
          <a href="#analytics">التحليلات</a>
        </nav>

        <nav aria-label="الحلول">
          <h4>الحلول</h4>
          <span className="mk-footer-soon">خدمة العملاء</span>
          <span className="mk-footer-soon">المبيعات</span>
          <span className="mk-footer-soon">التسويق</span>
          <span className="mk-footer-soon">التجارة</span>
        </nav>

        <nav aria-label="الموارد">
          <h4>الموارد</h4>
          <span className="mk-footer-soon">التوثيق</span>
          <span className="mk-footer-soon">الأدلة</span>
          <span className="mk-footer-soon">المدونة</span>
          <span className="mk-footer-soon">سجل التغييرات</span>
        </nav>

        <nav aria-label="الشركة والنظام">
          <h4>الشركة</h4>
          <span className="mk-footer-soon">من نحن</span>
          <Link href="/auth/signup">ابدأ الآن</Link>
          <Link href="/auth/login">تسجيل الدخول</Link>
          <h4 className="mk-footer-h4-gap">النظام</h4>
          <span className="mk-footer-soon">الحالة</span>
          <span className="mk-footer-soon">الخصوصية</span>
          <span className="mk-footer-soon">الشروط</span>
        </nav>
      </div>

      <div className="mk-container mk-footer-bottom">
        <span>© 2026 سيلز أو إس</span>
        <span className="mk-lang">العربية</span>
      </div>
    </footer>
  );
}
