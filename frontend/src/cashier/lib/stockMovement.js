// حركة المخزون: المرتجع يعود لرصيد نفس المتغير، والبديل يُخصم منه.
import { products } from "@/cashier/lib/mockData";

export function applyStockMovement(returns = [], replacements = []) {
  function originVariant(code, barcode) {
    for (const product of products) {
      const variant = product.variants.find((v) => (barcode && v.barcode === barcode) || v.sku === code);
      if (variant) return variant;
    }
    return null;
  }

  returns.forEach((line) => {
    const variant = originVariant(line.code, line.barcode);
    if (variant) variant.stock += line.qty;
  });

  replacements.forEach((line) => {
    const variant = originVariant(line.code, line.barcode);
    if (variant) variant.stock = Math.max(0, variant.stock - line.qty);
  });
}