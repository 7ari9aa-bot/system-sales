/**
 * TrackingPolicyDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function TrackingPolicyDialog(props) {
  const {
    formPolicyExpiry,
    formPolicyMode,
    handleSaveTrackingPolicy,
    isAr,
    policyDialogOpen,
    setFormPolicyExpiry,
    setFormPolicyMode,
    setPolicyDialogOpen,
  } = props;

  return (
      <Dialog open={policyDialogOpen} onOpenChange={setPolicyDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "تحديد سياسة تتبع الصنف" : "Set Tracking Policy"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSaveTrackingPolicy} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "نوع التتبع" : "Tracking Mode"}</Label>
              <Select value={formPolicyMode} onValueChange={setFormPolicyMode}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{isAr ? "بدون تتبع إضافي (None)" : "Standard (None)"}</SelectItem>
                  <SelectItem value="batch">{isAr ? "تتبع برقم الدفعة/التشغيلة (Batch/Lot)" : "Batch / Lot"}</SelectItem>
                  <SelectItem value="serial">{isAr ? "تتبع بالأرقام التسلسلية (Serial Number)" : "Serial Number"}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="policyExpiry"
                checked={formPolicyExpiry}
                onChange={(e) => setFormPolicyExpiry(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-[#E8761A] focus:ring-[#E8761A]"
              />
              <Label htmlFor="policyExpiry" className="cursor-pointer text-xs">
                {isAr ? "إلزامية تسجيل تاريخ انتهاء الصلاحية للدفعة" : "Require Expiry Date for Lots"}
              </Label>
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ السياسة" : "Save Policy"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
