"use client";

/** FIHRIST public-site i18n + theme — معزول تمامًا داخل مكونات الموقع العام.
 *  - LocaleProvider: عربي افتراضي (RTL) + إنجليزي (LTR)، الحفظ في localStorage.
 *  - الاتجاه واللغة بيتطبقوا على wrapper div مش <html> — عزل كامل عن باقي التطبيق.
 *  - ThemeProvider: فاتح افتراضي + داكن، مع تفضيل النظام عند أول زيارة. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export type Locale = "ar" | "en";
export type Theme = "light" | "dark";

/* ------------------------------------------------------------------ */
/* القاموس                                                             */
/* ------------------------------------------------------------------ */

const ar = {
  brand: "FIHRIST",
  brandTag: "فهرست",
  nav: {
    product: "المنتج",
    context: "سياق العمل",
    inbox: "المحادثات",
    ai: "الذكاء الاصطناعي",
    automation: "الأتمتة",
    pricing: "الأسعار",
    security: "الأمان",
    login: "تسجيل الدخول",
    start: "ابدأ الآن",
    openApp: "افتح التطبيق",
    toDark: "الوضع الداكن",
    toLight: "الوضع الفاتح",
    lang: "English",
    menu: "القائمة",
  },
  hero: {
    eyebrow: "منصة تشغيل الأعمال بالمحادثة",
    h1: "نظام واحد متصل لشركتك.",
    sub: "العملاء، المحادثات، التجارة، الأتمتة، الذكاء الاصطناعي والتحليلات — كلها متصلة عبر سياق عمل واحد.",
    start: "ابدأ الآن",
    explore: "استعرض المنتج",
    demo: "عرض تفاعلي — الردود محاكاة بدون أي بيانات حقيقية",
  },
  chat: {
    title: "مساعد FIHRIST",
    status: "وضع العرض التجريبي",
    greeting: "أهلًا بك 👋 أنا مساعد FIHRIST التجريبي. اسألني أي حاجة عن المنصة — أو جرب أحد الاقتراحات تحت.",
    ph: "اكتب رسالتك…",
    send: "إرسال",
    thinking: "بيكتب…",
    toolsTitle: "قدرات المساعد داخل النظام",
    tools: ["فهم نية العميل", "تنفيذ إجراءات مسموحة", "ملخص المحادثة", "اقتراح الرد التالي", "تصعيد للفريق"],
    s1: "إيه هو FIHRIST؟",
    s2: "إزاي الأتمتة بتشتغل؟",
    s3: "إيه بروتوكولات الأمان؟",
    r_intro: "FIHRIST نظام تشغيل متكامل لشركتك: المحادثات من كل القنوات، العملاء، الطلبات، الأتمتة والذكاء الاصطناعي — كلها في سياق واحد متصل بدل أدوات مفككة.",
    r_pricing: "دلوقتي الوصول المبكر مجاني لكل الخطط. عندنا 3 طبقات (البداية / النمو / التوسع) بتفرق في حجم الفريق والقنوات وحدود الـAI — التفاصيل في قسم الأسعار تحت.",
    r_automation: "الأتمتة بتشتغل بمسار واضح: حدث بيبدأ المسار → شرط → منطق أو AI → تحقق → موافقة عند الحاجة → تنفيذ → مراجعة وتدقيق. مثال: عميل عالي القيمة يبعت رسالة ومحدش يرد خلال 10 دقايق — المسار يصنّف الرسالة وي notify الفريق ويصعّد لو محتاج.",
    r_security: "الأمان مبني من الأول: عزل بيانات لكل مستأجر على مستوى قاعدة البيانات (RLS)، صلاحيات وأدوار، جلسات مصادقة آمنة، سجلات تدقيق كاملة، والذكاء الاصطناعي بينفذ عبر أدوات بصلاحيات محددة مسبقًا — بدون أي وصول مباشر لقاعدة البيانات.",
    r_channels: "شات الموقع شغّال حاليًا، وواتساب وتليجرام وإنستجرام وماسنجر في خطة التكامل القادمة. كل القنوات بتوصل لنفس الـInbox ونفس سياق العميل.",
    r_fallback: "سؤال ممتاز. باختصار: FIHRIST بيجمع المحادثات والعملاء والطلبات والأتمتة والـAI في نظام واحد — جرب تسألني عن الأسعار أو الأتمتة أو الأمان لتفاصيل أكتر.",
  },
  signals: {
    title: "اعرف اللي محتاج انتباهك.",
    sub: "النظام بيرتّب أولوياتك — مش مجرد تقارير.",
    demo: "مساحة تجريبية",
    note: "داخل التطبيق، كل إشارة بتفتح الشاشة المناسبة مع السياق الكامل — دي معاينة مبسطة.",
    items: [
      { label: "محادثات جديدة", detail: "واردة من القنوات المتصلة · محتاجة أول رد", badge: "AI بيعالج" },
      { label: "طلبات تحتاج انتباه", detail: "مراجعة يدوية أو دفع مكتمل جزئيًا", badge: "بانر المراجعة" },
      { label: "أتمتة فشلت", detail: "فشل نداء مزود خارجي · استُنفدت المحاولات", badge: "قابلة لإعادة التشغيل" },
      { label: "عملاء محتملون عالي القيمة", detail: "من آخر الحملات · محتاجة متابعة", badge: "توزيع تلقائي" },
      { label: "SLA في خطر", detail: "محادثة قربت من حد زمن الرد", badge: "تحويل بشري" },
    ],
    counts: [12, 4, 2, 3, 1],
    element: "عنصر",
  },
  context: {
    title: "شركتك مش المفروض تعيش في أدوات مفككة.",
    sub: "مش CRM قاعدة بيانات لوحدها + Inbox قاعدة بيانات لوحدها + AI لوحده. سياق واحد بيظهر في كل مكان — نفس العميل بنفس التاريخ والقيمة في كل شاشة.",
    hub: "العميل — سياق واحد",
    nodes: ["محادثة", "طلب", "تسويق", "دفع", "أتمتة", "AI", "تحليلات"],
  },
  c360: {
    title: "كل عميل بيجي معاه السياق الكامل.",
    sub: "سجل عميل حقيقي من النظام — المحادثة والطلب والدفع والتاريخ في مكان واحد.",
    demo: "بيانات تجريبية",
    name: "عميل مسجّل",
    vip: "VIP",
    active: "نشط",
    revenue: "الإيرادات",
    orders: "الطلبات",
    last: "آخر نشاط",
    tabs: ["نظرة عامة", "الخط الزمني", "المحادثات", "الطلبات", "المدفوعات", "التسويق", "المهام", "AI"],
    info: "معلومات العميل",
    phone: "الهاتف",
    email: "البريد",
    tags: "الوسوم",
    owner: "المسؤول",
    work: "سياق العمل",
    openOrders: "طلبات مفتوحة",
    payments: "المدفوعات",
    issues: "مشاكل مفتوحة",
    channel: "قناة مفضلة",
    aiCtx: "سياق AI",
    intent: "النية",
    value: "قيمة العميل",
    risk: "الخطر",
    next: "الإجراء التالي",
    masked: "••••  محمي",
    timelineTitle: "خط زمني مترابط — مش سجلات متفرقة",
    timeline: [
      ["محادثة", "استفسار وارد من قناة تواصل"],
      ["عميل محتمل", "اتسجل من حملة تسويقية"],
      ["طلب", "طلب جديد اتنشأ ودفع اتأكد"],
      ["دفعة", "اتحصّلت واتسجلت تلقائيًا"],
      ["حملة", "كود خصم للعميل الدائم"],
      ["أتمتة", "إشعار الشحن تلقائي"],
      ["تفاعل AI", "ملخص + إجراء مقترح"],
    ],
  },
  inbox: {
    title: "كل محادثة بتوصل ومعاها السياق.",
    sub: "الموظف مش بيخرج من المحادثة عشان يدور على العميل أو الطلب أو الدفع — كل ده ظاهر جنب شغله.",
    live: "شغّال",
    soon: "قريبًا",
    channels: ["شات الموقع", "واتساب", "إنستجرام", "ماسنجر", "تليجرام"],
    demo: "بيانات تجريبية",
    list: "المحادثات",
    thread: "المحادثة",
    ctx: "سياق العميل",
    convos: [
      ["محادثة نشطة", "شات الموقع · الآن"],
      ["محادثة جديدة", "تليجرام · منذ 12 د"],
      ["محادثة محلولة", "شات الموقع · أمس"],
    ],
    m1: "هل الطلب هيتوصل قبل الجمعة؟",
    m2: "أيوه، مجدول يوم الخميس — وابعتلك التتبع أول ما يتحرك.",
    m3: "تمام، شكرًا على المتابعة.",
    agent: "رد الفريق",
    suggestTag: "مسودة AI",
    suggest: "«أكيد — هحدّث الشحنة فورًا وأبعتلك التأكيد.»",
    newCustomer: "عميل جديد",
    orders: "الطلبات",
    value: "القيمة",
    intent: "النية",
    next: "الإجراء التالي",
    intentVal: "استفسار عن شحنة",
    nextVal: "تأكيد موعد التوصيل",
  },
  ai: {
    title: "ذكاء اصطناعي بيشتغل — جوه قواعدك.",
    sub: "مش نافذة شات. عامل جوه النظام: بيشوف السياق المسموح له بس، وبينفذ عبر أدوات بصلاحيات محددة، وكل خطوة بتتسجل.",
    steps: ["يفهم", "يجيب السياق", "يستنتج", "يستخدم أدوات", "يتحقق", "ينفذ", "يراجع", "يحوّل للبشر"],
    flow: ["محادثة", "سياق العميل", "AI", "أداة", "طلب", "أتمتة"],
    chips: ["صلاحيات وأدوار محددة", "سياسات وأدوات معتمدة", "موافقات بشرية للخطوات الحساسة", "حدود تكلفة لكل مستأجر", "تدقيق كامل لكل تشغيل", "مصادر معرفة مجمّعة بالصلاحيات"],
  },
  handoff: {
    title: "الـAI بيشتغل مع فريقك، مش براه.",
    sub: "لما الحالة تعقّد، التحويل بيحصل بسطر واحد — والسياق الكامل بيوصل مع الموظف. بدون إعادة من الصفر.",
    steps: [
      ["AI", "الـAI بيعالج المحادثة", "فهم النية · تنفيذ مسموح · ردود مسودة"],
      ["اكتشاف", "حالة معقدة تكتشف", "شكوى · استرجاع · عميل محبط"],
      ["تحويل", "تحويل لحد من الفريق", "حسب التخصص والعبء"],
      ["إنسان", "الموظف يستلم جاهز", "الملخص + الطلب + الدفع + التاريخ"],
    ],
    chips: ["حالة الـAI ظاهرة دايمًا", "ملكية بشرية واضحة", "موافقة على الخطوات الحساسة", "تدقيق لكل انتقال"],
  },
  automation: {
    title: "اوصفها. ابنِها. شغّلها.",
    sub: "أتمتة تشغيلية حقيقية — بتنفذ إجراءات عمل جوه النظام، مش إشعارات بس.",
    chain: ["حدث", "شرط", "AI / منطق", "أداة", "تحقق", "موافقة", "تنفيذ", "مراجعة", "تدقيق"],
    example: "مثال: مسار العملاء عالي القيمة",
    steps: ["عميل عالي القيمة يبعت رسالة", "تعريف العميل من السياق", "فحص قيمة العميل", "انتظار 10 دقايق", "مفيش رد بشري؟", "الـAI يصنّف الرسالة", "إشعار الفريق", "تصعيد لو مفيش استجابة"],
    caps: ["سجل إصدارات", "تشغيل تجريبي", "سجل تنفيذ", "إعادة تشغيل", "استرجاع بعد الفشل"],
  },
  analytics: {
    title: "اعرف اللي بيحصل. واعرف اللي محتاج فعل.",
    sub: "مقياس → استنتاج → السجلات اللي وراه → إجراء. مش رسومات على الفاضي.",
    demo: "بيانات تجريبية",
    metrics: [
      ["الإيرادات", "+12%", "up"],
      ["الطلبات", "+8%", "up"],
      ["التحويل", "−3%", "down"],
      ["العملاء", "+6%", "up"],
      ["نشاط AI", "↑", "up"],
      ["العمليات", "!", "alert"],
    ],
    insightTag: "استنتاج",
    insight: ["نسبة التحويل انخفضت أساسًا لدى ", "العملاء العائدين", " — بعد تغيير سياسة الشحن الأسبوع الماضي."],
    inspect: "فحص السجلات",
    act: "تعامل مع الأمر",
  },
  control: {
    title: "كل حاجة النظام بيعملها ظاهرة وقابلة للتحكم.",
    sub: "قوي، لكنه مش صندوق أسود: تراقب، تتحكم، تحقق، توافق، تراجع، تسترجع.",
    demo: "بيانات تجريبية",
    counters: [
      ["24 نشط", "وكلاء AI"],
      ["182 شغالة", "أتمتة"],
      ["7", "موافقات معلقة"],
      ["2", "مهام فاشلة"],
      ["4", "SLA في خطر"],
      ["$184", "استخدام AI"],
      ["31", "تحويلات بشرية"],
    ],
    chips: ["سياسات", "صلاحيات", "تدقيق", "أمان", "صحة النظام"],
  },
  pricing: {
    title: "خطط بتكبر مع شركتك.",
    sub: "هيكل واضح من الأول — من غير مفاجآت. الوصول المبكر مجاني حاليًا لكل الخطط.",
    badge: "وصول مبكر",
    popular: "الأكثر اختيارًا",
    cta: "ابدأ مجانًا",
    free: "مجانًا الآن",
    freeNote: "خلال فترة الوصول المبكر",
    tiers: [
      {
        name: "البداية",
        desc: "لنشأة صغيرة بتبدأ بالبيع بالمحادثة.",
        features: ["1 مستخدم", "شات الموقع", "محادثات وطلبات غير محدودة", "مساعد AI أساسي", "تقارير أساسية"],
      },
      {
        name: "النمو",
        desc: "لفرق بتكبر وعايزة أتمتة وAI أعمق.",
        features: ["حتى 10 مستخدمين", "كل قنوات التواصل عند توفرها", "أتمتة متقدمة + موافقات", "حصص AI موسعة", "تحليلات وربط حملات"],
      },
      {
        name: "التوسع",
        desc: "لعمليات متعددة الفروع والفرق الكبيرة.",
        features: ["مستخدمين غير محدودين", "مساحات ومواقع متعددة", "صلاحيات متقدمة وتدقيق", "حدود AI مخصصة", "دعم أولوية"],
      },
    ],
    note: "التسعير النهائي للإطلاق بيتحدد بناءً على فترة الوصول المبكر — المشتركين مبكرًا هيحصلوا على أفضل سعر.",
  },
  integrations: {
    title: "شغلك عايش فعلًا في أماكن كتير.",
    sub: "وصّل الأنظمة اللي بتستخدمها — النظام يستقبلها في نفس السياق الواحد.",
    flow: ["وصّل", "زامن", "نفّذ"],
    items: [
      ["Gemini", "النماذج اللغوية", "شغّال", true],
      ["n8n", "الأتمتة والتكاملات", "شغّال", true],
      ["شات الموقع", "قناة مباشرة بدون اعتماديات", "شغّال", true],
      ["WhatsApp", "القناة الأهم للتجارة", "قريبًا", false],
      ["Telegram", "محادثات ومجتمعات", "قريبًا", false],
      ["Instagram · Messenger", "التواصل الاجتماعي", "قريبًا", false],
    ],
  },
  security: {
    title: "مبني للتحكم والخصوصية والمساءلة.",
    sub: "اللي تحت دي قدرات مبنية فعلًا في النظام — بنكتب بس اللي شغال.",
    items: [
      ["عزل بيانات لكل مستأجر", "فصل على مستوى قاعدة البيانات (RLS) — بيانات كل شركة معزولة فعليًا، مش على مستوى الواجهة بس."],
      ["صلاحيات وأدوار", "كل مستخدم يشوف ويعمل اللي دوره يسمح بيه فقط — على مستوى الـAPI مش الواجهة."],
      ["مصادقة بجلسات آمنة", "توكنات قصيرة العمر + تدوير تلقائي + خروج آمن."],
      ["سجلات تدقيق", "كل تغيير مهم مسجل: مين، إمتى، وإيه اللي حصل."],
      ["صلاحيات منفصلة للـAI", "الذكاء الاصطناعي بينفذ عبر أدوات بصلاحيات محددة مسبقًا — ومفيش وصول مباشر لقاعدة البيانات."],
      ["حماية نداءات النظام", "التحقق من توقيع الـwebhooks ومنع الطلبات المكررة (idempotency)."],
    ],
  },
  final: {
    title: "سياق عمل واحد. نظام تشغيل واحد.",
    sub: "اجمع العملاء والمحادثات والتجارة والأتمتة والذكاء الاصطناعي والعمليات في نظام واحد متصل.",
    start: "ابدأ الآن",
    explore: "استعرض المنتج",
  },
  footer: {
    tag: "سياق عمل واحد. نظام تشغيل واحد.",
    product: "المنتج",
    solutions: "الحلول",
    solutionsItems: ["خدمة العملاء", "المبيعات", "التسويق", "التجارة"],
    resources: "الموارد",
    resourcesItems: ["التوثيق", "الأدلة", "المدونة", "سجل التغييرات"],
    company: "الشركة",
    system: "النظام",
    status: "الحالة",
    privacy: "الخصوصية",
    terms: "الشروط",
    rights: "© 2026 FIHRIST",
    overview: "نظرة عامة",
    features: "المميزات",
    aiF: "الذكاء الاصطناعي",
    automationF: "الأتمتة",
    analyticsF: "التحليلات",
    start: "ابدأ الآن",
    login: "تسجيل الدخول",
  },
  auth: {
    loginTitle: "أهلًا بعودتك",
    loginSub: "سجّل الدخول للمتابعة إلى مساحة عملك.",
    email: "البريد الإلكتروني",
    password: "كلمة المرور",
    submitLogin: "تسجيل الدخول",
    submittingLogin: "جارٍ تسجيل الدخول…",
    noAccount: "معندكش حساب؟",
    createAccount: "أنشئ حساب",
    signupTitle: "أنشئ حسابك",
    signupSub: "دقيقة واحدة وتكون جوه — باقي الإعداد بيتم بعد أول دخول.",
    storeName: "اسم المتجر / النشاط",
    fullName: "الاسم بالكامل",
    submitSignup: "إنشاء الحساب",
    submittingSignup: "جارٍ إنشاء الحساب…",
    haveAccount: "عندك حساب بالفعل؟",
    signin: "سجّل الدخول",
    pwHint: "8 حروف على الأقل",
    errInvalid: "البريد الإلكتروني أو كلمة المرور غير صحيحة.",
    errRate: "محاولات كثيرة جدًا. حاول مرة تانية بعد شوية.",
    errNetwork: "مش قادرين نوصل للسيرفر. اتأكد من اتصالك وحاول تاني.",
    errGeneric: "حدث خطأ غير متوقع. حاول مرة تانية.",
    errExists: "البريد ده مستخدم بالفعل. سجّل الدخول أو استخدم بريد تاني.",
    errCreate: "تعذر إنشاء الحساب. حاول مرة تانية.",
    errPw: "كلمة المرور لازم تكون 8 حروف على الأقل.",
    errAutoLogin: "الحساب اتعمل لكن تعذر الدخول التلقائي — سجّل الدخول يدويًا.",
    retry: "حاول مرة تانية",
    privacy: "الخصوصية",
    terms: "الشروط",
  },
};

