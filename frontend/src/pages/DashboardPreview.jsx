import React from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Bell,
  Boxes,
  CalendarDays,
  ChartNoAxesCombined,
  ChevronDown,
  CircleHelp,
  LayoutDashboard,
  MessageSquareText,
  Package,
  Search,
  Settings2,
  ShoppingBag,
  Sparkles,
  Users,
} from "lucide-react";
import { useI18n } from "@/lib/i18n";

const nav = [
  { icon: LayoutDashboard, en: "Overview", ar: "نظرة عامة", active: true },
  { icon: MessageSquareText, en: "Conversations", ar: "المحادثات" },
  { icon: Users, en: "Customers", ar: "العملاء" },
  { icon: ShoppingBag, en: "Orders", ar: "الطلبات" },
  { icon: Package, en: "Inventory", ar: "المخزون" },
];

const metrics = [
  { icon: ShoppingBag, label: "Orders", labelAr: "الطلبات", value: "342", change: "+12.8%", up: true },
  { icon: ChartNoAxesCombined, label: "Net sales", labelAr: "صافي المبيعات", value: "$24,860", change: "+8.2%", up: true },
  { icon: Users, label: "Customers", labelAr: "العملاء", value: "198", change: "+5.4%", up: true },
  { icon: Activity, label: "Open conversations", labelAr: "محادثات مفتوحة", value: "16", change: "−2.1%", up: false },
];

const bars = [30, 42, 35, 58, 48, 66, 52, 75, 61, 83, 70, 96];
const orders = [
  { id: "#SO-2481", customer: "Sample customer 01", amount: "$248.00", status: "Paid", statusAr: "مدفوع" },
  { id: "#SO-2480", customer: "Sample customer 02", amount: "$124.50", status: "Processing", statusAr: "قيد التجهيز" },
  { id: "#SO-2479", customer: "Sample customer 03", amount: "$86.00", status: "Paid", statusAr: "مدفوع" },
];

