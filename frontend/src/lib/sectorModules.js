// تعريف موديولات كل قطاع: القطاع هو اللي بيحدد الموديولات اللي ليه، وكل موديول لازم يكون ليه وظيفة حقيقية
// في القطاع ده ومسار API بيخدمها. أي موديول بلا وظيفة في القطاع مش بيتحسب عليه، وده تعريف قطاع مش إخفاء بند.
//
// الشكل: { key, title, function, pages: [{ to, label }], capability }
// key يطابق مفتاح التطبيق في سجل الـmanifests في الباك إند (backend/app/modules/applications).

export const APPAREL_MODULES = [
  {
    key: "retail.core",
    title: "البيع والمخزون",
    function: "يبيع من الكاشير ويسجل الوردية والخزنة، وبيعرض الأرصدة وحركة الأصناف والجرد.",
    capability: "retail.core",
    pages: [
      { to: "/pos", label: "الكاشير" },
      { to: "/returns", label: "المرتجع" },
      { to: "/exchanges", label: "الاستبدال" },
      { to: "/sales", label: "سجل المبيعات" },
      { to: "/shifts", label: "الورديات والخزنة" },
      { to: "/inventory", label: "المخزون" },
      { to: "/inventory/movements", label: "حركة الأصناف" },
      { to: "/inventory/stocktake", label: "الجرد الفعلي" },
    ],
  },
  {
    key: "retail.catalog",
    title: "المنتجات",
    function: "يدخل المنتج بمقاساته ولونه وماركته وموسمه، ويطبع الباركود ويربط المقاس بالكمية.",
    capability: "retail.core",
    pages: [
      { to: "/products", label: "المنتجات" },
      { to: "/products/new", label: "إضافة منتج" },
      { to: "/labels", label: "طباعة باركود" },
      { to: "/inventory/import", label: "استيراد الأصناف" },
    ],
  },
  {
    key: "retail.purchasing",
    title: "الموردون والمشتريات",
    function: "يشتري من المورد، ويستلم الأصناف بفحص جودة وكمية، ويحدد تكلفتها على الصنف.",
    capability: "retail.purchasing",
    pages: [
      { to: "/suppliers", label: "الموردون" },
      { to: "/purchases", label: "المشتريات" },
      { to: "/supply-chain/receipts", label: "أذونات الاستلام والجودة" },
      { to: "/supply-chain/valuation", label: "التقييم والتكاليف" },
    ],
  },
  {
    key: "retail.warehouse",
    title: "المخزون المتقدم",
    function: "ينقل الأصناف بين فروع المحل، ويتبع الدفعة، ويعرف فين الصنف واقف.",
    capability: "retail.warehouse",
    pages: [
      { to: "/supply-chain/transfers", label: "التحويلات بين الفروع" },
      { to: "/supply-chain/locations", label: "المواقع والرفوف" },
      { to: "/supply-chain/traceability", label: "التتبع والدفعات" },
    ],
  },
  {
    key: "customer.engagement",
    title: "العملاء والمحادثات",
    function: "يجمع بيانات العميل ومقاساته المفضلة، ويجمع رسايل إنستجرام وفيسبوك في صندوق واحد.",
    capability: "customer.engagement",
    pages: [
      { to: "/customers", label: "العملاء" },
      { to: "/inbox", label: "صندوق المحادثات" },
    ],
  },
];

// موديولات موجودة في المنصة وليها وظيفة في قطاعات تانية (توزيع، تجزئة متعددة القنوات) مش في محل الملابس.
// مش مخفية: ليها تعريفها في قطاعها، وبس بتظهر لما القطاع يطلبها.
export const OUT_OF_SCOPE_FOR_APPAREL = [
  {
    key: "retail.supply_chain_allocation",
    title: "تخصيص القنوات والتجديد",
    function: "يوزع الكميات على قنوات بيع ومستودعات متعددة، ويولّد أوامر تجديد تلقائية.",
    pages: [
      { to: "/supply-chain/allocations", label: "تخصيص القنوات" },
      { to: "/supply-chain/replenishment", label: "محرك التجديد" },
    ],
  },
];

export const SECTOR_MODULES = { apparel: APPAREL_MODULES };

export function modulesForSector(sector) {
  return SECTOR_MODULES[sector] ?? APPAREL_MODULES;
}

/** كل الصفحات اللي ليها موديول ووظيفة في القطاع، عشان نمنع أي بند بلا وظيفة. */
export function mappedPaths(sector) {
  return modulesForSector(sector).flatMap((m) => m.pages.map((p) => p.to));
}
