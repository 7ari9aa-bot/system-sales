import { useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import SupplierReturnFilters from "@/cashier/components/supplier-returns/SupplierReturnFilters";
import SupplierReturnDialog from "@/cashier/components/supplier-returns/SupplierReturnDialog";
import supplierReturnColumns from "@/cashier/components/supplier-returns/supplierReturnColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { supplierReturnRecords, supplierReturnsSummary } from "@/cashier/lib/storeOpsData";
import { SUPPLIER_RETURN_SETTLEMENTS, fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/933844b43_generated_image.png";
const HERO_ALT = "صندوق مرتجع مغلق على منضدة المخزن";

const EXPORT_COLUMNS = [
  { header: "رقم المرتجع", key: "number" },
  { header: "التاريخ", value: (r) => fmtDate(r.date) },
  { header: "المورد", key: "supplierName" },
  { header: "فاتورة التوريد", key: "poNumber" },
  { header: "الصنف", key: "productName" },
  { header: "اللون", key: "color" },
  { header: "المقاس", key: "size" },
  { header: "الكمية", key: "qty" },
  { header: "التكلفة", key: "unitCost" },
  { header: "القيمة", key: "amount" },
  { header: "السبب", key: "reason" },
  { header: "التسوية", value: (r) => SUPPLIER_RETURN_SETTLEMENTS[r.settlement]?.label ?? "—" },
];

export default function SupplierReturnsPage() {
  const [records, setRecords] = useState(supplierReturnRecords);
  const [term, setTerm] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [settlement, setSettlement] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  const summary = supplierReturnsSummary(records);
  const rows = records.filter((r) => {
    const t = term.trim().toLowerCase();
    if (t && !(r.number.toLowerCase().includes(t) || r.supplierName.toLowerCase().includes(t) || r.productName.toLowerCase().includes(t) || r.sku.toLowerCase().includes(t)))
      return false;
    if (supplierId && r.supplierId !== supplierId) return false;
    if (settlement && r.settlement !== settlement) return false;
    return true;
  });

  const rowsAmount = rows.reduce((s, r) => s + r.amount, 0);
  const rowsQty = rows.reduce((s, r) => s + r.qty, 0);
  const columns = supplierReturnColumns();

  function addRecord(record) {
    const nextNumber = `SR-2026-${String(107 + records.length).padStart(4, "0")}`;
    setRecords((prev) => [
      {
        ...record,
        id: `sr-new-${prev.length + 1}`,
        number: nextNumber,
        date: new Date().toISOString(),
        status: "completed",
      },
      ...prev,
    ]);
    toast.success(`تم تسجيل المرتجع ${nextNumber} — ${record.productName}`);
  }

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="جدول مرتجعات الموردين"
          description="الأصناف المرتجعة وكمياتها، أثرها على المخزون، وطريقة تسوية الحساب مع كل مورد"
        >
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("مرتجعات-الموردين.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} مرتجعًا`);
            }}
          >
            <Download />
            تصدير القائمة
          </Button>
          <Button className={BTN_PRIMARY} onClick={() => setDialogOpen(true)}>
            <Plus />
            تسجيل مرتجع للمورد
          </Button>
        </PageHero>
      }
    >
      <SupplierReturnFilters
        term={term}
        onTerm={setTerm}
        supplierId={supplierId}
        onSupplier={(value) => setSupplierId(value === "all" ? "" : value)}
        settlement={settlement}
        onSettlement={(value) => setSettlement(value === "all" ? "" : value)}
        onReset={() => {
          setTerm("");
          setSupplierId("");
          setSettlement("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={rows}
        pageSize={8}
        emptyTitle="لا توجد مرتجعات مطابقة"
        emptyDescription="جرّب تغيير المورد أو طريقة التسوية أو كلمة البحث."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} مرتجعًا معروضًا • القيمة {fmtMoney(rowsAmount)} • {fmtInt(rowsQty)} قطعة خرجت من المخزون
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          {
            label: "عدد المرتجعات",
            value: fmtInt(summary.count),
            hint: `${fmtInt(summary.qty)} قطعة خرجت من المخزون`,
          },
          {
            label: "قيمة المرتجعات",
            value: fmtMoney(summary.amount),
            hint: `${fmtInt(summary.suppliersCount)} مورد • خصم من الحساب ${fmtMoney(summary.credit)}`,
          },
          { label: "مسترد نقدًا", value: fmtMoney(summary.cash), hint: "استرداد نقدي من الموردين" },
          { label: "قيد المراجعة", value: fmtInt(summary.review), hint: "بانتظار موافقة المورد", accent: true },
        ]}
      />

      <SupplierReturnDialog open={dialogOpen} onOpenChange={setDialogOpen} onSubmit={addRecord} />
    </LedgerPage>
  );
}