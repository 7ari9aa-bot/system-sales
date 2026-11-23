import React, { useState } from 'react'
import {
  Monitor, Laptop, Smartphone, Download, WifiOff, Printer, ShieldCheck,
  CheckCircle2, Zap, HardDrive, Barcode, ArrowDownToLine, Cpu, Layers
} from 'lucide-react'
import { c, tx, Reveal, SectionIntro, Button } from '@/components/fihrist/Shared'

const desktopFeatures = [
  {
    icon: Zap,
    title: c('محرك Rust فائق السرعة والخفة', 'Ultra-fast Rust & Tauri Engine'),
    body: c('استهلاك موارد لا يتجاوز 50 ميجابايت من الذاكرة، مع سرعة إقلاع واستجابة لحظية حتى على أجهزة نقاط البيع القديمة والمحدودة.', 'Lightweight footprint under 50 MB RAM with instantaneous startup and responsiveness, even on modest POS hardware.'),
  },
  {
    icon: Barcode,
    title: c('توافق تام مع قارئات الباركود (USB/Serial)', 'Full Barcode Scanner Support'),
    body: c('دعم قارئات الباركود السلكية واللاسلكية عبر HID وSerial مع مسح فوري للأصناف في السلة بدون الحاجة للنقر على شريط البحث.', 'Direct support for USB HID and serial COM barcode scanners with instant cart population without focus lag.'),
  },
  {
    icon: Printer,
    title: c('طباعة الفواتير الحرارية ESC/POS', 'ESC/POS Thermal Receipt Printing'),
    body: c('طباعة إيصالات احترافية وفواتير ضريبية مبسطة مع رمز QR المعتمد، عبر منافذ USB والشبكة المحلية وطابعات السيريال.', 'Print professional receipts and simplified tax invoices with QR codes across USB, network LAN, and serial ports.'),
  },
  {
    icon: Layers,
    title: c('فتح درج النقدية تلقائياً (Cash Drawer Kick)', 'Automatic Cash Drawer RJ11 Kick'),
    body: c('إرسال نبضة كهربائية فورية لطرد درج النقدية عند إتمام الدفع النقدي، مع حماية أمنية وتدقيق لحركات فتح الدرج اليدوية.', 'Sends instant RJ11/RJ12 pulses to kick open cash drawers upon cash sales, with audit trails on manual drawer openings.'),
  },
  {
    icon: Monitor,
    title: c('شاشة عميل ثانوية (Customer Display)', 'Secondary Customer Display Window'),
    body: c('نافذة شاشة فرعية مستقلة تُعرض للعميل مباشرة لتوضيح الأصناف الممسوحة، الأسعار، الخصومات، وإجمالي الحساب فورياً.', 'Dedicated secondary window facing customers displaying scanned items, prices, discounts, and order totals in real time.'),
  },
  {
    icon: ShieldCheck,
    title: c('إدارة ورديات الكاشير وتقفيل اليومية', 'Shift & Daily Register Reconciliation'),
    body: c('فتح وإغلاق جلسات العمل، مطابقة النقدية الفعلية مع المتوقع، تسجيل السحوبات والإيداعات، وطباعة تقرير الـ X/Z اليومي.', 'Open and close cashier shifts, reconcile expected cash against drawer tally, record drop/payout, and print X/Z reports.'),
  },
]

