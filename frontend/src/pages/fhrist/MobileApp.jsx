import React from 'react'
import {
  Smartphone, Download, WifiOff, Printer, ShieldCheck,
  CheckCircle2, Zap, HardDrive, Barcode, ArrowDownToLine
} from 'lucide-react'
import { c, tx, Reveal, SectionIntro, Button } from '@/components/fihrist/Shared'

const features = [
  {
    icon: Zap,
    title: c('نقطة بيع سريعة ومتكاملة (POS)', 'Fast & Integrated POS Cashier'),
    body: c('تسجيل عمليات البيع، إضافة المنتجات للسلة، تطبيق الخصومات، والتبديل السريع بين وسائل الدفع (نقدي / بطاقة / آجل) في واجهة خفيفة ومناسبة للأجهزة المحمولة.', 'Record sales, add products to cart, apply discounts, and switch payment methods (cash/card/deferred) seamlessly on mobile devices.'),
  },
  {
    icon: WifiOff,
    title: c('العمل دون اتصال بالإنترنت (Offline-First)', 'Offline-First Architecture'),
    body: c('بيع بدون توقف حتى عند انقطاع الإنترنت. يتم حفظ جميع العمليات في طابور محلي مشفر ومحمي، وتُرفع تلقائياً للسيرفر فور عودة الاتصال مع منع التكرار.', 'Sell continuously even without internet. Operations queue securely offline and sync automatically upon reconnection with full idempotency.'),
  },
  {
    icon: Barcode,
    title: c('قارئ باركود ذكي بالكاميرا', 'Smart Barcode Scanner'),
    body: c('مسح فوري لأكواد الباركود وQR عبر كاميرا الهاتف مباشرة للتعرف على المنتجات وإضافتها لعملية البيع في أجزاء من الثانية.', 'Instant camera-based barcode and QR scanning for rapid item identification and checkout in fractions of a second.'),
  },
  {
    icon: Printer,
    title: c('طباعة الفواتير الحرارية (Bluetooth)', 'Bluetooth Thermal Receipt Printing'),
    body: c('ربط مباشر بطابعات الإيصالات الحرارية المتنقلة والثابتة عبر البلوتوث (ESC/POS)، مع دعم الفاتورة الضريبية المبسطة ورمز QR المعتمد.', 'Direct pairing with mobile and desktop ESC/POS thermal printers over Bluetooth, formatting tax receipts and QR codes accurately.'),
  },
  {
    icon: HardDrive,
    title: c('إدارة وتعديل المخزون الفوري', 'Real-time Stock Management'),
    body: c('متابعة كميات المنتجات والأصناف، استلام الشحنات وتأكيد أوامر الشراء، وإجراء تسويات الجرد بالزيادة أو النقصان مع تسجيل سبب الحركة.', 'Track real-time stock levels, receive purchase orders, and perform stock adjustments with complete audit trails.'),
  },
  {
    icon: ShieldCheck,
    title: c('أمان وعزل تام للمتاجر والفروع', 'Strict Multi-tenant Isolation'),
    body: c('حماية تامة وصلاحيات مخصصة لكل مستخدم وكاشير، مع عزل بيانات كل متجر وفرع على مستوى النظام وقاعدة البيانات.', 'Robust role-based security with strict cryptographic and database tenant isolation across all stores and branches.'),
  },
]

const specs = [
  { label: c('اسم التطبيق', 'App Name'), value: c('منظومة فهرس للمبيعات (Fihrist Mobile)', 'Fihrist Sales OS Mobile') },
  { label: c('اسم الحزمة', 'Package ID'), value: c('world.fihrist.fihrist_mobile', 'world.fihrist.fihrist_mobile') },
  { label: c('رقم الإصدار', 'Version'), value: c('1.0.0 (Build 1)', '1.0.0 (Build 1)') },
  { label: c('حجم الملف', 'File Size'), value: c('75.7 ميجابايت (APK)', '75.7 MB (APK)') },
  { label: c('الحد الأدنى للنظام', 'Min Android OS'), value: c('أندرويد 6.0 (Marshmallow - API 23+)', 'Android 6.0 (API 23+)') },
  { label: c('الإصدار المستهدف', 'Target Android OS'), value: c('أندرويد 15 (API 35+)', 'Android 15 (API 35+)') },
  { label: c('المعمارية المدعومة', 'Architecture'), value: c('Universal (arm64-v8a, armeabi-v7a, x86_64)', 'Universal (arm64-v8a, armeabi-v7a, x86_64)') },
  { label: c('نوع التثبيت', 'Installation Type'), value: c('تثبيت مباشر (Direct APK)', 'Direct APK Installation') },
]

