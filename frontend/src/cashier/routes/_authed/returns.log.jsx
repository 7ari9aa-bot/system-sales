import { Link } from "react-router-dom";
import { useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ReturnLogFilters from "@/cashier/components/returns/ReturnLogFilters";
import returnLogColumns from "@/cashier/components/returns/returnLogColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { returnsSummary } from "@/cashier/lib/opsData";
import { allReturnRecords, useReturnState } from "@/cashier/lib/returnsStore";
import { fmtDateTime, fmtInt, fmtMoney, REFUND_METHODS, RETURN_STATUS } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/7efdc1ae1_generated_image.png";
const HERO_ALT = "قطعة ملابس مرتجعة مع إيصال رد على منضدة المحل";

const EXPORT_COLUMNS = [
  { header: "رقم المرتجع", key: "number" },
  { header: "التاريخ", value: (r) => fmtDateTime(r.date) },
  { header: "الفاتورة الأصلية", key: "invoiceNumber" },
  { header: "العميل", key: "customer" },
  { header: "الصنف", value: (r) => `${r.productName} (${r.variant})` },
  { header: "الكمية", key: "qty" },
  { header: "القيمة", key: "amount" },
  { header: "طريقة الاسترداد", value: (r) => REFUND_METHODS[r.refundMethod]?.label ?? "—" },
  { header: "السبب", key: "reason" },
  { header: "الموظف", key: "employee" },
  { header: "الحالة", value: (r) => RETURN_STATUS[r.status]?.label ?? "—" },
];

export default function ReturnsLogPage() {
  const [term, setTerm] = useState("");
  const [refund, setRefund] = useState("");
  const [status, setStatus] = useState("");

  useReturnState(); // لمزامنة السجل بعد اعتماد عملية مرتجع جديدة
  const records = allReturnRecords();
  const summary = returnsSummary(records);
  const rows = records.filter((r) => {
    const t = term.trim().toLowerCase();
    if (
      t &&
      !(
        r.number.toLowerCase().includes(t) ||
        r.invoiceNumber.toLowerCase().includes(t) ||
        r.customer.toLowerCase().includes(t) ||
        r.productName.toLowerCase().includes(t)
      )
    )
      return false;
    if (refund && r.refundMethod !== refund) return false;
    if (status && r.status !== status) return false;
    return true;
  });

  const columns = returnLogColumns();

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="سجل المرتجعات" description="سجل كل عمليات الإرجاع ورد المبالغ — كل سطر مرتبط بفاتورة بيعه الأصلية">
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("سجل-المرتجعات.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} عملية مرتجع`);
            }}
          >
            <Download />
            تصدير السجل
          </Button>
          <Button asChild className={BTN_PRIMARY}>
            <Link to="/cashier/returns">
              <Plus />
              تسجيل مرتجع
            </Link>
          </Button>
        </PageHero>
      }
    >
      <ReturnLogFilters
        term={term}
        onTerm={setTerm}
        refund={refund}
        onRefund={(value) => setRefund(value === "all" ? "" : value)}
        status={status}
        onStatus={(value) => setStatus(value === "all" ? "" : value)}
        onReset={() => {
          setTerm("");
          setRefund("");
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
        emptyTitle="لا توجد عمليات مرتجع مطابقة"
        emptyDescription="جرّب تغيير الفلتر أو البحث برقم آخر."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} عملية • إجمالي {fmtMoney(rows.reduce((s, r) => s + r.amount, 0))} • {fmtInt(rows.reduce((s, r) => s + r.qty, 0))} قطعة
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "عدد المرتجعات", value: fmtInt(summary.count), hint: "آخر ٧ أيام", accent: true },
          { label: "إجمالي المبالغ المردودة", value: fmtMoney(summary.amount), hint: "نقدًا وبطاقة ومحفظة ورصيد" },
          { label: "القطع المرتجعة", value: fmtInt(summary.qty), hint: "عادت إلى المخزون" },
          { label: "عمليات قيد المراجعة", value: fmtInt(summary.review), hint: "بانتظار اعتماد المدير" },
        ]}
      />
    </LedgerPage>
  );
}