/**
 * TransferDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function TransferDialog(props) {
  const {
    fromWhId,
    handleCreateTransfer,
    isAr,
    setFromWhId,
    setToWhId,
    setTransferDialogOpen,
    setTransferNotes,
    setTransferQty,
    setTransferVariantId,
    toWhId,
    transferDialogOpen,
    transferNotes,
    transferQty,
    transferVariantId,
    variants,
    warehouses,
  } = props;

  return (
      <Dialog open={transferDialogOpen} onOpenChange={setTransferDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "طلب تحويل مخزون جديد" : "New Stock Transfer"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateTransfer} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "من مستودع (المصدر)" : "From Warehouse"}</Label>
              <Select value={fromWhId} onValueChange={setFromWhId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر المستودع" : "Select warehouse"} />
                </SelectTrigger>
                <SelectContent>
                  {warehouses.map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.name} ({w.code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">{isAr ? "إلى مستودع (الهدف)" : "To Warehouse"}</Label>
              <Select value={toWhId} onValueChange={setToWhId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر المستودع" : "Select warehouse"} />
                </SelectTrigger>
                <SelectContent>
                  {warehouses
                    .filter((w) => w.id !== fromWhId)
                    .map((w) => (
                      <SelectItem key={w.id} value={w.id}>
                        {w.name} ({w.code})
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">{isAr ? "الصنف المراد نقله" : "Product Variant"}</Label>
              <Select value={transferVariantId} onValueChange={setTransferVariantId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر الصنف" : "Select variant"} />
                </SelectTrigger>
                <SelectContent>
                  {variants.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">{isAr ? "الكمية" : "Quantity"}</Label>
              <Input
                type="number"
                min="1"
                value={transferQty}
                onChange={(e) => setTransferQty(e.target.value)}
                className="mt-1 h-9"
              />
            </div>

            <div>
              <Label className="text-xs">{isAr ? "ملاحظات التحويل" : "Notes"}</Label>
              <Input
                value={transferNotes}
                onChange={(e) => setTransferNotes(e.target.value)}
                placeholder={isAr ? "سبب النقل أو توجيهات الشحن" : "Reason or instructions"}
                className="mt-1 h-9"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "إنشاء طلب التحويل" : "Create Transfer"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
