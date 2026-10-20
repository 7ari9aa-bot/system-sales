import PageHeader from "@/cashier/components/ui-kit/PageHeader";
import StocktakeTable from "@/cashier/components/inventory/StocktakeTable";
import { stocktakeRows } from "@/cashier/lib/mockData";


export default function StocktakePage() {
  return (
    <div className="animate-fade-up">
      <PageHeader
        title="الجرد الفعلي"
        description="عدّ الأصناف وأدخل الكمية الفعلية — يظهر الفرق فورًا ولا تُعدّل الأرصدة إلا بعد اعتماد التسوية"
      />
      <StocktakeTable initialRows={stocktakeRows} />
    </div>
  );
}