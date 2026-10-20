import { useMemo, useState } from "react";
import { Download, Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import PageHero from "@/cashier/components/ui-kit/PageHero";
import SupplierFilters from "@/cashier/components/suppliers/SupplierFilters";
import SupplierHistoryDialog from "@/cashier/components/suppliers/SupplierHistoryDialog";
import supplierColumns from "@/cashier/components/suppliers/supplierColumns";
import { BTN, BTN_PRIMARY, LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { fmtDate, fmtInt, fmtMoney, SUPPLIER_STATUS } from "@/cashier/lib/format";
import { exportCsv } from "@/cashier/lib/exportCsv";


const HERO_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/58b7350d6_generated_image.png";
const HERO_ALT = "أرفف قماش مطوي في مخزن البوتيك";

const EXPORT_COLUMNS = [
  { header: "المورد", key: "name" },
  { header: "التخصص", key: "company" },
  { header: "المسؤول", key: "agent" },
  { header: "الهاتف", key: "phone" },
  { header: "المدينة", key: "city" },
  { header: "عدد الأصناف", key: "items" },
  { header: "آخر توريد", value: (r) => fmtDate(r.lastDeal) },
  { header: "إجمالي التوريد", key: "total" },
  { header: "مرتجعات مخصومة", key: "credit" },
  // The backend balance is already net of accepted credit returns.
  { header: "المستحق", key: "balance" },
  { header: "الحالة", value: (r) => SUPPLIER_STATUS[r.status]?.label ?? "—" },
];

import SupplierFormDialog from "@/cashier/components/suppliers/SupplierFormDialog";
import SupplierPaymentDialog from "@/cashier/components/suppliers/SupplierPaymentDialog";
import { useShiftState } from "@/cashier/api/useShifts";
import { useCatalog } from "@/cashier/api/usePosSale";
import { sumMoney, toMinor } from "@/cashier/api/money";
import { purchasingErrorMessage, suppliersSummary } from "@/cashier/api/purchasingAdapter";
import { useCreateSupplier, usePaySupplier, usePurchaseOrders, useSupplierReturns, useSuppliers, useUpdateSupplier } from "@/cashier/api/usePurchasing";
export default function SuppliersPage() {
  const { data: rows = [], isLoading, error: loadError, refetch } = useSuppliers();
  const names = useMemo(() => Object.fromEntries(rows.map((s) => [s.id, s.name])), [rows]);
  const catalog = useCatalog();
  const variants = useMemo(() => Object.fromEntries((catalog.data ?? []).map((v) => [v.id, v])), [catalog.data]);
  const orders = usePurchaseOrders({ suppliers: names, variants });
  const returns = useSupplierReturns({ suppliers: names, variants });
  const shiftState = useShiftState();
  const openSessionId = shiftState.data?.status === "open" ? shiftState.data.session.id : null;

  const createSupplier = useCreateSupplier();
  const updateSupplier = useUpdateSupplier();
  const paySupplier = usePaySupplier();

  const [term, setTerm] = useState("");
  const [city, setCity] = useState("");
  const [status, setStatus] = useState("");
  const [historySupplier, setHistorySupplier] = useState(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [paying, setPaying] = useState(null); // { supplier, order }

  const cities = useMemo(() => [...new Set(rows.map((s) => s.city).filter(Boolean))], [rows]);
  const visible = rows.filter((s) => {
    const t = term.trim().toLowerCase();
    if (t && !(s.name.toLowerCase().includes(t) || s.agent.toLowerCase().includes(t) || s.phone.includes(t) || s.company.toLowerCase().includes(t))) return false;
    if (city && s.city !== city) return false;
    if (status && s.status !== status) return false;
    return true;
  });

  const summary = suppliersSummary(rows);
  const lastDeal = rows.map((r) => r.lastDeal).filter(Boolean).sort().slice(-1)[0] ?? null;
  const shownTotal = sumMoney(visible.map((r) => r.total));
  const shownOwed = sumMoney(visible.filter((r) => toMinor(r.balance) > 0).map((r) => r.balance));
  const columns = supplierColumns({ onHistory: setHistorySupplier });

  function openAdd() {
    createSupplier.reset();
    updateSupplier.reset();
    setEditing(null);
    setFormOpen(true);
  }

  function submitSupplier(body) {
    const done = () => {
      setFormOpen(false);
      toast.success(editing ? "تم حفظ بيانات المورد" : `تمت إضافة المورد ${body.name}`);
    };
    if (editing) updateSupplier.mutate({ id: editing.id, body }, { onSuccess: done });
    else createSupplier.mutate(body, { onSuccess: done });
  }

  function submitPayment(payload) {
    paySupplier.mutate(
      { slot: `pay:${paying.supplier.id}:${paying.order?.id ?? "account"}`, payload },
      {
        onSuccess: () => {
          setPaying(null);
          toast.success("تم تسجيل الدفعة");
        },
      },
    );
  }

  const saveError = purchasingErrorMessage(editing ? updateSupplier.error : createSupplier.error);
  const supplierError = (editing ? updateSupplier.error : createSupplier.error) ? saveError : null;

  return (
    <LedgerPage
      hero={
        <PageHero
          image={HERO_IMAGE}
          imageAlt={HERO_ALT}
          title="جدول الموردين"
          description="التوريدات، آخر تعامل، والرصيد المستحق لكل مورد بعد خصم مرتجعاته المقبولة — محسوب من المستندات نفسها"
        >
          <Button className={BTN_PRIMARY} onClick={openAdd}>
            <Plus />
            إضافة مورد
          </Button>
          <Button
            className={BTN}
            onClick={() => {
              exportCsv("الموردون.csv", EXPORT_COLUMNS, visible);
              toast.success(`تم تصدير ${visible.length} موردًا`);
            }}
          >
            <Download />
            تصدير القائمة
          </Button>
        </PageHero>
      }
    >
      {loadError ? (
        <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل الموردين: {purchasingErrorMessage(loadError)}</span>
          <Button variant="outline" onClick={() => refetch()}>إعادة المحاولة</Button>
        </div>
      ) : null}

      <SupplierFilters
        term={term}
        onTerm={setTerm}
        city={city}
        onCity={(value) => setCity(value === "all" ? "" : value)}
        status={status}
        onStatus={(value) => setStatus(value === "all" ? "" : value)}
        cities={cities}
        onReset={() => {
          setTerm("");
          setCity("");
          setStatus("");
        }}
      />

      <DataTable
        className={LEDGER}
        toolbarClassName={LEDGER_TOOLBAR}
        footerClassName={LEDGER_FOOTER}
        columns={columns}
        rows={visible}
        pageSize={8}
        emptyTitle={isLoading ? "جارٍ التحميل…" : rows.length === 0 ? "لسه مفيش موردين" : "لا يوجد موردون مطابقون"}
        emptyDescription={rows.length === 0 ? "اضغط «إضافة مورد» لتسجيل أول مورد." : "جرّب تغيير المدينة أو الحالة أو كلمة البحث."}
        toolbar={
          <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
            <Image src={HERO_IMAGE} alt={HERO_ALT} className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]" />
            <span>
              {fmtInt(visible.length)} موردًا معروضًا • إجمالي التوريدات {fmtMoney(shownTotal)} • المستحق {fmtMoney(shownOwed)}
            </span>
          </div>
        }
      />

      <LedgerStats
        stats={[
          { label: "عدد الموردين", value: fmtInt(summary.count), hint: `${fmtInt(summary.active)} مورد نشط` },
          { label: "إجمالي التوريدات", value: fmtMoney(summary.total), hint: "قيمة الفواتير المستلمة" },
          {
            label: "إجمالي المستحق",
            value: fmtMoney(summary.owed),
            hint: toMinor(summary.inCredit) < 0 ? `بعد خصم المرتجعات • رصيد لصالح المحل ${fmtMoney(summary.inCredit)}` : "بعد خصم المرتجعات المقبولة",
            accent: true,
          },
          { label: "آخر توريد", value: lastDeal ? fmtDate(lastDeal) : "—", hint: "أحدث شحنة وصلت للمخزن" },
        ]}
      />

      <SupplierHistoryDialog
        open={!!historySupplier}
        onOpenChange={(open) => !open && setHistorySupplier(null)}
        supplier={historySupplier ? (rows.find((s) => s.id === historySupplier.id) ?? historySupplier) : null}
        orders={orders.data ?? []}
        returns={returns.data ?? []}
        onPay={(supplier, order) => {
          paySupplier.reset();
          setPaying({ supplier, order });
        }}
      />

      <SupplierFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        supplier={editing}
        onSubmit={submitSupplier}
        pending={createSupplier.isPending || updateSupplier.isPending}
        error={supplierError}
      />

      <SupplierPaymentDialog
        open={!!paying}
        onOpenChange={(open) => !open && setPaying(null)}
        supplier={paying?.supplier ?? null}
        order={paying?.order ?? null}
        openSessionId={openSessionId}
        onSubmit={submitPayment}
        pending={paySupplier.isPending}
        error={paySupplier.error ? purchasingErrorMessage(paySupplier.error) : null}
      />
    </LedgerPage>
  );
}
