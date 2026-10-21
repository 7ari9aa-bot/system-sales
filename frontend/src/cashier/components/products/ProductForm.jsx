import { useState } from "react";
import { toast } from "sonner";
import ProductEditorHero from "@/cashier/components/products/ProductEditorHero";
import ProductBasicsSection from "@/cashier/components/products/ProductBasicsSection";
import ProductPricingSection from "@/cashier/components/products/ProductPricingSection";
import ProductVariantsPicker from "@/cashier/components/products/ProductVariantsPicker";
import ProductSummarySection from "@/cashier/components/products/ProductSummarySection";
import ProductImageCard from "@/cashier/components/products/ProductImageCard";
import VariantsMatrix from "@/cashier/components/products/VariantsMatrix";
import { CARD, CARD_PAD, DOT, MAIN_COL, SECTION_HEAD, SECTION_HINT, SECTION_TITLE, WRAP } from "@/cashier/components/products/formStyles";
import { SIZE_SETS } from "@/cashier/lib/uiConstants";
import { nextSkuBase } from "@/cashier/api/catalogApi";
import { useExistingSkus } from "@/cashier/api/useCatalogWrite";
import { imageProblem, imagesOf } from "@/cashier/api/productImage";

const MAX_PRODUCT_IMAGES = 4;

// نموذج إضافة / تعديل منتج مع مولّد متغيرات اللون والمقاس.
export default function ProductForm({ product, onSubmit, onCancel, onPrintLabels }) {
  const isEdit = !!product;
  const { data: existingSkus = [] } = useExistingSkus();
  const [form, setForm] = useState({
    name: product?.name ?? "",
    categoryId: product?.categoryId ?? "",
    brandId: product?.brandId ?? "",
    description: product?.description ?? "",
    sellPrice: product?.sellPrice ?? "",
    threshold: product?.threshold ?? "",
  });
  const [colors, setColors] = useState(product?.colors ?? []);
  const [sizePreset, setSizePreset] = useState("clothing");
  const [sizes, setSizes] = useState(product?.sizes ?? []);
  // صور المنتج: المحفوظة في الباك (للعرض) + ملفات جديدة اختارها المستخدم (تُرفع بعد حفظ المنتج).
  const [picked, setPicked] = useState([]);
  const saved = imagesOf(product);
  const [rows, setRows] = useState(
    product
      ? product.variants.map((v) => ({ id: v.id, color: v.color, size: v.size, sku: v.sku, barcode: v.barcode, sellPrice: v.sellPrice, stock: 0 }))
      : [],
  );

  const presetSizes = SIZE_SETS[sizePreset] ?? [];

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
    // أساس SKU فريد من الأكواد الموجودة فعلاً في النظام (العشوائي كان يتكرر ويرفضه الباك بـ 409).
    // في التعديل نشيل لاحقة التركيبة من sku المنتج؛ في الإضافة الأساس جاهز (SKU-0203) ولا نقصّه.
    const skuBase = product?.sku ? product.sku.replace(/-\d{2,4}$/, "") : nextSkuBase(existingSkus);
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
    setRows((prev) => prev.map((r, i) => ({ ...r, barcode: `299${String(1000000000 + r.sku.length * 7919 + i * 137).slice(0, 10)}` })));
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
            <ProductBasicsSection form={form} onPatch={patch} sizePreset={sizePreset} onSizePresetChange={(v) => { setSizePreset(v); setSizes([]); }} />
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
            <div className="mt-[18px]">
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
          onSave={() => onSubmit({ ...form, colors, sizes, variants: rows, imageFiles: picked.map((p) => p.file) })}
          onCancel={onCancel}
        />
      </div>
    </>
  );
}