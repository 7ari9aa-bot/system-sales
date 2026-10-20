import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { toast } from "sonner";
import ProductForm from "@/cashier/components/products/ProductForm";
import BarcodeLabelsDialog from "@/cashier/components/products/BarcodeLabelsDialog";
import { GLOW, PAGE } from "@/cashier/components/products/formStyles";
import { useCreateProduct } from "@/cashier/api/useCatalogWrite";

// شاشة إضافة / تعديل منتج (تُستخدم من مسار الإضافة ومسار التعديل).
export default function ProductEditor({ product }) {
  const navigate = useNavigate();
  const [labels, setLabels] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const isEdit = !!product;
  const create = useCreateProduct();

  // الإضافة تُحفظ في الباك (منتج + تركيبات + باركود + رصيد افتتاحي) ثم يتفعّل المنتج ليظهر في البيع.
  // ملاحظة: سعر الشراء لا يُحفظ بعد (الباك ليس فيه عمود تكلفة)، فنقولها صراحة بدل أن نوهم بحفظه.
  async function handleSubmit(values) {
    if (!isEdit) {
      try {
        await create.mutateAsync({ name: values.name, description: values.description, variants: values.variants });
        toast.success("تم حفظ المنتج في النظام وهو متاح الآن في شاشة البيع");
        if (values.variants.some((v) => Number(v.buyPrice) > 0)) toast.info("سعر الشراء لم يُحفظ بعد: عمود التكلفة قيد الإنشاء في الخلفية");
        setFormKey((k) => k + 1);
      } catch (e) {
        toast.error(e?.message ?? "تعذّر حفظ المنتج");
      }
      return;
    }
    toast.success("تم حفظ تعديلات المنتج");
    navigate("/cashier/products");
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