const en: typeof ar = {
  brand: "FIHRIST",
  brandTag: "فهرست",
  nav: {
    product: "Product",
    context: "Business Context",
    inbox: "Conversations",
    ai: "AI",
    automation: "Automation",
    pricing: "Pricing",
    security: "Security",
    login: "Log in",
    start: "Get started",
    openApp: "Open app",
    toDark: "Dark mode",
    toLight: "Light mode",
    lang: "العربية",
    menu: "Menu",
  },
  hero: {
    eyebrow: "Conversational business operating platform",
    h1: "One connected system for your business.",
    sub: "Customers, conversations, commerce, automation, AI and analytics — connected through one business context.",
    start: "Get started",
    explore: "Explore the product",
    demo: "Interactive demo — simulated responses, no real data",
  },
  chat: {
    title: "FIHRIST Assistant",
    status: "Demo mode",
    greeting: "Welcome 👋 I'm the FIHRIST demo assistant. Ask me anything about the platform — or try a suggestion below.",
    ph: "Type your message…",
    send: "Send",
    thinking: "Typing…",
    toolsTitle: "Assistant capabilities inside the system",
    tools: ["Understand customer intent", "Run permitted actions", "Summarize conversations", "Suggest next reply", "Escalate to the team"],
    s1: "What is FIHRIST?",
    s2: "How does automation work?",
    s3: "What are the security practices?",
    r_intro: "FIHRIST is a complete operating system for your business: conversations from every channel, customers, orders, automation and AI — connected in one context instead of scattered tools.",
    r_pricing: "Early access is currently free across all plans. We have 3 tiers (Starter / Growth / Scale) that differ by team size, channels and AI limits — details in the pricing section below.",
    r_automation: "Automations follow a clear path: an event starts the run → condition → logic or AI → validation → approval when needed → action → review and audit. Example: a high-value customer messages and no one replies within 10 minutes — the run classifies the message, notifies the team and escalates if needed.",
    r_security: "Security is built in from day one: per-tenant data isolation at the database level (RLS), role-based permissions, secure session authentication, full audit logs, and AI that acts only through pre-authorized tools — with no direct database access.",
    r_channels: "Website chat is live today; WhatsApp, Telegram, Instagram and Messenger are on the integration roadmap. Every channel lands in the same inbox with the same customer context.",
    r_fallback: "Great question. In short: FIHRIST brings conversations, customers, orders, automation and AI into one system — try asking about pricing, automation or security for more detail.",
  },
  signals: {
    title: "Know what needs your attention.",
    sub: "The system prioritizes your work — not just reports.",
    demo: "Demo workspace",
    note: "Inside the app, every signal opens the right screen with full context — this is a simplified preview.",
    items: [
      { label: "New conversations", detail: "Arriving from connected channels · need a first reply", badge: "AI handling" },
      { label: "Orders needing attention", detail: "Manual review or partially paid", badge: "Review queue" },
      { label: "Failed automations", detail: "External provider call failed · retries exhausted", badge: "Re-runnable" },
      { label: "High-value leads", detail: "From recent campaigns · need follow-up", badge: "Auto-assigned" },
      { label: "SLA at risk", detail: "Conversation nearing the reply-time limit", badge: "Human handoff" },
    ],
    counts: [12, 4, 2, 3, 1],
    element: "items",
  },
  context: {
    title: "Your business shouldn't live in disconnected tools.",
    sub: "Not a CRM database + an inbox database + AI on the side. One context everywhere — the same customer with the same history and value on every screen.",
    hub: "Customer — one context",
    nodes: ["Conversation", "Order", "Marketing", "Payment", "Automation", "AI", "Analytics"],
  },
  c360: {
    title: "Every customer comes with the full context.",
    sub: "A real customer record from the system — conversations, orders, payments and history in one place.",
    demo: "Sample data",
    name: "Registered customer",
    vip: "VIP",
    active: "Active",
    revenue: "Revenue",
    orders: "Orders",
    last: "Last activity",
    tabs: ["Overview", "Timeline", "Conversations", "Orders", "Payments", "Marketing", "Tasks", "AI"],
    info: "Customer information",
    phone: "Phone",
    email: "Email",
    tags: "Tags",
    owner: "Owner",
    work: "Business context",
    openOrders: "Open orders",
    payments: "Payments",
    issues: "Open issues",
    channel: "Preferred channel",
    aiCtx: "AI context",
    intent: "Intent",
    value: "Customer value",
    risk: "Risk",
    next: "Next best action",
    masked: "••••  protected",
    timelineTitle: "A connected timeline — not scattered records",
    timeline: [
      ["Conversation", "Inquiry received from a channel"],
      ["Lead", "Signed up from a marketing campaign"],
      ["Order", "New order created and paid"],
      ["Payment", "Collected and recorded automatically"],
      ["Campaign", "Discount code for returning customers"],
      ["Automation", "Shipping notification sent automatically"],
      ["AI interaction", "Summary + suggested next action"],
    ],
  },
  inbox: {
    title: "Every conversation arrives with context.",
    sub: "Your team never leaves the conversation to hunt for the customer, order or payment — it's all beside the work.",
    live: "Live",
    soon: "Soon",
    channels: ["Website chat", "WhatsApp", "Instagram", "Messenger", "Telegram"],
    demo: "Sample data",
    list: "Conversations",
    thread: "Conversation",
    ctx: "Customer context",
    convos: [
      ["Active conversation", "Website chat · now"],
      ["New conversation", "Telegram · 12m ago"],
      ["Resolved conversation", "Website chat · yesterday"],
    ],
    m1: "Will the order arrive before Friday?",
    m2: "Yes, it's scheduled for Thursday — I'll send tracking as soon as it moves.",
    m3: "Great, thanks for following up.",
    agent: "Team reply",
    suggestTag: "AI draft",
    suggest: "“Of course — I'll update the shipment right away and send you the confirmation.”",
    newCustomer: "New customer",
    orders: "Orders",
    value: "Value",
    intent: "Intent",
    next: "Next best action",
    intentVal: "Shipment inquiry",
    nextVal: "Confirm delivery time",
  },
  ai: {
    title: "AI that can work — within your rules.",
    sub: "Not a chat window. An actor inside the system: it only sees the context it's allowed to see, acts through permission-bound tools, and every step is logged.",
    steps: ["Understand", "Retrieve context", "Reason", "Use tools", "Validate", "Act", "Verify", "Hand off"],
    flow: ["Conversation", "Customer context", "AI", "Tool", "Order", "Automation"],
    chips: ["Scoped roles & permissions", "Approved policies & tools", "Human approval for sensitive steps", "Per-tenant cost limits", "Full run audit", "Permission-filtered knowledge"],
  },
  handoff: {
    title: "AI works with your team, not outside it.",
    sub: "When a situation gets complex, the handoff is one line away — and the full context arrives with your teammate. No starting from zero.",
    steps: [
      ["AI", "AI handles the conversation", "Intent · permitted actions · drafts"],
      ["Detect", "Complex situation detected", "Complaint · refund · frustrated customer"],
      ["Handoff", "Routed to a teammate", "By expertise and workload"],
      ["Human", "Teammate picks up ready", "Summary + order + payment + history"],
    ],
    chips: ["AI status always visible", "Clear human ownership", "Approval on sensitive steps", "Audit on every transition"],
  },
  automation: {
    title: "Describe it. Build it. Run it.",
    sub: "Real operational automation — it performs business actions inside the system, not just notifications.",
    chain: ["Event", "Condition", "AI / logic", "Tool", "Validate", "Approval", "Action", "Review", "Audit"],
    example: "Example: high-value customer flow",
    steps: ["High-value customer sends a message", "Identify the customer from context", "Check customer value", "Wait 10 minutes", "No human reply?", "AI classifies the message", "Notify the team", "Escalate if no response"],
    caps: ["Version history", "Test run", "Execution log", "Re-run", "Failure recovery"],
  },
  analytics: {
    title: "Know what is happening. Know what needs action.",
    sub: "Metric → insight → the records behind it → action. Not charts for the sake of charts.",
    demo: "Sample data",
    metrics: [
      ["Revenue", "+12%", "up"],
      ["Orders", "+8%", "up"],
      ["Conversion", "−3%", "down"],
      ["Customers", "+6%", "up"],
      ["AI activity", "↑", "up"],
      ["Operations", "!", "alert"],
    ],
    insightTag: "Insight",
    insight: ["Conversion dropped mainly among ", "returning customers", " — after last week's shipping-policy change."],
    inspect: "Inspect records",
    act: "Take action",
  },
  control: {
    title: "Everything your system does stays visible and controllable.",
    sub: "Powerful, but not a black box: observe, control, investigate, approve, audit, recover.",
    demo: "Demo workspace",
    counters: [
      ["24 active", "AI agents"],
      ["182 running", "Automations"],
      ["7", "Pending approvals"],
      ["2", "Failed jobs"],
      ["4", "SLA at risk"],
      ["$184", "AI usage"],
      ["31", "Human handoffs"],
    ],
    chips: ["Policies", "Permissions", "Audit", "Security", "System health"],
  },
  pricing: {
    title: "Plans that grow with your business.",
    sub: "A clear structure from day one — no surprises. Early access is currently free across all plans.",
    badge: "Early access",
    popular: "Most popular",
    cta: "Start free",
    free: "Free now",
    freeNote: "during the early-access period",
    tiers: [
      {
        name: "Starter",
        desc: "For small teams getting started with conversational commerce.",
        features: ["1 user", "Website chat", "Unlimited conversations & orders", "Core AI assistant", "Basic reports"],
      },
      {
        name: "Growth",
        desc: "For growing teams that want deeper automation and AI.",
        features: ["Up to 10 users", "All channels as they ship", "Advanced automation + approvals", "Expanded AI limits", "Analytics & campaign attribution"],
      },
      {
        name: "Scale",
        desc: "For multi-location operations and large teams.",
        features: ["Unlimited users", "Multiple workspaces & locations", "Advanced permissions & audit", "Custom AI limits", "Priority support"],
      },
    ],
    note: "Final launch pricing will be set after the early-access period — early adopters lock in the best rate.",
  },
  integrations: {
    title: "Your business already lives in many places.",
    sub: "Connect the systems you already use — they land in the same unified context.",
    flow: ["Connect", "Sync", "Act"],
    items: [
      ["Gemini", "Language models", "Live", true],
      ["n8n", "Automation & integrations", "Live", true],
      ["Website chat", "Direct channel, zero dependencies", "Live", true],
      ["WhatsApp", "The core commerce channel", "Soon", false],
      ["Telegram", "Chats & communities", "Soon", false],
      ["Instagram · Messenger", "Social messaging", "Soon", false],
    ],
  },
  security: {
    title: "Built for control, privacy and accountability.",
    sub: "Everything below is actually implemented in the system — we only claim what works.",
    items: [
      ["Per-tenant data isolation", "Database-level separation (RLS) — every company's data is truly isolated, not just hidden in the UI."],
      ["Roles & permissions", "Each user only sees and does what their role allows — enforced at the API, not the interface."],
      ["Secure session authentication", "Short-lived tokens + automatic rotation + safe logout."],
      ["Audit logs", "Every important change is recorded: who, when, and what."],
      ["Separate AI permissions", "AI acts through pre-authorized tools — with no direct database access."],
      ["API protection", "Webhook signature verification and duplicate-request prevention (idempotency)."],
    ],
  },
  final: {
    title: "One business context. One operating system.",
    sub: "Bring customers, conversations, commerce, automation, AI and operations into one connected system.",
    start: "Get started",
    explore: "Explore the product",
  },
  footer: {
    tag: "One business context. One operating system.",
    product: "Product",
    solutions: "Solutions",
    solutionsItems: ["Customer operations", "Sales", "Marketing", "Commerce"],
    resources: "Resources",
    resourcesItems: ["Documentation", "Guides", "Blog", "Changelog"],
    company: "Company",
    system: "System",
    status: "Status",
    privacy: "Privacy",
    terms: "Terms",
    rights: "© 2026 FIHRIST",
    overview: "Overview",
    features: "Features",
    aiF: "AI",
    automationF: "Automation",
    analyticsF: "Analytics",
    start: "Get started",
    login: "Log in",
  },
  auth: {
    loginTitle: "Welcome back",
    loginSub: "Sign in to continue to your workspace.",
    email: "Email",
    password: "Password",
    submitLogin: "Sign in",
    submittingLogin: "Signing in…",
    noAccount: "No account yet?",
    createAccount: "Create one",
    signupTitle: "Create your account",
    signupSub: "One minute and you're in — the rest of the setup happens after your first sign-in.",
    storeName: "Store / business name",
    fullName: "Full name",
    submitSignup: "Create account",
    submittingSignup: "Creating account…",
    haveAccount: "Already have an account?",
    signin: "Sign in",
    pwHint: "At least 8 characters",
    errInvalid: "The email or password is incorrect.",
    errRate: "Too many attempts. Please try again later.",
    errNetwork: "Can't reach the server. Check your connection and try again.",
    errGeneric: "An unexpected error occurred. Please try again.",
    errExists: "This email is already registered. Sign in or use another email.",
    errCreate: "Couldn't create the account. Please try again.",
    errPw: "Password must be at least 8 characters.",
    errAutoLogin: "Account created but automatic sign-in failed — please sign in manually.",
    retry: "Try again",
    privacy: "Privacy",
    terms: "Terms",
  },
};

