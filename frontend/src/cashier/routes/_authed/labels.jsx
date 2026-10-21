import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Image } from "@/cashier/components/ui/image";
import DataTable from "@/cashier/components/ui-kit/DataTable";
import LabelFilters from "@/cashier/components/labels/LabelFilters";
import LabelPreviewDialog from "@/cashier/components/labels/LabelPreviewDialog";
import LedgerPage from "@/cashier/components/ui-kit/LedgerPage";
import LedgerStats from "@/cashier/components/ui-kit/LedgerStats";
import LabelsHero from "@/cashier/components/labels/LabelsHero";
import labelColumns from "@/cashier/components/labels/labelColumns";
import { LEDGER, LEDGER_FOOTER, LEDGER_TOOLBAR } from "@/cashier/components/ui-kit/ledgerStyles";
import { Button } from "@/cashier/components/ui/button";
import { useStock } from "@/cashier/api/useStock";
import { usePurchaseOrders, useSuppliers } from "@/cashier/api/usePurchasing";
import { clampLabelQty, countsFromOrder, labelProducts } from "@/cashier/api/labelsAdapter";
import { fmtInt } from "@/cashier/lib/format";


const TOOLBAR_IMAGE = "https://media.base44.com/images/public/6ad5982c1b45f350e41ffe73/165b465a1_generated_96ece487.jpg";