const mobileFeatures = [
  {
    icon: WifiOff,
    title: c('العمل دون اتصال بالإنترنت (Offline-First)', 'Offline-First Architecture'),
    body: c('بيع مستمر بدون توقف حتى عند انقطاع الإنترنت. يتم حفظ العمليات في طابور محلي مشفر ومحمي، وتُرفع تلقائياً فور عودة الاتصال.', 'Sell continuously without internet. Transactions queue locally and sync automatically with full idempotency once reconnected.'),
  },
  {
    icon: Barcode,
    title: c('قارئ باركود ذكي بالكاميرا', 'Smart Camera Barcode Scanner'),
    body: c('مسح فوري لأكواد الباركود وQR عبر كاميرا الهاتف مباشرة للتعرف على المنتجات وإضافتها لعملية البيع في أجزاء من الثانية.', 'Instant camera-based barcode and QR scanning for rapid item identification and checkout in fractions of a second.'),
  },
  {
    icon: Printer,
    title: c('طباعة الفواتير عبر البلوتوث (Bluetooth)', 'Bluetooth Thermal Receipt Printing'),
    body: c('ربط مباشر بطابعات الإيصالات الحرارية المتنقلة عبر البلوتوث، لطباعة الفواتير والإيصالات أثناء التوصيل أو في المعارض المتنقلة.', 'Pair with portable Bluetooth receipt printers to issue tax invoices on deliveries, pop-up markets, or mobile kiosks.'),
  },
  {
    icon: HardDrive,
    title: c('إدارة وجرد المخزون أثناء الحركة', 'Mobile Inventory & Stock Audits'),
    body: c('متابعة كميات المنتجات، استلام الشحنات وتأكيد أوامر الشراء، وإجراء تسويات الجرد بالزيادة أو النقصان من أرض المستودع مباشرة.', 'Track quantities, receive purchase orders, and conduct on-the-spot stock count adjustments directly in the warehouse.'),
  },
]

const hardwareSupported = [
  {
    title: c('قارئات الباركود (Barcode Scanners)', 'Barcode Scanners'),
    desc: c('Zebra, Honeywell, Datalogic, وأي قارئ باركود USB HID أو Serial أو Bluetooth قياسي.', 'Zebra, Honeywell, Datalogic, and standard USB HID / Serial / Bluetooth scanners.'),
    icon: Barcode,
  },
  {
    title: c('طابعات الفواتير (Thermal Printers)', 'Thermal Receipt Printers'),
    desc: c('Epson TM Series, Bixolon, Xprinter, Rongta, وأي طابعة حرارية تدعم بروتوكول ESC/POS (80mm / 58mm).', 'Epson TM Series, Bixolon, Xprinter, Rongta, and ESC/POS-compliant thermal printers (80mm / 58mm).'),
    icon: Printer,
  },
  {
    title: c('أدراج النقدية (Cash Drawers)', 'Cash Drawers'),
    desc: c('أدراج النقدية القياسية المتصلة بمنفذ RJ11/RJ12 بطابعة الفواتير (12V / 24V Kick Pulse).', 'Standard cash drawers triggered via printer RJ11/RJ12 kick port (12V / 24V).'),
    icon: Layers,
  },
  {
    title: c('شاشات العرض وأجهزة اللمس (Touch & Display)', 'Touch & Customer Displays'),
    desc: c('شاشات اللمس لأجهزة POS المتكاملة (All-In-One)، وشاشات العميل الثانوية عبر HDMI / Type-C.', 'All-in-one POS touch screens and secondary customer-facing monitors over HDMI / USB-C.'),
    icon: Monitor,
  },
]

const desktopSpecs = [
  { label: c('اسم التطبيق', 'App Name'), value: c('منظومة فهرس كاشير ديسكتوب (Fihrist POS Desktop)', 'Fihrist POS Desktop') },
  { label: c('الإصدار الحالي', 'Version'), value: c('v0.2.0 (Official Production)', 'v0.2.0 (Official Production)') },
  { label: c('أنظمة التشغيل', 'Supported OS'), value: c('Windows 10 / 11 (64-bit) • macOS 11+ (Apple Silicon & Intel)', 'Windows 10 / 11 (64-bit) • macOS 11+ (Apple Silicon & Intel)') },
  { label: c('المعمارية والتقنية', 'Core Technology'), value: c('Rust + Tauri 2 + React 19', 'Rust + Tauri 2 + React 19') },
  { label: c('حجم مثبت ويندوز EXE', 'Windows EXE Size'), value: c('2.51 ميجابايت (NSIS Setup)', '2.51 MB (NSIS Setup)') },
  { label: c('حجم حزمة ويندوز MSI', 'Windows MSI Size'), value: c('3.51 ميجابايت (Enterprise MSI)', '3.51 MB (Enterprise MSI)') },
  { label: c('حجم حزمة ماك DMG', 'macOS DMG Size'), value: c('4.42 ميجابايت (Apple Silicon / aarch64)', '4.42 MB (Apple Silicon / aarch64)') },
  { label: c('استهلاك الذاكرة', 'RAM Footprint'), value: c('أقل من 50 ميجابايت في وضع التشغيل', 'Under 50 MB active memory') },
  { label: c('تكامل العتاد', 'Hardware Interfacing'), value: c('USB HID, Serial COM, RJ11 Cash Drawer, ESC/POS', 'USB HID, Serial COM, RJ11 Cash Drawer, ESC/POS') },
]

