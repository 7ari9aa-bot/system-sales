import { Link } from "react-router-dom";
import { useState } from "react";
import { ClipboardList, Download, History, Search } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import InventoryProductGrid from "@/cashier/components/inventory/InventoryProductGrid";
import ProductDetailsDialog from "@/cashier/components/inventory/ProductDetailsDialog";
import SystemProductsSection from "@/cashier/components/inventory/SystemProductsSection";
import VariantMovementsDialog from "@/cashier/components/inventory/VariantMovementsDialog";
import { allVariants, branches, categories, shop, stockStatus } from "@/cashier/lib/mockData";
import { INVENTORY_STATUS, fmtInt, fmtMoneyShort } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const EXPORT_COLUMNS = [
  { header: "المنتج", key: "productName" },
  { header: "SKU", key: "sku" },
  { header: "الباركود", key: "barcode" },
  { header: "اللون", key: "color" },
  { header: "المقاس", key: "size" },
  { header: "الفرع", key: "branch" },
  { header: "الرصيد", key: "stock" },
  { header: "حد الطلب", key: "threshold" },
  { header: "الحالة", value: (v) => INVENTORY_STATUS[stockStatus(v.stock, v.threshold)]?.label ?? "—" },
];

const BTN =
  "h-auto gap-2 rounded-[10px] border-[#C7C2B8] bg-white px-4 py-2.5 text-[13px] font-medium text-[#3B3A36] shadow-none transition-[box-shadow,border-color,background] duration-200 hover:border-[#E8761A] hover:bg-white hover:text-[#3B3A36] hover:shadow-[0_4px_12px_rgba(59,58,54,.1)] active:bg-[#F4F1EC] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";
const BTN_PRIMARY =
  "h-auto gap-2 rounded-[10px] border border-[#3B3A36] bg-[#3B3A36] px-4 py-2.5 text-[13px] font-medium text-white shadow-none transition-[background,border-color] duration-200 hover:border-[#4D4B46] hover:bg-[#4D4B46] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";
const FIELD =
  "h-10 rounded-[10px] border-[#C7C2B8] bg-[#FBFAF7] px-3 text-[13px] text-[#3B3A36] transition-[border-color,box-shadow] duration-200 hover:border-[#E8761A] focus-visible:border-[#E8761A] focus-visible:ring-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#E8761A]";
const FIELD_LABEL = "mb-1.5 block text-[11px] font-medium text-[#7A766C]";

export default function InventoryPage() {
  const [term, setTerm] = useState("");
  const [category, setCategory] = useState("");
  const [branch, setBranch] = useState("");
  const [status, setStatus] = useState("");
  const [movementsOf, setMovementsOf] = useState(null);
  const [detailsOf, setDetailsOf] = useState(null);

  const rows = allVariants.filter((v) => {
    const t = term.trim().toLowerCase();
    if (t && !(v.productName.toLowerCase().includes(t) || v.sku.toLowerCase().includes(t) || v.barcode.includes(t))) return false;
    if (category && v.category !== category) return false;
    if (branch && v.branch !== branch) return false;
    if (status && stockStatus(v.stock, v.threshold) !== status) return false;
    return true;
  });

  const totals = {
    pieces: rows.reduce((s, v) => s + v.stock, 0),
    cost: rows.reduce((s, v) => s + v.buyPrice * v.stock, 0),
    retail: rows.reduce((s, v) => s + v.sellPrice * v.stock, 0),
    alerts: rows.filter((v) => stockStatus(v.stock, v.threshold) !== "in").length,
  };

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
            <Link to="/cashier/inventory/movements">
              <History />
              حركة الأصناف
            </Link>
          </Button>
          <Button asChild className={BTN_PRIMARY}>
            <Link to="/cashier/inventory/stocktake">
              <ClipboardList />
              بدء جرد
            </Link>
          </Button>
        </div>
      </header>

      <div className="animate-inv-rise grid gap-3.5 [animation-delay:.1s] sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="القطع المتوفرة" value={fmtInt(totals.pieces)} hint={`${fmtInt(rows.length)} متغيرًا في النتائج`} />
        <Stat label="قيمة المخزون بالتكلفة" value={fmtMoneyShort(totals.cost)} hint="حسب أسعار الشراء" />
        <Stat label="قيمة البيع المتوقعة" value={fmtMoneyShort(totals.retail)} hint="حسب أسعار البيع" />
        <Stat
          label="أصناف تحت حد الطلب"
          value={fmtInt(totals.alerts)}
          hint={`${fmtInt(rows.filter((v) => v.stock === 0).length)} صنفًا نافدًا • الحد ${shop.lowStockThreshold} قطع`}
        />
      </div>

      <FilterPanel
        className="animate-inv-rise rounded-[14px] border-[#E3DED4] bg-white [animation-delay:.2s]"
        activeCount={[category, branch, status].filter(Boolean).length + (term ? 1 : 0)}
        onReset={() => {
          setTerm("");
          setCategory("");
          setBranch("");
          setStatus("");
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <Label className={FIELD_LABEL}>بحث بالمنتج أو الكود أو الباركود</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#9A958A]" />
              <Input
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder="بنطلون جينز، SKU-0003"
                className={`pe-10 ${FIELD}`}
              />
            </div>
          </div>
          <div>
            <Label className={FIELD_LABEL}>التصنيف</Label>
            <Select value={category || "all"} onValueChange={(v) => setCategory(v === "all" ? "" : v)}>
              <SelectTrigger className={FIELD}>
                <SelectValue placeholder="كل التصنيفات" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل التصنيفات</SelectItem>
                {categories.map((c) => (
                  <SelectItem key={c} value={c}>
                    {c}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className={FIELD_LABEL}>الفرع</Label>
            <Select value={branch || "all"} onValueChange={(v) => setBranch(v === "all" ? "" : v)}>
              <SelectTrigger className={FIELD}>
                <SelectValue placeholder="كل الفروع" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل الفروع</SelectItem>
                {branches.map((b) => (
                  <SelectItem key={b} value={b}>
                    {b}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className={FIELD_LABEL}>حالة الرصيد</Label>
            <Select value={status || "all"} onValueChange={(v) => setStatus(v === "all" ? "" : v)}>
              <SelectTrigger className={FIELD}>
                <SelectValue placeholder="كل الحالات" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">كل الحالات</SelectItem>
                {Object.entries(INVENTORY_STATUS).map(([key, s]) => (
                  <SelectItem key={key} value={key}>
                    {s.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </FilterPanel>

      <InventoryProductGrid rows={rows} onOpen={setDetailsOf} onShowLow={() => setStatus("low")} />

      <SystemProductsSection onOpen={setDetailsOf} />

      <ProductDetailsDialog
        product={detailsOf}
        open={!!detailsOf}
        onOpenChange={(open) => !open && setDetailsOf(null)}
        onMovements={setMovementsOf}
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