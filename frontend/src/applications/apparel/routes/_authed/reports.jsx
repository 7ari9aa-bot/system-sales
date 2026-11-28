import { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/applications/apparel/components/ui/tabs";
import LedgerPage from "@/applications/apparel/components/ui-kit/LedgerPage";
import LedgerStats from "@/applications/apparel/components/ui-kit/LedgerStats";
import PageHero from "@/applications/apparel/components/ui-kit/PageHero";
import ReportsFilters from "@/applications/apparel/components/reports/ReportsFilters";
import SalesReportSection from "@/applications/apparel/components/reports/SalesReportSection";
import ZReportSection from "@/applications/apparel/components/reports/ZReportSection";
import { PERIODS } from "@/applications/apparel/lib/uiConstants";
import { useAuth } from "@/lib/AuthContext";
import { useShifts } from "@/applications/apparel/api/useShifts";
import { useSalesReport, useTopProducts } from "@/applications/apparel/api/usePosSale";
import ProductsReportSection from "@/applications/apparel/components/reports/ProductsReportSection";
import { useStock, useStockMaterials, useStockSeasons } from "@/applications/apparel/api/useStock";
import { valuationByCategory } from "@/applications/apparel/api/inventoryValuation";
import InventoryReportSection from "@/applications/apparel/components/reports/InventoryReportSection";
import ProfitReportSection from "@/applications/apparel/components/reports/ProfitReportSection";
import ProfitFilters from "@/applications/apparel/components/reports/ProfitFilters";
import SellThroughSection from "@/applications/apparel/components/reports/SellThroughSection";
import DeadStockSection from "@/applications/apparel/components/reports/DeadStockSection";
import { useSellThrough } from "@/applications/apparel/api/useSellThrough";
import { useDeadStock } from "@/applications/apparel/api/useDeadStock";
import { errorKind } from "@/applications/apparel/components/reports/profitView";
import { sellThroughErrorNotice } from "@/applications/apparel/components/reports/sellThroughView";
import { deadStockErrorNotice } from "@/applications/apparel/components/reports/deadStockView";
import { useProfitReport } from "@/applications/apparel/api/useProfitReport";
import { profitErrorNotice } from "@/applications/apparel/components/reports/profitView";
import { useBrands } from "@/applications/apparel/api/useCatalogWrite";
import { summarizeSales } from "@/applications/apparel/api/salesReport";
import { inShopPeriod } from "@/applications/apparel/lib/period";
import { fmtInt, fmtMoney } from "@/applications/apparel/lib/format";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/62d4eef78_generated_image.png";
const HERO_ALT = "مكتب إدارة المحل مع تقارير مبيعات ودفتر حساب";

// Only reports that read the backend are listed. The rest (returns by reason, purchases, expenses)
// return when they are built on real data: a made-up figure next to a real Z report would be read
// as the shop's real numbers. Profit is listed because GET /reports/profit/by-variant computes it
// from the real purchase layers, and it says out loud when a cost is missing.
const REPORTS = [
  { key: "sales", label: "المبيعات" },
  { key: "products", label: "الأصناف" },
  { key: "inventory", label: "تقييم المخزون" },
  { key: "profit", label: "الربح" },
  { key: "sellthrough", label: "التصريف" },
  { key: "deadstock", label: "راكد" },
  { key: "zreport", label: "إغلاق اليوم (Z)" },
];

const TAB_TRIGGER =
  "rounded-md px-3 py-1.5 text-[12px] font-normal text-[#7A766C] transition-colors hover:bg-[#FDEBD8] hover:text-[#33322E] data-[state=active]:bg-[#33322E] data-[state=active]:text-[#F7F5F0] data-[state=active]:shadow-none";

export default function ReportsPage() {
  const [period, setPeriod] = useState("7d");
  const [tab, setTab] = useState(REPORTS[0].key);
  // فلتر العلامة والموسم والخامة بتاع تقرير الربح لوحده: الفترة هي فلتر الصفحة المشترك.
  const [profitFilters, setProfitFilters] = useState({ brand: "", season: "", material: "" });

  const stockQuery = useStock({});
  const valuation = valuationByCategory(stockQuery.data ?? []);
  const salesQuery = useSalesReport(period);
  const topQuery = useTopProducts(period);
  const daily = salesQuery.data ?? [];

  // التقرير بيتطلب لما تاب الربح يتفتح: كاشير مش من حقه يشوفه، فمش محتاج طلب يترفض بـ403
  // ويسجّل خطأ كل مرة يفتح شاشة التقارير.
  const profitQueryResult = useProfitReport({
    period,
    brandId: profitFilters.brand,
    season: profitFilters.season,
    material: profitFilters.material,
    enabled: tab === "profit",
  });
  // التصريف بيستخدم نفس فلاتر الربح (علامة وموسم وخامة)، والراكد مالوش فلاتر: مدته من إعدادات المحل.
  const sellThroughResult = useSellThrough({
    period,
    brandId: profitFilters.brand,
    season: profitFilters.season,
    material: profitFilters.material,
    enabled: tab === "sellthrough",
  });
  const deadStockResult = useDeadStock({ enabled: tab === "deadstock" });
  const brandsQuery = useBrands();
  const seasonsQuery = useStockSeasons();
  const materialsQuery = useStockMaterials();
  const profitNotice = profitQueryResult.isError ? profitErrorNotice(profitQueryResult.error) : null;
  const sellThroughNotice = sellThroughResult.isError
    ? sellThroughErrorNotice(sellThroughResult.error, errorKind(sellThroughResult.error))
    : null;
  const deadStockNotice = deadStockResult.isError
    ? deadStockErrorNotice(deadStockResult.error, errorKind(deadStockResult.error))
    : null;

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
        <TabsContent value="products" className="mt-0">
          {topQuery.isLoading ? (
            <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل الأصناف…</p>
          ) : topQuery.isError ? (
            <p className="p-6 text-center text-sm font-semibold text-rose-600" role="alert">تعذّر تحميل تقرير الأصناف. حاول مرة أخرى.</p>
          ) : (
            <ProductsReportSection rows={topQuery.data ?? []} />
          )}
        </TabsContent>
        <TabsContent value="inventory" className="mt-0">
          {stockQuery.isLoading ? (
            <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل المخزون…</p>
          ) : stockQuery.isError ? (
            <p className="p-6 text-center text-sm font-semibold text-rose-600" role="alert">تعذّر تحميل المخزون. حاول مرة أخرى.</p>
          ) : (
            <InventoryReportSection rows={valuation} />
          )}
        </TabsContent>
        <TabsContent value="profit" className="mt-0">
          <div className="space-y-3">
            <ProfitFilters
              values={profitFilters}
              onChange={setProfitFilters}
              brands={brandsQuery.data ?? []}
              seasons={seasonsQuery.data ?? []}
              materials={materialsQuery.data ?? []}
            />
            {profitQueryResult.isPending ? (
              <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل تقرير الربح…</p>
            ) : profitNotice ? (
              <p
                className={
                  profitNotice.tone === "forbidden"
                    ? "border border-[#DED8CD] bg-white px-4 py-6 text-center text-[12.5px] text-[#7A766C]"
                    : "p-6 text-center text-sm font-semibold text-rose-600"
                }
                role="alert"
              >
                {profitNotice.message}
              </p>
            ) : (
              <ProfitReportSection
                rows={profitQueryResult.data?.rows ?? []}
                totals={profitQueryResult.data?.totals ?? null}
              />
            )}
          </div>
        </TabsContent>
        <TabsContent value="sellthrough" className="mt-0">
          <div className="space-y-3">
            <ProfitFilters
              values={profitFilters}
              onChange={setProfitFilters}
              brands={brandsQuery.data ?? []}
              seasons={seasonsQuery.data ?? []}
              materials={materialsQuery.data ?? []}
            />
            {sellThroughResult.isPending ? (
              <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل تقرير التصريف…</p>
            ) : sellThroughNotice ? (
              <p
                className={
                  sellThroughNotice.tone === "forbidden"
                    ? "border border-[#DED8CD] bg-white px-4 py-6 text-center text-[12.5px] text-[#7A766C]"
                    : "p-6 text-center text-sm font-semibold text-rose-600"
                }
                role="alert"
              >
                {sellThroughNotice.message}
              </p>
            ) : (
              <SellThroughSection
                rows={sellThroughResult.data?.rows ?? []}
                totals={sellThroughResult.data?.totals ?? null}
              />
            )}
          </div>
        </TabsContent>
        <TabsContent value="deadstock" className="mt-0">
          {deadStockResult.isPending ? (
            <p className="p-6 text-center text-sm text-muted-foreground" role="status">جارٍ تحميل المخزون الراكد…</p>
          ) : deadStockNotice ? (
            <p
              className={
                deadStockNotice.tone === "forbidden"
                  ? "border border-[#DED8CD] bg-white px-4 py-6 text-center text-[12.5px] text-[#7A766C]"
                  : "p-6 text-center text-sm font-semibold text-rose-600"
              }
              role="alert"
            >
              {deadStockNotice.message}
            </p>
          ) : (
            <DeadStockSection
              days={deadStockResult.data?.days ?? null}
              rows={deadStockResult.data?.rows ?? []}
              totals={deadStockResult.data?.totals ?? null}
            />
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
