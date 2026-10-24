import { useMemo, useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import PurchaseFilters from "@/cashier/components/purchases/PurchaseFilters";
import purchaseColumns from "@/cashier/components/purchases/purchaseColumns";
import PurchaseFormDialog from "@/cashier/components/purchases/PurchaseFormDialog";
import PurchaseDetailsDialog from "@/cashier/components/purchases/PurchaseDetailsDialog";
import SupplierPaymentDialog from "@/cashier/components/suppliers/SupplierPaymentDialog";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { useCatalog } from "@/cashier/api/usePosSale";
import {
  PAYMENT_LABEL,
  RECEIPT_LABEL,
  filterOrders,
  purchasesSummary,
  purchasingErrorMessage,
} from "@/cashier/api/purchasingAdapter";
import {
  useCancelPurchaseOrder,
  useCreatePurchaseOrder,
  usePaySupplier,
  usePurchaseOrders,
  useReceivePurchaseOrder,
  useSuppliers,
} from "@/cashier/api/usePurchasing";
import { fmtDate, fmtInt, fmtMoney } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";

const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/eb4cf191f_generated_image.png";
const HERO_ALT = "صناديق بضاعة جديدة تصل إلى مخزن البوتيك";

const EXPORT_COLUMNS = [
  { header: "رقم الفاتورة", key: "number" },
  { header: "التاريخ", value: (r) => fmtDate(r.date) },
  { header: "المورد", key: "supplierName" },
  { header: "عدد القطع", key: "pieces" },
  { header: "الإجمالي", key: "total" },
  { header: "المدفوع", key: "paid" },
  { header: "المستحق", key: "balance" },
  // Two separate facts: a cancelled or draft invoice must not look like a received one in Excel.
  { header: "الاستلام", value: (r) => RECEIPT_LABEL[r.receipt] ?? "—" },
  { header: "الدفع", value: (r) => (r.receipt === "received" ? (PAYMENT_LABEL[r.payment] ?? "—") : "—") },
];

export default function PurchasesPage() {
  const suppliers = useSuppliers();
  const names = useMemo(() => Object.fromEntries((suppliers.data ?? []).map((s) => [s.id, s.name])), [suppliers.data]);
  const catalog = useCatalog();
  const variants = useMemo(() => Object.fromEntries((catalog.data ?? []).map((v) => [v.id, v])), [catalog.data]);
  const orders = usePurchaseOrders({ suppliers: names, variants });

  const createOrder = useCreatePurchaseOrder();
  const receiveOrder = useReceivePurchaseOrder();
  const cancelOrder = useCancelPurchaseOrder();
  const paySupplier = usePaySupplier();

  const [term, setTerm] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [receipt, setReceipt] = useState("");
  const [payment, setPayment] = useState("");
  const [formOpen, setFormOpen] = useState(false);
  const [detailsId, setDetailsId] = useState(null);
  const [paying, setPaying] = useState(null);

  const rows = orders.data ?? [];
  const visible = filterOrders(rows, { term, supplierId, receipt, payment });
  const summary = purchasesSummary(visible);
  // Re-read from the list so the dialog shows the new balance right after a payment.
  const details = detailsId ? (rows.find((o) => o.id === detailsId) ?? null) : null;
  const columns = purchaseColumns({ onDetails: (o) => setDetailsId(o.id) });
  const actionError = [receiveOrder.error, cancelOrder.error].find(Boolean);

  function submitOrder(payload) {
    // One intention = one key: a retry after a lost response replays instead of receiving the goods twice.
    createOrder.mutate(
      { slot: "create", payload },
      {
        onSuccess: (order) => {
          setFormOpen(false);
          toast.success(`تم تسجيل فاتورة التوريد ${order.number} بقيمة ${fmtMoney(order.total)}`);
        },
      },
    );
  }

  function receive(order) {
    receiveOrder.mutate(
      { slot: `receive:${order.id}`, id: order.id },
      { onSuccess: () => toast.success(`تم استلام البضاعة وتحديث المخزن (${order.number})`) },
    );
  }

  function cancel(order) {
    cancelOrder.mutate(
      { slot: `cancel:${order.id}`, id: order.id },
      {
        onSuccess: () => {
          setDetailsId(null);
          toast.success(`تم إلغاء الفاتورة ${order.number}`);
        },
      },
    );
  }

  function submitPayment(payload) {
    paySupplier.mutate(
      { slot: `pay:${paying.order.id}`, payload },
      {
        onSuccess: () => {
          setPaying(null);
          toast.success("تم تسجيل الدفعة");
        },
      },
    );
  }

  const paySupplierRow = paying ? (suppliers.data ?? []).find((s) => s.id === paying.order.supplierId) : null;

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="جدول فواتير التوريد"
          description="البضاعة الداخلة للمحل: البنود والقطع، تكلفة كل فاتورة، وما سُدَّد وما تبقّى للموردين"
        >
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("المشتريات.csv", EXPORT_COLUMNS, visible);
              toast.success(`تم تصدير ${visible.length} فاتورة توريد`);
            }}
          >
            <Download />
            تصدير Excel
          </Button>
          <Button
            className={BTN_PRIMARY}
            onClick={() => {
              createOrder.reset();
              setFormOpen(true);
            }}
          >
            <Plus />
            تسجيل توريد جديد
          </Button>
        </PageHero>
      }
    >
      {orders.error ? (
        <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل الفواتير: {purchasingErrorMessage(orders.error)}</span>
          <Button variant="outline" onClick={() => orders.refetch()}>إعادة المحاولة</Button>
        </div>
      ) : null}

      <PurchaseFilters
        term={term}
        onTerm={setTerm}
        supplierId={supplierId}
        onSupplier={(v) => setSupplierId(v === "all" ? "" : v)}
        receipt={receipt}
        onReceipt={(v) => setReceipt(v === "all" ? "" : v)}
        payment={payment}
        onPayment={(v) => setPayment(v === "all" ? "" : v)}
        suppliers={suppliers.data ?? []}
        onReset={() => {
          setTerm("");
          setSupplierId("");
          setReceipt("");
          setPayment("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={visible}
        pageSize={8}
        emptyTitle={orders.isLoading ? "جارٍ التحميل…" : rows.length === 0 ? "لسه مفيش فواتير توريد" : "لا توجد فواتير توريد مطابقة"}
        emptyDescription={rows.length === 0 ? "سجّل أول توريد ليدخل المخزن ويتحسب في تكلفة الأصناف." : "جرّب تغيير المورد أو حالة الاستلام أو الدفع."}
        emptyAction={
          <Button className={BTN_PRIMARY} onClick={() => setFormOpen(true)}>
            <Plus />
            تسجيل توريد جديد
          </Button>
        }
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(visible.length)} فاتورة معروضة • إجمالي المستلم {fmtMoney(summary.total)} • المستحق {fmtMoney(summary.balance)}
            </span>
          </div>
        }
        footerNote={`${visible.length} فاتورة • إجمالي المستلم ${fmtMoney(summary.total)}`}
      />

      <LedgerStats
        stats={[
          { label: "عدد فواتير التوريد", value: fmtInt(summary.count), hint: `${fmtInt(summary.unpaidCount)} فاتورة مستلمة لم تُسدَّد بالكامل` },
          { label: "إجمالي المشتريات", value: fmtMoney(summary.total), hint: `${fmtInt(summary.pieces)} قطعة دخلت المحل` },
          { label: "المدفوع للموردين", value: fmtMoney(summary.paid), hint: "إجمالي ما سُدَّد من الفواتير المستلمة" },
          { label: "المستحق على المحل", value: fmtMoney(summary.balance), hint: "أرصدة لم تُسدد بعد", accent: true },
        ]}
      />

      <PurchaseFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        suppliers={suppliers.data ?? []}
        catalog={catalog.data ?? []}
        onSubmit={submitOrder}
        pending={createOrder.isPending}
        error={createOrder.error ? purchasingErrorMessage(createOrder.error) : null}
      />

      <PurchaseDetailsDialog
        open={!!details}
        onOpenChange={(open) => {
          if (!open) {
            setDetailsId(null);
            receiveOrder.reset();
            cancelOrder.reset();
          }
        }}
        order={details}
        busy={receiveOrder.isPending || cancelOrder.isPending}
        error={actionError ? purchasingErrorMessage(actionError) : null}
        onReceive={receive}
        onCancel={cancel}
        onPay={(order) => {
          paySupplier.reset();
          setPaying({ order });
        }}
      />

      <SupplierPaymentDialog
        open={!!paying}
        onOpenChange={(open) => !open && setPaying(null)}
        supplier={paySupplierRow}
        order={paying ? (rows.find((o) => o.id === paying.order.id) ?? paying.order) : null}
        onSubmit={submitPayment}
        pending={paySupplier.isPending}
        error={paySupplier.error ? purchasingErrorMessage(paySupplier.error) : null}
      />
    </LedgerPage>
  );
}
