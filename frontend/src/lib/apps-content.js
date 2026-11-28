// One entry per registered application in the backend registry.
//
// The keys mirror app/modules/applications/manifests.py. A page here describes what
// the application does for a store; it never promises a feature the code does not
// have, because the same list decides what a plan can include.
export const APPS = {
  'retail-core': {
    kicker: { ar: 'البيع والمخزون الأساسي', en: 'Core selling and stock' },
    title: { ar: 'التطبيق الأساسي للمحل — من FIHRIST', en: 'The store core application — built into FIHRIST' },
    description: {
      ar: 'المنتجات والمقاسات والتصنيفات والماركات والأرصدة والكاشير في مكان واحد، وهو التطبيق الذي تعتمد عليه باقي التطبيقات.',
      en: 'Products, variants, categories, brands, balances and the cashier in one place. Every other application depends on it.',
    },
    points: {
      ar: ['كتالوج بمقاسات وباركود وصور', 'أرصدة فورية مع كل بيع أو مرتجع', 'كاشير يشتغل على الديسكتوب والموبايل'],
      en: ['Catalog with variants, barcodes and photos', 'Live balances with every sale or return', 'A cashier on desktop and mobile'],
    },
  },
  'retail-purchasing': {
    kicker: { ar: 'المشتريات والموردين', en: 'Purchasing and suppliers' },
    title: { ar: 'من المورد إلى الرف — من FIHRIST', en: 'From supplier to shelf — built into FIHRIST' },
    description: {
      ar: 'أوامر شراء وموردين واستلام بضاعة يحدّث الأرصدة، عشان تعرف كل قطعة جت منين وراحت فين.',
      en: 'Purchase orders, suppliers and goods receipts that update balances, so every piece has a traceable origin.',
    },
    points: {
      ar: ['أمر شراء بسعر التكلفة والتوريد', 'استلام يرفع الرصيد مباشرة', 'سجل لكل مورد وتكلفته'],
      en: ['Purchase orders with cost and lead time', 'Receipts that raise stock immediately', 'A history per supplier and cost'],
    },
  },
  'retail-warehouse': {
    kicker: { ar: 'المخزن والتحويلات', en: 'Warehouse and transfers' },
    title: { ar: 'مخزن مركزي وفروع — من FIHRIST — من FIHRIST', en: 'A central warehouse and branches' },
    description: {
      ar: 'لما يبقى عندك أكتر من موقع، التطبيق ده بينقل البضاعة بينهم ويحافظ على رصيد كل موقع صح.',
      en: 'When you have more than one location, this moves stock between them and keeps each location correct.',
    },
    points: {
      ar: ['تحويل بين المخزن والفرع', 'رصيد منفصل لكل موقع', 'مراجعة الفروق قبل الاعتماد'],
      en: ['Transfers between warehouse and branch', 'A separate balance per location', 'Review differences before approving'],
    },
  },
  'inventory-advanced': {
    kicker: { ar: 'المخزون المتقدم', en: 'Advanced inventory' },
    title: { ar: 'حدود التنبيه والتسويات — من FIHRIST', en: 'Alert thresholds and adjustments' },
    description: {
      ar: 'حد أدنى لكل منتج وتنبيه قبل ما تخلص، وتسويات موثقة للجرد والتالف.',
      en: 'A minimum per product with an alert before it runs out, and documented adjustments for counts and damage.',
    },
    points: {
      ar: ['حد تنبيه لكل منتج ومقاس', 'تسويات جرد وتالف بسبب مسجّل', 'قائمة النواقص قبل ما تبيع'],
      en: ['An alert threshold per product and variant', 'Count and damage adjustments with a recorded reason', 'A shortage list before you sell'],
    },
  },
  'customer-engagement': {
    kicker: { ar: 'العملاء والمتابعة', en: 'Customers and follow-up' },
    title: { ar: 'ملف العميل ومحادثاته — من FIHRIST', en: 'The customer file and their conversations' },
    description: {
      ar: 'كل عميل بملف واحد: محادثاته وطلباته ومشترياته، ومتابعة اللي سكتوا.',
      en: 'One file per customer: their conversations, orders and purchases, plus follow-up on the ones who went quiet.',
    },
    points: {
      ar: ['صندوق موحّد لكل القنوات', 'سجل شراء لكل عميل', 'تذكيرات متابعة تلقائية'],
      en: ['One inbox across channels', 'A purchase history per customer', 'Automatic follow-up reminders'],
    },
  },
  'ai-support': {
    kicker: { ar: 'مساعد الردود', en: 'Reply assistant' },
    title: { ar: 'ردود بلهجة محلك — من FIHRIST — من FIHRIST', en: 'Replies in your store voice — built into FIHRIST' },
    description: {
      ar: 'مساعد بيقرأ محادثة العميل ويرد بلهجة محلك، وبيسيب القرار النهائي لك.',
      en: 'An assistant that reads the conversation and drafts a reply in your store voice, leaving the decision to you.',
    },
    points: {
      ar: ['ردود مقترحة من كتالوجك', 'تسليم للفريق عند الحاجة', 'بلا قوالب ثابتة'],
      en: ['Drafted replies grounded in your catalog', 'Handover to the team when needed', 'No canned templates'],
    },
  },
  'business-intelligence': {
    kicker: { ar: 'قراءة الأرقام', en: 'Reading the numbers' },
    title: { ar: 'أداء المحل في صورة — من FIHRIST', en: 'Store performance in one view — built into FIHRIST' },
    description: {
      ar: 'تقارير المبيعات والأرباح والمخزون الراكد، وإجابات على أسئلتك عن الأرقام بلغة واضحة.',
      en: 'Sales, profit and dead-stock reports, with answers to your questions about the numbers in plain language.',
    },
    points: {
      ar: ['ربح لكل منتج وموسم', 'المخزون الراكد وما يحتاج تصفية', 'سؤال بالعربي وإجابة من بياناتك'],
      en: ['Profit per product and season', 'Dead stock and what needs clearing', 'Ask in Arabic, answered from your data'],
    },
  },
}