const steps = [
  {
    num: '01',
    title: c('تحميل ملف APK', 'Download APK'),
    desc: c('اضغط على زر التحميل المباشر لحفظ ملف التثبيت على هاتفك أو جهاز نقطة البيع.', 'Click the direct download button to save the installation file on your phone or POS device.'),
  },
  {
    num: '02',
    title: c('فتح الملف', 'Open File'),
    desc: c('افتح الملف الذي تم تحميله من شريط الإشعارات أو من تطبيق "الملفات" (Downloads).', 'Open the downloaded file from the notification tray or your Files/Downloads folder.'),
  },
  {
    num: '03',
    title: c('السماح بالمصادر غير المعروفة', 'Allow Unknown Sources'),
    desc: c('في حال ظهرت رسالة أمان النظام، اضغط "الإعدادات" ثم فعّل "السماح بتثبيت التطبيقات من هذا المصدر".', 'If prompted by Android security, tap Settings and allow installing apps from this source.'),
  },
  {
    num: '04',
    title: c('التثبيت وتسجيل الدخول', 'Install & Sign In'),
    desc: c('اضغط على "تثبيت"، ثم افتح التطبيق وسجّل الدخول بحساب متجرك للبدء في البيع فوراً.', 'Tap Install, open the app, and sign in with your Fihrist store credentials to start selling.'),
  },
]

