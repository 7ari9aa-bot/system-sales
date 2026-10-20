import { useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Button } from "@/cashier/components/ui/button";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { colorHex, stockStatus } from "@/cashier/lib/mockData";
import { cn } from "@/cashier/lib/utils";

// اختيار اللون والمقاس عند إضافة منتج من البحث (مع احترام رصيد كل متغير).
export default function VariantPickerDialog({ product, open, onOpenChange, onPick }) {
  const [color, setColor] = useState(null);
  const activeColor = color ?? product?.colors?.[0] ?? null;
  const sizes = product?.variants.filter((v) => v.color === activeColor) ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{product?.name}</DialogTitle>
          <DialogDescription>
            اختر اللون والمقاس — سيتم خصم الكمية من رصيد المتغير المحدد.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">اللون</p>
            <div className="flex flex-wrap gap-2">
              {product?.colors.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={cn(
                    "flex items-center gap-2 rounded-lg border px-3 py-1.5 text-xs transition-colors",
                    activeColor === c ? "border-primary bg-accent font-semibold text-primary" : "border-border hover:bg-muted/60",
                  )}
                >
                  <span className="h-3.5 w-3.5 rounded-full ring-1 ring-black/10" style={{ backgroundColor: colorHex(c) }} />
                  {c}
                </button>
              ))}
            </div>
          </div>

          <div>
            <p className="mb-2 text-xs font-semibold text-muted-foreground">المقاس</p>
            <div className="flex flex-wrap gap-2">
              {sizes.map((v) => {
                const status = stockStatus(v.stock, product.threshold);
                const disabled = v.stock === 0;
                return (
                  <button
                    key={v.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      onPick(v);
                      onOpenChange(false);
                    }}
                    className={cn(
                      "min-w-[76px] rounded-lg border px-3 py-2 text-center transition-colors",
                      disabled
                        ? "cursor-not-allowed border-dashed border-border bg-muted/50 text-muted-foreground"
                        : "border-border hover:border-primary hover:bg-accent",
                    )}
                  >
                    <span className="block text-sm font-semibold">{v.size}</span>
                    <span
                      className={cn(
                        "num block text-[10px]",
                        status === "out" ? "text-rose-600" : status === "low" ? "text-amber-600" : "text-muted-foreground",
                      )}
                    >
                      {disabled ? "نافد" : `متاح ${v.stock}`}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex items-center justify-between rounded-lg bg-muted/60 px-3 py-2">
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              <ColorSwatch color={activeColor} hex={colorHex(activeColor)} />
              <span className="num">{product?.sku}</span>
            </span>
            <span className="num text-sm font-bold">{product?.sellPrice.toFixed(2)} ج.م</span>
          </div>

          <Button variant="outline" className="w-full" onClick={() => onOpenChange(false)}>
            إلغاء
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}