export default function LabelsPage() {
  const [term, setTerm] = useState("");
  const [category, setCategory] = useState("");
  const [counts, setCounts] = useState({});
  const [poNumber, setPoNumber] = useState("");
  const [previewOpen, setPreviewOpen] = useState(false);

  // Every active variant with its real barcode, price and stock. Search and category narrow it on screen.
  const stock = useStock({});
  const products = useMemo(() => labelProducts(stock.data ?? []), [stock.data]);
  const variantsById = useMemo(() => new Map(products.flatMap((p) => p.variants).map((v) => [v.id, v])), [products]);
  const categories = useMemo(() => [...new Set(products.map((p) => p.category).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ar")), [products]);

  const suppliers = useSuppliers();
  const supplierNames = useMemo(() => Object.fromEntries((suppliers.data ?? []).map((x) => [x.id, x.name])), [suppliers.data]);
  const variantInfo = useMemo(() => Object.fromEntries((stock.data ?? []).map((v) => [v.id, v])), [stock.data]);
  const orders = usePurchaseOrders({ suppliers: supplierNames, variants: variantInfo });
  const receivedOrders = (orders.data ?? []).filter((o) => o.receipt === "received");

  const filtered = products.filter((p) => {
    const t = term.trim().toLowerCase();
    if (t && !(p.name.toLowerCase().includes(t) || p.sku.toLowerCase().includes(t) || p.variants.some((v) => v.barcode.includes(t))))
      return false;
    if (category && p.category !== category) return false;
    return true;
  });

  const labelsOf = (p) => p.variants.reduce((s, v) => s + (counts[v.id] ?? 0), 0);
  const uniformQty = (p) => {
    const first = counts[p.variants[0]?.id] ?? 0;
    return p.variants.every((v) => (counts[v.id] ?? 0) === first) ? first : null;
  };

  const selected = products.filter((p) => labelsOf(p) > 0);
  const variantsCount = selected.reduce((s, p) => s + p.variants.length, 0);
  const totalLabels = selected.reduce((s, p) => s + labelsOf(p), 0);

  const labelRows = selected.flatMap((p) =>
    p.variants
      .filter((v) => (counts[v.id] ?? 0) > 0)
      .map((v) => ({
        id: v.id,
        productName: p.name,
        color: v.color,
        size: v.size,
        barcode: v.barcode,
        sellPrice: p.sellPrice,
        qty: counts[v.id] ?? 0,
      })),
  );


  function setProductQty(product, value) {
    const qty = clampLabelQty(value);
    setCounts((prev) => {
      const next = { ...prev };
      product.variants.forEach((v) => {
        if (qty > 0) next[v.id] = qty;
        else delete next[v.id];
      });
      return next;
    });
  }

  function fillFiltered(qty) {
    setCounts((prev) => {
      const next = { ...prev };
      filtered.forEach((p) =>
        p.variants.forEach((v) => {
          if (qty > 0) next[v.id] = qty;
          else delete next[v.id];
        }),
      );
      return next;
    });
  }

  // سحب الكميات اللي دخلت المحل من فاتورة توريد — لكل لون ومقاس على حدة.
  function fillFromPurchase(number) {
    const order = receivedOrders.find((o) => o.number === number);
    if (!order) return;
    const { counts: fromOrder, skipped, pieces } = countsFromOrder(order, variantsById);
    setCounts((prev) => ({ ...prev, ...fromOrder }));
    toast.success(`تم سحب ${fmtInt(pieces)} ملصقًا من الفاتورة ${order.number}`);
    if (skipped.length) toast.warning(`${fmtInt(skipped.length)} صنفًا في الفاتورة بلا باركود، فلم يُسحب له ملصق`);
  }

  function handlePurchaseOrder(value) {
    if (value === "none") {
      setPoNumber("");
      return;
    }
    setPoNumber(value);
    fillFromPurchase(value);
  }

  const columns = labelColumns({ labelsOf, uniformQty, setProductQty });

  return (
    <LedgerPage hero={<LabelsHero totalLabels={totalLabels} onPreview={() => setPreviewOpen(true)} />}>
        {stock.error ? (
          <div role="alert" className="mb-3 flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            <span>تعذّر تحميل المنتجات.</span>
            <Button variant="outline" onClick={() => stock.refetch()}>إعادة المحاولة</Button>
          </div>
        ) : null}
        <LabelFilters
          term={term}
          onTerm={setTerm}
          category={category}
          onCategory={(value) => setCategory(value === "all" ? "" : value)}
          categories={categories}
          orders={receivedOrders}
          poNumber={poNumber}
          onPo={handlePurchaseOrder}
          onQuickFill={fillFiltered}
          onReset={() => {
            setTerm("");
            setCategory("");
            setPoNumber("");
            setCounts({});
          }}
        />

        <DataTable
          className={LEDGER}
          toolbarClassName={LEDGER_TOOLBAR}
          footerClassName={LEDGER_FOOTER}
          columns={columns}
          rows={filtered}
          pageSize={8}
          emptyTitle={stock.isPending ? "جاري التحميل…" : "لا توجد منتجات مطابقة"}
          emptyDescription={stock.isPending ? "" : "جرّب تغيير التصنيف أو كلمة البحث."}
          toolbar={
            <div className="num flex items-center gap-3 text-[12px] text-[#7A766C]">
              <Image
                src={TOOLBAR_IMAGE}
                alt="رف تيشيرتات مطوي بالمقاسات"
                className="h-[34px] w-[34px] overflow-hidden rounded-[4px] border border-[#DED8CD]"
              />
              <span>
                {fmtInt(filtered.length)} منتجًا معروضًا • {fmtInt(selected.length)} منتجًا مختارًا • {fmtInt(totalLabels)} ملصقًا في أمر الطباعة
              </span>
            </div>
          }
        />

        <LedgerStats
          stats={[
            { label: "منتجات متاحة", value: fmtInt(products.length), hint: "كل الأصناف في الكتالوج" },
            { label: "منتجات مختارة", value: fmtInt(selected.length), hint: poNumber || category || "كل التصنيفات" },
            { label: "متغيرات مشمولة", value: fmtInt(variantsCount), hint: "لون + مقاس لكل منتج" },
            { label: "إجمالي الملصقات", value: fmtInt(totalLabels), hint: "جاهزة للطباعة الآن", accent: true },
          ]}
        />

        <LabelPreviewDialog open={previewOpen} onOpenChange={setPreviewOpen} rows={labelRows} />
    </LedgerPage>
  );
}