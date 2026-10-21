import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { toast } from "sonner";
import ProductForm from "@/cashier/components/products/ProductForm";
import BarcodeLabelsDialog from "@/cashier/components/products/BarcodeLabelsDialog";
import { GLOW, PAGE } from "@/cashier/components/products/formStyles";
import { useCreateProduct, useUpdateProduct } from "@/cashier/api/useCatalogWrite";
import { uploadProductImages } from "@/cashier/api/productImage";

// شاشة إضافة / تعديل منتج (تُستخدم من مسار الإضافة ومسار التعديل).
export default function ProductEditor({ product }) {
  const navigate = useNavigate();
  const [labels, setLabels] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const isEdit = !!product;
  const create = useCreateProduct();
  const update = useUpdateProduct(product?.id);

  // الإضافة تُحفظ في الباك (منتج + تركيبات + باركود + رصيد افتتاحي) ثم يتفعّل المنتج ليظهر في شاشة البيع.
  // التعديل يُرسل الفرق فقط (بيانات المنتج وسعر/كود/باركود كل تركيبة وتركيبات جديدة). الرصيد يتغيّر بالجرد وحركات المخزون.
  // المنتج اتحفظ خلاص، فأي صورة تفشل ما تلغيش الحفظ: نرفع الباقي ونقول بالاسم أنهي صورة ما اترفعتش.
  async function uploadPhotos(productId, files) {
    if (!files?.length) return true;
    if (!productId) {
      toast.error("المنتج اتحفظ لكن الصور ما اترفعتش (تعذّر تحديد المنتج). افتح المنتج وأضفها من التعديل.");
      return false;
    }
    const { failed } = await uploadProductImages(productId, files);
    if (failed.length === 0) return true;
    toast.error(`المنتج اتحفظ لكن ${failed.length} صورة ما اترفعتش: ${failed.map((f) => `${f.name} (${f.message})`).join("، ")}`);
    return false;
  }

  async function handleSubmit(values) {
    try {
      if (!isEdit) {
        const created = await create.mutateAsync({ name: values.name, description: values.description, categoryId: values.categoryId, brandId: values.brandId, variants: values.variants });
        const photosOk = await uploadPhotos(created?.product?.id, values.imageFiles);
        if (photosOk) toast.success("تم حفظ المنتج في النظام وهو متاح الآن في شاشة البيع");
        setFormKey((k) => k + 1);
        return;
      }
      const { changed } = await update.mutateAsync({ before: product, after: values });
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
        onCancel={handleCancel}
        onPrintLabels={(rows) => setLabels({ rows, name: product?.name ?? "منتج جديد" })}
        onSubmit={handleSubmit}
      />

      <BarcodeLabelsDialog open={!!labels} onOpenChange={(o) => !o && setLabels(null)} rows={labels?.rows ?? []} productName={labels?.name ?? ""} />
    </div>
  );
}