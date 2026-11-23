import { useEffect, useState } from "react";
import { toast } from "sonner";
import ProductEditorHero from "@/cashier/components/products/ProductEditorHero";
import ProductBasicsSection from "@/cashier/components/products/ProductBasicsSection";
import ProductPricingSection from "@/cashier/components/products/ProductPricingSection";
import ProductVariantsPicker from "@/cashier/components/products/ProductVariantsPicker";
import ProductSummarySection from "@/cashier/components/products/ProductSummarySection";
import ProductImageCard from "@/cashier/components/products/ProductImageCard";
import VariantsMatrix from "@/cashier/components/products/VariantsMatrix";
import { variantLimitProblem } from "@/cashier/lib/productLimits";
import { useWarehouses } from "@/cashier/api/useCatalogWrite";
import { CARD, CARD_PAD, DOT, MAIN_COL, SECTION_HEAD, SECTION_HINT, SECTION_TITLE, WRAP } from "@/cashier/components/products/formStyles";
import { useShopOptions } from "@/cashier/api/useShopOptions";
import { useStockMaterials } from "@/cashier/api/useStock";
import { resolveSizePreset } from "@/cashier/lib/shopOptions";
import { resolveSkuBase } from "@/cashier/api/catalogApi";
import { useExistingSkus, useNextSkuBase } from "@/cashier/api/useCatalogWrite";
import { imageProblem, imagesOf } from "@/cashier/api/productImage";
import { initialProductForm } from "@/cashier/components/products/productSeed";
import { MAX_IMAGES_PER_SKU } from "@/cashier/lib/productImageRules";

const MAX_PRODUCT_IMAGES = MAX_IMAGES_PER_SKU;

