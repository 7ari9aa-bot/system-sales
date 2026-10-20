import { useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import ExpenseDialog from "@/cashier/components/expenses/ExpenseDialog";
import ExpenseFilters from "@/cashier/components/expenses/ExpenseFilters";
import expenseColumns from "@/cashier/components/expenses/expenseColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { expenseRows, expensesSummary } from "@/cashier/lib/storeOpsData";
import { PAYMENT_METHODS, fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/2115fad41_generated_image.png";
const HERO_ALT = "درج نقدية مفتوح على منضدة المحل مع فواتير";

const EXPORT_COLUMNS = [
  { header: "رقم المصروف", key: "number" },
  { header: "التاريخ", value: (r) => fmtDate(r.date) },
  { header: "التصنيف", key: "category" },
  { header: "البيان", key: "description" },
  { header: "المبلغ", key: "amount" },
  { header: "طريقة الدفع", value: (r) => PAYMENT_METHODS[r.payment]?.label ?? "—" },
  { header: "الموظف", key: "employee" },
];

export default function ExpensesPage() {
  const [rows, setRows] = useState(expenseRows);
  const [term, setTerm] = useState("");
  const [category, setCategory] = useState("");
  const [payment, setPayment] = useState("");
  const [editing, setEditing] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(null);

  const summary = expensesSummary(rows);
  const filtered = rows.filter((e) => {
    const t = term.trim().toLowerCase();
    if (t && !(e.number.toLowerCase().includes(t) || e.description.toLowerCase().includes(t) || e.category.toLowerCase().includes(t) || e.employee.toLowerCase().includes(t)))
      return false;
    if (category && e.category !== category) return false;
    if (payment && e.payment !== payment) return false;
    return true;
  });

  function nextNumber() {
    const max = rows.reduce((m, r) => Math.max(m, Number(String(r.number).replace(/\D/g, "")) || 0), 0);
    return `EXP-${max + 1}`;
  }

  function saveExpense(record) {
    if (record.id) {
      setRows((prev) => prev.map((r) => (r.id === record.id ? { ...r, ...record } : r)));
      toast.success(`تم تعديل المصروف ${record.number}`);
    } else {
      const number = nextNumber();
      setRows((prev) => [{ ...record, id: `ex-new-${prev.length + 1}`, number }, ...prev]);
      toast.success(`تم تسجيل المصروف ${number} بمبلغ ${fmtMoney(record.amount)}`);
    }
  }

  function removeExpense(record) {
    setRows((prev) => prev.filter((r) => r.id !== record.id));
    toast.success(`تم حذف المصروف ${record.number}`);
  }

  const columns = expenseColumns({
    onEdit: (expense) => {
      setEditing(expense);
      setDialogOpen(true);
    },
    onDelete: setDeleting,
  });

  return (
    <LedgerPage
      hero={
        <PageHero image={HERO_IMAGE} imageAlt={HERO_ALT} title="المصروفات" description="تسجيل مصروفات المحل حسب التصنيف والتاريخ والمبلغ وطريقة الدفع">
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("المصروفات.csv", EXPORT_COLUMNS, filtered);
              toast.success(`تم تصدير ${filtered.length} مصروفًا`);
            }}
          >
            <Download />
            تصدير القائمة
          </Button>
          <Button
            className={BTN_PRIMARY}
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
          >
            <Plus />
            تسجيل مصروف
          </Button>
        </PageHero>
      }
    >
      <ExpenseFilters
        term={term}
        onTerm={setTerm}
        category={category}
        onCategory={(value) => setCategory(value === "all" ? "" : value)}
        payment={payment}
        onPayment={(value) => setPayment(value === "all" ? "" : value)}
        onReset={() => {
          setTerm("");
          setCategory("");
          setPayment("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={filtered}
        pageSize={8}
        emptyTitle="لا توجد مصروفات مطابقة"
        emptyDescription="جرّب تغيير التصنيف أو طريقة الدفع أو كلمة البحث."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(filtered.length)} مصروفًا • الإجمالي {fmtMoney(filtered.reduce((s, e) => s + e.amount, 0))}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "إجمالي المصروفات", value: fmtMoney(summary.total), hint: `${fmtInt(summary.count)} مصروفًا مسجلًا`, accent: true },
          { label: "مصروفات اليوم", value: fmtMoney(summary.today), hint: "مسجلة في تاريخ اليوم" },
          { label: "مدفوع نقدًا", value: fmtMoney(summary.cash), hint: "يُخصم من خزنة الوردية" },
          { label: "أكبر تصنيف", value: summary.top, hint: `${fmtMoney(summary.topAmount)} من إجمالي المصروفات` },
        ]}
      />

      <ExpenseDialog open={dialogOpen} onOpenChange={setDialogOpen} expense={editing} onSubmit={saveExpense} />
      <ConfirmDialog
        open={Boolean(deleting)}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`حذف المصروف ${deleting?.number ?? ""}؟`}
        description="سيتم حذف المصروف من السجل ولن يظهر في التقارير."
        confirmLabel="حذف المصروف"
        onConfirm={() => {
          removeExpense(deleting);
          setDeleting(null);
        }}
      />
    </LedgerPage>
  );
}