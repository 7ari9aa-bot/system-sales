import { useState } from "react";
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
import { activityRows, activitySummary } from "@/cashier/lib/activityData";
import { ACTIVITY_TYPES, fmtDateTime, fmtInt } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/9bf26342a_generated_image.png";
const HERO_ALT = "كلبورد بسجل عمليات المحل على مكتب خشبي";

const EXPORT_COLUMNS = [
  { header: "التاريخ", value: (r) => fmtDateTime(r.date) },
  { header: "نوع العملية", value: (r) => ACTIVITY_TYPES[r.type]?.label ?? r.type },
  { header: "المستند", key: "doc" },
  { header: "التفاصيل", key: "details" },
  { header: "الموظف", key: "employee" },
  { header: "الفرع", key: "branch" },
];

export default function ActivityLogPage() {
  const [term, setTerm] = useState("");
  const [type, setType] = useState("");
  const [employee, setEmployee] = useState("");

  const summary = activitySummary();
  const employeesList = [...new Set(activityRows.map((r) => r.employee))].sort((a, b) => a.localeCompare(b, "ar"));

  const rows = activityRows.filter((r) => {
    const t = term.trim().toLowerCase();
    if (t && !(r.doc.toLowerCase().includes(t) || r.details.toLowerCase().includes(t) || r.employee.toLowerCase().includes(t))) return false;
    if (type && r.type !== type) return false;
    if (employee && r.employee !== employee) return false;
    return true;
  });

  const columns = activityLogColumns();

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="سجل العمليات" description="خط زمني لكل ما يحدث في المحل: البيع والمرتجعات والاستبدال والتوريد والمصروفات وحركات المخزون والورديات">
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("سجل-العمليات.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} عملية`);
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
        onReset={() => {
          setTerm("");
          setType("");
          setEmployee("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={rows}
        pageSize={10}
        emptyTitle="لا توجد عمليات مطابقة"
        emptyDescription="جرّب تغيير نوع العملية أو الموظف أو كلمة البحث."
        emptyAction={
          <Button variant="outline" size="sm" onClick={() => setType("")}>
            مسح الفلاتر
          </Button>
        }
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>{fmtInt(rows.length)} عملية مسجلة • مرتبة من الأحدث للأقدم</span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "إجمالي العمليات", value: fmtInt(summary.count), hint: "كل الحركات المسجلة في النظام", accent: true },
          { label: "عمليات اليوم", value: fmtInt(summary.today), hint: "منذ بداية اليوم" },
          { label: "موظفون مسجّلون", value: fmtInt(summary.employees), hint: "نفّذوا عمليات في السجل" },
          { label: "آخر عملية", value: summary.last ? fmtDateTime(summary.last.date) : "—", hint: summary.last?.employee ?? "" },
        ]}
      />
    </LedgerPage>
  );
}