export default function MobileApp({ locale }) {
  const apkDownloadUrl = '/downloads/fihrist-mobile.apk'

  return (
    <>
      <section className="detail-hero">
        <div className="container detail-grid">
          <div>
            <span className="eyebrow">
              <Smartphone size={15} /> {tx(c('تطبيق الموبايل والكاشير', 'Mobile & POS App'), locale)}
            </span>
            <h1>{tx(c('نظام مبيعات وكاشير متكامل في جيبك.', 'Full POS & sales system right in your pocket.'), locale)}</h1>
            <p className="hero-lede">
              {tx(
                c(
                  'حمّل تطبيق فهرس لأجهزة وهواتف أندرويد. بيع متواصل دون إنترنت، مسح باركود ذكي بالكاميرا، طباعة فواتير حرارية عبر البلوتوث، ومزامنة فورية مع متجرك.',
                  'Download the official Fihrist Android app. Offline sales capability, camera barcode scanning, Bluetooth thermal receipt printing, and seamless cloud synchronization.'
                ),
                locale
              )}
            </p>
            <div className="hero-actions" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
              <a
                className="btn btn-primary"
                href={apkDownloadUrl}
                download="fihrist-mobile.apk"
                data-testid="button-download-apk"
                style={{ padding: '14px 28px', fontSize: '1rem', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
              >
                <ArrowDownToLine size={20} aria-hidden="true" />
                <span>{tx(c('تحميل التطبيق مباشرة (APK)', 'Download APK Directly'), locale)}</span>
              </a>
              <Button href="#specs" kind="secondary">
                {tx(c('المواصفات التقنية', 'Technical Specs'), locale)}
              </Button>
            </div>
            <div className="hero-note" style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '8px', opacity: 0.85 }}>
              <CheckCircle2 size={16} color="var(--primary, #059669)" />
              <small>
                {tx(
                  c('نسخة أندرويد رسمية v1.0.0 • حجم الملف 75.7 MB • أندرويد 6.0 وما فوق', 'Official Android release v1.0.0 • 75.7 MB • Android 6.0+'),
                  locale
                )}
              </small>
            </div>
          </div>
          <div className="detail-visual">
            <div className="principle-card" style={{ padding: '28px' }}>
              <span className="principle-mark"><Smartphone size={32} /></span>
              <span className="demo-badge"><span className="demo-dot" /> {tx(c('إصدار جاهز للإنتاج', 'Production Release'), locale)}</span>
              <h3 style={{ marginTop: '16px', marginBottom: '8px' }}>{tx(c('Fihrist POS Mobile', 'Fihrist POS Mobile'), locale)}</h3>
              <p style={{ fontSize: '0.9rem', opacity: 0.85, lineHeight: 1.5 }}>
                {tx(
                  c(
                    'مصمم خصيصاً للعمل في المتاجر ونقاط البيع السريعة، مع دعم أجهزة POS المحمولة وطابعات الفواتير.',
                    'Engineered for retail stores and fast-paced cashier counters, supporting handheld POS devices and receipt printers.'
                  ),
                  locale
                )}
              </p>
              <div style={{ marginTop: '20px', borderTop: '1px solid rgba(125,125,125,0.2)', paddingTop: '16px' }}>
                <a
                  href={apkDownloadUrl}
                  download="fihrist-mobile.apk"
                  className="btn btn-secondary"
                  style={{ width: '100%', justifyContent: 'center', gap: '8px' }}
                >
                  <Download size={16} />
                  <span>{tx(c('تحميل (75.7 MB)', 'Download (75.7 MB)'), locale)}</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('المميزات', 'Features'), locale)}
            title={tx(c('كل ما يحتاجه التاجر والكاشير في تطبيق واحد.', 'Everything a merchant & cashier needs in one app.'), locale)}
            body={tx(
              c(
                'سرعة في الأداء، دقة في حركة المخزون، وثقة تامة في استمرار البيع في أصعب ظروف الاتصال.',
                'Blazing speed, accurate inventory movement, and reliable sales continuity under any network condition.'
              ),
              locale
            )}
          />
          <div className="feature-grid">
            {features.map(({ icon: Icon, title, body }) => (
              <Reveal className="reveal-cell" key={title.ar}>
                <article className="feature-card">
                  <span className="icon-tile"><Icon size={20} /></span>
                  <h3>{tx(title, locale)}</h3>
                  <p>{tx(body, locale)}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* Specifications Table */}
      <section className="section" id="specs" style={{ background: 'rgba(125,125,125,0.03)' }}>
        <div className="container">
          <SectionIntro
            kicker={tx(c('بيانات الملف والتشغيل', 'Specifications'), locale)}
            title={tx(c('المواصفات التقنية للتطبيق.', 'Technical Specifications.'), locale)}
            body={tx(
              c(
                'تفاصيل حزمة التثبيت ومتطلبات التوافق مع أجهزة الهواتف والأجهزة اللوحية.',
                'Package specifications and compatibility requirements for mobile and tablet hardware.'
              ),
              locale
            )}
          />
          <Reveal>
            <div
              style={{
                maxWidth: '720px',
                margin: '0 auto',
                background: 'var(--card-bg, rgba(255,255,255,0.05))',
                borderRadius: '12px',
                border: '1px solid rgba(125,125,125,0.2)',
                overflow: 'hidden',
              }}
            >
              {specs.map((item, idx) => (
                <div
                  key={item.label.en}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    padding: '14px 20px',
                    borderBottom: idx === specs.length - 1 ? 'none' : '1px solid rgba(125,125,125,0.15)',
                    background: idx % 2 === 0 ? 'transparent' : 'rgba(125,125,125,0.02)',
                  }}
                >
                  <span style={{ fontWeight: 600, color: 'var(--text-muted, #888)' }}>{tx(item.label, locale)}</span>
                  <span style={{ fontFamily: 'monospace', fontWeight: 500 }}>{tx(item.value, locale)}</span>
                </div>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* Installation Guide */}
      <section className="section section-workflow">
        <div className="container">
          <SectionIntro
            kicker={tx(c('طريقة التثبيت', 'Installation Guide'), locale)}
            title={tx(c('خطوات بسيطة لتثبيت التطبيق على جهازك.', 'Simple steps to install the app.'), locale)}
            body={tx(
              c(
                'يمكنك تثبيت ملف الـ APK مباشرة باتباع الخطوات التالية:',
                'Install the APK directly onto your device with these steps:'
              ),
              locale
            )}
          />
          <div className="workflow">
            {steps.map((st, i) => (
              <div className="workflow-step" key={st.num}>
                <span className="step-number">{st.num}</span>
                <span>{tx(st.title, locale)}</span>
                <small className="step-desc">{tx(st.desc, locale)}</small>
                {i < steps.length - 1 && <span className="step-line" />}
              </div>
            ))}
          </div>

          <div style={{ textAlign: 'center', marginTop: '48px' }}>
            <a
              className="btn btn-primary"
              href={apkDownloadUrl}
              download="fihrist-mobile.apk"
              style={{ padding: '14px 32px', fontSize: '1.05rem', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <ArrowDownToLine size={20} />
              <span>{tx(c('تحميل التطبيق الآن (75.7 MB)', 'Download App Now (75.7 MB)'), locale)}</span>
            </a>
          </div>
        </div>
      </section>
    </>
  )
}
