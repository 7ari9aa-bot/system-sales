/**
 * LotDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LotDialog(props) {
  const {
    handleCreateLot,
    isAr,
    lotCode,
    lotDialogOpen,
    lotExpiresAt,
    lotUnitCost,
    setLotCode,
    setLotDialogOpen,
    setLotExpiresAt,
    setLotUnitCost,
  } = props;

  return (
      <Dialog open={lotDialogOpen} onOpenChange={setLotDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إضافة دفعة تشغيل / تاريخ صلاحية" : "Create New Lot / Batch"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateLot} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "رمز الدفعة (Lot Code)" : "Lot Code"}</Label>
              <Input
                value={lotCode}
                onChange={(e) => setLotCode(e.target.value)}
                placeholder="LOT-2026-B01"
                required
                className="mt-1 h-9"
              />
            </div>

            <div>
              <Label className="text-xs">{isAr ? "تاريخ انتهاء الصلاحية" : "Expiry Date"}</Label>
              <Input
                type="date"
                value={lotExpiresAt}
                onChange={(e) => setLotExpiresAt(e.target.value)}
                className="mt-1 h-9"
              />
            </div>

            <div>
              <Label className="text-xs">{isAr ? "تكلفة الوحدة في هذه الدفعة (اختياري)" : "Unit Cost (Optional)"}</Label>
              <Input
                type="number"
                step="0.01"
                value={lotUnitCost}
                onChange={(e) => setLotUnitCost(e.target.value)}
                placeholder="25.00"
                className="mt-1 h-9"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ الدفعة" : "Create Lot"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
