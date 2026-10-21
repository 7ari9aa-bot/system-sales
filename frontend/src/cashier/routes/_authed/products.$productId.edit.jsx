import { Link, useParams } from "react-router-dom";
import { PackageSearch } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import PageHeader from "@/cashier/components/ui-kit/PageHeader";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import ProductEditor from "@/cashier/components/products/ProductEditor";
import { useProductForEdit } from "@/cashier/api/useCatalogWrite";

export default function ProductEditPage() {
  const { productId } = useParams();
  const { data: product, isPending, isError } = useProductForEdit(productId);

  if (isPending) {
    return <p className="py-16 text-center text-[13px] text-[#7A766C]">جاري تحميل المنتج…</p>;
  }

  if (isError || !product) {
    return (
      <div className="animate-fade-up">
        <PageHeader title="تعديل منتج" description="لم يتم العثور على المنتج المطلوب" />
        <EmptyState
          icon={PackageSearch}
          title="المنتج غير موجود"
          description="ربما تم حذف المنتج أو أن الرابط غير صحيح."
          action={
            <Button asChild variant="outline">
              <Link to="/cashier/products">رجوع إلى المنتجات</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return <ProductEditor product={product} />;
}
