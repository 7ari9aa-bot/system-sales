import { useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import PurchaseFilters from "@/cashier/components/purchases/PurchaseFilters";
import purchaseColumns from "@/cashier/components/purchases/purchaseColumns";
import PurchaseFormDialog from "@/cashier/components/purchases/PurchaseFormDialog";
import PurchaseDetailsDialog from "@/cashier/components/purchases/PurchaseDetailsDialog";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { PURCHASE_STATUSES, purchaseOrders, purchasesSummary } from "@/cashier/lib/purchasesData";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/eb4cf191f_generated_image.png";
const HERO_ALT = "صناديق بضاعة جديدة تصل إلى مخزن البوتيك";

const EXPORT_COLUMNS = [
  { header: "رقم الفاتورة", key: "number" },
  { header: "التاريخ", value: (r) => fmtDate(r.date) },
  { header: "المورد", key: "supplierName" },
  { header: "عدد القطع", key: "pieces" },
  { header: "الإجمالي", key: "total" },
  { header: "المدفوع", key: "paid" },
  { header: "المستحق", key: "balance" },
  { header: "المخزن", key: "warehouse" },
  { header: "الحالة", value: (r) => PURCHASE_STATUSES.find((s) => s.key === r.status)?.label ?? "—" },
];

export default function PurchasesPage() {
  const [rows, setRows] = useState(purchaseOrders);
  const [term, setTerm] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [status, setStatus] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [details, setDetails] = useState(null);

  const visible = rows.filter((r) => {
    const t = term.trim().toLowerCase();
    if (t && !(r.number.toLowerCase().includes(t) || r.supplierName.toLowerCase().includes(t))) return false;
    if (supplierId && r.supplierId !== supplierId) return false;
    if (status && r.status !== status) return false;
    return true;
  });

  const summary = purchasesSummary(visible);
  const nextNumber = `PO-2026-${String(118 + rows.length).padStart(4, "0")}`;
  const columns = purchaseColumns({ onDetails: setDetails });

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="جدول فواتير التوريد"
          description="البضاعة الداخلة للمحل: البنود والقطع، تكلفة كل فاتورة، وما سُدَّد وما تبقّى للموردين"
        >
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("المشتريات.csv", EXPORT_COLUMNS, visible);
              toast.success(`تم تصدير ${visible.length} فاتورة توريد`);
            }}
          >
            <Download />
            تصدير Excel
          </Button>
          <Button className={BTN_PRIMARY} onClick={() => setFormOpen(true)}>
            <Plus />
            تسجيل توريد جديد
          </Button>
        </PageHero>
      }
    >
      <PurchaseFilters
        term={term}
        onTerm={setTerm}
        supplierId={supplierId}
        onSupplier={(value) => setSupplierId(value === "all" ? "" : value)}
        status={status}
        onStatus={(value) => setStatus(value === "all" ? "" : value)}
        onReset={() => {
          setTerm("");
          setSupplierId("");
          setStatus("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={visible}
        pageSize={8}
        emptyTitle="لا توجد فواتير توريد مطابقة"
        emptyDescription="جرّب تغيير المورد أو حالة السداد، أو سجّل توريدًا جديدًا."
        emptyAction={
          <Button className={BTN_PRIMARY} onClick={() => setFormOpen(true)}>
            <Plus />
            تسجيل توريد جديد
          </Button>
        }
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(visible.length)} فاتورة معروضة • إجمالي {fmtMoney(summary.total)} • المستحق {fmtMoney(summary.balance)}
            </span>
          </div>
        }
        footerNote={`${visible.length} فاتورة • إجمالي ${fmtMoney(summary.total)}`}
      />

      <LedgerStats
        stats={[
          {
            label: "عدد فواتير التوريد",
            value: fmtInt(summary.count),
            hint: `${fmtInt(summary.pending)} فاتورة قيد السداد`,
          },
          { label: "إجمالي المشتريات", value: fmtMoney(summary.total), hint: `${fmtInt(summary.pieces)} قطعة دخلت المحل` },
          { label: "المدفوع للموردين", value: fmtMoney(summary.paid), hint: "إجمالي ما سُدَّد من الفواتير" },
          { label: "المستحق على المحل", value: fmtMoney(summary.balance), hint: "أرصدة لم تُسدد بعد", accent: true },
        ]}
      />

      <PurchaseFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        nextNumber={nextNumber}
        onSave={(order) => {
          setRows((prev) => [order, ...prev]);
          toast.success(`تم حفظ فاتورة التوريد ${order.number} بقيمة ${fmtMoney(order.total)}`);
        }}
      />

      <PurchaseDetailsDialog open={!!details} onOpenChange={(open) => !open && setDetails(null)} order={details} />
    </LedgerPage>
  );
}