const mobileSpecs = [
  { label: c('اسم التطبيق', 'App Name'), value: c('منظومة فهرس للمبيعات (Fihrist Mobile)', 'Fihrist Sales OS Mobile') },
  { label: c('اسم الحزمة', 'Package ID'), value: c('world.fihrist.fihrist_mobile', 'world.fihrist.fihrist_mobile') },
  { label: c('رقم الإصدار', 'Version'), value: c('1.0.0 (Build 1)', '1.0.0 (Build 1)') },
  { label: c('حجم الملف', 'File Size'), value: c('75.7 ميجابايت (Universal APK)', '75.7 MB (Universal APK)') },
  { label: c('الحد الأدنى للنظام', 'Min Android OS'), value: c('أندرويد 6.0 (Marshmallow - API 23+)', 'Android 6.0 (API 23+)') },
  { label: c('الإصدار المستهدف', 'Target Android OS'), value: c('أندرويد 15 (Vanilla Ice Cream - API 35+)', 'Android 15 (API 35+)') },
  { label: c('المعمارية المدعومة', 'Architecture'), value: c('Universal (arm64-v8a, armeabi-v7a, x86_64)', 'Universal (arm64-v8a, armeabi-v7a, x86_64)') },
  { label: c('الاتصال والعتاد', 'Connectivity & Hardware'), value: c('Bluetooth ESC/POS Thermal Printers, Camera Barcode', 'Bluetooth ESC/POS Thermal Printers, Camera Barcode') },
]

