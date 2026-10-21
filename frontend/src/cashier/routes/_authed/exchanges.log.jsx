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
import ExchangeLogFilters from "@/cashier/components/exchanges/ExchangeLogFilters";
import exchangeLogColumns from "@/cashier/components/exchanges/exchangeLogColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { useExchangesLog } from "@/cashier/api/usePosSale";
import { filterExchanges, settlementOf, summarizeExchanges } from "@/cashier/api/exchangesLog";
import { fmtDateTime, fmtInt, fmtMoney, SETTLEMENT_TYPES } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/bb4a26da7_generated_image.png";
const HERO_ALT = "عمليتا استبدال ورد قطعتين ملابس على منضدة المحل";

const EXPORT_COLUMNS = [
  { header: "رقم الاستبدال", key: "number" },
  { header: "إيصال المرتجع", key: "returnReceiptNumber" },
  { header: "التاريخ", value: (r) => fmtDateTime(r.date) },
  { header: "الفاتورة الأصلية", key: "invoiceNumber" },
  { header: "الصنف المرتجع", key: "returnedItem" },
  { header: "الصنف البديل", key: "newItem" },
  { header: "قيمة المستبدل", key: "returnedValue" },
  { header: "قيمة البديل", key: "newValue" },
  { header: "الفرق", value: (r) => settlementOf(r).difference },
  { header: "التسوية", value: (r) => SETTLEMENT_TYPES[settlementOf(r).kind]?.label ?? "—" },
];

export default function ExchangesLogPage() {
  const [term, setTerm] = useState("");
  const [settlement, setSettlement] = useState("");

  const { data: all = [], isLoading, isError } = useExchangesLog();
  const summary = summarizeExchanges(all);
  const rows = filterExchanges(all, { term, settlement });

  const columns = exchangeLogColumns();

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="سجل الاستبدال" description="سجل عمليات استبدال الأصناف مع فرق التحصيل أو الرد لكل عملية">
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("سجل-الاستبدال.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} عملية استبدال`);
            }}
          >
            <Download />
            تصدير السجل
          </Button>
          <Button asChild className={BTN_PRIMARY}>
            <Link to="/cashier/exchanges">
              <Plus />
              تسجيل استبدال
            </Link>
          </Button>
        </PageHero>
      }
    >
      <ExchangeLogFilters
        term={term}
        onTerm={setTerm}
        settlement={settlement}
        onSettlement={(value) => setSettlement(value === "all" ? "" : value)}
        onReset={() => {
          setTerm("");
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
        emptyTitle={isLoading ? "جارٍ التحميل…" : isError ? "تعذّر تحميل سجل الاستبدال" : "لا توجد عمليات استبدال مطابقة"}
        emptyDescription={isError ? "أعد المحاولة بعد لحظة." : "جرّب تغيير الفلتر أو البحث برقم آخر."}
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} عملية • تم تحصيل {fmtMoney(rows.reduce((s, r) => s + Math.max(0, settlementOf(r).difference), 0))} • تم رد{" "}
              {fmtMoney(rows.reduce((s, r) => s + Math.max(0, -settlementOf(r).difference), 0))}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "عدد عمليات الاستبدال", value: fmtInt(summary.count), hint: "كل الورديات", accent: true },
          { label: "قيمة الأصناف البديلة", value: fmtMoney(summary.newValue), hint: "سعر بيع الأصناف المسلّمة" },
          { label: "صافي فروق التحصيل", value: fmtMoney(summary.net), hint: "تحصيل فرق ناقص المبالغ المردودة" },
          { label: "عمليات بفارق صفر", value: fmtInt(summary.even), hint: "استبدال بدون تحصيل أو رد" },
        ]}
      />
    </LedgerPage>
  );
}