import { Link, useParams } from "react-router-dom";
import { PackageSearch, WifiOff } from "lucide-react";
import { Button } from "@/applications/apparel/components/ui/button";
import PageHeader from "@/applications/apparel/components/ui-kit/PageHeader";
import EmptyState from "@/applications/apparel/components/ui-kit/EmptyState";
import ProductEditor from "@/applications/apparel/components/products/ProductEditor";
import { useProductForEdit } from "@/applications/apparel/api/useCatalogWrite";
import { editLoadProblem } from "@/applications/apparel/api/productEdit";
import { appPath } from "../../basePath";

export default function ProductEditPage() {
  const { productId } = useParams();
  const { data: product, isPending, isError, error, refetch } = useProductForEdit(productId);

  if (isPending) {
    return <p className="py-16 text-center text-[13px] text-[#7A766C]">جاري تحميل المنتج…</p>;
  }

  // A failed load is not a missing product: only a 404 means that. A 503 after a deploy, a dropped
  // connection or a refusal gets its own message and a way to try again.
  if (isError && editLoadProblem(error) !== "missing") {
    const refused = editLoadProblem(error) === "forbidden";
    return (
      <div className="animate-fade-up" data-testid="product-edit-load-failed">
        <PageHeader title="تعديل منتج" description={refused ? "لا تملك صلاحية فتح هذا المنتج" : "تعذّر تحميل المنتج الآن"} />
        <EmptyState
          icon={WifiOff}
          title={refused ? "غير مسموح" : "تعذّر الاتصال بالخادم"}
          description={refused ? "اطلب من صاحب المتجر صلاحية تعديل المنتجات." : "المنتج موجود ولم يُحذف. أعد المحاولة بعد لحظات."}
          action={
            refused ? undefined : (
              <Button onClick={() => refetch()} className="h-auto gap-2 rounded-[10px] border border-[#E8761A] !bg-[#E8761A] px-4 py-2.5 text-[13px] font-semibold !text-white hover:!bg-[#D1650F]">
                إعادة المحاولة
              </Button>
            )
          }
        />
      </div>
    );
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
              <Link to={appPath("/products")}>رجوع إلى المنتجات</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return <ProductEditor product={product} />;
}
