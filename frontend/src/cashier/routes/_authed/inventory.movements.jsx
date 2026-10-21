import { Link } from "react-router-dom";
import { useState } from "react";
import { ArrowLeftRight, Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import MovementFilters from "@/cashier/components/inventory/MovementFilters";
import movementColumns from "@/cashier/components/inventory/movementColumns";
import { BTN, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { useAllMovements } from "@/cashier/api/useMovements";
import { movementTotals } from "@/cashier/api/movementsAdapter";
import { MOVEMENT_TYPES, fmtDateTime, fmtInt, localDay } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/3dfcc7412_generated_image.png";
const HERO_ALT = "صناديق وملابس على رفوف المخزن مع سجل جرد";

const LEDGER_WINDOW = 500; // matches the limit asked of the server

const EXPORT_COLUMNS = [
  { header: "التاريخ", value: (m) => fmtDateTime(m.date) },
  { header: "المنتج", key: "productName" },
  { header: "اللون", key: "color" },
  { header: "المقاس", key: "size" },
  { header: "SKU", key: "sku" },
  { header: "نوع الحركة", value: (m) => MOVEMENT_TYPES[m.reason]?.label ?? m.label },
  { header: "داخل", key: "qtyIn" },
  { header: "خارج", key: "qtyOut" },
  { header: "الرصيد", key: "balance" },
  { header: "المستند", key: "doc" },
];

export default function MovementsPage() {
  const [term, setTerm] = useState("");
  const [type, setType] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  // The type filter runs on the server so it reaches movements beyond the loaded window; search and
  // dates narrow what is loaded.
  const { data: loaded = [], isPending, error: loadError, refetch } = useAllMovements({ reason: type });
  const rows = loaded.filter((m) => {
    const t = term.trim().toLowerCase();
    if (t && !(m.productName.toLowerCase().includes(t) || m.sku.toLowerCase().includes(t) || m.doc.toLowerCase().includes(t))) return false;
    const day = localDay(m.date);
    if (from && day < from) return false;
    if (to && day > to) return false;
    return true;
  });

  const totals = movementTotals(rows);

  const columns = movementColumns();

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="حركة الأصناف" description="كل حركة دخلت أو خرجت من المخزن مع الرصيد بعدها والمستند المسؤول">
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("حركة-الأصناف.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} حركة`);
            }}
          >
            <Download />
            تصدير Excel
          </Button>
          <Button asChild className={BTN}>
            <Link to="/cashier/inventory">
              <ArrowLeftRight />
              أرصدة المخزون
            </Link>
          </Button>
        </PageHero>
      }
    >
      {loadError ? (
        <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل حركة الأصناف.</span>
          <Button variant="outline" onClick={() => refetch()}>إعادة المحاولة</Button>
        </div>
      ) : null}
      {!loadError && loaded.length >= LEDGER_WINDOW ? (
        <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          المعروض آخر {fmtInt(LEDGER_WINDOW)} حركة فقط. للأقدم استخدم حركة منتج واحد من شاشة المخزون.
        </div>
      ) : null}

      <MovementFilters
        term={term}
        onTerm={setTerm}
        type={type}
        onType={(value) => setType(value === "all" ? "" : value)}
        from={from}
        onFrom={setFrom}
        to={to}
        onTo={setTo}
        onReset={() => {
          setTerm("");
          setType("");
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
        pageSize={10}
        emptyTitle={isPending ? "جاري التحميل…" : "لا توجد حركات مطابقة"}
        emptyDescription={isPending ? "" : "جرّب تغيير نوع الحركة أو نطاق التاريخ."}
        emptyAction={
          <Button variant="outline" size="sm" onClick={() => setType("")}>
            مسح الفلاتر
          </Button>
        }
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} حركة • داخل {fmtInt(totals.in)} • خارج {fmtInt(totals.out)} • صافي {fmtInt(totals.in - totals.out)} قطعة
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "عدد الحركات", value: fmtInt(rows.length), hint: `${fmtInt(totals.docs)} مستندًا مرتبطًا`, accent: true },
          { label: "إجمالي الداخل", value: fmtInt(totals.in), hint: "توريد ومرتجعات وتحويلات" },
          { label: "إجمالي الخارج", value: fmtInt(totals.out), hint: "بيع وتحويلات وتسويات" },
          { label: "صافي الحركة", value: fmtInt(totals.in - totals.out), hint: "الفرق بين الداخل والخارج" },
        ]}
      />
    </LedgerPage>
  );
}