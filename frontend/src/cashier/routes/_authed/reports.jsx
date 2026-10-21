import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/cashier/components/ui/tabs";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ReportsFilters from "@/cashier/components/reports/ReportsFilters";
import SalesReportSection from "@/cashier/components/reports/SalesReportSection";
import ZReportSection from "@/cashier/components/reports/ZReportSection";
import { PERIODS } from "@/cashier/lib/opsData";
import { useAuth } from "@/lib/AuthContext";
import { useShifts } from "@/cashier/api/useShifts";
import { useSalesReport } from "@/cashier/api/usePosSale";
import { summarizeSales } from "@/cashier/api/salesReport";
import { inShopPeriod } from "@/cashier/lib/period";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/62d4eef78_generated_image.png";
const HERO_ALT = "مكتب إدارة المحل مع تقارير مبيعات ودفتر حساب";

// Only reports that read the backend are listed. The others (top products, profit, inventory value,
// returns by reason, purchases) return when they are built on real data: a made-up profit or stock
// figure next to a real Z report would be read as the shop's real numbers.
const REPORTS = [
  { key: "sales", label: "المبيعات" },
  { key: "zreport", label: "إغلاق اليوم (Z)" },
];

const TAB_TRIGGER =
  "rounded-md px-3 py-1.5 text-[12px] font-normal text-[#7A766C] transition-colors hover:bg-[#FDEBD8] hover:text-[#33322E] data-[state=active]:bg-[#33322E] data-[state=active]:text-[#F7F5F0] data-[state=active]:shadow-none";

export default function ReportsPage() {
  const [period, setPeriod] = useState("7d");
  const [tab, setTab] = useState(REPORTS[0].key);

  const salesQuery = useSalesReport(period);
  const daily = salesQuery.data ?? [];

  // ورديات نفس الفترة المختارة من الخادم (تقرير Z يتبع فلتر الفترة مثل باقي التقارير).
  const { user } = useAuth();
  const shifts = useShifts({ employees: user?.id ? { [user.id]: user.full_name || user.email } : {} });
  const zRows = (shifts.data ?? []).filter((r) => inShopPeriod(r.date, period));

  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "";
  const totals = summarizeSales(daily);

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="تقارير المحل"
          description="مبيعات كل يوم من الفواتير الفعلية، وتقرير إغلاق كل وردية"
        />
      }
    >
      <ReportsFilters
        period={period}
        onPeriod={setPeriod}
        onReset={() => setPeriod("7d")}
      />

      <Tabs value={tab} onValueChange={setTab} dir="rtl">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1 rounded-none border border-[#DED8CD] border-b-0 bg-white p-1.5">
          {REPORTS.map((report) => (
            <TabsTrigger key={report.key} value={report.key} className={TAB_TRIGGER}>
              {report.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="sales" className="mt-0">
          {salesQuery.isLoading ? (
            <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل المبيعات…</p>
          ) : salesQuery.isError ? (
            <p className="p-6 text-center text-sm font-semibold text-rose-600" role="alert">تعذّر تحميل تقرير المبيعات. حاول مرة أخرى.</p>
          ) : (
            <SalesReportSection rows={daily} />
          )}
        </TabsContent>
        <TabsContent value="zreport" className="mt-0">
          {shifts.isLoading ? (
            <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل الورديات…</p>
          ) : shifts.isError ? (
            <p className="p-6 text-center text-sm font-semibold text-rose-600" role="alert">تعذّر تحميل الورديات. حاول مرة أخرى.</p>
          ) : (
            <ZReportSection rows={zRows} />
          )}
        </TabsContent>
      </Tabs>

      <LedgerStats
        stats={[
          { label: "صافي المبيعات", value: fmtMoney(totals.net), hint: `${periodLabel} • من الفواتير الفعلية`, accent: true },
          { label: "عدد الفواتير", value: fmtInt(totals.invoices), hint: `${fmtInt(totals.pieces)} قطعة مباعة` },
          { label: "المرتجعات", value: fmtMoney(totals.returns), hint: "مطروحة من صافي المبيعات" },
          { label: "الخصومات", value: fmtMoney(totals.discount), hint: "خصومات الفواتير في الفترة" },
        ]}
      />
    </LedgerPage>
  );
}