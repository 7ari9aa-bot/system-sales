import { useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import SupplierFilters from "@/cashier/components/suppliers/SupplierFilters";
import SupplierHistoryDialog from "@/cashier/components/suppliers/SupplierHistoryDialog";
import supplierColumns from "@/cashier/components/suppliers/supplierColumns";
import { BTN, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { supplierRows, suppliersSummary } from "@/cashier/lib/opsData";
import { supplierReturnCredit } from "@/cashier/lib/storeOpsData";
import { fmtDate, fmtInt, fmtMoney, SUPPLIER_STATUS } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/58b7350d6_generated_image.png";
const HERO_ALT = "أرفف قماش مطوي في مخزن البوتيك";

const EXPORT_COLUMNS = [
  { header: "المورد", key: "name" },
  { header: "التخصص", key: "company" },
  { header: "المسؤول", key: "agent" },
  { header: "الهاتف", key: "phone" },
  { header: "المدينة", key: "city" },
  { header: "عدد الأصناف", key: "items" },
  { header: "آخر توريد", value: (r) => fmtDate(r.lastDeal) },
  { header: "إجمالي التوريد", key: "total" },
  { header: "المستحق", value: (s) => +(s.balance - supplierReturnCredit(s.id)).toFixed(2) },
  { header: "الحالة", value: (r) => SUPPLIER_STATUS[r.status]?.label ?? "—" },
];

export default function SuppliersPage() {
  const [term, setTerm] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("");
  const [historySupplier, setHistorySupplier] = useState(null);

  const summary = suppliersSummary();
  const totalCredit = +supplierRows.reduce((s, r) => s + supplierReturnCredit(r.id), 0).toFixed(2);
  const rows = supplierRows.filter((s) => {
    const t = term.trim().toLowerCase();
    if (t && !(s.name.toLowerCase().includes(t) || s.agent.toLowerCase().includes(t) || s.phone.includes(t) || s.company.toLowerCase().includes(t)))
      return false;
    if (city && s.city !== city) return false;
    if (status && s.status !== status) return false;
    return true;
  });

  const rowsTotal = rows.reduce((s, r) => s + r.total, 0);
  const rowsBalance = rows.reduce((s, r) => s + r.balance - supplierReturnCredit(r.id), 0);
  const columns = supplierColumns({ onHistory: setHistorySupplier });

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="جدول الموردين"
          description="التوريدات، آخر تعامل، والرصيد المستحق لكل مورد بعد خصم مرتجعاته — في جدول واحد"
        >
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("الموردون.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} موردًا`);
            }}
          >
            <Download />
            تصدير القائمة
          </Button>
        </PageHero>
      }
    >
      <SupplierFilters
        term={term}
        onTerm={setTerm}
        city={city}
        onCity={(value) => setCity(value === "all" ? "" : value)}
        status={status}
        onStatus={(value) => setStatus(value === "all" ? "" : value)}
        onReset={() => {
          setTerm("");
          setCity("");
          setStatus("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={rows}
        pageSize={8}
        emptyTitle="لا يوجد موردون مطابقون"
        emptyDescription="جرّب تغيير المدينة أو الحالة أو كلمة البحث."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} موردًا معروضًا • إجمالي التوريدات {fmtMoney(rowsTotal)} • المستحق {fmtMoney(rowsBalance)}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          {
            label: "عدد الموردين",
            value: fmtInt(summary.count),
            hint: `${fmtInt(supplierRows.filter((s) => s.status === "active").length)} مورد نشط`,
          },
          { label: "إجمالي التوريدات", value: fmtMoney(summary.total), hint: "قيمة كل فواتير التوريد" },
          {
            label: "إجمالي المستحق",
            value: fmtMoney(+(summary.balance - totalCredit).toFixed(2)),
            hint: `${fmtInt(summary.late)} مورد مستحق • خصم مرتجعات ${fmtMoney(totalCredit)}`,
            accent: true,
          },
          { label: "آخر توريد", value: fmtDate(summary.lastDeal), hint: "أحدث شحنة وصلت للمخزن" },
        ]}
      />

      <SupplierHistoryDialog
        open={!!historySupplier}
        onOpenChange={(open) => !open && setHistorySupplier(null)}
        supplier={historySupplier}
      />
    </LedgerPage>
  );
}