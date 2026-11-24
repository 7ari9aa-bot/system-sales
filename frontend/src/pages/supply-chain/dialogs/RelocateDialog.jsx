/**
 * RelocateDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export default function RelocateDialog(props) {
  const {
    handleRelocateStock,
    isAr,
    locations,
    relocFromLocId,
    relocQty,
    relocToLocId,
    relocVariantId,
    relocateDialogOpen,
    setRelocFromLocId,
    setRelocQty,
    setRelocToLocId,
    setRelocVariantId,
    setRelocateDialogOpen,
    variants,
  } = props;

  return (
      <Dialog open={relocateDialogOpen} onOpenChange={setRelocateDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "نقل بضاعة بين الرفوف داخلياً" : "Relocate Stock Internally"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleRelocateStock} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "الصنف المراد نقله" : "Variant"}</Label>
              <Select value={relocVariantId} onValueChange={setRelocVariantId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
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
              <Label className="text-xs">{isAr ? "من الرف / الموقع" : "From Location"}</Label>
              <Select value={relocFromLocId} onValueChange={setRelocFromLocId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر رف المصدر" : "From location"} />
                </SelectTrigger>
                <SelectContent>
                  {locations.map((l) => (
                    <SelectItem key={l.id} value={l.id}>
                      {l.code} - {l.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">{isAr ? "إلى الرف / الموقع" : "To Location"}</Label>
              <Select value={relocToLocId} onValueChange={setRelocToLocId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر رف الوجهة" : "To location"} />
                </SelectTrigger>
                <SelectContent>
                  {locations
                    .filter((l) => l.id !== relocFromLocId)
                    .map((l) => (
                      <SelectItem key={l.id} value={l.id}>
                        {l.code} - {l.name}
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
                value={relocQty}
                onChange={(e) => setRelocQty(e.target.value)}
                className="mt-1 h-9"
              />
            </div>
            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "تنفيذ النقل الداخلي" : "Execute Relocation"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
