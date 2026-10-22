import { useMemo, useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import SupplierReturnFilters from "@/cashier/components/supplier-returns/SupplierReturnFilters";
import SupplierReturnDialog from "@/cashier/components/supplier-returns/SupplierReturnDialog";
import supplierReturnColumns from "@/cashier/components/supplier-returns/supplierReturnColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { sumMoney } from "@/cashier/api/money";
import {
  RETURN_STATUS_LABEL,
  SETTLEMENT_LABEL,
  purchasingErrorMessage,
  returnsSummary,
} from "@/cashier/api/purchasingAdapter";
import { useCatalog } from "@/cashier/api/usePosSale";
import { useShiftState } from "@/cashier/api/useShifts";
import {
  useAcceptSupplierReturn,
  useCreateSupplierReturn,
  usePurchaseOrders,
  useRejectSupplierReturn,
  useSupplierReturns,
  useSuppliers,
} from "@/cashier/api/usePurchasing";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";

const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/933844b43_generated_image.png";
const HERO_ALT = "صندوق مرتجع مغلق على منضدة المخزن";

const EXPORT_COLUMNS = [
  { header: "رقم المرتجع", key: "number" },
  { header: "التاريخ", value: (r) => fmtDate(r.date) },
  { header: "المورد", key: "supplierName" },
  { header: "فاتورة التوريد", key: "poNumber" },
  { header: "الأصناف", value: (r) => r.items.map((i) => `${i.name} ${i.color} ${i.size} ×${i.qty}`.replace(/\s+/g, " ")).join(" ; ") },
  { header: "الكمية", key: "qty" },
  { header: "القيمة", key: "amount" },
  { header: "التسوية", value: (r) => SETTLEMENT_LABEL[r.settlement] ?? "—" },
  // A return under review or refused is not money: Excel must not sum it as such.
  { header: "قرار المورد", value: (r) => RETURN_STATUS_LABEL[r.status] ?? "—" },
];

export default function SupplierReturnsPage() {
  const suppliers = useSuppliers();
  const names = useMemo(() => Object.fromEntries((suppliers.data ?? []).map((s) => [s.id, s.name])), [suppliers.data]);
  const catalog = useCatalog();
  const variants = useMemo(() => Object.fromEntries((catalog.data ?? []).map((v) => [v.id, v])), [catalog.data]);
  const orders = usePurchaseOrders({ suppliers: names, variants });
  const orderNumbers = useMemo(() => Object.fromEntries((orders.data ?? []).map((o) => [o.id, o.number])), [orders.data]);
  const returns = useSupplierReturns({ suppliers: names, variants, orders: orderNumbers });
  const shiftState = useShiftState();
  const openSessionId = shiftState.data?.status === "open" ? shiftState.data.session.id : null;
  const create = useCreateSupplierReturn();
  const accept = useAcceptSupplierReturn();
  const reject = useRejectSupplierReturn();

  const [term, setTerm] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [settlement, setSettlement] = useState("");
  const [status, setStatus] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);

  const records = returns.data ?? [];
  const rows = records.filter((r) => {
    const t = term.trim().toLowerCase();
    if (t && !(r.number.toLowerCase().includes(t) || r.supplierName.toLowerCase().includes(t) || r.items.some((i) => i.name.toLowerCase().includes(t)))) return false;
    if (supplierId && r.supplierId !== supplierId) return false;
    if (settlement && r.settlement !== settlement) return false;
    if (status && r.status !== status) return false;
    return true;
  });
  const summary = returnsSummary(records);
  const decision = accept.isPending ? accept.variables?.id : reject.isPending ? reject.variables?.id : null;
  const decisionError = [accept.error, reject.error].find(Boolean);

  function submit(payload) {
    create.mutate(
      { slot: "create", payload },
      {
        onSuccess: (ret) => {
          setDialogOpen(false);
          toast.success(`تم تسجيل المرتجع ${ret.number}: البضاعة خرجت من المخزن وبانتظار قرار المورد`);
        },
      },
    );
  }

  function decide(ret, accepted) {
    const slot = `${accepted ? "accept" : "reject"}:${ret.id}`;
    const done = { onSuccess: () => toast.success(accepted ? `تم قبول المرتجع ${ret.number}` : `تم رفض المرتجع ${ret.number}: البضاعة رجعت للمخزن`) };
    if (accepted) accept.mutate({ slot, id: ret.id, sessionId: ret.settlement === "cash" ? openSessionId : null }, done);
    else reject.mutate({ slot, id: ret.id }, done);
  }

  const columns = supplierReturnColumns({ onAccept: (r) => decide(r, true), onReject: (r) => decide(r, false), busyId: decision });
  const shownAmount = sumMoney(rows.filter((r) => r.status === "accepted").map((r) => r.amount));
  const shownQty = rows.reduce((s, r) => s + r.qty, 0);

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="مرتجعات الموردين"
          description="البضاعة اللي رجعت للمورد: بتخرج من المخزن فورًا، والفلوس بتتحرك بس لما المورد يوافق"
        >
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("مرتجعات-الموردين.csv", EXPORT_COLUMNS, rows);
              toast.success(`تم تصدير ${rows.length} مرتجعًا`);
            }}
          >
            <Download />
            تصدير Excel
          </Button>
          <Button
            className={BTN_PRIMARY}
            onClick={() => {
              create.reset();
              setDialogOpen(true);
            }}
          >
            <Plus />
            تسجيل مرتجع للمورد
          </Button>
        </PageHero>
      }
    >
      {returns.error ? (
        <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل المرتجعات: {purchasingErrorMessage(returns.error)}</span>
          <Button variant="outline" onClick={() => returns.refetch()}>
            إعادة المحاولة
          </Button>
        </div>
      ) : null}
      {decisionError ? (
        <div role="alert" className="mb-3 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          {purchasingErrorMessage(decisionError)}
        </div>
      ) : null}

      <SupplierReturnFilters
        term={term}
        onTerm={setTerm}
        supplierId={supplierId}
        onSupplier={setSupplierId}
        settlement={settlement}
        onSettlement={setSettlement}
        status={status}
        onStatus={setStatus}
        suppliers={suppliers.data ?? []}
        onReset={() => {
          setTerm("");
          setSupplierId("");
          setSettlement("");
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
        emptyTitle={returns.isLoading ? "جارٍ التحميل…" : records.length === 0 ? "لسه مفيش مرتجعات للموردين" : "لا توجد مرتجعات مطابقة"}
        emptyDescription="سجّل مرتجعًا جديدًا، أو غيّر الفلاتر."
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(rows.length)} مرتجعًا معروضًا • مقبول بقيمة {fmtMoney(shownAmount)} • {fmtInt(shownQty)} قطعة
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "عدد المرتجعات", value: fmtInt(summary.count), hint: `${fmtInt(summary.qty)} قطعة خرجت من المخزن` },
          { label: "خصم من الحساب", value: fmtMoney(summary.credit), hint: "مرتجعات المورد قبلها" },
          { label: "مسترد نقدًا", value: fmtMoney(summary.cash), hint: "دخل درج الوردية" },
          { label: "بانتظار المورد", value: fmtInt(summary.review), hint: `قيمتها ${fmtMoney(summary.pendingAmount)} (لسه مش فلوس)`, accent: true },
        ]}
      />

      <SupplierReturnDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        suppliers={(suppliers.data ?? []).filter((s) => s.status === "active")}
        orders={orders.data ?? []}
        catalog={catalog.data ?? []}
        onSubmit={submit}
        pending={create.isPending}
        error={create.error ? purchasingErrorMessage(create.error) : ""}
      />
    </LedgerPage>
  );
}
