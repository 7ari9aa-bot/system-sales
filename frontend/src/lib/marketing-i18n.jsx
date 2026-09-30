import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

/**
 * Constant Frame i18n
 * - Layout stays LTR-anchored at all times (dir="ltr" on <html>).
 * - Only text content swaps; containers/positions never move.
 * - Technical terms (FIHRIST, AI, API, VAT, SKU, ID) are stored once in
 *   English and reused in both locales via the `term` helper.
 * - Arabic text runs render correctly inside their fixed containers through
 *   `dir="auto"` on text nodes (see <T> component).
 */

export const LOCALES = ['ar', 'en'];
export const STORAGE_KEY = 'fihrist.locale';

const dictionary = {
  // ---- Header / nav ----
  'nav.platform': { ar: 'المنصة', en: 'Platform' },
  'nav.conversations': { ar: 'المحادثات', en: 'Conversations' },
  'nav.assistant': { ar: 'المساعد', en: 'Assistant' },
  'nav.pricing': { ar: 'الأسعار', en: 'Pricing' },
  'nav.security': { ar: 'الأمان', en: 'Security' },
  'nav.contact': { ar: 'تواصل مع المبيعات', en: 'Contact sales' },
  'nav.signin': { ar: 'تسجيل الدخول', en: 'Sign in' },
  'nav.start': { ar: 'ابدأ الآن', en: 'Start now' },
  'nav.openapp': { ar: 'فتح التطبيق', en: 'Open app' },
  'nav.search': { ar: 'بحث', en: 'Search' },
  'nav.searchPlaceholder': { ar: 'ابحث في FIHRIST…', en: 'Search FIHRIST…' },
  'nav.toggleTheme': { ar: 'تبديل الوضع', en: 'Toggle theme' },
  'nav.toggleLang': { ar: 'تغيير اللغة', en: 'Switch language' },

  // ---- Hero ----
  'hero.eyebrow': { ar: 'نظام تشغيل المبيعات', en: 'Sales operating system' },
  'hero.title.1': { ar: 'مبيعات بلا', en: 'Sales without' },
  'hero.title.2': { ar: 'من أول محادثة إلى الإغلاق.', en: 'from first conversation to close.' },
  'hero.lede': {
    ar: 'FIHRIST يربط المحادثات بالعملاء والطلبات والمتابعة في مصدر واحد موثوق — حتى لا تفقد فرقتك الخطوة التالية.',
    en: 'FIHRIST connects conversations to customers, orders, and follow-ups in one trusted source — so your team never loses the next action.',
  },
  'hero.note': { ar: 'بدون بطاقة ائتمان · إعداد في دقائق', en: 'No credit card · Setup in minutes' },
  'hero.kinetic.1': { ar: 'فوضى.', en: 'chaos.' },
  'hero.kinetic.2': { ar: 'فجوات.', en: 'gaps.' },
  'hero.kinetic.3': { ar: 'تخمين.', en: 'guesswork.' },

  // ---- Trust strip ----
  'trust.label': {
    ar: 'مصمم لفرق المبيعات التي لا تريد فقدان أي فرصة',
    en: 'For sales teams that refuse to lose the next action',
  },
  'trust.badge': { ar: 'محتوى تجريبي', en: 'Demo content' },

  // ---- Workflow ----
  'workflow.eyebrow': { ar: 'كيف يعمل', en: 'How it works' },
  'workflow.title': { ar: 'خمس خطوات، نتيجة واحدة', en: 'Five steps, one outcome' },
  'workflow.lede': {
    ar: 'تدفق واحد من الإشارة إلى الإغلاق، مرئي وقابل للمراجعة في كل خطوة.',
    en: 'A single flow from signal to close, visible and reviewable at every step.',
  },
  'workflow.s1': { ar: 'التقط الإشارة', en: 'Capture the signal' },
  'workflow.s1.d': { ar: 'رسالة تصل من أي قناة، بلا نسخ ولصق.', en: 'A message arrives from any channel — no copy-paste.' },
  'workflow.s2': { ar: 'افهم النية', en: 'Understand intent' },
  'workflow.s2.d': { ar: 'يفهم النظام: استفسار؟ طلب؟ شكوى؟', en: 'The system reads intent: question, order, complaint?' },
  'workflow.s3': { ar: 'عيّن المسؤول', en: 'Assign ownership' },
  'workflow.s3.d': { ar: 'لكل محادثة صاحب وموعد استجابة.', en: 'Every thread gets an owner and response window.' },
  'workflow.s4': { ar: 'تابع في الوقت المناسب', en: 'Follow up on time' },
  'workflow.s4.d': { ar: 'تذكير وقالب رد قبل أن يبرد العميل.', en: 'A reminder and reply draft before the lead goes cold.' },
  'workflow.s5': { ar: 'أغلق وتعلّم', en: 'Close and learn' },
  'workflow.s5.d': { ar: 'النتيجة تتحول إلى بيانات تحسّن ما بعدها.', en: 'The outcome becomes data for the next round.' },

  // ---- Features ----
  'features.eyebrow': { ar: 'المنصة', en: 'The platform' },
  'features.title': { ar: 'كل شيء في مكانه، بلا فوضى', en: 'Everything in its place, no chaos' },
  'features.lede': {
    ar: 'أربع ركائز تربط المحادثة بالنتيجة، بمرجعية واحدة للبيانات.',
    en: 'Four pillars connect the conversation to the outcome, with one data reference.',
  },
  'features.f1.t': { ar: 'صندوق وارد موحد', en: 'Unified inbox' },
  'features.f1.d': { ar: 'كل قناة في صندوق واحد، مع ملكية واضحة وحالة لكل محادثة.', en: 'Every channel in one inbox, with clear ownership and status per thread.' },
  'features.f2.t': { ar: 'سياق العميل', en: 'Customer context' },
  'features.f2.d': { ar: 'آخر طلب، المالك، ومصدر البيانات — في مكان واحد موثوق.', en: 'Last order, owner, and data source — in one trusted place.' },
  'features.f3.t': { ar: 'مساعد AI قابل للمراجعة', en: 'Reviewable AI assistant' },
  'features.f3.d': { ar: 'يقترح الخطوة التالية، وفريقك يراجع ويعتمد قبل التنفيذ.', en: 'Suggests the next step; your team reviews and approves before it runs.' },
  'features.f4.t': { ar: 'أتمتة مفهومة', en: 'Automation you can read' },
  'features.f4.d': { ar: 'قواعد واضحة قابلة للتعديل، لا صندوق أسود.', en: 'Clear, editable rules — no black box.' },
  'features.link': { ar: 'استكشف', en: 'Explore' },

  // ---- Proof ----
  'proof.eyebrow': { ar: 'النتيجة', en: 'The outcome' },
  'proof.title': { ar: 'بيانات تتحول إلى قرارات', en: 'Data that becomes decisions' },
  'proof.lede': {
    ar: 'كل محادثة تترك أثراً منظماً يحسّن الجولة القادمة من المبيعات.',
    en: 'Every conversation leaves a structured trace that improves the next sales round.',
  },
  'proof.stat1': { ar: 'استجابة أسرع', en: 'Faster response' },
  'proof.stat1.v': { ar: '−63%', en: '−63%' },
  'proof.stat2': { ar: 'متابعة في الوقت', en: 'On-time follow-up' },
  'proof.stat2.v': { ar: '+41%', en: '+41%' },
  'proof.stat3': { ar: 'وضوح السياق', en: 'Context clarity' },
  'proof.stat3.v': { ar: '86%', en: '86%' },
  'proof.cta': { ar: 'تحدث مع خبير مبيعات', en: 'Talk to a sales expert' },

  // ---- CTA ----
  'cta.title': { ar: 'ابدأ بأول محادثة اليوم', en: 'Start with your first conversation today' },
  'cta.lede': {
    ar: 'أنشئ مساحة عمل في دقائق، وادمج قنواتك دون كود.',
    en: 'Spin up a workspace in minutes, connect your channels with no code.',
  },
  'cta.primary': { ar: 'ابدأ الآن', en: 'Start now' },
  'cta.secondary': { ar: 'شاهد العرض', en: 'See the demo' },

  // ---- Footer ----
  'footer.product': { ar: 'المنصة', en: 'Product' },
  'footer.company': { ar: 'الشركة', en: 'Company' },
  'footer.legal': { ar: 'قانوني', en: 'Legal' },
  'footer.privacy': { ar: 'الخصوصية', en: 'Privacy' },
  'footer.terms': { ar: 'الشروط', en: 'Terms' },
  'footer.security': { ar: 'الأمان', en: 'Security' },
  'footer.about': { ar: 'من نحن', en: 'About' },
  'footer.contact': { ar: 'تواصل', en: 'Contact' },
  'footer.rights': { ar: 'جميع الحقوق محفوظة.', en: 'All rights reserved.' },

  // ---- Product page ----
  'product.eyebrow': { ar: 'المنصة', en: 'Platform' },
  'product.title': { ar: 'هيكل ثابت، بيانات سائلة', en: 'A constant frame, liquid data' },
  'product.lede': {
    ar: 'FIHRIST Sales OS يحافظ على هيكل العمل ثابتاً بينما تتدفق البيانات عبر الركائز الأربع.',
    en: 'FIHRIST Sales OS keeps the work structure constant while data flows across the four pillars.',
  },

  // ---- Pricing page ----
  'pricing.eyebrow': { ar: 'الأسعار', en: 'Pricing' },
  'pricing.title': { ar: 'خطط واضحة، بلا مفاجآت', en: 'Clear plans, no surprises' },
  'pricing.lede': { ar: 'اختر الخطة المناسبة لفريقك، ووسّعها حين تحتاج.', en: 'Pick the plan that fits your team, scale when you need.' },
  'pricing.monthly': { ar: 'شهري', en: 'Monthly' },
  'pricing.yearly': { ar: 'سنوي', en: 'Yearly' },
  'pricing.save': { ar: 'وفّر 20%', en: 'Save 20%' },
  'pricing.starter': { ar: 'المبتدئ', en: 'Starter' },
  'pricing.starter.d': { ar: 'للفريق الصغير الذي يبدأ.', en: 'For the small team starting out.' },
  'pricing.growth': { ar: 'النمو', en: 'Growth' },
  'pricing.growth.d': { ar: 'للفرق المتنامية ذات القنوات المتعددة.', en: 'For growing teams with multiple channels.' },
  'pricing.scale': { ar: 'المؤسسة', en: 'Scale' },
  'pricing.scale.d': { ar: 'للعمليات واسعة النطاق والمتطلبات المخصصة.', en: 'For large-scale operations and custom needs.' },
  'pricing.perMonth': { ar: '/ شهرياً', en: '/ mo' },
  'pricing.cta': { ar: 'اختر الخطة', en: 'Choose plan' },
  'pricing.popular': { ar: 'الأكثر شيوعاً', en: 'Most popular' },
  'pricing.feat.inbox': { ar: 'صندوق وارد موحد', en: 'Unified inbox' },
  'pricing.feat.context': { ar: 'سياق العميل', en: 'Customer context' },
  'pricing.feat.assistant': { ar: 'مساعد AI', en: 'AI assistant' },
  'pricing.feat.automation': { ar: 'أتمتة', en: 'Automation' },
  'pricing.feat.sso': { ar: 'دخول موحد SSO', en: 'SSO' },
  'pricing.feat.api': { ar: 'وصول API', en: 'API access' },
  'pricing.feat.dedicated': { ar: 'مدير حساب مخصص', en: 'Dedicated manager' },
  'pricing.feat.audit': { ar: 'سجل تدقيق', en: 'Audit log' },

  // ---- Security page ----
  'security.eyebrow': { ar: 'الأمان', en: 'Security' },
  'security.title': { ar: 'ثقة يمكن مراجعتها', en: 'Trust you can review' },
  'security.lede': {
    ar: 'الأمان في FIHRIST ليس وعداً — بل بنية قابلة للفحص.',
    en: 'Security in FIHRIST is not a promise — it is a reviewable architecture.',
  },
  'security.s1.t': { ar: 'تشفير في الراحة والنقل', en: 'Encryption at rest & in transit' },
  'security.s1.d': { ar: 'AES-256 للبيانات المخزنة، TLS 1.3 للنقل.', en: 'AES-256 at rest, TLS 1.3 in transit.' },
  'security.s2.t': { ar: 'تحكم في الوصول قائم على الدور', en: 'Role-based access control' },
  'security.s2.d': { ar: 'أدوار واضحة وصلاحيات دقيقة لكل مستخدم.', en: 'Clear roles and granular permissions per user.' },
  'security.s3.t': { ar: 'سجل تدقيق كامل', en: 'Full audit log' },
  'security.s3.d': { ar: 'كل إجراء موثّق وقابل للمراجعة.', en: 'Every action recorded and reviewable.' },
  'security.s4.t': { ar: 'استضافة وبيانات إقليمية', en: 'Regional hosting & data residency' },
  'security.s4.d': { ar: 'بياناتك تبقى في المنطقة التي تختارها.', en: 'Your data stays in the region you choose.' },
};

