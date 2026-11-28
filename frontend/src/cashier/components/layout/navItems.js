// بنية التنقل: صفحات الكاشير كبنود رئيسية مباشرة في السايدبار الرئيسي (بدون مجموعات متداخلة).
// الإعدادات ليست هنا: قسم الإعدادات واحد فقط في النظام الرئيسي.

import {
  BarChart3,
  Boxes,
  ClipboardList,
  List,
  Plus,
  Printer,
  Receipt,
  ReceiptText,
  RefreshCw,
  RotateCcw,
  ScanBarcode,
  Shirt,
  ShoppingBag,
  Truck,
  Undo2,
  Wallet,
} from "lucide-react";

export const navGroups = [
  {
    title: "البيع",
    titleKey: "nav.salesAndPos",
    items: [
      { to: "/pos", label: "الكاشير", icon: ScanBarcode },
      { to: "/returns", label: "المرتجع", icon: RotateCcw },
      { to: "/exchanges", label: "الاستبدال", icon: RefreshCw },
      { to: "/sales", label: "سجل المبيعات", icon: Receipt },
      { to: "/shifts", label: "الورديات والخزنة", icon: Wallet },
    ],
  },
  {
    title: "المنتجات",
    titleKey: "nav.products",
    items: [
      { to: "/products", label: "المنتجات", icon: Shirt },
      { to: "/products/new", label: "إضافة منتج", icon: Plus },
      { to: "/labels", label: "طباعة باركود", icon: Printer },
    ],
  },
  {
    title: "المخزون",
    titleKey: "nav.stock",
    items: [
      {
        to: "/inventory",
        label: "المخزون",
        icon: Boxes,
        // كل واحدة صفحة مستقلة بمسارها بدل تبويبات في صفحة واحدة.
        children: [
          { to: "/inventory/movements", label: "حركة الأصناف", icon: ClipboardList },
          { to: "/inventory/stocktake", label: "الجرد الفعلي", icon: List },
          { to: "/inventory/import", label: "استيراد الأصناف", icon: RefreshCw },
        ],
      },
      {
        to: "/supply-chain",
        label: "سلاسل الإمداد",
        icon: Truck,
        children: [
          { to: "/supply-chain/receipts", label: "أذونات الاستلام والجودة", icon: ClipboardList },
          { to: "/supply-chain/transfers", label: "التحويلات بين المستودعات", icon: RefreshCw },
          { to: "/supply-chain/replenishment", label: "محرك التجديد", icon: Plus },
          { to: "/supply-chain/locations", label: "المواقع والرفوف", icon: Boxes },
          { to: "/supply-chain/valuation", label: "التقييم والتكاليف", icon: Wallet },
          { to: "/supply-chain/traceability", label: "التتبع والدفعات", icon: ScanBarcode },
          { to: "/supply-chain/allocations", label: "تخصيص القنوات", icon: Truck },
        ],
      },
    ],
  },
  {
    title: "الموردون والمشتريات",
    titleKey: "nav.suppliersAndPurchases",
    items: [
      { to: "/suppliers", label: "الموردون", icon: Truck },
      { to: "/purchases", label: "المشتريات", icon: ShoppingBag },
      { to: "/supplier-returns", label: "مرتجعات الموردين", icon: Undo2 },
      { to: "/expenses", label: "المصروفات", icon: ReceiptText },
    ],
  },
  {
    title: "التقارير وسجل العمليات",
    titleKey: "nav.reportsAndLogs",
    items: [
      { to: "/reports", label: "التقارير", icon: BarChart3 },
      { to: "/activity-log", label: "سجل العمليات", icon: ClipboardList },
    ],
  },
];


/**
 * يحوّل بنود الكاشير لبنود السايدبار تحت /cashier مع أبنائها.
 *
 * كان السايدبار بيعيد بناء البنود يدويًا (to/label/icon/badge) فيضيّع children، فبند المخزون
 * وسلاسل الإمداد كانوا بيوصلوا للشاشة من غير تفريع. الدالة دي مسؤولة عن التحويل لوحدها
 * ومغطاة باختبار.
 */
export function toCashierNav(groups = navGroups, { badge } = {}) {
  return groups.map((group) => ({
    titleKey: group.titleKey,
    title: group.title,
    items: group.items.map((item) => ({
      to: `/cashier${item.to}`,
      label: item.label,
      icon: item.icon,
      badge: badge ? badge(item) : undefined,
      children: (item.children || []).map((child) => ({
        to: `/cashier${child.to}`,
        label: child.label,
        icon: child.icon,
      })),
    })),
  }));
}

export const flatNav = navGroups.flatMap((g) => g.items);

export function pageTitle(pathname) {
  if (pathname === "/pos") return "الكاشير";
  if (pathname === "/products") return "المنتجات";
  if (pathname === "/products/new") return "إضافة منتج";
  if (pathname.startsWith("/products/") && pathname.endsWith("/edit")) return "تعديل منتج";
  if (pathname === "/inventory/movements") return "حركة الأصناف";
  if (pathname === "/inventory/stocktake") return "الجرد الفعلي";
  if (pathname === "/supply-chain" || pathname === "/cashier/supply-chain") return "سلاسل الإمداد والمستودعات";
  // Each supply-chain module is its own page now, so the header names the module, not the section.
  const supplySection = pathname.replace(/^\/cashier/, "").match(/^\/supply-chain\/([a-z-]+)$/);
  if (supplySection) {
    const titles = {
      receipts: "أذونات الاستلام والجودة",
      transfers: "التحويلات بين المستودعات",
      replenishment: "محرك التجديد وإعادة الشراء",
      locations: "المواقع والرفوف الداخلية",
      valuation: "تقييم FIFO والتكاليف",
      traceability: "التتبع والدفعات والسيريال",
      allocations: "تخصيص القنوات",
    };
    if (titles[supplySection[1]]) return titles[supplySection[1]];
  }
  if (pathname === "/returns/log") return "سجل المرتجعات";
  if (pathname === "/exchanges/log") return "سجل الاستبدال";
  const match = flatNav
    .filter((item) => pathname === item.to || pathname.startsWith(`${item.to}/`))
    .sort((a, b) => b.to.length - a.to.length)[0];
  return match?.label ?? "الكاشير";
}
// اسم صريح للاستخدام من سايدبار النظام الرئيسي.
export const cashierNavGroups = navGroups;
/** الـ14 بند الرئيسية للكاشير بترتيبها، مباشرة في السايدبار. */
export const cashierNavItems = flatNav;

// قطاع الملابس المفرد مش محتاج «سلاسل الإمداد» (توزيع، مستودعات متعددة، تخصيص قنوات).
// البند بيختفي من التنقل، لكن مساراته وصفحاته تفضل في الكود كما هي لحد ما يبقى فيه عميل توزيع.
export const SHOW_SUPPLY_CHAIN = false;

if (!SHOW_SUPPLY_CHAIN) {
  for (const group of navGroups) {
    group.items = group.items.filter((item) => item.to !== "/supply-chain");
  }
}
