import { useNavigate } from "react-router-dom";
import { useRef, useState } from "react";
import { toast } from "sonner";
import ProductForm from "@/cashier/components/products/ProductForm";
import { nextProductSeed } from "@/cashier/components/products/productSeed";
import BarcodeLabelsDialog from "@/cashier/components/products/BarcodeLabelsDialog";
import { GLOW, PAGE } from "@/cashier/components/products/formStyles";
import { useCreateProduct, useUpdateProduct } from "@/cashier/api/useCatalogWrite";
import { retryFailedImages, uploadProductImages } from "@/cashier/api/productImage";
import { createSaveGuard } from "@/cashier/lib/saveOnce";

// شاشة إضافة / تعديل منتج (تُستخدم من مسار الإضافة ومسار التعديل).
export default function ProductEditor({ product }) {
  const navigate = useNavigate();
  const [labels, setLabels] = useState(null);
  const [formKey, setFormKey] = useState(0);
  // بيانات المحل اللي بتتكرر (موسم/فئة/ماركة/خامة) بتفضل في النموذج بعد الحفظ، فإدخال الموديل اللي بعده
  // ما بيحتاجش يختارها من الأول. اللي بيخص المنتج نفسه بيتفضّى.
  const [seed, setSeed] = useState(null);
  const isEdit = !!product;
  const create = useCreateProduct();
  const update = useUpdateProduct(product?.id);

  // الإضافة تُحفظ في الباك (منتج + تركيبات + باركود + رصيد افتتاحي) ثم يتفعّل المنتج ليظهر في شاشة البيع.
  // التعديل يُرسل الفرق فقط (بيانات المنتج وسعر/كود/باركود كل تركيبة وتركيبات جديدة). الرصيد يتغيّر بالجرد وحركات المخزون.
  // المنتج اتحفظ خلاص، فأي صورة تفشل ما تلغيش الحفظ: نرفع الباقي ونقول بالاسم أنهي صورة ما اترفعتش.
  // تقدم الرفع لكل صورة: الشاشة بتعرض "جاري الرفع/تم/فشل" لكل صورة، والفاشل بيتعاد لوحده.
  const [uploadProgress, setUploadProgress] = useState({});
  const [failedPhotos, setFailedPhotos] = useState([]);

  async function uploadPhotos(productId, files) {
    if (!files?.length) return true;
    if (!productId) {
      toast.error("المنتج اتحفظ لكن الصور ما اترفعتش (تعذّر تحديد المنتج). افتح المنتج وأضفها من التعديل.");
      return false;
    }
    setUploadProgress({});
    const { failed } = await uploadProductImages(productId, files, {
      onProgress: (index, state) => setUploadProgress((prev) => ({ ...prev, [index]: state })),
    });
    setFailedPhotos(failed);
    if (failed.length === 0) return true;
    toast.error(`المنتج اتحفظ لكن ${failed.length} صورة ما اترفعتش: ${failed.map((f) => `${f.name} (${f.message})`).join("، ")}`);
    return false;
  }

  // ضغطة تانية أثناء الحفظ بترجّع نفس الطلب بدل ما تعمل منتج تاني بنفس الاسم.
  const saveGuard = useRef(null);
  if (saveGuard.current === null) saveGuard.current = createSaveGuard((values) => save(values));
  const isSaving = create.isPending || update.isPending;

  function handleSubmit(values) {
    return saveGuard.current(values);
  }

  async function save(values) {
    try {
      if (!isEdit) {
        const created = await create.mutateAsync({ name: values.name, description: values.description, categoryId: values.categoryId, brandId: values.brandId, season: values.season, material: values.material, threshold: values.threshold, variants: values.variants, warehouses: values.warehouses, warehouseId: values.warehouseId });
        const photosOk = await uploadPhotos(created?.product?.id, values.imageFiles);
        if (photosOk) toast.success("تم حفظ المنتج في النظام وهو متاح الآن في شاشة البيع — الموسم والفئة والماركة والخامة اتحفظوا للمنتج اللي بعده");
        // التوزيع على مخازن تانية بيتم بعد الحفظ؛ اللي فشل بيتقال بالاسم بدل ما يضيع في صمت.
        const split = created?.distribution;
        if (split?.planned?.length) {
          const failed = split.failed ?? [];
          if (failed.length) {
            toast.error(`المنتج اتحفظ لكن ${failed.length} توزيع مخزن ما اتسجلش: ${failed.map((f) => `${f.warehouseName} ${f.quantity}`).join("، ")}. سجّلها من شاشة المخزون.`);
          } else {
            toast.success(`الرصيد الافتتاحي اتوزّع على ${new Set(split.planned.map((m) => m.warehouseName)).size + 1} مخازن`);
          }
        }
        setSeed(nextProductSeed(values));
        setFormKey((k) => k + 1);
        return;
      }
      const { changed } = await update.mutateAsync({ before: product, after: values, warehouseId: values.warehouseId });
      const hasPhotos = values.imageFiles?.length > 0;
      const photosOk = await uploadPhotos(product.id, values.imageFiles);
      if (photosOk) toast.success(changed || hasPhotos ? "تم حفظ تعديلات المنتج" : "لا توجد تعديلات لحفظها");
      navigate("/cashier/products");
    } catch (e) {
      toast.error(e?.message ?? "تعذّر حفظ المنتج");
    }
  }

  function handleCancel() {
    if (isEdit) navigate("/cashier/products");
    else setFormKey((k) => k + 1);
  }

  return (
    <div className={PAGE}>
      <div className={GLOW} />

      <ProductForm
        key={formKey}
        product={product}
        seed={seed}
        onCancel={handleCancel}
        onPrintLabels={(rows) => setLabels({ rows, name: product?.name ?? "منتج جديد" })}
        onSubmit={handleSubmit}
        isSaving={isSaving}
        uploadProgress={uploadProgress}
        failedPhotos={failedPhotos.length}
        onRetryFailed={async () => {
          const id = product?.id;
          if (!id) return;
          setUploadProgress({});
          const { failed } = await retryFailedImages(id, failedPhotos, {
            onProgress: (index, state) => setUploadProgress((prev) => ({ ...prev, [index]: state })),
          });
          setFailedPhotos(failed);
          if (failed.length === 0) toast.success("كل الصور اترفعت");
        }}
      />

      <BarcodeLabelsDialog open={!!labels} onOpenChange={(o) => !o && setLabels(null)} rows={labels?.rows ?? []} productName={labels?.name ?? ""} />
    </div>
  );
}