// نموذج إضافة / تعديل منتج مع مولّد متغيرات اللون والمقاس.
export default function ProductForm({ product, seed, onSubmit, onCancel, onPrintLabels, isSaving = false }) {
  const isEdit = !!product;
  // أساس الـSKU من السيرفر (استعلام واحد). العدّ في المتصفح بقى خطة رجوع بس لنشر قديم بلا الـendpoint.
  const { data: serverSkuBase } = useNextSkuBase();
  const { data: existingSkus = [] } = useExistingSkus(serverSkuBase === null);
  const [form, setForm] = useState(() => initialProductForm(product, seed));
  const [colors, setColors] = useState(product?.colors ?? []);
  const [sizePreset, setSizePreset] = useState("clothing");
  const [sizes, setSizes] = useState(product?.sizes ?? []);
  // صور المنتج: المحفوظة في الباك (للعرض) + ملفات جديدة اختارها المستخدم (تُرفع بعد حفظ المنتج).
  const [picked, setPicked] = useState([]);
  const saved = imagesOf(product);
  // سبب منع التوليد، بيتعرض فوق الجدول بدل ما الصفوف تتولّد وتتوقف في السيرفر.
  const [matrixError, setMatrixError] = useState("");
  const [rows, setRows] = useState(
    product
      ? product.variants.map((v) => ({
          id: v.id,
          color: v.color,
          size: v.size,
          sku: v.sku,
          barcode: v.barcode,
          sellPrice: v.sellPrice,
          // حد التنبيه المحفوظ بيفتح في الشاشة؛ لو اتسقط هنا الشاشة بتحفظ صفر على كل تركيبة.
          reorderLevel: v.reorderLevel ?? "0",
          stock: 0,
        }))
      : [],
  );

  // المخزن اللي هيستلم الرصيد الافتتاحي: المحل اللي عنده فرع ومخزن مش هيقبل «أول مخزن نشط» كاختيار إجباري.
  const { data: warehouses = [] } = useWarehouses();
  const activeWarehouses = warehouses.filter((w) => w.is_active !== false);
  useEffect(() => {
    if (form.warehouseId || activeWarehouses.length === 0) return;
    patch({ warehouseId: activeWarehouses[0].id });
  }, [form.warehouseId, activeWarehouses]);

  const { options: shopOptions } = useShopOptions();
  // اقتراحات الخامة هي خامات المحل نفسه (زي ما المواسم بتيجي من مواسم المحل): قائمة مقترحة،
  // والخانة نفسها نص حر فصاحب المحل يقدر يكتب خامة جديدة.
  const { data: materials = [] } = useStockMaterials();
  const presetSizes = shopOptions.sizeSets[resolveSizePreset(shopOptions.sizeSets, sizePreset)] ?? [];

  function patch(fields) {
    setForm((prev) => ({ ...prev, ...fields }));
  }

  function toggleColor(name) {
    setColors((prev) => (prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name]));
  }

  function toggleSize(size) {
    setSizes((prev) => (prev.includes(size) ? prev.filter((s) => s !== size) : [...prev, size]));
  }

  function pickImages(files) {
    const list = Array.from(files ?? []);
    if (list.length === 0) return;
    const room = MAX_PRODUCT_IMAGES - saved.length - picked.length;
    const next = [];
    for (const file of list.slice(0, Math.max(room, 0))) {
      const problem = imageProblem(file);
      if (problem) toast.error(`${file.name}: ${problem}`);
      else next.push({ file, url: URL.createObjectURL(file) });
    }
    if (list.length > room) toast.error(`الحد الأقصى ${MAX_PRODUCT_IMAGES} صور للمنتج`);
    if (next.length) setPicked((prev) => [...prev, ...next]);
  }

  function removePicked(index) {
    setPicked((prev) => {
      URL.revokeObjectURL(prev[index]?.url);
      return prev.filter((_, i) => i !== index);
    });
  }

  function generateRows() {
    // العدد بيتحسب قبل التوليد: 200 لون × 60 مقاس = 12,000 صف كان بيتولّد كامل ثم يرفضه الباك إند.
    const problem = variantLimitProblem(colors, sizes);
    if (problem) {
      setMatrixError(problem);
      return;
    }
    setMatrixError("");
    // أساس SKU فريد من الأكواد الموجودة فعلاً في النظام (العشوائي كان يتكرر ويرفضه الباك بـ 409).
    // في التعديل نشيل لاحقة التركيبة من sku المنتج؛ في الإضافة الأساس جاهز (SKU-0203) ولا نقصّه.
    const skuBase = resolveSkuBase({ product, serverBase: serverSkuBase, existingSkus });
    const next = [];
    colors.forEach((color, ci) => {
      sizes.forEach((size, si) => {
        const existing = rows.find((r) => r.color === color && r.size === size);
        next.push(
          existing ?? {
            id: `row-${ci}-${si}`,
            color,
            size,
            sku: `${skuBase}-${String(ci + 1).padStart(2, "0")}${String(si + 1).padStart(2, "0")}`,
            barcode: "",
            sellPrice: form.sellPrice,
            stock: 0,
          },
        );
      });
    });
    setRows(next);
  }

  function updateRow(id, fields) {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...fields } : r)));
  }

  function generateBarcodes() {
    // الرقم بيتاخد من عدّاد المحل في الباك عند الحفظ (EAN-13 صحيح ومش بيتكرر). هنا بنعلّم الصفوف اللي من غير باركود بس.
    setRows((prev) => prev.map((r) => (String(r.barcode ?? "").trim() ? r : { ...r, autoBarcode: true })));
  }

  const canSave = form.name.trim().length > 2 && rows.length > 0 && rows.every((r) => Number(r.sellPrice) > 0);

  return (
    <>
      <ProductEditorHero
        title={isEdit ? `تعديل المنتج: ${product.name}` : "إضافة منتج"}
        subtitle="سجل بيانات الموديل ومقاساته وألوانه وسعر البيع والمخزون الافتتاحي. تكلفة الشراء تُحسب من فواتير الشراء."
        sku={product?.sku}
        canPrint={rows.length > 0}
        onPrintLabels={() => onPrintLabels?.(rows)}
      />

      <div className={WRAP}>
        <div className={MAIN_COL}>
          <div className={`${CARD} ${CARD_PAD} flex animate-up flex-col gap-7 [animation-delay:.15s]`}>
            <ProductBasicsSection
              form={form}
              onPatch={patch}
              sizePreset={sizePreset}
              onSizePresetChange={(v) => { setSizePreset(v); setSizes([]); }}
              materials={materials}
            />
            <ProductPricingSection form={form} onPatch={patch} />
            <ProductVariantsPicker
              colors={colors}
              onToggleColor={toggleColor}
              sizes={sizes}
              onToggleSize={toggleSize}
              presetSizes={presetSizes}
              canGenerate={colors.length > 0 && sizes.length > 0}
              onGenerate={generateRows}
            />
            <ProductSummarySection rows={rows} />
          </div>

          <div className={`${CARD} ${CARD_PAD} animate-up [animation-delay:.2s]`}>
            <div className={SECTION_HEAD}>
              <span className={DOT} />
              <h2 className={SECTION_TITLE}>جدول التركيبات</h2>
              <span className={SECTION_HINT}>SKU وباركود ورصيد افتتاحي لكل تركيبة لون × مقاس</span>
            </div>
            <div className="mt-[18px] space-y-3">
              {activeWarehouses.length > 0 && (
                <label className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-muted/30 px-3 py-2">
                  <span className="text-xs font-semibold text-muted-foreground">المخزن اللي هيستلم الرصيد الافتتاحي</span>
                  <select
                    className="h-8 rounded-md border border-input bg-background px-2 text-xs font-semibold"
                    value={form.warehouseId ?? ""}
                    onChange={(e) => patch({ warehouseId: e.target.value })}
                  >
                    {activeWarehouses.map((w) => (
                      <option key={w.id} value={w.id}>{w.name}</option>
                    ))}
                  </select>
                  {activeWarehouses.length === 1 && (
                    <span className="text-[11px] text-muted-foreground">(المحل عنده مخزن واحد — يتضاف غيره من إعدادات المخازن)</span>
                  )}
                </label>
              )}
              {matrixError && (
                <p role="alert" className="rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm font-semibold text-destructive">
                  {matrixError}
                </p>
              )}
              <VariantsMatrix
                rows={rows}
                onChange={updateRow}
                onGenerate={generateRows}
                onGenerateBarcodes={generateBarcodes}
                defaultSell={form.sellPrice}
              />
            </div>
          </div>
        </div>

        <ProductImageCard
          saved={saved}
          picked={picked}
          maxImages={MAX_PRODUCT_IMAGES}
          onPickImages={pickImages}
          onRemovePicked={removePicked}
          canSave={canSave}
          isSaving={isSaving}
          onSave={() => onSubmit({ ...form, colors, sizes, variants: rows, imageFiles: picked.map((p) => p.file) })}
          onCancel={onCancel}
        />
      </div>
    </>
  );
}