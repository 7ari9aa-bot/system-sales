import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import ProductCard from "@/cashier/components/inventory/ProductCard";
import { fmtInt } from "@/cashier/lib/format";
import { shop, stockStatus } from "@/cashier/lib/mockData";
import { systemProducts, useAddedProducts } from "@/cashier/lib/productStore";

// منتجات النظام في شبكة بطاقات — المُضاف من شاشة إضافة منتج يظهر أول القائمة.
export default function SystemProductsSection({ onOpen }) {
  const added = useAddedProducts();

  const products = systemProducts(added).map((p) => {
    const threshold = p.threshold ?? shop.lowStockThreshold;
    return {
      id: p.id,
      name: p.name,
      sku: p.sku,
      category: p.category,
      brand: p.brand,
      price: p.sellPrice,
      stock: p.totalStock,
      variantsCount: p.variantsCount,
      threshold,
      statusValue: stockStatus(p.totalStock, threshold),
      variants: p.variants ?? [],
      image: p.image,
    };
  });

  return (
    <section className="animate-inv-rise flex flex-col gap-3 [animation-delay:.3s]">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-[15px] font-semibold">منتجات النظام</h2>
          <p className="mt-1 text-[11px] text-[#7A766C]">
            {fmtInt(products.length)} منتجًا • {fmtInt(added.length)} مُضاف من شاشة إضافة منتج
          </p>
        </div>
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-9 gap-1.5 rounded-[10px] border-[#C7C2B8] bg-white text-xs text-[#3B3A36] transition-[border-color,box-shadow] duration-200 hover:border-[#E8761A] hover:bg-white hover:text-[#3B3A36]"
        >
          <Link to="/cashier/products">
            <Plus className="h-3.5 w-3.5" />
            إضافة منتج
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {products.map((p) => (
          <ProductCard key={p.id} product={p} onOpen={onOpen} />
        ))}
      </div>
    </section>
  );
}