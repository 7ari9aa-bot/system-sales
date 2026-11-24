/**
 * LandedCostDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function LandedCostDialog(props) {
  const {
    handleCreateLandedCost,
    isAr,
    landedCostDialogOpen,
    lcAmount,
    lcNote,
    setLandedCostDialogOpen,
    setLcAmount,
    setLcNote,
  } = props;

  return (
      <Dialog open={landedCostDialogOpen} onOpenChange={setLandedCostDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إضافة مصاريف شحن أو جمارك" : "Add Landed Cost"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateLandedCost} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "المبلغ الإجمالي (ج.م)" : "Total Amount"}</Label>
              <Input
                type="number"
                step="0.01"
                min="0"
                value={lcAmount}
                onChange={(e) => setLcAmount(e.target.value)}
                placeholder="1500.00"
                required
                className="mt-1 h-9"
              />
            </div>
            <div>
              <Label className="text-xs">{isAr ? "بيان المصروف" : "Note / Description"}</Label>
              <Input
                value={lcNote}
                onChange={(e) => setLcNote(e.target.value)}
                placeholder={isAr ? "مصاريف تخليص جمركي أو شحن بحري" : "Customs clearance, freight"}
                className="mt-1 h-9"
              />
            </div>
            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ التكلفة" : "Save Landed Cost"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