export default function MobileApp({ locale }) {
  const [activePlatform, setActivePlatform] = useState('all')

  const windowsExeUrl = '/downloads/fihrist-setup.exe'
  const windowsMsiUrl = '/downloads/fihrist.msi'
  const macOsDmgUrl = '/downloads/fihrist-macos.dmg'
  const apkDownloadUrl = '/downloads/fihrist-mobile.apk'

  return (
    <>
      {/* Hero Section */}
      <section className="detail-hero">
        <div className="container detail-grid">
          <div>
            <span className="eyebrow">
              <Laptop size={15} /> {tx(c('مركز تحميل التطبيقات | ديسكتوب وموبايل', 'App Download Center | Desktop & Mobile'), locale)}
            </span>
            <h1>{tx(c('نظام كاشير ومبيعات متكامل لكل أجهزتك.', 'Full POS & Sales System for All Your Devices.'), locale)}</h1>
            <p className="hero-lede">
              {tx(
                c(
                  'اختر نسختك المفضلة: تطبيق الديسكتوب فائق الخفة والسرعة للكمبيوتر ونقاط البيع الثابتة مع دعم كامل لأجهزة الباركود وطابعات الإيصالات ودرج النقدية (ويندوز وماك)، أو تطبيق الموبايل المرن للبيع أوفلاين وإدارة المخزون أثناء الحركة (أندرويد).',
                  'Choose your edition: high-speed Desktop POS for PCs and cashier counters with hardware integrations for barcode scanners, receipt printers, and cash drawers (Windows & macOS), or mobile POS for handheld Android devices with offline sales.'
                ),
                locale
              )}
            </p>

            <div className="hero-actions" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
              <a
                className="btn btn-primary"
                href="#download-cards"
                style={{ padding: '14px 28px', fontSize: '1rem', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
              >
                <ArrowDownToLine size={20} aria-hidden="true" />
                <span>{tx(c('استعراض روابط التحميل', 'Browse Download Links'), locale)}</span>
              </a>
              <Button href="#specs" kind="secondary">
                {tx(c('المواصفات التقنية', 'Technical Specs'), locale)}
              </Button>
            </div>

            <div className="hero-note" style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '8px', opacity: 0.85 }}>
              <CheckCircle2 size={16} color="var(--primary, #059669)" />
              <small>
                {tx(
                  c('إصدارات رسمية جاهزة للإنتاج • خالية من الإعلانات • تحديثات مستمرة وأمان معزول', 'Official production releases • Ad-free • Continuous updates & isolated multi-tenancy'),
                  locale
                )}
              </small>
            </div>
          </div>

          <div className="detail-visual">
            <div className="principle-card" style={{ padding: '24px' }}>
              <span className="principle-mark"><Cpu size={32} /></span>
              <span className="demo-badge"><span className="demo-dot" /> {tx(c('جاهز للتشغيل الفوري', 'Ready To Deploy'), locale)}</span>
              <h3 style={{ marginTop: '16px', marginBottom: '8px' }}>{tx(c('منظومة تطبيقات فهرس', 'Fihrist Apps Ecosystem'), locale)}</h3>
              <p style={{ fontSize: '0.9rem', opacity: 0.85, lineHeight: 1.5 }}>
                {tx(
                  c(
                    'تطبيقات أصلية (Native) خفيفة وسريعة مصممة خصيصاً للمتاجر ونقاط البيع السريعة، مع دعم أجهزة العتاد المكتبي والمحمول.',
                    'Fast, native apps crafted specifically for retail stores and high-volume cashier counters with broad hardware compatibility.'
                  ),
                  locale
                )}
              </p>

              <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <a
                  href={windowsExeUrl}
                  download="fihrist-setup.exe"
                  className="btn btn-secondary"
                  style={{ width: '100%', justifyContent: 'space-between', padding: '10px 16px', fontSize: '0.9rem' }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                    <Monitor size={18} />
                    <span>{tx(c('ديسكتوب ويندوز (.exe)', 'Windows Desktop (.exe)'), locale)}</span>
                  </span>
                  <span style={{ fontFamily: 'monospace', opacity: 0.7 }}>2.5 MB</span>
                </a>

                <a
                  href={macOsDmgUrl}
                  download="fihrist-macos.dmg"
                  className="btn btn-secondary"
                  style={{ width: '100%', justifyContent: 'space-between', padding: '10px 16px', fontSize: '0.9rem' }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                    <Laptop size={18} />
                    <span>{tx(c('ديسكتوب ماك (.dmg)', 'macOS Desktop (.dmg)'), locale)}</span>
                  </span>
                  <span style={{ fontFamily: 'monospace', opacity: 0.7 }}>4.4 MB</span>
                </a>

                <a
                  href={apkDownloadUrl}
                  download="fihrist-mobile.apk"
                  className="btn btn-secondary"
                  style={{ width: '100%', justifyContent: 'space-between', padding: '10px 16px', fontSize: '0.9rem' }}
                >
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                    <Smartphone size={18} />
                    <span>{tx(c('موبايل أندرويد (.apk)', 'Android Mobile (.apk)'), locale)}</span>
                  </span>
                  <span style={{ fontFamily: 'monospace', opacity: 0.7 }}>75.7 MB</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Download Cards Section */}
      <section className="section" id="download-cards" style={{ paddingTop: '20px' }}>
        <div className="container">
          <SectionIntro
            kicker={tx(c('حزم التحميل المباشرة', 'Direct Downloads'), locale)}
            title={tx(c('اختر المنصة المناسبة لمتجرك وفريقك.', 'Select the platform for your store and staff.'), locale)}
            body={tx(
              c(
                'روابط تحميل مباشرة سريعة وآمنة بدون وسائط، لجميع أنظمة التشغيل المعتمدة.',
                'Direct, fast, and secure installation packages for all supported operating systems.'
              ),
              locale
            )}
          />

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '24px', marginTop: '32px' }}>
            {/* Windows Card */}
            <Reveal className="reveal-cell">
              <article className="feature-card" style={{ height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: '32px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <span className="icon-tile"><Monitor size={24} /></span>
                    <span className="demo-badge" style={{ background: 'rgba(5, 150, 105, 0.15)', color: 'var(--primary, #059669)' }}>
                      Windows 10 / 11
                    </span>
                  </div>
                  <h3 style={{ marginTop: '20px', fontSize: '1.35rem' }}>{tx(c('تطبيق ديسكتوب ويندوز', 'Windows POS Desktop'), locale)}</h3>
                  <p style={{ marginTop: '8px', lineHeight: 1.6, opacity: 0.85 }}>
                    {tx(
                      c(
                        'مثالي لأجهزة الكاشير المكتبية وأجهزة نقاط البيع التي تعمل بنظام ويندوز. ربط مباشر بقارئ الباركود، درج النقدية RJ11، وطابعات الفواتير الحرارية ESC/POS.',
                        'Engineered for Windows cashier terminals. Native integration with USB/Serial barcode scanners, RJ11 cash drawers, and ESC/POS thermal printers.'
                      ),
                      locale
                    )}
                  </p>
                  <ul style={{ listStyle: 'none', padding: 0, margin: '20px 0', fontSize: '0.88rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('حجم خفيف جداً: 2.5 ميجابايت فقط', 'Ultra lightweight: Only 2.5 MB'), locale)}</span>
                    </li>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('محرك سريع مبني بلغة Rust وTauri 2', 'Blazing speed built with Rust & Tauri 2'), locale)}</span>
                    </li>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('شاشة عميل ثانوية وإدارة الورديات', 'Customer display window & shift manager'), locale)}</span>
                    </li>
                  </ul>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '20px' }}>
                  <a
                    className="btn btn-primary"
                    href={windowsExeUrl}
                    download="fihrist-setup.exe"
                    data-testid="button-download-windows-exe"
                    style={{ width: '100%', justifyContent: 'center', gap: '8px' }}
                  >
                    <Download size={18} />
                    <span>{tx(c('تحميل مثبت ويندوز (.exe - 2.5 MB)', 'Download Windows (.exe - 2.5 MB)'), locale)}</span>
                  </a>
                  <a
                    className="btn btn-secondary"
                    href={windowsMsiUrl}
                    download="fihrist.msi"
                    data-testid="button-download-windows-msi"
                    style={{ width: '100%', justifyContent: 'center', gap: '8px', fontSize: '0.85rem' }}
                  >
                    <span>{tx(c('تحميل حزمة الشركات (.msi - 3.5 MB)', 'Enterprise MSI (.msi - 3.5 MB)'), locale)}</span>
                  </a>
                </div>
              </article>
            </Reveal>

            {/* macOS Card */}
            <Reveal className="reveal-cell">
              <article className="feature-card" style={{ height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: '32px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <span className="icon-tile"><Laptop size={24} /></span>
                    <span className="demo-badge" style={{ background: 'rgba(59, 130, 246, 0.15)', color: '#3b82f6' }}>
                      macOS 11+
                    </span>
                  </div>
                  <h3 style={{ marginTop: '20px', fontSize: '1.35rem' }}>{tx(c('تطبيق ديسكتوب ماك', 'macOS POS Desktop'), locale)}</h3>
                  <p style={{ marginTop: '8px', lineHeight: 1.6, opacity: 0.85 }}>
                    {tx(
                      c(
                        'نسخة أصلية صُممت لأجهزة Mac (بمعالجات Apple Silicon M1/M2/M3/M4 وأجهزة Intel). واجهة سلسة وعالية الدقة متوافقة مع شاشات Retina.',
                        'Native edition for macOS (Apple Silicon M1-M4 & Intel). Sleek, high-resolution interface optimized for Retina displays and fast checkout.'
                      ),
                      locale
                    )}
                  </p>
                  <ul style={{ listStyle: 'none', padding: 0, margin: '20px 0', fontSize: '0.88rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('حجم الحزمة: 4.4 ميجابايت فقط', 'Package size: Only 4.4 MB'), locale)}</span>
                    </li>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('تكامل مع طابعات الإيصالات وقارئات USB', 'Thermal printers & USB scanners support'), locale)}</span>
                    </li>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('تزامن لحظي ومحمي مع السيرفر', 'Secure real-time server synchronization'), locale)}</span>
                    </li>
                  </ul>
                </div>
                <div style={{ marginTop: '20px' }}>
                  <a
                    className="btn btn-primary"
                    href={macOsDmgUrl}
                    download="fihrist-macos.dmg"
                    data-testid="button-download-macos-dmg"
                    style={{ width: '100%', justifyContent: 'center', gap: '8px' }}
                  >
                    <Download size={18} />
                    <span>{tx(c('تحميل حزمة ماك (.dmg - 4.4 MB)', 'Download macOS (.dmg - 4.4 MB)'), locale)}</span>
                  </a>
                </div>
              </article>
            </Reveal>

            {/* Android Card */}
            <Reveal className="reveal-cell">
              <article className="feature-card" style={{ height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', padding: '32px' }}>
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <span className="icon-tile"><Smartphone size={24} /></span>
                    <span className="demo-badge" style={{ background: 'rgba(234, 88, 12, 0.15)', color: '#ea580c' }}>
                      Android 6.0+
                    </span>
                  </div>
                  <h3 style={{ marginTop: '20px', fontSize: '1.35rem' }}>{tx(c('تطبيق أندرويد للموبايل والـ POS', 'Android Mobile & POS'), locale)}</h3>
                  <p style={{ marginTop: '8px', lineHeight: 1.6, opacity: 0.85 }}>
                    {tx(
                      c(
                        'نظام كاشير ومبيعات ومخزون متكامل في جيبك. بيع أوفلاين دون اتصال، مسح باركود ذكي بكاميرا الهاتف، وطباعة إيصالات حرارية بالبلوتوث.',
                        'Complete sales and inventory system in your pocket. Offline selling, camera barcode scanning, and portable Bluetooth receipt printing.'
                      ),
                      locale
                    )}
                  </p>
                  <ul style={{ listStyle: 'none', padding: 0, margin: '20px 0', fontSize: '0.88rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('حفظ العمليات أوفلاين والمزامنة التلقائية', 'Offline queue with automatic sync'), locale)}</span>
                    </li>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('جرد واستلام البضائع بالباركود', 'Mobile stock audits & goods receiving'), locale)}</span>
                    </li>
                    <li style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <CheckCircle2 size={16} color="var(--primary, #059669)" />
                      <span>{tx(c('متوافق مع أجهزة نقاط البيع المحمولة (Smart POS)', 'Handheld Smart POS terminals ready'), locale)}</span>
                    </li>
                  </ul>
                </div>
                <div style={{ marginTop: '20px' }}>
                  <a
                    className="btn btn-primary"
                    href={apkDownloadUrl}
                    download="fihrist-mobile.apk"
                    data-testid="button-download-apk"
                    style={{ width: '100%', justifyContent: 'center', gap: '8px' }}
                  >
                    <Download size={18} />
                    <span>{tx(c('تحميل ملف APK المباشر (75.7 MB)', 'Download Direct APK (75.7 MB)'), locale)}</span>
                  </a>
                </div>
              </article>
            </Reveal>
          </div>
        </div>
      </section>

      {/* Desktop Hardware Interfacing Section */}
      <section className="section" style={{ background: 'rgba(125,125,125,0.02)' }}>
        <div className="container">
          <SectionIntro
            kicker={tx(c('عتاد نقاط البيع المتكامل', 'POS Hardware Integration'), locale)}
            title={tx(c('توافق شامل مع أجهزة الكاشير والملحقات التجارية.', 'Comprehensive compatibility with commercial POS hardware.'), locale)}
            body={tx(
              c(
                'تم تصميم تطبيق الديسكتوب ليتصل مباشرة وبدون برامج وسيطة مع كافة ملحقات نقاط البيع القياسية في المتاجر والسوبرماركت والمطاعم.',
                'The desktop app communicates directly without middleware to all standard retail POS peripherals.'
              ),
              locale
            )}
          />
          <div className="feature-grid">
            {hardwareSupported.map(({ icon: Icon, title, desc }) => (
              <Reveal className="reveal-cell" key={title.ar}>
                <article className="feature-card">
                  <span className="icon-tile"><Icon size={20} /></span>
                  <h3>{tx(title, locale)}</h3>
                  <p>{tx(desc, locale)}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* Features Grid: Desktop & Mobile Highlights */}
      <section className="section section-features">
        <div className="container">
          <SectionIntro
            kicker={tx(c('المميزات الشاملة', 'Core Features'), locale)}
            title={tx(c('قوة في الأداء، سهولة للكاشير، وتحكم كامل لصاحب المتجر.', 'Power for the owner, blazing speed for the cashier.'), locale)}
            body={tx(
              c(
                'استفد من مزايا نظام الديسكتوب داخل نقطة البيع الرئيسية، وتطبيق الموبايل أثناء الجرد والتوصيل والمعارض الخارجية.',
                'Combine the power of the desktop app at the checkout counter with the mobile app on the retail floor.'
              ),
              locale
            )}
          />

          <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Monitor size={22} color="var(--primary, #059669)" />
            <span>{tx(c('مميزات تطبيق الديسكتوب (Windows & macOS)', 'Desktop POS Features (Windows & macOS)'), locale)}</span>
          </h3>
          <div className="feature-grid" style={{ marginBottom: '48px' }}>
            {desktopFeatures.map(({ icon: Icon, title, body }) => (
              <Reveal className="reveal-cell" key={title.ar}>
                <article className="feature-card">
                  <span className="icon-tile"><Icon size={20} /></span>
                  <h3>{tx(title, locale)}</h3>
                  <p>{tx(body, locale)}</p>
                </article>
              </Reveal>
            ))}
          </div>

          <h3 style={{ marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Smartphone size={22} color="var(--primary, #059669)" />
            <span>{tx(c('مميزات تطبيق الموبايل (Android)', 'Mobile POS Features (Android)'), locale)}</span>
          </h3>
          <div className="feature-grid">
            {mobileFeatures.map(({ icon: Icon, title, body }) => (
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
            kicker={tx(c('بيانات الملفات والتشغيل', 'Specifications'), locale)}
            title={tx(c('المواصفات التقنية للتطبيقات.', 'Technical Specifications.'), locale)}
            body={tx(
              c(
                'تفاصيل حزم التثبيت ومتطلبات التوافق مع أنظمة التشغيل ومواصفات العتاد.',
                'Package specifications and compatibility requirements across platforms.'
              ),
              locale
            )}
          />

          {/* Platform Tab Buttons */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', marginBottom: '32px' }}>
            <button
              type="button"
              className={`btn ${activePlatform === 'all' || activePlatform === 'desktop' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActivePlatform('desktop')}
              style={{ fontSize: '0.9rem', padding: '8px 20px', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <Monitor size={16} />
              <span>{tx(c('مواصفات الديسكتوب (Windows & Mac)', 'Desktop Specs (Windows & Mac)'), locale)}</span>
            </button>
            <button
              type="button"
              className={`btn ${activePlatform === 'mobile' ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setActivePlatform('mobile')}
              style={{ fontSize: '0.9rem', padding: '8px 20px', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <Smartphone size={16} />
              <span>{tx(c('مواصفات الموبايل (Android)', 'Mobile Specs (Android)'), locale)}</span>
            </button>
          </div>

          <Reveal>
            <div
              style={{
                maxWidth: '780px',
                margin: '0 auto',
                background: 'var(--card-bg, rgba(255,255,255,0.05))',
                borderRadius: '12px',
                border: '1px solid rgba(125,125,125,0.2)',
                overflow: 'hidden',
              }}
            >
              {(activePlatform === 'mobile' ? mobileSpecs : desktopSpecs).map((item, idx, arr) => (
                <div
                  key={item.label.en}
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    padding: '14px 20px',
                    borderBottom: idx === arr.length - 1 ? 'none' : '1px solid rgba(125,125,125,0.15)',
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
            title={tx(c('خطوات سهلة وسريعة لبدء البيع فوراً.', 'Simple steps to start selling in minutes.'), locale)}
            body={tx(
              c(
                'اختر جهازك واتبع الخطوات البسيطة لتثبيت المنظومة وربطها بمتجرك:',
                'Follow these simple steps to install the system on your chosen device:'
              ),
              locale
            )}
          />

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px', marginTop: '32px' }}>
            {/* Windows Steps */}
            <div className="principle-card" style={{ padding: '24px' }}>
              <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <Monitor size={18} color="var(--primary, #059669)" />
                <span>{tx(c('تثبيت ويندوز (Windows)', 'Windows Installation'), locale)}</span>
              </h4>
              <ol style={{ paddingInlineStart: '20px', margin: 0, display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.9rem', lineHeight: 1.5 }}>
                <li>{tx(c('حمّل ملف fihrist-setup.exe (أو fihrist.msi للشركات).', 'Download fihrist-setup.exe (or fihrist.msi for enterprise).'), locale)}</li>
                <li>{tx(c('انقر مرتين على الملف واضغط "تثبيت" (Install).', 'Double-click the installer and follow the setup wizard.'), locale)}</li>
                <li>{tx(c('افتح التطبيق وسجّل الدخول بحساب كاشير متجرك للبدء في البيع الفوري.', 'Open the app, sign in with your cashier credentials, and start selling.'), locale)}</li>
              </ol>
            </div>

            {/* macOS Steps */}
            <div className="principle-card" style={{ padding: '24px' }}>
              <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <Laptop size={18} color="#3b82f6" />
                <span>{tx(c('تثبيت ماك (macOS)', 'macOS Installation'), locale)}</span>
              </h4>
              <ol style={{ paddingInlineStart: '20px', margin: 0, display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.9rem', lineHeight: 1.5 }}>
                <li>{tx(c('حمّل حزمة fihrist-macos.dmg.', 'Download the fihrist-macos.dmg package.'), locale)}</li>
                <li>{tx(c('افتح ملف DMG واسحب أيقونة Fihrist إلى مجلد التطبيقات (Applications).', 'Open the DMG and drag Fihrist to your Applications folder.'), locale)}</li>
                <li>{tx(c('شغّل التطبيق وسجّل الدخول للوصول إلى كاشير المتجر.', 'Launch the app and log in to access the store cashier.'), locale)}</li>
              </ol>
            </div>

            {/* Android Steps */}
            <div className="principle-card" style={{ padding: '24px' }}>
              <h4 style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                <Smartphone size={18} color="#ea580c" />
                <span>{tx(c('تثبيت أندرويد (Android APK)', 'Android APK Installation'), locale)}</span>
              </h4>
              <ol style={{ paddingInlineStart: '20px', margin: 0, display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.9rem', lineHeight: 1.5 }}>
                <li>{tx(c('حمّل ملف fihrist-mobile.apk مباشرة على هاتفك أو جهاز الـ POS.', 'Download fihrist-mobile.apk directly to your phone or POS.'), locale)}</li>
                <li>{tx(c('افتح الملف وفعّل "السماح بالتثبيت من مصادر غير معروفة" إذا طُلب منك.', 'Open the APK and enable "Install from Unknown Sources" if prompted.'), locale)}</li>
                <li>{tx(c('اضغط "تثبيت" وافتح التطبيق للبيع أوفلاين وإدارة المخزون.', 'Tap Install and open the app to sell offline and audit inventory.'), locale)}</li>
              </ol>
            </div>
          </div>

          <div style={{ textAlign: 'center', marginTop: '48px', display: 'flex', justifyContent: 'center', gap: '16px', flexWrap: 'wrap' }}>
            <a
              className="btn btn-primary"
              href={windowsExeUrl}
              download="fihrist-setup.exe"
              style={{ padding: '14px 28px', fontSize: '1rem', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <Monitor size={18} />
              <span>{tx(c('تحميل لويندوز (2.5 MB)', 'Download for Windows (2.5 MB)'), locale)}</span>
            </a>

            <a
              className="btn btn-secondary"
              href={macOsDmgUrl}
              download="fihrist-macos.dmg"
              style={{ padding: '14px 28px', fontSize: '1rem', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <Laptop size={18} />
              <span>{tx(c('تحميل لماك (4.4 MB)', 'Download for macOS (4.4 MB)'), locale)}</span>
            </a>

            <a
              className="btn btn-secondary"
              href={apkDownloadUrl}
              download="fihrist-mobile.apk"
              style={{ padding: '14px 28px', fontSize: '1rem', display: 'inline-flex', alignItems: 'center', gap: '8px' }}
            >
              <Smartphone size={18} />
              <span>{tx(c('تحميل لأندرويد (75.7 MB)', 'Download for Android (75.7 MB)'), locale)}</span>
            </a>
          </div>
        </div>
      </section>
    </>
  )
}
