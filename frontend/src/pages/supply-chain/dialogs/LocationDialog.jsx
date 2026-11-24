/**
 * LocationDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function LocationDialog(props) {
  const {
    handleCreateLocation,
    isAr,
    locCode,
    locKind,
    locName,
    locationDialogOpen,
    setLocCode,
    setLocKind,
    setLocName,
    setLocationDialogOpen,
  } = props;

  return (
      <Dialog open={locationDialogOpen} onOpenChange={setLocationDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إضافة موقع تخزين / رف جديد" : "Add Storage Location"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateLocation} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "رمز الرف / الموقع (Code)" : "Code"}</Label>
              <Input
                value={locCode}
                onChange={(e) => setLocCode(e.target.value)}
                placeholder="A-01-BIN"
                required
                className="mt-1 h-9"
              />
            </div>
            <div>
              <Label className="text-xs">{isAr ? "اسم الموقع" : "Name"}</Label>
              <Input
                value={locName}
                onChange={(e) => setLocName(e.target.value)}
                placeholder={isAr ? "رف التخزين العلوي 1" : "Bin Shelf 1"}
                required
                className="mt-1 h-9"
              />
            </div>
            <div>
              <Label className="text-xs">{isAr ? "نوع الموقع الوظيفي" : "Kind"}</Label>
              <Select value={locKind} onValueChange={setLocKind}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="storage">{isAr ? "تخزين رئيسي (Storage)" : "Storage"}</SelectItem>
                  <SelectItem value="picking">{isAr ? "التقاط وتجهيز (Picking)" : "Picking"}</SelectItem>
                  <SelectItem value="bin">{isAr ? "صندوق / قاطع (Bin)" : "Bin"}</SelectItem>
                  <SelectItem value="shelf">{isAr ? "رف (Shelf)" : "Shelf"}</SelectItem>
                  <SelectItem value="rack">{isAr ? "حامل / ستاند (Rack)" : "Rack"}</SelectItem>
                  <SelectItem value="receiving">{isAr ? "منطقة الاستلام (Receiving)" : "Receiving"}</SelectItem>
                  <SelectItem value="qc">{isAr ? "منطقة فحص الجودة (QC)" : "QC"}</SelectItem>
                  <SelectItem value="quarantine">{isAr ? "منطقة الحجر (Quarantine)" : "Quarantine"}</SelectItem>
                  <SelectItem value="damaged">{isAr ? "تالف (Damaged)" : "Damaged"}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ الموقع" : "Save Location"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
