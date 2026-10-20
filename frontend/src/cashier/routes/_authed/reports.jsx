import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/cashier/components/ui/tabs";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ReportsFilters from "@/cashier/components/reports/ReportsFilters";
import SalesReportSection from "@/cashier/components/reports/SalesReportSection";
import ProductsReportSection from "@/cashier/components/reports/ProductsReportSection";
import ProfitReportSection from "@/cashier/components/reports/ProfitReportSection";
import InventoryReportSection from "@/cashier/components/reports/InventoryReportSection";
import ReturnsReportSection from "@/cashier/components/reports/ReturnsReportSection";
import PurchasesReportSection from "@/cashier/components/reports/PurchasesReportSection";
import ZReportSection from "@/cashier/components/reports/ZReportSection";
import { categoryProfitRows, dailySalesRows, inPeriod, inventoryValueRows, PERIODS, returnsReportRows, topProductRows } from "@/cashier/lib/opsData";
import { purchasesReportRows, shiftRows } from "@/cashier/lib/storeOpsData";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/62d4eef78_generated_image.png";
const HERO_ALT = "مكتب إدارة المحل مع تقارير مبيعات ودفتر حساب";

const REPORTS = [
  { key: "sales", label: "المبيعات" },
  { key: "products", label: "الأصناف" },
  { key: "returns", label: "المرتجعات" },
  { key: "purchases", label: "المشتريات" },
  { key: "profit", label: "الأرباح" },
  { key: "inventory", label: "تقييم المخزون" },
  { key: "zreport", label: "إغلاق اليوم (Z)" },
];

const TAB_TRIGGER =
  "rounded-md px-3 py-1.5 text-[12px] font-normal text-[#7A766C] transition-colors hover:bg-[#FDEBD8] hover:text-[#33322E] data-[state=active]:bg-[#33322E] data-[state=active]:text-[#F7F5F0] data-[state=active]:shadow-none";

export default function ReportsPage() {
  const [period, setPeriod] = useState("7d");
  const [category, setCategory] = useState("");
  const [tab, setTab] = useState("sales");

  const daily = dailySalesRows(period);
  const profitRows = category ? categoryProfitRows.filter((r) => r.category === category) : categoryProfitRows;
  const productRows = category ? topProductRows.filter((r) => r.category === category) : topProductRows;
  const inventoryRows = category ? inventoryValueRows.filter((r) => r.category === category) : inventoryValueRows;

  // ورديات نفس الفترة المختارة (تقرير Z يتبع فلتر الفترة مثل باقي التقارير).
  const zRows = shiftRows.filter((r) => inPeriod(r.date, period));

  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "";
  const salesTotal = daily.reduce((s, r) => s + r.net, 0);
  const invoicesTotal = daily.reduce((s, r) => s + r.invoices, 0);
  const piecesTotal = daily.reduce((s, r) => s + r.pieces, 0);
  const returnsTotal = daily.reduce((s, r) => s + r.returns, 0);
  const profitTotal = profitRows.reduce((s, r) => s + r.profit, 0);

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="تقارير المحل"
          description="سبعة تقارير في جدول واحد: المبيعات اليومية، الأصناف الأكثر مبيعًا، المرتجعات، المشتريات، الأرباح، تقييم المخزون، وإغلاق اليوم (Z)"
        />
      }
    >
      <ReportsFilters
        period={period}
        onPeriod={setPeriod}
        category={category}
        onCategory={(value) => setCategory(value === "all" ? "" : value)}
        onReset={() => {
          setPeriod("7d");
          setCategory("");
        }}
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
          <SalesReportSection rows={daily} />
        </TabsContent>
        <TabsContent value="products" className="mt-0">
          <ProductsReportSection rows={productRows} />
        </TabsContent>
        <TabsContent value="returns" className="mt-0">
          <ReturnsReportSection rows={returnsReportRows} />
        </TabsContent>
        <TabsContent value="purchases" className="mt-0">
          <PurchasesReportSection rows={purchasesReportRows} />
        </TabsContent>
        <TabsContent value="profit" className="mt-0">
          <ProfitReportSection rows={profitRows} />
        </TabsContent>
        <TabsContent value="inventory" className="mt-0">
          <InventoryReportSection rows={inventoryRows} />
        </TabsContent>
        <TabsContent value="zreport" className="mt-0">
          <ZReportSection rows={zRows} />
        </TabsContent>
      </Tabs>

      <LedgerStats
        stats={[
          { label: "صافي المبيعات", value: fmtMoney(salesTotal), hint: `${periodLabel} • محسوب من الفواتير الفعلية`, accent: true },
          { label: "عدد الفواتير", value: fmtInt(invoicesTotal), hint: `${fmtInt(piecesTotal)} قطعة مباعة` },
          { label: "المرتجعات", value: fmtMoney(returnsTotal), hint: "مطروحة من صافي المبيعات" },
          { label: "إجمالي الربح", value: fmtMoney(profitTotal), hint: category || "كل التصنيفات" },
        ]}
      />
    </LedgerPage>
  );
}