import { Link } from "react-router-dom";
import { useState } from "react";
import { ClipboardList, Download, History, Percent, Printer, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import StockFilters from "@/cashier/components/inventory/StockFilters";
import InventoryProductGrid from "@/cashier/components/inventory/InventoryProductGrid";
import InventoryGridSkeleton from "@/cashier/components/inventory/InventoryGridSkeleton";
import ProductDetailsDialog from "@/cashier/components/inventory/ProductDetailsDialog";
import VariantMovementsDialog from "@/cashier/components/inventory/VariantMovementsDialog";
import SeasonMarkdownDialog from "@/cashier/components/inventory/SeasonMarkdownDialog";
import { costLabel } from "@/cashier/api/stockAdapter";
import { useStock, useStockCategories, useStockMaterials, useStockSeasons, useStockSummary } from "@/cashier/api/useStock";
import { useBrands } from "@/cashier/api/useCatalogWrite";
import { INVENTORY_STATUS, fmtInt, fmtMoneyShort } from "@/cashier/lib/format";
import { resolveOpenProduct } from "@/cashier/lib/inventoryGroups";
import { exportCsv } from "@/cashier/lib/exportCsv";
import { appPath } from "../../basePath";


const EXPORT_COLUMNS = [
  { header: "المنتج", key: "productName" },
  { header: "SKU", key: "sku" },
  { header: "الباركود", key: "barcode" },
  { header: "الموسم", key: "season" },
  { header: "الخامة", key: "material" },
  { header: "اللون", key: "color" },
  { header: "المقاس", key: "size" },
  { header: "الرصيد", key: "stock" },
  { header: "حد الطلب", key: "threshold" },
  { header: "متوسط التكلفة", value: (v) => costLabel(v.buyPrice, (n) => n.toFixed(2)) },
  { header: "الحالة", value: (v) => INVENTORY_STATUS[v.status]?.label ?? "—" },
];

const BTN =
  "h-auto gap-2 rounded-[10px] border-[#C7C2B8] !bg-white px-4 py-2.5 text-[13px] font-medium !text-[#3B3A36] !shadow-none transition-[box-shadow,border-color,background] duration-200 hover:border-[#E8761A] hover:!bg-white hover:!text-[#3B3A36] hover:shadow-[0_4px_12px_rgba(59,58,54,.1)] active:!bg-[#F4F1EC] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";
const BTN_PRIMARY =
  "h-auto gap-2 rounded-[10px] border border-[#E8761A] !bg-[#E8761A] px-4 py-2.5 text-[13px] font-semibold !text-white shadow-sm transition-all duration-200 hover:border-[#D1650F] hover:!bg-[#D1650F] hover:!text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";

export default function InventoryPage() {
  const [filters, setFilters] = useState({ term: "", category: "", brand: "", season: "", material: "", status: "" });
  const { term, category, brand, season, material, status } = filters;
  const [movementsOf, setMovementsOf] = useState(null);
  const [detailsOf, setDetailsOf] = useState(null);
  const [markdownOpen, setMarkdownOpen] = useState(false);

  // Search and status are filtered ON THE SERVER, so they reach every variant and the status can
  // never disagree with the backend rule. The totals below come from the summary endpoint, which
  // covers all active variants, not just the rows that happen to be on screen.
  const stock = useStock({ term, categoryId: category, brandId: brand, season, material, status });
  const summary = useStockSummary();
  const categories = useStockCategories();
  const brands = useBrands();
  const seasons = useStockSeasons();
  const materials = useStockMaterials();
  const rows = stock.data ?? [];
  const totals = summary.data;
  const openProduct = resolveOpenProduct(detailsOf, rows);

  return (
    <div className="-mx-2 -my-2 flex min-h-[calc(100vh-1rem)] flex-col gap-5 bg-[#F4F1EC] px-6 py-6 text-[#3B3A36] sm:-mx-3 sm:px-9 sm:py-8">
      <header className="animate-inv-rise flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="font-heading text-[26px] font-semibold leading-tight sm:text-[30px]">المخزون والجرد</h1>
          <p className="mt-1.5 text-[13px] leading-relaxed text-[#7A766C]">
            أرصدة كل لون ومقاس مع حد إعادة الطلب، حركة الأصناف، وورقة الجرد
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          <Button
            variant="outline"
            className={BTN}
            onClick={() => {
              exportCsv("المخزون.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} صنفًا`);
            }}
          >
            <Download />
            تصدير Excel
          </Button>
          <Button asChild variant="outline" className={BTN}>
            <Link to={appPath("/inventory/import")}>
              <Upload />
              استيراد من ملف
            </Link>
          </Button>
          <Button asChild variant="outline" className={BTN}>
            <Link to={appPath("/inventory/movements")}>
              <History />
              حركة الأصناف
            </Link>
          </Button>
          <Button variant="outline" className={BTN} onClick={() => setMarkdownOpen(true)}>
            <Percent />
            تخفيض موسم
          </Button>
          <Button asChild variant="outline" className={BTN}>
            <Link to={appPath("/labels")}>
              <Printer />
              طباعة الباركود
            </Link>
          </Button>
          <Button asChild variant="ghost" className={BTN_PRIMARY}>
            <Link to={appPath("/inventory/stocktake")}>
              <ClipboardList className="h-4 w-4 shrink-0 !text-white" />
              <span className="!text-white font-semibold">بدء جرد</span>
            </Link>
          </Button>
        </div>
      </header>

      <div className="animate-inv-rise grid gap-3.5 [animation-delay:.1s] sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="القطع المتوفرة"
          value={totals ? fmtInt(totals.pieces) : "…"}
          hint={`${fmtInt(rows.length)} متغيرًا في النتائج`}
        />
        <Stat
          label="قيمة المخزون بالتكلفة"
          value={totals ? fmtMoneyShort(totals.costValue) : "…"}
          hint={
            totals?.unknownCost
              ? `ناقصة: ${fmtInt(totals.unknownCost)} صنفًا بلا تكلفة مسجلة`
              : "حسب متوسط تكلفة الشراء"
          }
        />
        <Stat
          label="قيمة البيع المتوقعة"
          value={totals ? fmtMoneyShort(totals.retailValue) : "…"}
          hint="حسب أسعار البيع"
        />
        <Stat
          label="أصناف تحت حد الطلب"
          value={totals ? fmtInt(totals.alerts) : "…"}
          hint={totals ? `${fmtInt(totals.out)} صنفًا نافدًا • ${fmtInt(totals.low)} منخفضًا` : ""}
        />
      </div>

      <StockFilters
        values={filters}
        onChange={setFilters}
        categories={categories.data ?? []}
        brands={brands.data ?? []}
        seasons={seasons.data ?? []}
        materials={materials.data ?? []}
      />

      {stock.isError ? (
        <div role="alert" className="rounded-2xl border border-[#E3DED4] bg-white p-6 text-center text-[13px]">
          <p className="font-medium">تعذّر تحميل المخزون</p>
          <p className="mt-1 text-[#7A766C]">لم تُعرض أي أرقام لأنها قد تكون غير صحيحة. تحقق من الاتصال وأعد المحاولة.</p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => stock.refetch()}>
            إعادة المحاولة
          </Button>
        </div>
      ) : stock.isPending ? (
        <InventoryGridSkeleton />
      ) : (
        <InventoryProductGrid rows={rows} onOpen={setDetailsOf} onShowLow={() => setFilters((f) => ({ ...f, status: "low" }))} />
      )}

      <ProductDetailsDialog
        product={openProduct}
        open={!!openProduct}
        onOpenChange={(open) => !open && setDetailsOf(null)}
        onMovements={setMovementsOf}
      />

      <SeasonMarkdownDialog
        open={markdownOpen}
        onOpenChange={setMarkdownOpen}
        seasons={seasons.data ?? []}
        brands={brands.data ?? []}
      />

      <VariantMovementsDialog
        open={!!movementsOf}
        onOpenChange={(open) => !open && setMovementsOf(null)}
        variant={movementsOf}
      />
    </div>
  );
}

function Stat({ label, value, hint }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-[14px] border border-[#E3DED4] bg-white p-4 shadow-[0_1px_2px_rgba(59,58,54,.05)]">
      <span className="text-[12px] font-medium text-[#7A766C]">{label}</span>
      <span className="num text-[24px] font-semibold leading-none">{value}</span>
      {hint && <span className="text-[11px] leading-relaxed text-[#9A958A]">{hint}</span>}
    </div>
  );
}