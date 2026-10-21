import { History, Inbox } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/cashier/components/ui/table";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { colorHex, shop, stockStatus } from "@/cashier/lib/mockData";
import ReorderLevelCell from "@/cashier/components/inventory/ReorderLevelCell";
import { fmtInt, fmtMoneyShort } from "@/cashier/lib/format";

// تفاصيل منتج مفتوح من بطاقة: بياناته الأساسية مع كل تركيبات اللون والمقاس وأرصدتها.
export default function ProductDetailsDialog({ product, open, onOpenChange, onMovements }) {
  if (!product) return null;

  const threshold = product.threshold ?? shop.lowStockThreshold;
  const variants = product.variants ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-3xl border-[#E3DED4]">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{product.name}</DialogTitle>
          <DialogDescription className="num text-[12px] text-[#7A766C]">
            {[product.sku, product.category, product.brand].filter(Boolean).join(" • ")}
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-3 gap-2 rounded-2xl border border-[#E3DED4] bg-[#F4F1EC] p-3">
          {[
            ["السعر", fmtMoneyShort(product.price)],
            ["الرصيد", fmtInt(product.stock)],
            ["التركيبات", fmtInt(product.variantsCount)],
          ].map(([label, value]) => (
            <span key={label} className="flex flex-col gap-0.5 text-[10px] text-[#9A958A]">
              {label}
              <b className="num text-[14px] font-semibold text-[#3B3A36]">{value}</b>
            </span>
          ))}
        </div>

        {variants.length === 0 ? (
          <EmptyState icon={Inbox} title="لا توجد تركيبات" description="لم تُسجَّل تركيبات لهذا المنتج بعد." compact />
        ) : (
          <div className="max-h-[52vh] overflow-y-auto scroll-slim rounded-2xl border border-[#E3DED4]">
            <Table className="min-w-[620px]">
              <TableHeader>
                <TableRow className="bg-[#F4F1EC] hover:bg-[#F4F1EC]">
                  <TableHead>اللون / المقاس</TableHead>
                  <TableHead>الباركود</TableHead>
                  <TableHead className="text-center">حد الطلب</TableHead>
                  <TableHead className="text-center">الرصيد</TableHead>
                  <TableHead>الحالة</TableHead>
                  {onMovements && <TableHead className="text-center">الإجراءات</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {variants.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell>
                      <span className="flex items-center gap-2">
                        <ColorSwatch color={v.color} hex={colorHex(v.color)} />
                        <span className="text-xs">مقاس {v.size}</span>
                      </span>
                    </TableCell>
                    <TableCell className="num text-xs">{v.barcode || "—"}</TableCell>
                    <TableCell className="text-center">
                      {v.status ? (
                        <ReorderLevelCell variantId={v.id} value={v.threshold} />
                      ) : (
                        <span className="num text-xs text-muted-foreground">{v.threshold ?? "—"}</span>
                      )}
                    </TableCell>
                    <TableCell className="num text-center font-semibold">{fmtInt(v.stock)}</TableCell>
                    <TableCell>
                      <StatusBadge kind="inventory" value={v.status ?? stockStatus(v.stock, v.threshold ?? threshold)} />
                    </TableCell>
                    {onMovements && (
                      <TableCell className="text-center">
                        <Button variant="ghost" size="sm" className="h-8 gap-1.5 text-xs" onClick={() => onMovements(v)}>
                          <History className="h-3.5 w-3.5" />
                          الحركات
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}