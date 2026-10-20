import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { toast } from "sonner";
import ProductForm from "@/cashier/components/products/ProductForm";
import BarcodeLabelsDialog from "@/cashier/components/products/BarcodeLabelsDialog";
import { GLOW, PAGE } from "@/cashier/components/products/formStyles";
import { addProduct, buildProductRecord } from "@/cashier/lib/productStore";

// شاشة إضافة / تعديل منتج (تُستخدم من مسار الإضافة ومسار التعديل).
export default function ProductEditor({ product }) {
  const navigate = useNavigate();
  const [labels, setLabels] = useState(null);
  const [formKey, setFormKey] = useState(0);
  const isEdit = !!product;

  // شاشة الإضافة تبقى ظاهرة بنموذج فارغ لصنف جديد، وشاشة التعديل ترجع لقسم المنتجات.
  function handleSubmit(values) {
    if (!isEdit) {
      addProduct(buildProductRecord(values));
      toast.success("تم حفظ المنتج — تجده في منتجات النظام بصفحة المخزون");
      setFormKey((k) => k + 1);
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