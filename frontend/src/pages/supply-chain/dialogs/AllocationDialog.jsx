/**
 * AllocationDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RefreshCw } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function AllocationDialog(props) {
  const {
    allocDialogOpen,
    allocFormChannel,
    allocFormQty,
    allocFormVarId,
    allocFormWhId,
    allocSaveLoading,
    handleCreateAllocation,
    isAr,
    setAllocDialogOpen,
    setAllocFormChannel,
    setAllocFormQty,
    setAllocFormVarId,
    setAllocFormWhId,
    variants,
    warehouses,
  } = props;

  return (
      <Dialog open={allocDialogOpen} onOpenChange={setAllocDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>
              {isAr ? "تخصيص كوتة مخزون لقناة بيع" : "Allocate Stock to Channel"}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateAllocation} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "المستودع" : "Warehouse"}</Label>
              <Select value={allocFormWhId} onValueChange={setAllocFormWhId}>
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
              <Label className="text-xs">{isAr ? "المنتج / الصنف" : "Product Variant"}</Label>
              <Select value={allocFormVarId} onValueChange={setAllocFormVarId}>
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
              <Label className="text-xs">{isAr ? "قناة البيع المستهدفة" : "Target Sales Channel"}</Label>
              <Select value={allocFormChannel} onValueChange={setAllocFormChannel}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pos">
                    {isAr ? "الكاشير ونقطة البيع (POS)" : "Point of Sale (POS)"}
                  </SelectItem>
                  <SelectItem value="whatsapp">
                    {isAr ? "واتساب (WhatsApp)" : "WhatsApp"}
                  </SelectItem>
                  <SelectItem value="online_store">
                    {isAr ? "المتجر الإلكتروني (Online Store)" : "Online Store"}
                  </SelectItem>
                  <SelectItem value="instagram">
                    {isAr ? "إنستغرام (Instagram)" : "Instagram"}
                  </SelectItem>
                  <SelectItem value="telegram">
                    {isAr ? "تيليجرام (Telegram)" : "Telegram"}
                  </SelectItem>
                  <SelectItem value="messenger">
                    {isAr ? "ماسنجر (Messenger)" : "Messenger"}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">
                {isAr ? "الكمية المخصصة (الكوتة)" : "Allocated Quantity (Quota)"}
              </Label>
              <Input
                type="number"
                min="0"
                value={allocFormQty}
                onChange={(e) => setAllocFormQty(e.target.value)}
                placeholder="10"
                required
                className="mt-1 h-9"
              />
              <p className="mt-1 text-[11px] text-[#7A766C]">
                {isAr
                  ? "القناة لا يمكنها بيع أو حجز أكثر من هذه الكمية ما لم تتم زيادة الكوتة."
                  : "The channel cannot sell or reserve more than this allocated quota."}
              </p>
            </div>

            <DialogFooter className="mt-4">
              <Button
                type="submit"
                disabled={allocSaveLoading}
                className="bg-[#E8761A] text-white hover:bg-[#D1650F]"
              >
                {allocSaveLoading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : isAr ? (
                  "حفظ التخصيص"
                ) : (
                  "Save Allocation"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
