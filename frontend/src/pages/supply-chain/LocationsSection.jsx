import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Plus, RotateCcw } from "lucide-react";

/**
 * Locations — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function LocationsSection(props) {
  const {
  isAr,
  locations,
  setLocationDialogOpen,
  setRelocateDialogOpen,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "مواقع التخزين والرفوف والقواطع الداخلية" : "Warehouse Storage Locations & Bins"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "تحديد الرفوف، القواطع (Bins)، وحالات الحجر الصحي، مع نقل البضائع بين المواقع داخلياً"
                    : "Zones, Racks, Shelves, Bins and internal stock movements"}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-9 gap-1.5 rounded-lg border-[#D6D1C7] text-xs font-semibold"
                  onClick={() => setRelocateDialogOpen(true)}
                >
                  <RotateCcw className="h-4 w-4" />
                  {isAr ? "نقل بضاعة بين الرفوف" : "Internal Relocate"}
                </Button>
                <Button
                  size="sm"
                  className="h-9 gap-1.5 rounded-lg bg-[#E8761A] text-xs font-semibold text-white hover:bg-[#D1650F]"
                  onClick={() => setLocationDialogOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  {isAr ? "إضافة موقع / رف جديد" : "Add Location"}
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {locations.length === 0 ? (
                <div className="col-span-full rounded-xl border border-dashed border-[#D6D1C7] p-12 text-center text-xs text-[#7A766C]">
                  {isAr
                    ? "لا توجد مواقع أو رفوف معرفة لهذا المستودع حتى الآن. اضغط 'إضافة موقع / رف جديد' لإعداد خريطة المستودع."
                    : "No locations found in this warehouse."}
                </div>
              ) : (
                locations.map((loc) => (
                  <div
                    key={loc.id}
                    className="flex flex-col justify-between rounded-xl border border-[#EBE7DF] bg-white p-4 shadow-sm"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-bold text-[#E8761A]">{loc.code}</span>
                        <Badge variant="outline" className="text-[10px]">
                          {loc.kind}
                        </Badge>
                      </div>
                      <h4 className="mt-2 text-sm font-semibold text-[#3B3A36]">{loc.name}</h4>
                    </div>

                    <div className="mt-4 flex items-center justify-between border-t border-[#EBE7DF] pt-3 text-[11px] text-[#7A766C]">
                      <span>{isAr ? "السعة القصوى:" : "Capacity:"}</span>
                      <span className="font-medium">{loc.capacity ? `${loc.capacity} وحدة` : (isAr ? "غير محددة" : "Unlimited")}</span>
                    </div>
                  </div>
                ))
              )}

            </div>
          </div>
        
    </>
  );
}
