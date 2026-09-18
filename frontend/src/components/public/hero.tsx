import Link from "next/link";
import { ProductEnvironment } from "@/components/public/product-environment";

export function Hero() {
  return (
    <section className="mk-hero" id="product">
      <div className="mk-container">
        <div className="mk-hero-copy">
          <span className="mk-eyebrow">منصة تشغيل الأعمال بالمحادثة</span>
          <h1>نظام واحد متصل لشركتك.</h1>
          <p className="mk-hero-sub">
            العملاء، المحادثات، التجارة، الأتمتة، الذكاء الاصطناعي والتحليلات —
            كلها متصلة عبر سياق عمل واحد.
          </p>
          <div className="mk-hero-cta">
            <Link href="/auth/signup" className="btn mk-btn-lg">ابدأ الآن</Link>
            <a href="#product" className="btn btn-secondary mk-btn-lg">استعرض المنتج</a>
          </div>
        </div>

        <div className="mk-hero-env">
          <ProductEnvironment />
        </div>
      </div>
    </section>
  );
}
