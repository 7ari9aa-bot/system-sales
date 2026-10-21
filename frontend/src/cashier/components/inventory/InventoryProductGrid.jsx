import { Inbox } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import ProductCard from "@/cashier/components/inventory/ProductCard";
import { fmtInt } from "@/cashier/lib/format";
import { groupVariantsByProduct } from "@/cashier/lib/inventoryGroups";

// شبكة بطاقات المنتجات المعروضة حسب فلاتر المخزون الحالية.
export default function InventoryProductGrid({ rows, onOpen, onShowLow }) {
  const products = groupVariantsByProduct(rows);

  return (
    <section className="animate-inv-rise flex flex-col gap-3 [animation-delay:.3s]">
      <div>
        <h2 className="text-[15px] font-semibold">المنتجات ضمن جدول المخزون</h2>
        <p className="mt-1 text-[11px] text-[#7A766C]">
          {fmtInt(products.length)} منتجًا • {fmtInt(rows.length)} متغيرًا حسب الفلاتر الحالية
        </p>
      </div>

      {products.length === 0 ? (
        <div className="rounded-2xl border border-[#E3DED4] bg-white">
          <EmptyState
            icon={Inbox}
            title="لا توجد أصناف مطابقة"
            description="جرّب تغيير التصنيف أو الفرع أو حالة الرصيد."
            action={
              <Button variant="outline" size="sm" onClick={onShowLow}>
                اعرض النواقص
              </Button>
            }
          />
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((p) => (
            <ProductCard key={p.id} product={p} onOpen={(product) => onOpen(product.id)} />
          ))}
        </div>
      )}
    </section>
  );
}