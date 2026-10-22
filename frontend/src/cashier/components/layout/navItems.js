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
    items: [
      { to: "/pos", label: "الكاشير / المبيعات", icon: ScanBarcode },
      { to: "/sales", label: "سجل المبيعات", icon: Receipt },
      { to: "/returns", label: "مرتجعات العملاء", icon: RotateCcw },
      { to: "/exchanges", label: "الاستبدال", icon: RefreshCw },
    ],
  },
  {
    title: "المنتجات والمخزون",
    items: [
      { to: "/products/new", label: "إضافة منتج", icon: Shirt },
      { to: "/labels", label: "طباعة الملصقات", icon: Printer },
      { to: "/inventory", label: "المخزون والجرد", icon: Boxes },
    ],
  },
  {
    title: "المشتريات والموردون",
    items: [
      { to: "/suppliers", label: "الموردون", icon: Truck },
      { to: "/purchases", label: "المشتريات", icon: ShoppingBag },
      { to: "/supplier-returns", label: "مرتجعات الموردين", icon: Undo2 },
    ],
  },
  {
    title: "تشغيل المحل",
    items: [
      { to: "/shifts", label: "الورديات والخزنة", icon: Wallet },
      { to: "/expenses", label: "المصروفات", icon: ReceiptText },
    ],
  },
  {
    title: "المتابعة والإدارة",
    items: [
      { to: "/reports", label: "التقارير", icon: BarChart3 },
      { to: "/activity-log", label: "سجل العمليات", icon: ClipboardList },
    ],
  },
];

export const flatNav = navGroups.flatMap((g) => g.items);

export function pageTitle(pathname) {
  if (pathname === "/pos") return "المبيعات";
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
