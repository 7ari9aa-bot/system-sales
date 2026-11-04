// بنية التنقل: صفحات الكاشير كبنود رئيسية مباشرة في السايدبار الرئيسي (بدون مجموعات متداخلة).
// الإعدادات ليست هنا: قسم الإعدادات واحد فقط في النظام الرئيسي.

import {
  BarChart3,
  Boxes,
  ClipboardList,
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
    title: "المنتجات والمخزون",
    titleKey: "nav.productsAndStock",
    items: [
      { to: "/products/new", label: "إضافة منتج", icon: Shirt },
      { to: "/labels", label: "طباعة باركود", icon: Printer },
      { to: "/inventory", label: "المخزون", icon: Boxes },
    ],
  },
  {
    title: "الموردون والمشتريات والمصروفات",
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

export const flatNav = navGroups.flatMap((g) => g.items);

export function pageTitle(pathname) {
  if (pathname === "/pos") return "الكاشير";
  if (pathname === "/products/new") return "إضافة منتج";
  if (pathname.startsWith("/products/") && pathname.endsWith("/edit")) return "تعديل منتج";
  if (pathname === "/inventory/movements") return "حركة الأصناف";
  if (pathname === "/inventory/stocktake") return "الجرد الفعلي";
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