const LanguageContext = createContext(null);

export function LanguageProvider({ children }) {
  const [locale, setLocale] = useState(() => {
    if (typeof window === 'undefined') return 'ar';
    return window.localStorage.getItem(STORAGE_KEY) || 'ar';
  });

  useEffect(() => {
    window.localStorage.setItem(STORAGE_KEY, locale);
    document.documentElement.lang = locale;
    // Layout direction stays LTR — only the script changes. This is the
    // core of "The Constant Frame": positions never move between locales.
    document.documentElement.dir = 'ltr';
  }, [locale]);

  const toggle = useCallback(() => setLocale((l) => (l === 'ar' ? 'en' : 'ar')), []);

  const t = useCallback(
    (key) => {
      const entry = dictionary[key];
      if (!entry) return key;
      return entry[locale] ?? entry.en ?? key;
    },
    [locale]
  );

  const value = { locale, setLocale, toggle, t };
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error('useI18n must be used within LanguageProvider');
  return ctx;
}

/**
 * <T> renders a translated string with the correct text direction for the
 * script, while keeping its container position untouched. Arabic runs get
 * dir="auto" so they read RTL inside their fixed LTR-anchored box.
 */
export function T({ k, className = '', as: Tag = 'span' }) {
  const { t, locale } = useI18n();
  return (
    <Tag className={`fade-text ${className}`} dir={locale === 'ar' ? 'rtl' : 'ltr'} data-locale={locale}>
      {t(k)}
    </Tag>
  );
}