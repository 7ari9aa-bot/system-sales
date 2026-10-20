import { useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import ExpenseDialog from "@/cashier/components/expenses/ExpenseDialog";
import VoidExpenseDialog from "@/cashier/components/expenses/VoidExpenseDialog";
import ExpenseFilters from "@/cashier/components/expenses/ExpenseFilters";
import expenseColumns from "@/cashier/components/expenses/expenseColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { PAYMENT_METHODS, fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";
import { useAuth } from "@/lib/AuthContext";
import { EXPENSE_METHODS, expenseErrorMessage, filterExpenses, summarize } from "@/cashier/api/expensesAdapter";
import { useExpenseCategories, useExpenses, usePostExpense, useVoidExpense } from "@/cashier/api/useExpenses";
import { useShiftState } from "@/cashier/api/useShifts";


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
  // A voided expense stays in the file but is marked, or Excel would add it to the total.
  { header: "الحالة", value: (r) => (r.voided ? "ملغي" : "مسجّل") },
];

export default function ExpensesPage() {
  const { user } = useAuth?.() ?? {};
  const users = user?.id ? { [user.id]: user.full_name || user.email } : {};
  const categoriesQ = useExpenseCategories();
  const categories = categoriesQ.data ?? [];
  const { data: rows = [], isLoading, error: loadError, refetch } = useExpenses({ categories, users });
  const shiftState = useShiftState();
  const openSessionId = shiftState.data?.status === "open" ? shiftState.data.session.id : null;
  const post = usePostExpense();
  const voidMut = useVoidExpense();

  const [term, setTerm] = useState("");
  const [category, setCategory] = useState("");
  const [payment, setPayment] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [voiding, setVoiding] = useState(null);

  const summary = summarize(rows);
  const filtered = filterExpenses(rows, { term, category, payment });
  const shownTotal = summarize(filtered).total;

  function saveExpense(payload) {
    post.mutate(
      { payload },
      {
        onSuccess: (created) => {
          setDialogOpen(false);
          toast.success(`تم تسجيل المصروف ${created.number} بمبلغ ${fmtMoney(created.amount)}`);
        },
      },
    );
  }

  function voidExpense(reason) {
    voidMut.mutate(
      { id: voiding.id, expenseId: voiding.id, reason },
      {
        onSuccess: () => {
          toast.success(`تم إلغاء المصروف ${voiding.number}`);
          setVoiding(null);
        },
      },
    );
  }

  const columns = expenseColumns({ onVoid: (expense) => { voidMut.reset(); setVoiding(expense); } });

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
            disabled={categoriesQ.isLoading || categories.length === 0}
            onClick={() => {
              post.reset();
              setDialogOpen(true);
            }}
          >
            <Plus />
            تسجيل مصروف
          </Button>
        </PageHero>
      }
    >
      {loadError || categoriesQ.error ? (
        <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل المصروفات: {expenseErrorMessage(loadError || categoriesQ.error)}</span>
          <Button variant="outline" onClick={() => { categoriesQ.refetch(); refetch(); }}>إعادة المحاولة</Button>
        </div>
      ) : null}

      <ExpenseFilters
        term={term}
        onTerm={setTerm}
        category={category}
        onCategory={(value) => setCategory(value === "all" ? "" : value)}
        payment={payment}
        onPayment={(value) => setPayment(value === "all" ? "" : value)}
        categories={categories}
        methods={EXPENSE_METHODS}
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
        emptyTitle={isLoading ? "جارٍ التحميل…" : "لا توجد مصروفات مطابقة"}
        emptyDescription="جرّب تغيير التصنيف أو طريقة الدفع أو كلمة البحث."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(filtered.length)} مصروفًا • الإجمالي {fmtMoney(shownTotal)}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "إجمالي المصروفات", value: fmtMoney(summary.total), hint: `${fmtInt(summary.count)} مصروفًا${summary.voidedCount ? ` • ${fmtInt(summary.voidedCount)} ملغي` : ""}`, accent: true },
          { label: "مصروفات اليوم", value: fmtMoney(summary.today), hint: "مسجلة في تاريخ اليوم" },
          { label: "مدفوع نقدًا", value: fmtMoney(summary.cash), hint: "يُخصم من خزنة الوردية" },
          { label: "أكبر تصنيف", value: summary.top, hint: `${fmtMoney(summary.topAmount)} من إجمالي المصروفات` },
        ]}
      />

      <ExpenseDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        categories={categories}
        methods={EXPENSE_METHODS}
        openSessionId={openSessionId}
        onSubmit={saveExpense}
        pending={post.isPending}
        error={post.error ? expenseErrorMessage(post.error) : null}
      />
      <VoidExpenseDialog
        expense={voiding}
        onOpenChange={(open) => !open && setVoiding(null)}
        onSubmit={voidExpense}
        pending={voidMut.isPending}
        error={voidMut.error ? expenseErrorMessage(voidMut.error) : null}
      />
    </LedgerPage>
  );
}