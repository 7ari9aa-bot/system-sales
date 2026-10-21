import { useMemo, useRef, useState } from "react";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ActivityLogFilters from "@/cashier/components/activity/ActivityLogFilters";
import activityLogColumns from "@/cashier/components/activity/activityLogColumns";
import { BTN, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { employeesIn } from "@/cashier/api/activityAdapter";
import { useActivity, useActivitySummary } from "@/cashier/api/useActivity";
import { ACTIVITY_TYPES, fmtDateTime, fmtInt } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/9bf26342a_generated_image.png";
const HERO_ALT = "كلبورد بسجل عمليات المحل على مكتب خشبي";

const EXPORT_COLUMNS = [
  { header: "التاريخ", value: (r) => fmtDateTime(r.date) },
  { header: "نوع العملية", value: (r) => ACTIVITY_TYPES[r.type]?.label ?? r.type },
  { header: "المستند", key: "doc" },
  { header: "التفاصيل", key: "details" },
  { header: "القيمة", value: (r) => (r.quantity != null ? `${r.quantity} قطعة` : r.amount) },
  { header: "الموظف", key: "employee" },
];

export default function ActivityLogPage() {
  const [term, setTerm] = useState("");
  const [type, setType] = useState("");
  const [employee, setEmployee] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const dateError = from && to && to < from;
  const filters = { term, type, employeeId: employee, from: dateError ? "" : from, to: dateError ? "" : to };
  const feed = useActivity(filters);
  const counts = useActivitySummary({ from: filters.from, to: filters.to });

  const rows = useMemo(() => (feed.data?.pages ?? []).flatMap((p) => p.rows), [feed.data]);

  // The employee list comes from what has been loaded. Remember everyone seen so choosing one
  // employee does not make the others vanish from the list.
  const seen = useRef(new Map());
  for (const e of employeesIn(rows)) seen.current.set(e.id, e.name);
  const employeesList = [...seen.current].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name, "ar"));

  const total = counts.data ? Object.values(counts.data).reduce((a, b) => a + b, 0) : null;
  const today = rows.filter((r) => new Date(r.date).toDateString() === new Date().toDateString()).length;
  const last = rows[0];

  const columns = activityLogColumns();
  const reset = () => {
    setTerm("");
    setType("");
    setEmployee("");
    setFrom("");
    setTo("");
  };

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="سجل العمليات" description="خط زمني لكل ما يحدث في المحل: البيع والمرتجعات والتوريد ودفعات الموردين والمصروفات وحركات المخزون والورديات">
          <Button
            className={BTN}
            disabled={!rows.length}
            onClick={() => {
              exportCsv("سجل-العمليات.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} عملية${feed.hasNextPage ? " (المحمّلة فقط)" : ""}`);
            }}
          >
            <Download />
            تصدير السجل
          </Button>
        </PageHero>
      }
    >
      <ActivityLogFilters
        term={term}
        onTerm={setTerm}
        type={type}
        onType={(value) => setType(value === "all" ? "" : value)}
        employee={employee}
        onEmployee={(value) => setEmployee(value === "all" ? "" : value)}
        employeesList={employeesList}
        from={from}
        onFrom={setFrom}
        to={to}
        onTo={setTo}
        onReset={reset}
      />

      {dateError ? (
        <p role="alert" className="mx-1 text-xs text-[#B3402E]">
          تاريخ النهاية قبل تاريخ البداية، فتم تجاهل نطاق التاريخ.
        </p>
      ) : null}

      {feed.isError ? (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-[6px] border border-[#E4B9B0] bg-[#FBF1EF] px-3 py-2 text-xs text-[#B3402E]">
          <span>تعذّر تحميل السجل. تأكد من الاتصال ثم حاول مرة أخرى.</span>
          <Button variant="outline" size="sm" onClick={() => feed.refetch()}>
            إعادة المحاولة
          </Button>
        </div>
      ) : null}

      <DataTable
        key={JSON.stringify(filters)}
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={rows}
        pageSize={10}
        emptyTitle={feed.isLoading ? "جارٍ تحميل العمليات…" : "لا توجد عمليات مطابقة"}
        emptyDescription={feed.isLoading ? "لحظات ويظهر السجل." : "جرّب تغيير نوع العملية أو الموظف أو التاريخ أو كلمة البحث."}
        emptyAction={
          feed.isLoading ? null : (
            <Button variant="outline" size="sm" onClick={reset}>
              مسح الفلاتر
            </Button>
          )
        }
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} عملية معروضة • مرتبة من الأحدث للأقدم
              {feed.hasNextPage ? " • يوجد المزيد" : ""}
            </span>
            {feed.hasNextPage ? (
              <Button variant="outline" size="sm" disabled={feed.isFetchingNextPage} onClick={() => feed.fetchNextPage()}>
                {feed.isFetchingNextPage ? "جارٍ التحميل…" : "تحميل عمليات أقدم"}
              </Button>
            ) : null}
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "إجمالي العمليات", value: total == null ? "—" : fmtInt(total), hint: from || to ? "ضمن النطاق المحدد" : "كل الحركات المسجلة في النظام", accent: true },
          { label: "عمليات اليوم", value: fmtInt(today), hint: "ضمن المعروض حاليًا" },
          { label: "موظفون ظاهرون", value: fmtInt(employeesList.length), hint: "نفّذوا عمليات في المعروض" },
          { label: "آخر عملية", value: last ? fmtDateTime(last.date) : "—", hint: last?.employee ?? "" },
        ]}
      />
    </LedgerPage>
  );
}
