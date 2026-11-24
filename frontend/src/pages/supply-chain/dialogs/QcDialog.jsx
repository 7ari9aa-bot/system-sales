/**
 * QcDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function QcDialog(props) {
  const {
    handleCompleteQC,
    isAr,
    qcDialogOpen,
    qcNote,
    qcVerdict,
    setQcDialogOpen,
    setQcNote,
    setQcVerdict,
  } = props;

  return (
      <Dialog open={qcDialogOpen} onOpenChange={setQcDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "فحص جودة استلام البضائع" : "Quality Inspection"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "قرار الفحص الإجمالي" : "Verdict"}</Label>
              <Select value={qcVerdict} onValueChange={setQcVerdict}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="passed">{isAr ? "سليم ومقبول للبيع (Pass)" : "Passed"}</SelectItem>
                  <SelectItem value="quarantined">{isAr ? "عزل وحجر صحي (Quarantine)" : "Quarantined"}</SelectItem>
                  <SelectItem value="rejected">{isAr ? "مرفوض وتالف (Reject)" : "Rejected"}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">{isAr ? "تقرير وملاحظات الفاحص" : "Inspector Note"}</Label>
              <Input
                value={qcNote}
                onChange={(e) => setQcNote(e.target.value)}
                placeholder={isAr ? "سليم بالكامل أو تفاصيل التلف" : "Details or notes"}
                className="mt-1 h-9"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button onClick={handleCompleteQC} className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "تأكيد نتيجة الفحص" : "Submit Verdict"}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>
  );
}
