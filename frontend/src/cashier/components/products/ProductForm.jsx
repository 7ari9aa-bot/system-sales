import { useEffect, useState } from "react";
import { toast } from "sonner";
import ProductEditorHero from "@/cashier/components/products/ProductEditorHero";
import ProductBasicsSection from "@/cashier/components/products/ProductBasicsSection";
import ProductPricingSection from "@/cashier/components/products/ProductPricingSection";
import ProductVariantsPicker from "@/cashier/components/products/ProductVariantsPicker";
import ProductSummarySection from "@/cashier/components/products/ProductSummarySection";
import ProductImageCard from "@/cashier/components/products/ProductImageCard";
import VariantsMatrix from "@/cashier/components/products/VariantsMatrix";
import StockDistribution from "@/cashier/components/products/StockDistribution";
import { allocationProblem, withPrimaryWarehouse } from "@/cashier/lib/stockDistribution";
import { variantLimitProblem } from "@/cashier/lib/productLimits";
import { useWarehouses } from "@/cashier/api/useCatalogWrite";
import {
  bindProductImage,
  deleteProductImage,
  reorderProductImages,
} from "@/cashier/api/productImage";
import { useQueryClient } from "@tanstack/react-query";
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
export default function ProductForm({
  product,
  seed,
  onSubmit,
  onCancel,
  onPrintLabels,
  isSaving = false,
  uploadProgress = {},
  failedPhotos = 0,
  onRetryFailed,
}) {
  const isEdit = !!product;
  // أساس الـSKU من السيرفر (استعلام واحد). العدّ في المتصفح بقى خطة رجوع بس لنشر قديم بلا الـendpoint.
  const { data: serverSkuBase } = useNextSkuBase();
  const { data: existingSkus = [] } = useExistingSkus(serverSkuBase === null);
  const [form, setForm] = useState(() => {
    const base = initialProductForm(product, seed);
    // حد التنبيه بيتحفظ لكل تركيبة؛ الشاشة بتعرض حد واحد، فلازم تفتح على المحفوظ مش على فاضي.
    const savedLevel = product?.variants?.find((v) => v.reorderLevel != null)?.reorderLevel;
    return base.threshold === "" && savedLevel != null ? { ...base, threshold: String(savedLevel) } : base;
  });
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

  // «حد التنبيه» في الشاشة حد واحد للموديل: تعديله لازم يوصل لكل تركيبة،
  // وإلا فرق الحفظ مابيشوفش حاجة ويطلع «لا توجد تعديلات لحفظها».
  const patchWithThreshold = (next) => {
    patch(next);
    if (next.threshold === undefined) return;
    const level = String(next.threshold ?? "").trim() === "" ? "0" : String(next.threshold);
    setRows((prev) => prev.map((row) => ({ ...row, reorderLevel: level })));
  };

  const queryClient = useQueryClient();
  // الصور المحفوظة بتتحكم من هنا (حذف/ترتيب/ربط بلون) وبتحفظ على السيرفر فورًا.
  const refreshProduct = () => queryClient.invalidateQueries();

  async function handleDeleteSaved(image) {
    try {
      await deleteProductImage(product.id, image.id);
      toast.success("اتحذفت الصورة");
      await refreshProduct();
    } catch (e) {
      toast.error(e?.message ?? "تعذّر حذف الصورة");
    }
  }

  async function handleMoveSaved(image, step) {
    const ids = saved.map((i) => i.id);
    const from = ids.indexOf(image.id);
    const to = from + step;
    if (from < 0 || to < 0 || to >= ids.length) return;
    [ids[from], ids[to]] = [ids[to], ids[from]];
    try {
      await reorderProductImages(product.id, ids);
      await refreshProduct();
    } catch (e) {
      toast.error(e?.message ?? "تعذّر ترتيب الصور");
    }
  }

  async function handleBindSaved(image, variantId) {
    try {
      await bindProductImage(product.id, image.id, variantId);
      toast.success(variantId ? "الصورة اتربطت باللون" : "الصورة رجعت لمعرض المنتج");
      await refreshProduct();
    } catch (e) {
      toast.error(e?.message ?? "تعذّر ربط الصورة");
    }
  }

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

  // التوزيع الغلط بيمنع الحفظ: منتج برصيد أكبر من اللي في الجدول مش حاجة تتحفظ وتتصلح بعدين.
  const canSave =
    form.name.trim().length > 2 &&
    rows.length > 0 &&
    rows.every((r) => Number(r.sellPrice) > 0) &&
    !allocationProblem(rows, activeWarehouses, form.warehouseId);

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
            <ProductPricingSection form={form} onPatch={patchWithThreshold} />
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
                    onChange={(e) => {
                      const next = e.target.value;
                      setRows((prev) => withPrimaryWarehouse(prev, next));
                      patch({ warehouseId: next });
                    }}
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
              <StockDistribution
                rows={rows}
                warehouses={activeWarehouses}
                primaryId={form.warehouseId}
                onChangeAllocation={(rowId, warehouseId, value) =>
                  setRows((prev) =>
                    prev.map((r) => (r.id === rowId ? { ...r, alloc: { ...(r.alloc ?? {}), [warehouseId]: value } } : r)),
                  )
                }
                problem={allocationProblem(rows, activeWarehouses, form.warehouseId)}
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
          colors={(product?.variants ?? [])
            .filter((v) => v.color)
            .map((v) => ({ variantId: v.id, name: v.color }))
            .filter((c, i, all) => all.findIndex((x) => x.name === c.name) === i)}
          progress={uploadProgress}
          failedCount={failedPhotos}
          onRetryFailed={onRetryFailed}
          onDeleteSaved={product ? handleDeleteSaved : undefined}
          onMoveSaved={product ? handleMoveSaved : undefined}
          onBindSaved={product ? handleBindSaved : undefined}
          canSave={canSave}
          isSaving={isSaving}
          onSave={() => onSubmit({ ...form, colors, sizes, variants: rows, warehouses: activeWarehouses, imageFiles: picked.map((p) => p.file) })}
          onCancel={onCancel}
        />
      </div>
    </>
  );
}