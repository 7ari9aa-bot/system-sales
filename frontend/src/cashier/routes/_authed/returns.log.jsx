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
import { useReturnsLog } from "@/cashier/api/usePosSale";
import { filterReturns, summarizeReturns } from "@/cashier/api/returnsLog";
import { fmtDateTime, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/7efdc1ae1_generated_image.png";
const HERO_ALT = "قطعة ملابس مرتجعة مع إيصال رد على منضدة المحل";

const EXPORT_COLUMNS = [
  { header: "رقم المرتجع", key: "number" },
  { header: "التاريخ", value: (r) => fmtDateTime(r.date) },
  { header: "الفاتورة الأصلية", key: "invoiceNumber" },
  { header: "الكمية", key: "qty" },
  { header: "القيمة", key: "amount" },
];

export default function ReturnsLogPage() {
  const [term, setTerm] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const { data: all = [], isLoading, isError } = useReturnsLog();
  const rows = filterReturns(all, { term, from, to });
  const summary = summarizeReturns(rows);
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
        from={from}
        onFrom={setFrom}
        to={to}
        onTo={setTo}
        onReset={() => {
          setTerm("");
          setFrom("");
          setTo("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={rows}
        pageSize={8}
        emptyTitle={isLoading ? "جارٍ التحميل…" : isError ? "تعذّر تحميل المرتجعات" : "لا توجد عمليات مرتجع مطابقة"}
        emptyDescription="جرّب تغيير الفلتر أو البحث برقم آخر."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(summary.count)} عملية • إجمالي {fmtMoney(summary.amount)} • {fmtInt(summary.qty)} قطعة
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "عدد المرتجعات", value: fmtInt(summary.count), hint: "حسب الفلتر الحالي", accent: true },
          { label: "إجمالي المبالغ المردودة", value: fmtMoney(summary.amount), hint: "على طريقة الدفع الأصلية" },
          { label: "القطع المرتجعة", value: fmtInt(summary.qty), hint: "من كل الورديات" },
        ]}
      />
    </LedgerPage>
  );
}