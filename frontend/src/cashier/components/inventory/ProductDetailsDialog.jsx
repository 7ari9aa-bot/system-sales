import { useState } from "react";
import { Archive, History, Inbox, Pencil } from "lucide-react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { catalogApi } from "@/cashier/api/catalogApi";
import { CATALOG_KEY } from "@/cashier/api/usePosSale";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/cashier/components/ui/table";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import { colorHex, stockStatus } from "@/cashier/lib/uiConstants";
import ReorderLevelCell from "@/cashier/components/inventory/ReorderLevelCell";
import { fmtInt, fmtMoneyShort } from "@/cashier/lib/format";

// تفاصيل منتج مفتوح من بطاقة: بياناته الأساسية مع كل تركيبات اللون والمقاس وأرصدتها.
/** Where this product is edited, or null when it has no id (nothing to open). */
export function editProductPath(product) {
  return product?.id ? `/cashier/products/${encodeURIComponent(product.id)}/edit` : null;
}

// Orange like "بدء جرد": the way to correct a product must be seen, not hunted for.
const EDIT_BTN =
  "h-auto gap-2 rounded-[10px] border border-[#E8761A] !bg-[#E8761A] px-4 py-2 text-[13px] font-semibold !text-white shadow-sm transition-all duration-200 hover:border-[#D1650F] hover:!bg-[#D1650F] hover:!text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#E8761A]";

const ARCHIVE_BTN =
  "h-auto gap-2 rounded-[10px] border border-[#C6432F] bg-white px-3 py-2 text-[13px] font-semibold text-[#C6432F] transition-colors duration-200 hover:bg-[#C6432F] hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#C6432F]";

const CONFIRM_BTN =
  "h-auto rounded-[10px] border border-[#C6432F] !bg-[#C6432F] px-3 py-2 text-[13px] font-semibold !text-white transition-colors duration-200 hover:!bg-[#A93726] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#C6432F]";

export default function ProductDetailsDialog({ product, open, onOpenChange, onMovements }) {
  // Hooks first: the early return below must not sit between them and the render.
  const queryClient = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!product) return null;

  // الأرشفة كانت في الخادم بس ومفيش طريق ليها من الشاشة: المنتج الغلط يفضل يوسّخ الكتالوج للأبد.
  async function archive() {
    setBusy(true);
    setError("");
    try {
      await catalogApi.archiveProduct(product.id);
      await queryClient.invalidateQueries({ queryKey: CATALOG_KEY });
      setAsking(false);
      onOpenChange(false);
    } catch (e) {
      setError(e?.message || "تعذّرت أرشفة المنتج. جرّب تاني");
    } finally {
      setBusy(false);
    }
  }

  const threshold = product.threshold; // the reorder level comes from the backend; none set = no "low" state
  const variants = product.variants ?? [];
  const editTo = editProductPath(product);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-3xl border-[#E3DED4]">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{product.name}</DialogTitle>
          <DialogDescription className="num text-[12px] text-[#7A766C]">
            {[product.sku, product.category, product.brand].filter(Boolean).join(" • ")}
          </DialogDescription>
          <div className="flex flex-wrap items-center gap-2">
            {editTo && (
              <Button asChild variant="ghost" className={EDIT_BTN}>
                <Link to={editTo}>
                  <Pencil className="h-4 w-4 shrink-0 !text-white" />
                  <span className="!text-white">تعديل المنتج</span>
                </Link>
              </Button>
            )}
            {editTo && !asking && (
              <Button type="button" variant="ghost" className={ARCHIVE_BTN} onClick={() => setAsking(true)}>
                <Archive className="h-4 w-4 shrink-0" />
                <span>أرشفة المنتج</span>
              </Button>
            )}
          </div>
          {asking && (
            <div className="mt-2 rounded-xl border border-[#E3B4A6] bg-[#FDF3EF] p-3 text-[12px] text-[#7A3B2A]">
              <p className="m-0">
                أرشفة «{product.name}»؟ هيختفي من البيع والكتالوج، وتاريخه ومبيعاته تفضل محفوظة.
              </p>
              {error && <p className="m-0 mt-1 font-semibold">{error}</p>}
              <div className="mt-2 flex gap-2">
                <Button
                  type="button"
                  className={CONFIRM_BTN}
                  disabled={busy}
                  onClick={archive}
                >
                  {busy ? "جارٍ الأرشفة…" : "أيّوه، أرشفة"}
                </Button>
                <Button type="button" variant="ghost" disabled={busy} onClick={() => setAsking(false)}>
                  إلغاء
                </Button>
              </div>
            </div>
          )}
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