export type Dict = typeof ar;

const DICTS: Record<Locale, Dict> = { ar, en };

/* ------------------------------------------------------------------ */
/* Contexts                                                            */
/* ------------------------------------------------------------------ */

type I18nCtx = {
  locale: Locale;
  dir: "rtl" | "ltr";
  t: Dict;
  setLocale: (l: Locale) => void;
};
type ThemeCtx = {
  theme: Theme;
  setTheme: (t: Theme) => void;
  toggle: () => void;
};

const I18nContext = createContext<I18nCtx | null>(null);
const ThemeContext = createContext<ThemeCtx | null>(null);

const LOCALE_KEY = "fh_locale";
const THEME_KEY = "fh_theme";

export function FihristProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ar");
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    const savedLocale = window.localStorage.getItem(LOCALE_KEY) as Locale | null;
    if (savedLocale === "en" || savedLocale === "ar") setLocaleState(savedLocale);
    const savedTheme = window.localStorage.getItem(THEME_KEY) as Theme | null;
    if (savedTheme === "dark" || savedTheme === "light") setThemeState(savedTheme);
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches) setThemeState("dark");
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    window.localStorage.setItem(LOCALE_KEY, l);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    window.localStorage.setItem(THEME_KEY, t);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "light" ? "dark" : "light";
      window.localStorage.setItem(THEME_KEY, next);
      return next;
    });
  }, []);

  const i18nValue = useMemo<I18nCtx>(
    () => ({ locale, dir: locale === "ar" ? "rtl" : "ltr", t: DICTS[locale], setLocale }),
    [locale, setLocale],
  );
  const themeValue = useMemo<ThemeCtx>(() => ({ theme, setTheme, toggle: toggleTheme }), [theme, setTheme, toggleTheme]);

  return (
    <ThemeContext.Provider value={themeValue}>
      <I18nContext.Provider value={i18nValue}>{children}</I18nContext.Provider>
    </ThemeContext.Provider>
  );
}

export function useI18n(): I18nCtx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n must be used within FihristProvider");
  return ctx;
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within FihristProvider");
  return ctx;
}

/** جذر الموقع العام: بيحمل الاتجاه واللغة والثيم + كلاس العزل */
export function FihristRoot({ children, bare = false }: { children: React.ReactNode; bare?: boolean }) {
  const { dir, locale } = useI18n();
  const { theme } = useTheme();
  return (
    <div
      dir={dir}
      lang={locale}
      data-theme={theme}
      className={bare ? "fh-root fh-root-bare" : "fh-root"}
    >
      {children}
    </div>
  );
}