export default function DashboardPreview() {
  const { lang } = useI18n();
  const isArabic = lang === "ar";
  const text = (en, ar) => (isArabic ? ar : en);

  return (
    <div data-dashboard-theme-scope className="min-h-screen bg-background text-foreground">
      <div className="flex min-h-screen">
        <aside className="hidden w-60 shrink-0 flex-col border-r border-border bg-card px-4 py-5 lg:flex">
          <div className="mb-8 flex items-center gap-3 px-2">
            <div className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground">
              <Sparkles aria-hidden="true" className="size-5" />
            </div>
            <div>
              <p className="text-sm font-semibold tracking-tight">Fihrist</p>
              <p className="text-xs text-muted-foreground">Sales workspace</p>
            </div>
          </div>
          <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            {text("Workspace", "مساحة العمل")}
          </p>
          <ul aria-label={text("Dashboard sections", "أقسام لوحة التحكم")} className="flex flex-col gap-1">
            {nav.map(({ icon: Icon, en, ar, active }) => (
              <li
                key={en}
                aria-current={active ? "page" : undefined}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm ${active ? "bg-primary/10 font-medium text-primary" : "text-muted-foreground"}`}
              >
                <Icon aria-hidden="true" className="size-4" />
                <span>{text(en, ar)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-auto rounded-xl border border-border bg-background p-3">
            <div className="flex items-center gap-2 text-xs font-medium">
              <span className="size-2 rounded-full bg-primary" />
              {text("Preview workspace", "مساحة معاينة")}
            </div>
            <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
              {text("Sample data only. No account or live API is connected.", "بيانات تجريبية فقط؛ لا يوجد حساب أو اتصال مباشر بالخادم.")}
            </p>
          </div>
        </aside>

        <main className="min-w-0 flex-1">
          <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur sm:px-6 lg:px-8">
            <div className="flex items-center gap-3">
              <div className="grid size-9 place-items-center rounded-lg bg-primary/10 text-primary lg:hidden">
                <LayoutDashboard aria-hidden="true" className="size-4" />
              </div>
              <div className="relative hidden sm:block">
                <Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <span className="block w-56 rounded-lg border border-border bg-card py-2 pl-9 pr-3 text-xs text-muted-foreground">
                  {text("Search workspace", "ابحث في مساحة العمل")}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2 sm:gap-3">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
                <span className="size-1.5 rounded-full bg-primary" />
                {text("DEMO PREVIEW", "معاينة تجريبية")}
              </span>
              <span aria-hidden="true" className="grid size-9 place-items-center rounded-lg border border-border text-muted-foreground">
                <Bell className="size-4" />
              </span>
              <span title={text("Demo profile", "حساب تجريبي")} aria-hidden="true" className="hidden size-8 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary sm:grid">D</span>
            </div>
          </header>

          <div className="mx-auto flex max-w-[1440px] flex-col gap-5 p-4 sm:p-6 lg:gap-6 lg:p-8">
            <section className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="mb-1 text-xs font-medium text-muted-foreground">{text("Tuesday, November 24", "الثلاثاء، 24 نوفمبر")}</p>
                <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{text("Good morning", "صباح الخير")}</h1>
                <p className="mt-1 text-sm text-muted-foreground">{text("Here’s what’s happening with your business.", "إليك ملخص نشاط متجرك.")}</p>
              </div>
              <span className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
                <CalendarDays aria-hidden="true" className="size-4" />
                {text("Last 30 days", "آخر 30 يومًا")}
              </span>
            </section>

            <section aria-label={text("Sample business metrics", "مؤشرات تجريبية للأعمال")} className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {metrics.map(({ icon: Icon, label, labelAr, value, change, up }) => (
                <article key={label} className="rounded-xl border border-border bg-card p-4 sm:p-5">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-muted-foreground">{text(label, labelAr)}</span>
                    <span className="grid size-8 place-items-center rounded-lg bg-primary/10 text-primary"><Icon aria-hidden="true" className="size-4" /></span>
                  </div>
                  <div className="mt-4 flex items-end justify-between gap-2">
                    <p className="text-2xl font-semibold tracking-tight">{value}</p>
                    <span className={`mb-0.5 inline-flex items-center gap-0.5 text-xs font-medium ${up ? "text-primary" : "text-muted-foreground"}`}>
                      {up ? <ArrowUpRight aria-hidden="true" className="size-3.5" /> : <ArrowDownRight aria-hidden="true" className="size-3.5" />}
                      {change}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">{text("vs. previous 30 days", "مقارنة بآخر 30 يومًا")}</p>
                </article>
              ))}
            </section>

            <section className="grid gap-5 xl:grid-cols-[1.7fr_1fr]">
              <article className="rounded-xl border border-border bg-card p-4 sm:p-5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-sm font-semibold">{text("Sales performance", "أداء المبيعات")}</h2>
                    <p className="mt-1 text-xs text-muted-foreground">{text("Sample net sales over the last 12 months", "صافي مبيعات تجريبي خلال آخر 12 شهرًا")}</p>
                  </div>
                  <span className="text-lg font-semibold">$24,860</span>
                </div>
                <div role="img" aria-label={text("Sample monthly sales bar chart", "رسم بياني تجريبي للمبيعات الشهرية")} className="mt-6 flex h-36 items-end gap-2 border-b border-border px-1 sm:gap-3">
                  {bars.map((height, index) => (
                    <div key={index} className="flex h-full flex-1 items-end">
                      <div aria-hidden="true" className={`w-full rounded-t-md ${index === bars.length - 1 ? "bg-primary" : "bg-primary/15"}`} style={{ height: `${height}%` }} />
                    </div>
                  ))}
                </div>
                <div aria-hidden="true" className="mt-2 flex justify-between text-[10px] text-muted-foreground">
                  {["Jan", "Mar", "May", "Jul", "Sep", "Nov"].map((month) => <span key={month}>{month}</span>)}
                </div>
              </article>

              <article className="rounded-xl border border-border bg-card p-4 sm:p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-sm font-semibold">{text("Needs attention", "يحتاج إلى متابعة")}</h2>
                    <p className="mt-1 text-xs text-muted-foreground">{text("A quick look at your workspace", "نظرة سريعة على مساحة العمل")}</p>
                  </div>
                  <CircleHelp aria-hidden="true" className="size-4 text-muted-foreground" />
                </div>
                <div className="mt-5 flex flex-col gap-3">
                  <div className="flex items-center gap-3 rounded-lg bg-muted/60 p-3">
                    <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-amber-500/10 text-amber-700"><Boxes aria-hidden="true" className="size-4" /></span>
                    <div className="min-w-0 flex-1"><p className="text-sm font-medium">{text("Low stock items", "منتجات قاربت على النفاد")}</p><p className="mt-0.5 text-xs text-muted-foreground">{text("5 products need a restock", "5 منتجات تحتاج إعادة تخزين")}</p></div>
                    <span className="text-sm font-semibold">05</span>
                  </div>
                  <div className="flex items-center gap-3 rounded-lg bg-muted/60 p-3">
                    <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><MessageSquareText aria-hidden="true" className="size-4" /></span>
                    <div className="min-w-0 flex-1"><p className="text-sm font-medium">{text("Unanswered messages", "رسائل بانتظار الرد")}</p><p className="mt-0.5 text-xs text-muted-foreground">{text("3 conversations are waiting", "3 محادثات بانتظار الرد")}</p></div>
                    <span className="text-sm font-semibold">03</span>
                  </div>
                  <div className="flex items-center gap-3 rounded-lg bg-muted/60 p-3">
                    <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary"><Settings2 aria-hidden="true" className="size-4" /></span>
                    <div className="min-w-0 flex-1"><p className="text-sm font-medium">{text("Workspace setup", "إعداد مساحة العمل")}</p><p className="mt-0.5 text-xs text-muted-foreground">{text("Your sample workspace is ready", "مساحة العرض التجريبية جاهزة")}</p></div>
                    <span className="text-xs font-medium text-primary">100%</span>
                  </div>
                </div>
              </article>
            </section>

            <section className="rounded-xl border border-border bg-card">
              <div className="flex items-center justify-between border-b border-border px-4 py-4 sm:px-5">
                <div>
                  <h2 className="text-sm font-semibold">{text("Recent orders", "أحدث الطلبات")}</h2>
                  <p className="mt-1 text-xs text-muted-foreground">{text("Sample records for preview only", "سجلات تجريبية للمعاينة فقط")}</p>
                </div>
                <span aria-hidden="true" className="grid size-8 place-items-center rounded-lg text-muted-foreground"><ChevronDown className="size-4" /></span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px] text-left text-sm">
                  <thead className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    <tr><th scope="col" className="px-4 py-3 font-medium sm:px-5">{text("Order", "الطلب")}</th><th scope="col" className="px-4 py-3 font-medium">{text("Customer", "العميل")}</th><th scope="col" className="px-4 py-3 font-medium">{text("Amount", "القيمة")}</th><th scope="col" className="px-4 py-3 font-medium">{text("Status", "الحالة")}</th></tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {orders.map((order) => (
                      <tr key={order.id}>
                        <td className="px-4 py-3.5 font-medium sm:px-5">{order.id}</td>
                        <td className="px-4 py-3.5 text-muted-foreground">{order.customer}</td>
                        <td className="px-4 py-3.5 font-medium">{order.amount}</td>
                        <td className="px-4 py-3.5"><span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">{text(order.status, order.statusAr)}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <p className="flex items-center justify-center gap-2 pb-2 text-xs text-muted-foreground">
              <span className="size-1.5 rounded-full bg-primary" />
              {text("Demo preview — all figures and records are synthetic.", "معاينة تجريبية — جميع الأرقام والسجلات غير حقيقية.")}
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
