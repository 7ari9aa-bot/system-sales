// سجل تطبيق الملابس في الواجهة: مصدر واحد لقائمة الشاشات وصلاحياتها.
//
// الشاشات تُعلن مسارها المستهدف تحت /apparel ومسارها الحالي الذي يعمل الآن،
// فالنقل يتم بمسارات توافق تحفظ كل رابط قديم (industry-applications §11).
// الاختبار يقرأ سجل الـBackend الفعلي ويرفض أي اختلاف بينهما.

export const APPAREL = {
  key: "apparel",
  industry: "apparel",
  titleAr: "FIHRIST للملابس",
  titleEn: "FIHRIST Apparel",
  version: "1.0.0",
  entrypoint: "/apparel/dashboard",
};

/** الشاشات التي تخص الهيكل نفسه لا وحدة تجارية. */
export const SHELL = "__shell__";

export const apparelSections = [
  {
    key: "sell",
    titleAr: "البيع",
    items: [
      { path: "/apparel/pos", currentPath: "/cashier/pos", label: "الكاشير", module: "pos", permission: "apparel.pos.access" },
      { path: "/apparel/returns", currentPath: "/cashier/returns", label: "المرتجعات", module: "returns", permission: "apparel.returns.view" },
      { path: "/apparel/sales", currentPath: "/cashier/sales", label: "سجل المبيعات", module: "sales", permission: "apparel.sales.view" },
    ],
  },
  {
    key: "catalog",
    titleAr: "المنتجات",
    items: [
      { path: "/apparel/products", currentPath: "/cashier/products", label: "المنتجات", module: "catalog", permission: "apparel.products.view" },
      { path: "/apparel/products/new", currentPath: "/cashier/products/new", label: "إضافة منتج", module: "catalog", permission: "apparel.products.create" },
    ],
  },
  {
    key: "stock",
    titleAr: "المخزون والمشتريات",
    items: [
      { path: "/apparel/inventory", currentPath: "/cashier/inventory", label: "المخزون", module: "inventory", permission: "apparel.inventory.view" },
      { path: "/apparel/purchases", currentPath: "/cashier/purchases", label: "المشتريات", module: "purchasing", permission: "apparel.purchases.view" },
      { path: "/apparel/suppliers", currentPath: "/cashier/suppliers", label: "الموردون", module: "purchasing", permission: "apparel.purchases.view" },
    ],
  },
  {
    key: "engage",
    titleAr: "العملاء والرسائل",
    items: [
      { path: "/apparel/customers", currentPath: "/customers", label: "العملاء", module: "customers", permission: "apparel.customers.view" },
      { path: "/apparel/inbox", currentPath: "/inbox", label: "صندوق الرسائل", module: "integrations", permission: "apparel.integrations.view" },
      { path: "/apparel/marketing", currentPath: "/marketing", label: "الحملات", module: "integrations", permission: "apparel.integrations.manage" },
    ],
  },
  {
    key: "insight",
    titleAr: "التحليل والمساعدة",
    items: [
      { path: "/apparel/reports", currentPath: "/cashier/reports", label: "التقارير", module: "reporting", permission: "apparel.reports.view" },
      { path: "/apparel/assistant", currentPath: "/sales-assistant", label: "المساعد الذكي", module: "ai", permission: "apparel.ai.manage" },
    ],
  },
  {
    key: "shell",
    titleAr: "عام",
    items: [
      { path: "/apparel/dashboard", currentPath: "/dashboard", label: "لوحة التحكم", module: SHELL, permission: "apparel.dashboard.view" },
      { path: "/apparel/settings", currentPath: "/settings", label: "إعدادات المتجر", module: SHELL, permission: null },
    ],
  },
];

/** كل الشاشات المسطحة، بلا مجموعات. */
export const apparelScreens = apparelSections.flatMap((section) => section.items);

export const apparelPaths = apparelScreens.map((screen) => screen.path);

/**
 * هل يملك هذا المستخدم صلاحية الشاشة؟
 *
 * إخفاء بند من السايدبار ليس حماية: هذه الدالة تُستخدم لتقرير ما يُعرض،
 * والخادم يتحقق من الصلاحية مرة أخرى على كل طلب (industry-applications §11).
 */
export function canSeeScreen(screen, permissionCodes) {
  if (!screen.permission) return true;
  const held = permissionCodes instanceof Set ? permissionCodes : new Set(permissionCodes || []);
  return held.has(screen.permission);
}

/** الشاشات التي يراها مستخدم بصلاحيات معيّنة. */
export function visibleScreens(permissionCodes) {
  return apparelScreens.filter((screen) => canSeeScreen(screen, permissionCodes));
}
