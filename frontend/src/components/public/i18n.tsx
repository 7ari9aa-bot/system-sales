"use client";

/** FIHRIST public-site i18n + theme — معزول تمامًا داخل مكونات الموقع العام.
 *  - LocaleProvider: عربي افتراضي + إنجليزي، الترجمة نصية فقط — الاتجاه ثابت RTL.
 *  - الثيم واللغة بيتحفظوا في localStorage، واللغة/الثيم على wrapper div
 *    عشان العزل الكامل عن باقي التطبيق. */

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
    start: "ابدأ مجانًا",
    openApp: "افتح التطبيق",
    toDark: "الوضع الداكن",
    toLight: "الوضع الفاتح",
    lang: "English",
    menu: "القائمة",
  },
  hero: {
    eyebrow: "نظام تشغيل الأعمال بالمحادثة — مصري 100%",
    h1: "شغلك كله في نظام واحد.",
    kinetic: ["تبيع أسرع", "تخدم أحسن", "تؤتمتت بدريك", "تكبر بثبات"],
    sub: "FIHRIST بيجمع محادثات عملائك من كل القنوات، طلباتك ومخزونك، أتمتتك، ومساعد ذكي بيفهم وينفذ — كله في مكان واحد متصل. مصمم للمتاجر والأنشطة اللي بتبيع أونلاين في مصر والخليج، مش لعقة برمجية بتكلفك فلوس من غير نتيجة.",
    start: "ابدأ مجانًا",
    explore: "شوف إزاي بيشتغل",
    trust: "مجاني بالكامل خلال الوصول المبكر · بدون بطاقة · بدون التزام",
    mockBadge: "٣ محادثات نشطة",
    mockRows: [
      ["سارة محمد", "VIP", "طلب #1024"],
      ["أحمد علي", "جديد", "ردّ منتظر"],
      ["نورة", "تم الرد", "طلب #1023"],
    ],
    mockAi: "العميل ده من العملاء المميزين وطلبهم شُحن بالفعل — أقترح ردّ جاهز للتأكيد.",
    mockAiRows: [
      "العميل ده من العملاء المميزين وطلبهم شُحن بالفعل — أقترح ردّ جاهز للتأكيد.",
      "مفيش حد ردّ على العميل ده من 10 دقايق — أقترح تصعيد لفريق المبيعات.",
      "الطلب اتردّ عليه بنجاح — أقترح متابعة بعد الشحن لقياس الرضا.",
    ],
  },
  trustSignals: ["عزل بيانات لكل مستأجر", "تدقيق كامل لكل خطوة", "بدون بطاقة ولا التزام", "AI بصلاحيات محدودة"],
  stats: {
    items: [
      ["١", "نظام واحد لكل شغلك"],
      ["٦", "قدرات متصلة ببعض"],
      ["٤+", "قنوات بيع موحدة"],
      ["٢٤/٧", "أتمتة شغّالة بدريك"],
    ],
  },
  how: {
    title: "إزاي بيشتغل؟ ثلاث خطوات وكفاية.",
    sub: "من غير إعدادات معقدة ولا كود. تفتح حسابك وتبدأ تبيع من أول يوم.",
    steps: [
      ["اربط قنواتك", "شات الموقع شغّال النهاردة بلا إعدادات. واتساب وتليجرام وانستجرام جايين قريب. كل رسايل عملائك هتوصل صندوق واحد موحّد بدل ما تطرد في كذا مكان."],
      ["السياق يشتغل معاك", "كل محادثة وراها عميل بطلباته ودفعاته وتاريخه كامل. الموظف بياخد القرار في ثواني لأن كل اللي محتاجه قدامه — مش رايح يدوّر في إكسل وواتساب وموقع."],
      ["النظام ينفّذ عنك", "أتمتة ومساعد ذكي بينفذوا جوه صلاحياتك وقواعدك: ردود جاهزة، تأكيدات طلبات، تذكيرات، تصعيد. وكل خطوة مسجلة وقابلة للمراجعة."],
    ],
    more: "شوف الصورة الكاملة للنظام",
    tags: [
      ["واتساب", "تليجرام", "إنستجرام", "شات"],
      ["طلبات", "مخزون", "دفعات", "تاريخ"],
      ["أتمتة", "AI", "تذكيرات", "تصعيد"],
    ],
  },
  graph: {
    title: "كل حاجة متصلة بكل حاجة — ده اللي بيوفرلك وقت.",
    sub: "المحادثة مرتبطة بالعميل، والعميل بطلباته، والطلب بدفعته ومخزونه. سياق واحد بيتحرك معاك في كل شاشة. ده الفرق بين نظام بيشتغل وأدوات مفككة بتنسخ وتلصق.",
    hub: "العميل — قلب السياق",
    nodes: ["محادثة", "طلب", "مخزون", "دفع", "أتمتة", "AI", "تحليلات"],
  },
  chat: {
    title: "اسأل المساعد التجريبي.",
    sub: "ده مش صورة ولا فيديو — عرض تفاعلي فعلًا جوه الصفحة. الردود محاكاة بدون أي بيانات حقيقية.",
    status: "وضع العرض التجريبي",
    greeting: "أهلًا بك 👋 أنا مساعد FIHRIST التجريبي. اسألني أي حاجة عن النظام — أو جرب اقتراح من اللي تحت.",
    ph: "اكتب رسالتك…",
    send: "ابعت",
    simulated: "محاكاة",
    userTag: "أنت",
    botTag: "مساعد FIHRIST · عرض تجريبي",
    toolsTitle: "إيه اللي بيرد على رسايل عملائك جوه النظام فعلًا؟",
    tools: ["فهم نية العميل", "تنفيذ إجراءات مسموحة", "ملخص المحادثة", "اقتراح الرد التالي", "تصعيد للفريق"],
    s1: "عميل بسأل: طلبي وصل فين؟",
    s2: "مفيش حد رد على عميل من 10 دقايق",
    s3: "إيه اللي بيخلي بياناتي آمنة؟",
    r_intro: "FIHRIST نظام تشغيل متكامل لشركتك: المحادثات من كل القنوات، العملاء، الطلبات، الأتمتة والذكاء الاصطناعي — كلها في سياق واحد متصل بدل أدوات مفككة.",
    r_pricing: "دلوقتي الوصول المبكر مجاني لكل الخطط. عندنا 3 خطط (البداية / النمو / التوسع) بتفرق في حجم الفريق والقنوات وحدود الـAI — التفاصيل في صفحة الأسعار.",
    r_automation: "الأتمتة بتشتغل بمسار واضح: حدث بيبدأ المسار → شرط → منطق أو AI → تحقق → موافقة عند الحاجة → تنفيذ → مراجعة وتدقيق. مثال: عميل عالي القيمة يبعت رسالة ومحدش يرد خلال 10 دقايق — المسار يصنّف الرسالة ويُنبّه الفريق ويصعّد لو محتاج.",
    r_security: "الأمان مبني من الأول: عزل بيانات لكل مستأجر على مستوى قاعدة البيانات (RLS)، صلاحيات وأدوار، جلسات مصادقة آمنة، سجلات تدقيق كاملة، والذكاء الاصطناعي بينفذ عبر أدوات بصلاحيات محددة مسبقًا — بدون أي وصول مباشر لقاعدة البيانات.",
    r_channels: "شات الموقع شغّال النهاردة، وواتساب وتليجرام وإنستجرام وماسنجر في مرحلة التكامل القادمة. كل القنوات هتوصل لنفس الصندوق ونفس سياق العميل.",
    r_order: "أهلًا بيك في العرض التفاعلي — اللي بيحصل جوه FIHRIST: المساعد بيقرأ سياق العميل (طلباته ودفعاته) مباشرة من النظام، ويرد عليه بحالة طلبه الفعلية — من غير ما الموظف يدور في أدوات تانية. وهنا المساعد التجريبي بيرد بمعرفة عامة عن النظام لأن مفيش بيانات حقيقية وراه.",
    r_escalate: "ده بالظبط دور الأتمتة: مسار بيراقب زمن الرد — لو عدى 10 دقايق من غير رد بشري، المسار يصنّف الرسالة بالـAI، ويُنبّه الفريق، ويصعّد لو الحالة حساسة. وكل خطوة مسجلة في سجل التدقيق.",
    r_fallback: "سؤال ممتاز. باختصار: FIHRIST بيجمع المحادثات والعملاء والطلبات والأتمتة والـAI في نظام واحد — جرب تسألني عن الأسعار أو الأتمتة أو الأمان لتفاصيل أكتر.",
  },
  automation: {
    title: "أتمتة بتنفّذ شغل فعلًا.",
    sub: "مسارات تشغيلية بحدث وشرط ومنطق — بتنفذ إجراءات جوه النظام، بموافقات بشرية لما يلزم، وتدقيق كامل لكل تشغيل.",
    chain: ["حدث", "شرط", "AI / منطق", "أداة", "تحقق", "موافقة", "تنفيذ", "مراجعة", "تدقيق"],
    example: "مثال: مسار العملاء عالي القيمة",
    steps: ["عميل عالي القيمة يبعت رسالة", "تعريف العميل من السياق", "فحص قيمة العميل", "انتظار 10 دقايق", "مفيش رد بشري؟", "الـAI يصنّف الرسالة", "إشعار الفريق", "تصعيد لو مفيش استجابة"],
    caps: ["سجل إصدارات", "تشغيل تجريبي", "سجل تنفيذ", "إعادة تشغيل", "استرجاع بعد الفشل"],
    more: "كل تفاصيل الأتمتة",
  },
  integrations: {
    title: "شغلك موزّع على أدوات كتير — وإحنا بنجمعه.",
    sub: "وصّل الأنظمة اللي بتستخدمها — النظام يستقبلها في سياق واحد.",
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
  securityTeaser: {
    colTitle: "الأمان",
    title: "الأمان مكتوب في أول سطر كود.",
    sub: "عزل بيانات لكل مستأجر على مستوى قاعدة البيانات، صلاحيات وأدوار، تدقيق كامل — والذكاء الاصطناعي بينفذ عبر أدوات مصرح ليها فقط.",
    points: [
      ["عزل بيانات لكل مستأجر (RLS)", "كل بياناتك معزولة على مستوى قاعدة البيانات عن أي عميل تاني."],
      ["صلاحيات وأدوار", "كل مستخدم بيشتغل بصلاحياته — ومفيش حد بيعدّي حدوده."],
      ["ذكاء اصطناعي بصلاحيات", "الـ AI بينفذ إجراءات مسموحة فقط — من غير وصول مباشر لقاعدة البيانات."],
      ["تدقيق كامل", "كل تغيير مهم مسجّل: مين، إمتى، وإيه اتغيّر."],
    ],
    more: "كل تفاصيل الأمان",
  },
  pricing: {
    title: "خطط واضحة بتكبر مع شركتك.",
    sub: "هيكل شفاف من اليوم الأول — من غير مفاجآت ولا رسوم مخفية. الوصول المبكر مجاني دلوقتي لكل الخطط.",
    badge: "وصول مبكر",
    popular: "موصى بها للفرق",
    cta: "ابدأ مجانًا",
    free: "مجانًا دلوقتي",
    freeNote: "خلال فترة الوصول المبكر",
    more: "كل تفاصيل الأسعار والأسئلة الشائعة",
    tiers: [
      {
        name: "للمتجر الفردي",
        desc: "للمتجر الفردي اللي بيبدأ بالبيع بالمحادثة.",
        features: ["1 مستخدم", "شات الموقع", "محادثات وطلبات غير محدودة", "مساعد AI أساسي", "تقارير أساسية"],
      },
      {
        name: "للفريق المتنامي",
        desc: "للفريق المتنامي اللي عايز أتمتة أعمق وذكاء أوسع.",
        features: ["حتى 10 مستخدمين", "كل قنوات التواصل عند توفرها", "أتمتة متقدمة + موافقات", "حدود AI موسعة", "تحليلات وربط حملات"],
      },
      {
        name: "للعمليات الكبيرة",
        desc: "للعمليات الكبيرة متعددة الفروع والفرق.",
        features: ["عدد مستخدمين غير محدود", "مساحات ومواقع متعددة", "صلاحيات متقدمة وتدقيق", "حدود AI مخصصة", "دعم بأولوية"],
      },
    ],
    note: "التسعير النهائي بيتحدد بعد فترة الوصول المبكر — واللي هيشترك بدري هياخد أفضل شروط نقدر نقدمها النهاردة.",
  },
  features: {
    title: "ليه FIHRIST؟ ست قدرات في نظام واحد متصل.",
    sub: "مش تجميع أدوات كل واحدة لوحدها. كل قدرة بتبقى متصلة بنفس سياق العمل — فالقرارات أسرع والجهد أقل والنتيجة بتظهر.",
    items: [
      ["صندوق موحّد لكل المحادثات", "شات الموقع وواتساب وتليجرام وانستجرام في صندوق واحد — مع تاريخ العميل وطلباته جنب كل رسالة، وتوزيع تلقائي ومسودة رد بالـAI جاهزة."],
      ["سياق عمل متصل", "المحادثة مرتبطة بالعميل، والعميل بطلباته، والطلب بدفعته ومخزونه — سياق واحد بيتحرك معاك في كل شاشة من غير نسخ ولصق بين أدوات."],
      ["أتمتة بمسارات ومنطق", "مسارات بحدث وشرط ومنطق بتنفذ إجراءات جوه النظام — تأكيدات وتذكيرات وتصعيد — بموافقات بشرية لما تلزم وتدقيق كامل."],
      ["ذكاء اصطناعي بصلاحيات", "مساعد بيفهم نية العميل ويرد من بياناتك وينفذ إجراءات مسموحة فقط — من غير أي وصول مباشر لقاعدة البيانات، وكل تشغيلة مسجلة."],
      ["تجارة ومخزون", "منتجات ومخزون وطلبات ومدفوعات — كل اللي بتحتاجه عشان تبيع وتدير عمليتك في مكان واحد، من الرسالة للشحن."],
      ["تحليلات وتقارير", "لوحات أداء ومؤشرات وتتبّع حملات — قرارات مبنية على بيانات حقيقية مش حدس، وكل رقم وراه سجلات حقيقية."],
    ],
  },
  useCases: {
    title: "FIHRIST لمين؟",
    sub: "مصمم لكل اللي بيبيع أونلاين — من المتجر الصغير للعملية الكبيرة متعددة الفروع.",
    items: [
      ["المتاجر الإلكترونية", "وحّد محادثات البيع والاستفسارات والمتابعات في صندوق واحد، وخلّي الأتمتة تردّ على الأسئلة الشائعة وتأكد الطلبات وتصعّد لما يلزم."],
      ["الأنشطة التجارية", "مطاعم وكافيهات وصالونات — ردود سريعة للعملاء، طلبات منظّمة، ومسارات تلقائية للتأكيدات والتذكيرات والاسترجاع."],
      ["وكالات التسويق", "أدِر محادثات عملاء متعددين من فريق واحد، مع صلاحيات لكل عضو وتقارير أداء لكل عميل ولوحة تحكم موحدة."],
      ["خدمة العملاء", "كل محادثة بتوصل بتاريخ العميل الكامل — مش لازم تدوّر، والـAI بيقترح الرد والتشغيلة بتبقى مسجلة."],
      ["العمليات الكبيرة", "مواقع وفروع متعددة، صلاحيات متقدمة، تدقيق كامل — بنية جاهزة تكبر مع شركتك من غير ما تعيد بناء نظامك."],
    ],
    results: [
      "استجابة أسرع للعملاء المميزتين",
      "ترد في دقيقة مع كل الإجراءات مسجلة",
      "أتمتة تشغيلية بدون تدخل بشري",
    ],
  },
  faq: {
    title: "أسئلة شائعة",
    sub: "كل اللي بيهمك تعرفه قبل ما تبدأ — ولو مفيش إجابتك، اسأل المساعد فوق.",
    items: [
      ["هل فعلاً مجاني؟", "أيوة — الوصول المبكر مجاني لكل الخطط بدون بطاقة وبدون التزام. لما يبدأ التسعير الفعلي هننبّهك قبل أي تغيير بأسبوع على الأقل."],
      ["أحتاج كود أو تثبيت؟", "لأ — FIHRIST منصة على المتصفح. بتعمل حساب وتبدأ على طول، مش محتاج مطور ولا سيرفر ولا صيانة."],
      ["قنواتي موجودة؟", "شات الموقع شغّال دلوقتي بلا إعدادات. واتساب وتيلجرام وانستجرام وماسنجر على خريطة التكامل القادمة — وهتوصل لنفس الصندوق."],
      ["بياناتي آمنة؟", "عزل بيانات لكل مستأجر على مستوى قاعدة البيانات (RLS)، صلاحيات وأدوار، جلسات مصادقة آمنة، وسجلات تدقيق كاملة — والـAI بينفذ عبر أدوات مصرح ليها فقط."],
      ["أقدر ألغي؟", "أيوة — تقدر تحذف حسابك وبياناتك في أي وقت من غير أي التزام."],
      ["الذكاء الاصطناعي بيستخدم بياناتي للتدريب؟", "لأ — مفيش استخدام لبياناتك في تدريب أي نموذج، ومفيش بيع أو مشاركة للبيانات مع أي حد."],
    ],
  },
  final: {
    title: "سياق عمل واحد. نظام تشغيل واحد.",
    sub: "ابدأ النهاردة مجانًا — بدون بطاقة وبدون التزام. شوف بنفسك إزاي كل حاجة بتشتغل جوه النظام.",
    start: "ابدأ مجانًا",
    explore: "شوف إزاي بيشتغل",
  },
  footer: {
    tag: "نظام تشغيل الأعمال بالمحادثة.",
    product: "المنتج",
    system: "النظام",
    status: "الحالة",
    privacy: "سياسة الخصوصية",
    terms: "شروط الاستخدام",
    rights: "© 2026 FIHRIST",
    earlyAccess: "وصول مبكر",
    contact: "أسئلة؟ راسل حمد عادل:",
  },
  auth: {
    valueTitle: "نظام تشغيل أعمالك بالمحادثة",
    valueSub: "المحادثات والعملاء والطلبات والأتمتة والذكاء الاصطناعي — في سياق عمل واحد.",
    valuePoints: [
      "صندوق موحّد لكل محادثاتك من كل القنوات",
      "سياق عمل متصل — قرارات أسرع بجهد أقل",
      "أتمتة وذكاء اصطناعي بصلاحيات وتدقيق كامل",
    ],
    valueBadge: "وصول مبكر مجاني · بدون بطاقة",
    loginTitle: "أهلًا بعودتك",
    loginSub: "سجّل الدخول للمتابعة لمساحة عملك.",
    email: "البريد الإلكتروني",
    password: "كلمة المرور",
    submitLogin: "تسجيل الدخول",
    submittingLogin: "جارٍ تسجيل الدخول…",
    noAccount: "معندكش حساب؟",
    createAccount: "أنشئ حساب",
    signupTitle: "أنشئ حسابك",
    signupSub: "بريد وكلمة مرور — وتدخل على طول. اسم مساحتك بيتولد تلقائيًا وتقدر تعدّله جوه.",
    storeName: "اسم المتجر / النشاط",
    fullName: "الاسم بالكامل",
    submitSignup: "إنشاء الحساب",
    submittingSignup: "جارٍ إنشاء الحساب…",
    haveAccount: "عندك حساب بالفعل؟",
    signin: "سجّل الدخول",
    pwHint: "8 حروف على الأقل",
    showPw: "إظهار",
    hidePw: "إخفاء",
    errInvalid: "البريد الإلكتروني أو كلمة المرور مش صحيحة.",
    errRate: "محاولات كتير أوي. استنى شوية وحاول تاني.",
    errNetwork: "مش قادرين نوصل للسيرفر. اتأكد من اتصالك وحاول تاني.",
    errGeneric: "حصلت مشكلة غير متوقعة. حاول مرة تانية.",
    errExists: "البريد ده متسجل قبل كده. سجّل الدخول أو استخدم بريد تاني.",
    errCreate: "مش قادرين نعمل الحساب. حاول مرة تانية.",
    errPw: "كلمة المرور لازم تكون 8 حروف على الأقل.",
    errEmail: "البريد الإلكتروني مش صحيح.",
    errAutoLogin: "الحساب اتعمل بس الدخول التلقائي فشل — سجّل الدخول بنفسك.",
    dismiss: "حسنًا",
    privacy: "سياسة الخصوصية",
    terms: "شروط الاستخدام",
  },

  pages: {
      product: {
        title: "نظام تشغيل كامل لشغلك — مش أداة منفصلة.",
        sub: "FIHRIST مش CRM لوحده ولا chatbot لوحده — بيئة واحدة بتشغّل البيع والخدمة والعمليات، بسياق واحد بيطي كل حاجة. كل قدرة بتتكلم مع التانية، فالقرار أسرع والجهد أقل.",
        features: [
          ["محادثات موحّدة", "كل قنوات تواصل عملائك في صندوق واحد: توزيع تلقائي، مسودات ذكاء اصطناعي، وتحويل للفريق بالسياق الكامل — من غير ما حد يخرج من المحادثة يدوّر على معلومة."],
          ["عملاء وطلبات ومخزون", "ملف واحد لكل عميل: طلباته، مدفوعاته، تاريخه، وقناته المفضلة. والطلبات مربوطة بالمخزون — من الرسالة للشحنة."],
          ["ذكاء اصطناعي خاضع لقواعدك", "مساعد بيفهم محادثاتك، بيجاوب من معرفة شركتك، وبي نفذ إجراءات حقيقية — عبر أدوات مصرح ليها فقط، وكل خطوة مسجلة."],
          ["أتمتة تشغيلية", "مسارات بحدث وشرط ومنطق: تذكير، تصنيف، إشعار، تصعيد — بموافقات بشرية للخطوات الحساسة."],
          ["تحليلات مربوطة بالواقع", "كل رقم وراه سجلات حقيقية: من المؤشر، للاستنتاج، للسجلات اللي وراه، للإجراء اللي اتعمل."],
          ["جاهز للتوسع", "متعدد المستأجرين بعزل بيانات على مستوى قاعدة البيانات — بنية جاهزة تنمو مع شركتك."],
        ],
        forWho: {
          title: "لمين ده النظام؟",
          items: [
            ["نشأة بتبيع أونلاين", "عاوزة تدير البيع والخدمة من مكان واحد بدل جروبات ومنشورات وتسابي متفرقة."],
            ["فريق خدمة عملاء", "محتاج كل محادثة توصل ومعاها تاريخ العميل وطلباته — ورد سريع بمساعدة AI."],
            ["عملية بتكبر", "محتاجة أتمتة حقيقية وصلاحيات وتدقيق — قبل ما التوسع يبوظ التجربة."],
          ],
        },
        cta: "جاهز تشوفها بنفسك؟",
      },
    context: {
      title: "سياق واحد. من غير تكرار.",
      sub: "أكبر مشكلة في أدوات الأعمال المتفرقة إن معلومة واحدة بتتكتب في خمس أماكن — ولا واحدة منهم عارفة الصورة كاملة. FIHRIST بيحل دي من الجذر.",
      problem: {
        title: "المشكلة: الأدوات المفككة",
        items: [
          ["المعلومة متكررة", "العميل مسجل في الـCRM، ومحادثته في شات تاني، وطلبه في مكان تالت — وكل أداة شايفة جزء."],
          ["القرار بيبقى أعمى", "الموظف بيرد من غير ما يشوف إن العميل ده خسران من زمان أو إن طلبه متأخر."],
          ["الأتمتة بتقصّر", "الأتمتة في أداة معزولة مش شايفة المحادثة ولا الطلب — فبتعمل إشعارات بس."],
        ],
      },
      solution: {
        title: "الحل: مصدر حقيقة واحد",
        items: [
          ["العميل في المركز", "كل كيان — محادثة، طلب، دفعة، حملة — مربوط بنفس السياق تلقائيًا."],
          ["السياق بيتحرك", "أفتح أي محادثة تلاقي وراها كل حاجة. وأي تغيير في أي مكان بيتشاف في كل مكان."],
          ["الذكاء الاصطناعي بيتغذى منه", "مساعد الـAI بيجاوب من نفس السياق — مش من ملخصات قديمة."],
        ],
      },
      cta: "جرّب السياق بنفسك جوه النظام",
    },
    conversations: {
      title: "كل المحادثات في صندوق واحد.",
      sub: "مهما كانت القناة — المحادثة بتوصل لنفس المكان، ومعاها كل حاجة عن العميل اللي وراها.",
      channels: {
        title: "القنوات",
        items: [
          ["شات الموقع", "شغّال النهاردة — قناة مباشرة بدون اعتماديات خارجية."],
          ["واتساب", "القناة الأهم للتجارة — في خطة التكامل القادمة."],
          ["تليجرام", "محادثات ومجتمعات — قريبًا."],
          ["إنستجرام وماسنجر", "التواصل الاجتماعي — قريبًا."],
        ],
      },
      inbox: {
        title: "إيه اللي بيخلي الفريق أسرع؟",
        items: [
          ["سياق جنب كل محادثة", "العميل وطلباته وتاريخه ظاهرين جنب الرسالة — من غير بحث في أدوات تانية."],
          ["مسودات ذكاء اصطناعي", "الـAI بيقترح رد جاهز للمراجعة — والفريق يعدله ويبعته بضغطة."],
          ["تحويل بالسياق الكامل", "لما الحالة تعقّد، التحويل لزميل بيحصل بسطر — واللي يستلم بيدخل على كل حاجة جاهزة."],
          ["أولويات واضحة", "النظام بيرفع المحادثات اللي قربت من حد زمن الرد — فمفيش عميل بيتنسى."],
        ],
      },
      handoff: {
        title: "الـAI بيساعد، والبشر بيقرروا.",
        steps: [
          ["AI", "الـAI بيعالج الروتين", "فهم النية · إجراءات مسموحة · مسودات رد"],
          ["اكتشاف", "الحالة المعقدة بتتكتشف", "شكوى · استرداد · عميل محبط"],
          ["تحويل", "تحويل لحد من الفريق", "حسب التخصص والعبء"],
          ["إنسان", "الموظف يستلم جاهز", "الملخص + الطلب + الدفع + التاريخ"],
        ],
      },
      cta: "ابدأ بقناة شات الموقع النهاردة",
    },
    ai: {
      title: "ذكاء اصطناعي شغّال جوه قواعدك.",
      sub: "مش صندوق أسود ولا نافذة شات — عامل متكامل جوه النظام بيراعي صلاحياتك وسياساتك، وكل حرف بيقوله بيتسجل.",
      loop: {
        title: "دورة العمل في 8 خطوات",
        steps: ["يفهم", "يجيب السياق", "يستنتج", "يستخدم أدوات", "يتحقق", "ينفذ", "يراجع", "يحوّل للبشر"],
      },
      can: {
        title: "بيقدر يعمل إيه؟",
        items: [
          ["يجاوب من معرفة شركتك", "من منتجاتك وسياساتك — مش من الإنترنت العشوائي."],
          ["ينفذ إجراءات حقيقية", "فحص حالة طلب، تحديث بيانات، إنشاء مهمة — عبر أدوات مصرح ليها فقط."],
          ["يلخص ويقترح", "ملخص المحادثة الطويلة، والرد التالي المقترح للفريق."],
          ["يعرف حدوده", "لو الحالة خارج صلاحياته — بيحوّل للبشر فورًا، مش بيمثّل."],
        ],
      },
      guard: {
        title: "اللي بيمنعه من التجاوز",
        items: [
          ["صلاحيات وأدوار", "الـAI شايف بس اللي مسموح لدوره يشوفه — على مستوى الـAPI."],
          ["أدوات معتمدة", "مفيش وصول مباشر لقاعدة البيانات — أي تنفيذ بيعدي على أداة معتمدة ومحددة مسبقًا."],
          ["موافقات بشرية", "الخطوات الحساسة (استرجاع، خصم، إلغاء) بتعدي على موافقة بشرية."],
          ["حدود تكلفة", "لكل مستأجر سقف استخدام — مفيش فاتورة مفاجئة."],
          ["تدقيق كامل", "كل تشغيل مسجل: السؤال، السياق، الأدوات المستخدمة، والنتيجة."],
          ["معرفة حسب الصلاحيات", "الـAI بيجاوب من معرفة شركتك حسب صلاحية كل مستخدم."],
        ],
      },
      cta: "شوف الـAI جوه النظام بنفسك",
    },
    automationPage: {
      title: "اوصفها. ابنِها. شغّلها.",
      sub: "أتمتة تشغيلية حقيقية — بتنفذ إجراءات عمل جوه النظام: طلبات، إشعارات، تصعيد، متابعة. مش مجرد إشعارات بريد.",
      chainTitle: "بنية المسار",
      exampleTitle: "مثال: مسار العملاء عالي القيمة",
      capsTitle: "إدارة بعد التشغيل",
      caps: [
        ["سجل إصدارات", "كل تعديل في المسار محفوظ — ترجع لأي نسخة في أي وقت."],
        ["تشغيل تجريبي", "اختبر المسار على بيانات وهمية قبل ما يشتغل على العملاء."],
        ["سجل تنفيذ", "كل تشغيل مسجل بالخطوات — تعرف بالظبط إيه اللي حصل وليه."],
        ["إعادة تشغيل", "فشل نداء مزود خارجي؟ أعد تشغيل المسار من نقطة الفشل."],
        ["استرجاع بعد الفشل", "المسارات الفاشلة بتظهر في أولوياتك مع سبب الفشل وخيار إعادة."],
      ],
      guardTitle: "حواجز الحماية",
      guardItems: [
        ["تحقق قبل التنفيذ", "كل خطوة بتتأكد من صحة البيانات قبل ما تتنفذ."],
        ["موافقة بشرية", "الإجراءات الحساسة بتعدي على موافقة — إنت اللي بتحدد إيه الحساس."],
        ["تدقيق كامل", "كل تشغيل له أثر تدقيق دائم."],
      ],
      cta: "ابنِ أول مسار ليك",
    },
    pricingPage: {
      title: "الأسعار والخطط.",
      sub: "هيكل واضح — ووصول مبكر مجاني لكل الخطط. بدون بطاقة، وبدون التزام.",
      faqTitle: "أسئلة شائعة",
      faq: [
        ["هل الوصول المبكر مجاني فعلًا؟", "أيوه — كل الخطط مجانية دلوقتي خلال فترة الوصول المبكر، من غير بطاقة ولا التزام."],
        ["هيدفعوا إيه بعد الوصول المبكر؟", "التسعير النهائي هيتحدد بعد الفترة دي، والمشتركين مبكرًا هيحصلوا على أفضل سعر — بنبّه قبل أي تغيير."],
        ["إيه الفرق بين الخطط؟", "حجم الفريق (مستخدمين)، القنوات المتاحة، حدود استخدام الذكاء الاصطناعي، ومستوى الدعم."],
        ["محتاج إيه عشان أبدأ؟", "بريد إلكتروني وكلمة مرور — الحساب بيتعمل في دقيقة وتدخل على طول. اسم مساحتك بيتولد تلقائيًا."],
        ["هل بياناتي معزولة عن باقي العملاء؟", "أيوه — عزل على مستوى قاعدة البيانات (RLS) لكل مستأجر، مش مجرد فلترة في الواجهة."],
        ["أقدر أسيب في أي وقت؟", "أيوه — وبيانات مساحتك ملكك. الحذف والتصدير جزء من النظام."],
      ],
      cta: "ابدأ مجانًا النهاردة",
    },
    securityPage: {
      title: "الأمان والتحكم.",
      sub: "مبدأنا بسيط: بنكتب بس اللي مبني فعلًا. كل اللي تحت شغّال في النظام النهاردة.",
      areas: [
        ["عزل بيانات لكل مستأجر", "كل شركة بياناتها معزولة على مستوى قاعدة البيانات نفسها (Row-Level Security) — مش فلترة في الواجهة. حتى استعلام فيه خطأ برمجي مش هيشوف بيانات مستأجر تاني."],
        ["صلاحيات وأدوار", "الأدوار والصلاحيات مفروضة في طبقة الـAPI قبل أي تنفيذ — الواجهة مجرد عرض، والحماية الحقيقية في العمليات."],
        ["مصادقة بجلسات آمنة", "توكنات وصول قصيرة العمر مع تدوير تلقائي، وخروج آمن بإبطال الجلسات."],
        ["سجلات تدقيق", "كل تغيير مهم بيتسجل: مين، إمتى، إيه اللي اتغير — بمرجعية دائمة قابلة للمراجعة."],
        ["صلاحيات منفصلة للذكاء الاصطناعي", "الـAI مالوش وصول مباشر لقاعدة البيانات نهائيًا — بينفذ عبر أدوات محددة بصلاحيات مسبقة، وكل تشغيل مسجل بالكامل."],
        ["حماية نداءات النظام", "التحقق من توقيع الـwebhooks الواردة، ومنع تكرار النداءات (idempotency) — فالنداء المفقود أو المتكرر مش بيعمل ضرر."],
        ["المراقبة والتحكم", "أي حاجة النظام بيعملها — وكلاء، أتمتة، موافقات معلقة، مهام فاشلة — ظاهرة في مركز تحكم جوه التطبيق، مش مخفية."],
      ],
      honest: "لسه مش معتمدين عند أي جهة خارجية — ومش هنادّي إننا معتمدين قبل ما ناخد الشهادات فعلًا. اللي شايفه فوق هو البنية المطبقة فعلًا، وبتتحدث مع كل مرحلة بناء.",
      cta: "جرّب وأنت مطمّن",
    },
    privacy: {
      title: "سياسة الخصوصية",
      updated: "آخر تحديث: سبتمبر 2026",
      intro: "الخصوصية عندنا مش صفحة قانونية — جزء من تصميم النظام. السياسة دي بتشرح بوضوح إيه اللي بيحصل لبياناتك فعلًا.",
      sections: [
        ["البيانات اللي بنجمعها", "بيانات الحساب: الاسم والبريد الإلكتروني واسم النشاط اللي بتدخله عند التسجيل. بيانات مساحتك: كل محتوى بتدخله أو بيجي من قنواتك (محادثات، طلبات، إعدادات). سجلات تشغيل: أوقات الدخول وسجلات التدقيق المطلوبة لتشغيل النظام بأمان."],
        ["إزاي بنخزنها ونحميها", "بيانات كل شركة معزولة على مستوى قاعدة البيانات (Row-Level Security) عن باقي الشركات. الوصول للبيانات مقيّد بصلاحيات وأدوار، وكل عملية حساسة ليها سجل تدقيق."],
        ["الذكاء الاصطناعي وبياناتك", "معالجة الذكاء الاصطناعي بتحصل عبر مزود خارجي (Google Gemini) عند طلب المساعد أو البحث في المعرفة. إحنا مبنستخدمش بياناتك لتدريب نماذج الذكاء الاصطناعي، ومش بنبيع بيانات لأي طرف — إطلاقًا. صلاحيات الـAI محددة بأدوات مصرح بيها مسبقًا."],
        ["الكوكيز", "بنستخدم تخزين محلي أساسي بس لحفظ جلسة الدخول وتفضيلاتك (اللغة والثيم). مفيش تتبع إعلاني."],
        ["الاحتفاظ والحذف", "بيانات مساحتك ملكك — الحذف والتصدير جزء من النظام. أثناء مرحلة الوصول المبكر، قناة طلبات البيانات الرسمية بتتجهز، وأي طلب حذف بننفذه يدويًا وفورًا لحد ما القناة الرسمية تكتمل."],
        ["تغييرات السياسة", "لو السياسة اتغيرت بشكل جوهري هننبّه المستخدمين جوه النظام قبل التغيير."],
        ["التواصل", "عندك سؤال عن السياسة دي أو بياناتك؟ راسل حمد عادل على 7ari9aa@gmail.com."],
      ],
      cta: "أي سؤال عن الخصوصية؟ اسأل المساعد في الصفحة الرئيسية.",
    },
    terms: {
      title: "شروط الاستخدام",
      updated: "آخر تحديث: سبتمبر 2026",
      intro: "دي الشروط اللي بتنظم استخدامك لنظام FIHRIST. كتبناها واضحة ومختصرة عشان تقرأها فعلًا.",
      sections: [
        ["الخدمة في مرحلة وصول مبكر", "FIHRIST لسه في مرحلة تطوير نشطة. المميزات بتتغير وتتحسن بسرعة، وممكن تحصل انقطاعات. بنبني بإتقان، لكن في المرحلة دي مفيش ضمان لاستمرارية الخدمة الكاملة."],
        ["حسابك", "إنت مسؤول عن سرية بيانات دخولك وعن كل حاجة بتحصل من حسابك. لو حسيت إن حد بيستخدم حسابك من غير إذن، بلّغنا فورًا على 7ari9aa@gmail.com."],
        ["الاستخدام المقبول", "ممنوع استخدام النظام لأي غرض غير قانوني أو ضار، أو لمضايقة الآخرين، أو محاولة اختراق أو تعطيل النظام أو الوصول لبيانات مش بتاعتك."],
        ["محتواك", "اللي بتدخله من محتوى وبيانات يبقى ملكك — وإحنا بنستخدمه بس عشان نشغّل الخدمة ليك. ملكية النظام والبرمجيات لينا."],
        ["الفواتير", "الوصول المبكر مجاني. لما يبدأ التسعير الفعلي هننبّهك قبل أي تغيير، وتقدر تسيب قبل ما يتطبق."],
        ["الإنهاء", "تقدر تحذف حسابك في أي وقت. وإحنا بنقدر نوقف حساب بيخالف قواعد الاستخدام المقبول — بنبّه قبلها في الحالات العادية."],
        ["إخلاء مسؤولية", "الخدمة بتنزل \"كما هي\" خلال الوصول المبكر. بنحاول نقدم أفضل تجربة ممكنة، لكن مبنضمنش نتائج تجارية محددة."],
        ["تحديث الشروط", "لو الشروط اتغيرت بشكل جوهري هننبّهك جوه النظام. استمرار الاستخدام بعد التغيير يعني موافقتك."],
      ],
      cta: "موافق؟ يلا نبدأ.",
    },
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
    login: "Sign in",
    start: "Start free",
    openApp: "Open app",
    toDark: "Dark mode",
    toLight: "Light mode",
    lang: "العربية",
    menu: "Menu",
  },
  hero: {
    eyebrow: "A conversation-driven business OS — built for MENA",
    h1: "Your whole business in one system.",
    kinetic: ["sell faster", "serve better", "automate more", "scale steadily"],
    sub: "FIHRIST unifies every customer conversation, your orders and inventory, your automation, and a smart assistant that understands and acts — all in one connected place. Built for merchants and businesses selling online in Egypt and the Gulf, not a bloated tool that costs you money without results.",
    start: "Start free",
    explore: "How it works",
    trust: "Fully free during early access · no card · no commitment",
    mockBadge: "3 active conversations",
    mockRows: [
      ["Sara M.", "VIP", "Order #1024"],
      ["Ahmed A.", "New", "Awaiting reply"],
      ["Noura", "Replied", "Order #1023"],
    ],
    mockAi: "This is a VIP customer and their order has shipped — here's a suggested reply to confirm.",
    mockAiRows: [
      "This is a VIP customer and their order has shipped — here's a suggested reply to confirm.",
      "No one has replied to this customer in 10 min — I suggest escalating to the sales team.",
      "This conversation was resolved — I suggest a follow-up after delivery to measure satisfaction.",
    ],
  },
  trustSignals: ["Per-tenant data isolation", "Full audit on every step", "No card, no commitment", "Permissioned AI only"],
  stats: {
    items: [
      ["1", "One system for everything"],
      ["6", "Connected capabilities"],
      ["4+", "Unified sales channels"],
      ["24/7", "Automation that works for you"],
    ],
  },
  how: {
    title: "How it works. Three steps, that's it.",
    sub: "No complex setup, no code. Open your account and start selling on day one.",
    steps: [
      ["Connect your channels", "Website chat works today with zero setup. WhatsApp, Telegram and Instagram are coming soon. Every customer message lands in one unified inbox instead of chasing across apps."],
      ["Let context do the work", "Every conversation has a customer behind it — with their orders, payments and full history. Your team decides in seconds because everything is right there, not scattered across Excel and WhatsApp."],
      ["Let the system execute", "Automation and a smart assistant act within your permissions and rules: ready replies, order confirmations, reminders, escalations. Every step logged and reviewable."],
    ],
    more: "See the full system",
    tags: [
      ["WhatsApp", "Telegram", "Instagram", "Chat"],
      ["Orders", "Inventory", "Payments", "History"],
      ["Automation", "AI", "Reminders", "Escalation"],
    ],
  },
  graph: {
    title: "Everything connects to everything — that's what saves you time.",
    sub: "A conversation links to the customer, the customer to their orders, the order to its payment and inventory. One context moves with you across every screen. That's the difference between a system that works and disconnected tools that copy and paste.",
    hub: "Customer — the heart of context",
    nodes: ["Conversation", "Order", "Inventory", "Payment", "Automation", "AI", "Analytics"],
  },
  chat: {
    title: "Ask the demo assistant.",
    sub: "This is a real interactive demo inside the page — ask anything about the platform. Responses are simulated with no real data.",
    status: "Demo mode",
    greeting: "Welcome 👋 I'm the FIHRIST demo assistant. Ask me anything about the platform — or try a suggestion below.",
    ph: "Type your message…",
    send: "Send",
    simulated: "Simulated",
    userTag: "You",
    botTag: "FIHRIST assistant · demo",
    toolsTitle: "What actually answers inside the system",
    tools: ["Understand customer intent", "Run permitted actions", "Summarize conversations", "Suggest next reply", "Escalate to the team"],
    s1: "A customer asks: where is my order?",
    s2: "No one replied to a customer for 10 minutes",
    s3: "What makes my data safe?",
    r_intro: "FIHRIST is a complete operating system for your business: conversations from every channel, customers, orders, automation and AI — connected in one context instead of scattered tools.",
    r_pricing: "Early access is currently free across all plans. We have 3 plans (Starter / Growth / Scale) that differ by team size, channels and AI limits — details on the pricing page.",
    r_automation: "Automations follow a clear path: an event starts the run → condition → logic or AI → validation → approval when needed → action → review and audit. Example: a high-value customer messages and no one replies within 10 minutes — the run classifies the message, alerts the team and escalates if needed.",
    r_security: "Security is built in from day one: per-tenant data isolation at the database level (RLS), role-based permissions, secure session authentication, full audit logs, and AI that acts only through pre-authorized tools — with no direct database access.",
    r_channels: "Website chat is live today; WhatsApp, Telegram, Instagram and Messenger are on the integration roadmap. Every channel lands in the same inbox with the same customer context.",
    r_order: "Welcome to the interactive demo — here's what happens inside FIHRIST: the assistant reads the customer's context (orders, payments) directly from the system and answers with their actual order status — no tool-hopping for the teammate. This demo assistant answers with general platform knowledge because there's no real data behind it.",
    r_escalate: "That's exactly what automation is for: a run watches reply time — if 10 minutes pass without a human reply, it classifies the message with AI, alerts the team, and escalates if the case is sensitive. Every step is audit-logged.",
    r_fallback: "Great question. In short: FIHRIST brings conversations, customers, orders, automation and AI into one system — try asking about pricing, automation or security for more detail.",
  },
  automation: {
    title: "Automation that does real work.",
    sub: "Operational runs with events, conditions and logic — performing actions inside the system, with human approvals where needed and a full audit of every run.",
    chain: ["Event", "Condition", "AI / logic", "Tool", "Validation", "Approval", "Action", "Review", "Audit"],
    example: "Example: high-value customer flow",
    steps: ["High-value customer sends a message", "Identify the customer from context", "Check customer value", "Wait 10 minutes", "No human reply?", "AI classifies the message", "Notify the team", "Escalate if no response"],
    caps: ["Version history", "Test run", "Execution log", "Re-run", "Failure recovery"],
    more: "All automation details",
  },
  integrations: {
    title: "Your work is spread across too many tools — we bring it together.",
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
  securityTeaser: {
    colTitle: "Security",
    title: "Secure from the first line of code.",
    sub: "Per-tenant data isolation at the database level, role-based permissions, full audit — and AI that acts only through pre-authorized tools.",
    points: [
      ["Per-tenant data isolation (RLS)", "Your data is isolated at the database level from every other customer."],
      ["Roles & permissions", "Every user works within their permissions — no one crosses their limits."],
      ["AI with permissions", "AI runs only permitted actions — with no direct database access."],
      ["Full audit", "Every important change is logged: who, when, and what changed."],
    ],
    more: "All security details",
  },
  pricing: {
    title: "Clear plans that grow with your business.",
    sub: "A transparent structure from day one — no surprises, no hidden fees. Early access is free across all plans right now.",
    badge: "Early access",
    popular: "Recommended for teams",
    cta: "Start free",
    free: "Free now",
    freeNote: "during the early-access period",
    more: "Full pricing details & FAQ",
    tiers: [
      {
        name: "Solo Merchant",
        desc: "For the solo merchant starting with conversational commerce.",
        features: ["1 user", "Website chat", "Unlimited conversations & orders", "Core AI assistant", "Basic reports"],
      },
      {
        name: "Growing Team",
        desc: "For the growing team that wants deeper automation and AI.",
        features: ["Up to 10 users", "All channels, as they launch", "Advanced automation + approvals", "Expanded AI limits", "Analytics & campaign attribution"],
      },
      {
        name: "Large Operations",
        desc: "For large operations with multiple locations and teams.",
        features: ["Unlimited users", "Multiple workspaces & locations", "Advanced permissions & audit", "Custom AI limits", "Priority support"],
      },
    ],
    note: "Final pricing is set after early access — early adopters get the best terms we can offer today.",
  },
  features: {
    title: "Why FIHRIST? Six capabilities in one connected system.",
    sub: "Not a bundle of separate tools. Every capability shares the same business context — so decisions are faster, effort is lower, and results show.",
    items: [
      ["One inbox for every conversation", "Website chat, WhatsApp, Telegram and Instagram in a single inbox — with the customer's history and orders beside every message, auto-assignment, and an AI-drafted reply ready to go."],
      ["Connected business context", "A conversation links to the customer, the customer to their orders, the order to its payment and inventory — one context moves with you across every screen, no copy-pasting between tools."],
      ["Automation with paths and logic", "Runs with events, conditions and logic that perform actions inside the system — confirmations, reminders, escalations — with human approvals where needed and full audit."],
      ["AI with permissions", "An assistant that understands customer intent, replies from your data, and runs only permitted actions — with no direct database access, and every run logged."],
      ["Commerce and inventory", "Products, inventory, orders and payments — everything you need to sell and run your operation in one place, from message to shipment."],
      ["Analytics and reports", "Dashboards, KPIs and campaign tracking — decisions based on real data not guesswork, and every number has real records behind it."],
    ],
  },
  useCases: {
    title: "Who is FIHRIST for?",
    sub: "Built for everyone selling online — from the small store to the large multi-branch operation.",
    items: [
      ["E-commerce stores", "Unify sales chats, inquiries and follow-ups in one inbox, and let automation answer common questions, confirm orders, and escalate when needed."],
      ["Local businesses", "Restaurants, cafés and salons — fast customer replies, organized orders, and automatic flows for confirmations, reminders and refunds."],
      ["Marketing agencies", "Manage multiple clients' conversations from one team, with per-member permissions, per-client performance reports, and a unified dashboard."],
      ["Customer service", "Every conversation arrives with the customer's full history — no digging required, and AI suggests the reply while every run is logged."],
      ["Large operations", "Multiple sites and branches, advanced permissions, full audit — an architecture that grows with your company without rebuilding your system."],
    ],
    results: [
      "Faster response for VIP customers",
      "Reply in a minute with every step logged",
      "Commerce automation without human intervention",
    ],
  },
  faq: {
    title: "Frequently asked questions",
    sub: "Everything you need to know before you start — if your answer isn't here, ask the assistant above.",
    items: [
      ["Is it really free?", "Yes — early access is free across all plans, no card and no commitment. When real pricing starts we'll notify you at least a week before any change."],
      ["Do I need code or setup?", "No — FIHRIST is a browser platform. You create an account and start right away, no developer, no server, no maintenance."],
      ["Are my channels available?", "Website chat works today with zero setup. WhatsApp, Telegram, Instagram and Messenger are on the upcoming integration roadmap — all landing in the same inbox."],
      ["Is my data secure?", "Per-tenant data isolation at the database level (RLS), roles and permissions, secure auth sessions, and full audit logs — and the AI acts only through pre-authorized tools."],
      ["Can I cancel?", "Yes — you can delete your account and data anytime, with no commitment."],
      ["Does the AI use my data for training?", "No — your data is never used to train any model, and never sold or shared with anyone."],
    ],
  },
  final: {
    title: "One business context. One operating system.",
    sub: "Start today for free — no card, no commitment. See for yourself how everything works inside the system.",
    start: "Start free",
    explore: "See how it works",
  },
  footer: {
    tag: "The conversational operating system for your business.",
    product: "Product",
    system: "System",
    status: "Status",
    privacy: "Privacy Policy",
    terms: "Terms of Use",
    rights: "© 2026 FIHRIST",
    earlyAccess: "Early access",
    contact: "Questions? Email Hamed Adel:",
  },
  auth: {
    valueTitle: "The conversational operating system for your business",
    valueSub: "Conversations, customers, orders, automation and AI — in one connected context.",
    valuePoints: [
      "One inbox for every conversation across all channels",
      "Connected business context — faster decisions, less effort",
      "Automation and AI with permissions and full audit",
    ],
    valueBadge: "Early access free · No card required",
    loginTitle: "Welcome back",
    loginSub: "Sign in to continue to your workspace.",
    email: "Email",
    password: "Password",
    submitLogin: "Sign in",
    submittingLogin: "Signing in…",
    noAccount: "No account yet?",
    createAccount: "Create one",
    signupTitle: "Create your account",
    signupSub: "Email and password — you're in. Your workspace name is generated automatically; you can change it inside the app.",
    storeName: "Store / business name",
    fullName: "Full name",
    submitSignup: "Create account",
    submittingSignup: "Creating account…",
    haveAccount: "Already have an account?",
    signin: "Sign in",
    pwHint: "At least 8 characters",
    showPw: "Show",
    hidePw: "Hide",
    errInvalid: "The email or password is incorrect.",
    errRate: "Too many attempts. Please try again later.",
    errNetwork: "Can't reach the server. Check your connection and try again.",
    errGeneric: "An unexpected error occurred. Please try again.",
    errExists: "This email is already registered. Sign in or use another email.",
    errCreate: "Couldn't create the account. Please try again.",
    errPw: "Password must be at least 8 characters.",
    errEmail: "That email address doesn't look right.",
    errAutoLogin: "Account created but automatic sign-in failed — please sign in manually.",
    dismiss: "OK",
    privacy: "Privacy Policy",
    terms: "Terms of Use",
  },

  pages: {
      product: {
        title: "A complete operating system for your business — not a standalone tool.",
        sub: "FIHRIST isn't a CRM alone or a chatbot alone — one environment that runs sales, service and operations, with a single context covering everything. Every capability talks to the next, so decisions are faster and effort is lower.",
        features: [
          ["Unified conversations", "Every customer channel in one inbox: automatic assignment, AI drafts, and team handoff with full context — nobody leaves the conversation to hunt for information."],
          ["Customers, orders & inventory", "One record per customer: their orders, payments, history and preferred channel. Orders tie into inventory — from message to shipment."],
          ["AI that follows your rules", "An assistant that understands your conversations, answers from your company knowledge, and performs real actions — through pre-authorized tools only, with every step logged."],
          ["Operational automation", "Runs with events, conditions and logic: reminders, classification, notifications, escalation — with human approvals for sensitive steps."],
          ["Analytics tied to reality", "Every number has real records behind it — trace any metric to the insight, the source records, and the action taken."],
          ["Built to scale", "Multi-tenant with database-level data isolation — architecture ready to grow with your company."],
        ],
        forWho: {
          title: "Who is this system for?",
          items: [
            ["A new online business", "That wants to run sales and service from one place instead of scattered groups, posts and chats."],
            ["A customer-service team", "That needs every conversation to arrive with the customer's history and orders — plus fast AI-assisted replies."],
            ["A growing operation", "That needs real automation, permissions and audit — before scale breaks the experience."],
          ],
        },
        cta: "Ready to see it for yourself?",
      },
    context: {
      title: "One context. Zero repetition.",
      sub: "Disconnected tools write the same information in five places — and none of them sees the full picture. FIHRIST fixes this at the root.",
      problem: {
        title: "The problem: disconnected tools",
        items: [
          ["Information is duplicated", "The customer lives in the CRM, their conversation in a chat app, their order somewhere else — and each tool sees a fragment."],
          ["Decisions go blind", "The teammate replies without knowing this customer has been slipping away for weeks, or that their order is late."],
          ["Automation falls short", "Automation in an isolated tool can't see conversations or orders — so it only sends notifications."],
        ],
      },
      solution: {
        title: "The solution: one source of truth",
        items: [
          ["The customer at the center", "Every entity — conversation, order, payment, campaign — links to the same context automatically."],
          ["Context travels", "Open any conversation and everything behind it is there. Any change anywhere is visible everywhere."],
          ["AI feeds on it", "The assistant answers from the same context — not from stale summaries."],
        ],
      },
      cta: "Try the context inside the system",
    },
    conversations: {
      title: "All conversations, one inbox.",
      sub: "Whatever the channel — the conversation lands in the same place, with everything about the customer behind it.",
      channels: {
        title: "Channels",
        items: [
          ["Website chat", "Live today — a direct channel with no external dependencies."],
          ["WhatsApp", "The core commerce channel — on the integration roadmap."],
          ["Telegram", "Chats and communities — coming soon."],
          ["Instagram & Messenger", "Social messaging — coming soon."],
        ],
      },
      inbox: {
        title: "What makes your team faster?",
        items: [
          ["Context beside every conversation", "The customer, their orders and history are visible next to the message — no searching in other tools."],
          ["AI drafts", "The assistant suggests a ready reply for review — the teammate edits and sends in one click."],
          ["Handoff with full context", "When things get complex, the transfer to a teammate is one line — and whoever picks up gets everything ready."],
          ["Clear priorities", "The system raises conversations nearing the reply-time limit — so no customer gets forgotten."],
        ],
      },
      handoff: {
        title: "AI assists. Humans decide.",
        steps: [
          ["AI", "AI handles the routine", "Intent · permitted actions · reply drafts"],
          ["Detect", "Complex situations detected", "Complaint · refund · frustrated customer"],
          ["Handoff", "Routed to a teammate", "By expertise and workload"],
          ["Human", "Teammate picks up ready", "Summary + order + payment + history"],
        ],
      },
      cta: "Start with website chat today",
    },
    ai: {
      title: "AI that works within your rules.",
      sub: "Not a black box, not a bolt-on chat window — an assistant built into the system that respects your permissions and policies, and logs every word it says.",
      loop: {
        title: "The 8-step loop",
        steps: ["Understand", "Retrieve context", "Reason", "Use tools", "Validate", "Act", "Review", "Hand off"],
      },
      can: {
        title: "What can it do?",
        items: [
          ["Answer from your knowledge", "From your products and policies — not from the random internet."],
          ["Perform real actions", "Check an order status, update data, create a task — through pre-authorized tools only."],
          ["Summarize and suggest", "Summarize long conversations and suggest the team's next reply."],
          ["Know its limits", "If the case is outside its permissions — it hands off to humans immediately, no pretending."],
        ],
      },
      guard: {
        title: "What keeps it in check",
        items: [
          ["Roles & permissions", "AI only sees what its role allows — enforced at the API level."],
          ["Approved tools", "No direct database access — every action goes through a pre-approved, pre-defined tool."],
          ["Human approvals", "Sensitive steps (refunds, discounts, cancellations) require human approval."],
          ["Cost limits", "A usage ceiling per tenant — no surprise invoices."],
          ["Full audit", "Every run is logged: the question, the context, the tools used, the outcome."],
          ["Permission-filtered knowledge", "The assistant answers from your company knowledge according to each user's permissions."],
        ],
      },
      cta: "See the AI inside the system",
    },
    automationPage: {
      title: "Describe it. Build it. Run it.",
      sub: "Real operational automation — performing business actions inside the system: orders, notifications, escalation, follow-up. Not just email alerts.",
      chainTitle: "Run anatomy",
      exampleTitle: "Example: high-value customer flow",
      capsTitle: "Run management",
      caps: [
        ["Version history", "Every change to the run is saved — roll back to any version anytime."],
        ["Test run", "Test the flow on sample data before it touches real customers."],
        ["Execution log", "Every run is logged step by step — you know exactly what happened and why."],
        ["Re-run", "An external provider call failed? Re-run the flow from the point of failure."],
        ["Failure recovery", "Failed runs show up in your priorities with the cause and a re-run action."],
      ],
      guardTitle: "Guardrails",
      guardItems: [
        ["Validation before action", "Every step validates its data before acting."],
        ["Human approval", "Sensitive actions require approval — you decide what counts as sensitive."],
        ["Full audit", "Every run leaves a permanent audit trail."],
      ],
      cta: "Build your first flow",
    },
    pricingPage: {
      title: "Pricing & plans.",
      sub: "A clear structure — and free early access for every plan. No card, no commitment.",
      faqTitle: "Frequently asked questions",
      faq: [
        ["Is early access really free?", "Yes — all plans are free during the early-access period, with no card and no commitment."],
        ["What happens after early access?", "Final pricing will be set after this period, and early adopters get the best terms we can offer today — we'll notify you before any change."],
        ["What differs between plans?", "Team size (users), available channels, AI usage limits, and support level."],
        ["What do I need to start?", "An email and a password — the account takes a minute and you're in. Your workspace name is generated automatically."],
        ["Is my data separated from other customers?", "Yes — database-level isolation (RLS) per tenant, not just UI filtering."],
        ["Can I leave anytime?", "Yes — and your workspace data is yours. Deletion and export are part of the system."],
      ],
      cta: "Start free today",
    },
    securityPage: {
      title: "Security & control.",
      sub: "Our principle is simple: we only claim what's actually built. Everything below runs in the system today.",
      areas: [
        ["Per-tenant data isolation", "Each company's data is isolated at the database level itself (Row-Level Security) — not UI filtering. Even a buggy query can't see another tenant's data."],
        ["Roles & permissions", "Roles and permissions are enforced in the API layer before anything executes — the interface is just a view; the real protection is the operations."],
        ["Secure session authentication", "Short-lived access tokens with automatic rotation, and safe logout that invalidates sessions."],
        ["Audit logs", "Every important change is recorded: who, when, what changed — with a permanent, reviewable reference."],
        ["Separate AI permissions", "AI has no direct database access at all — it acts through pre-defined, pre-authorized tools, and every run is fully logged."],
        ["Webhook & request protection", "Verification of incoming webhook signatures and duplicate-request prevention (idempotency) — a lost or repeated call causes no harm."],
        ["Monitoring & control", "Everything the system does — agents, automations, pending approvals, failed jobs — is visible in a control center inside the app, never hidden."],
      ],
      honest: "We don't claim certifications we don't hold yet — and we won't until we actually earn them. What you see above is the implemented foundation, updated with every build phase.",
      cta: "Try it with peace of mind",
    },
    privacy: {
      title: "Privacy Policy",
      updated: "Last updated: September 2026",
      intro: "Privacy here isn't a legal page — it's part of the system design. This policy explains, in plain language, what actually happens to your data.",
      sections: [
        ["Data we collect", "Account data: your name, email and the business name you enter at signup. Workspace data: everything you enter or arrives from your channels (conversations, orders, settings). Operational logs: sign-in times and audit records required to run the system safely."],
        ["How we store and protect it", "Each customer's data is isolated at the database level (Row-Level Security) from all other customers. Data access is restricted by roles and permissions, and every sensitive operation has an audit record."],
        ["AI and your data", "AI processing happens through an external provider (Google Gemini) when the assistant or knowledge search is used. We do not use your data to train AI models, and we never sell data to anyone. AI permissions are scoped to pre-authorized tools."],
        ["Cookies", "We use essential local storage only, to keep your session and preferences (language and theme). No advertising trackers."],
        ["Retention & deletion", "Your workspace data is yours — deletion and export are part of the system. During early access, the formal data-request channel is being prepared, and any deletion request is executed manually and immediately in the meantime."],
        ["Policy changes", "If the policy changes materially, we notify users inside the system before the change takes effect."],
        ["Contact", "Questions about this policy or your data? Email Hamed Adel at 7ari9aa@gmail.com."],
      ],
      cta: "Any privacy question? Ask the assistant on the homepage.",
    },
    terms: {
      title: "Terms of Use",
      updated: "Last updated: September 2026",
      intro: "These terms govern your use of the FIHRIST platform. We wrote them clearly and briefly so you'd actually read them.",
      sections: [
        ["The service is in early access", "FIHRIST is in active development. Features change and improve quickly, and interruptions can happen. We build carefully, but at this stage there's no guarantee of full service continuity."],
        ["Your account", "You're responsible for keeping your credentials secure and for everything that happens through your account. Report suspected unauthorized use immediately to 7ari9aa@gmail.com."],
        ["Acceptable use", "Don't use the platform for anything illegal or harmful, to harass others, or to attempt to breach, disrupt, or access data that isn't yours."],
        ["Your content", "What you enter — content and data — belongs to you; we use it only to operate the service for you. Platform ownership and software belong to us."],
        ["Billing", "Early access is free. When real pricing begins, we'll notify you before any change — and you can leave before it applies."],
        ["Termination", "You can delete your account anytime. We can suspend an account that violates acceptable use — with notice in normal circumstances."],
        ["Disclaimer", "The service is provided \"as is\" during early access. We strive for the best possible experience, but we don't guarantee specific business outcomes."],
        ["Changes to terms", "If the terms change materially, we notify you inside the system. Continued use after a change means acceptance."],
      ],
      cta: "Sound good? Start now.",
    },
  },
};

export type Dict = typeof ar;

const DICTS: Record<Locale, Dict> = { ar, en };

/* ------------------------------------------------------------------ */
/* Contexts                                                            */
/* ------------------------------------------------------------------ */

type I18nCtx = {
  locale: Locale;
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

function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

export function FihristProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("ar");
  const [theme, setThemeState] = useState<Theme>("light");

  useEffect(() => {
    const savedLocale = window.localStorage.getItem(LOCALE_KEY) as Locale | null;
    if (savedLocale === "en" || savedLocale === "ar") {
      setLocaleState(savedLocale);
      document.documentElement.lang = savedLocale;
    }
    const savedTheme = window.localStorage.getItem(THEME_KEY) as Theme | null;
    if (savedTheme === "dark" || savedTheme === "light") setThemeState(savedTheme);
    else if (window.matchMedia("(prefers-color-scheme: dark)").matches) setThemeState("dark");
  }, []);

  const setLocale = useCallback((l: Locale) => {
    setLocaleState(l);
    store(LOCALE_KEY, l);
    // keep <html lang> in sync for screen readers and font selection
    document.documentElement.lang = l;
  }, []);

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t);
    store(THEME_KEY, t);
  }, []);

  const toggleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next = prev === "light" ? "dark" : "light";
      store(THEME_KEY, next);
      return next;
    });
  }, []);

  // الترجمة نصية فقط — الاتجاه ثابت RTL مهما كانت اللغة
  const i18nValue = useMemo<I18nCtx>(() => ({ locale, t: DICTS[locale], setLocale }), [locale, setLocale]);
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

/** جذر الموقع العام: بيحمل اللغة والثيم + كلاس العزل — الاتجاه RTL ثابت */
export function FihristRoot({
  children,
  bare = false,
  className = "",
}: {
  children: React.ReactNode;
  bare?: boolean;
  className?: string;
}) {
  const { locale } = useI18n();
  const { theme } = useTheme();
  return (
    <div
      lang={locale}
      data-theme={theme}
      className={`fh-root${bare ? " fh-root-bare" : ""} ${className}`.trim()}
    >
      {children}
    </div>
  );
}
