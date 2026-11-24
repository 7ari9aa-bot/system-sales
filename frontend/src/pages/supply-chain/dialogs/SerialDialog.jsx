/**
 * SerialDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function SerialDialog(props) {
  const {
    handleRegisterSerials,
    isAr,
    serialDialogOpen,
    serialWhId,
    serialsText,
    setSerialDialogOpen,
    setSerialWhId,
    setSerialsText,
    warehouses,
  } = props;

  return (
      <Dialog open={serialDialogOpen} onOpenChange={setSerialDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "تسجيل أرقام تسلسلية جديدة" : "Register Serial Numbers"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleRegisterSerials} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "المستودع المودع به" : "Warehouse"}</Label>
              <Select value={serialWhId} onValueChange={setSerialWhId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
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
              <Label className="text-xs">
                {isAr ? "الأرقام التسلسلية (رقم بكل سطر أو مفصولة بفواصل)" : "Serial Numbers (one per line or comma-separated)"}
              </Label>
              <textarea
                value={serialsText}
                onChange={(e) => setSerialsText(e.target.value)}
                rows={4}
                required
                placeholder="SN-10001&#10;SN-10002&#10;SN-10003"
                className="mt-1 w-full rounded-md border border-[#D6D1C7] bg-[#FAF8F5] p-2 text-xs font-mono focus:border-[#E8761A] focus:outline-none"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#0066CC] text-white hover:bg-[#0052a3]">
                {isAr ? "تسجيل الأرقام" : "Register Serials"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
