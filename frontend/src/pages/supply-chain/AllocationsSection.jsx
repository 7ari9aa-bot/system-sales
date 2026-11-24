import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Plus, Share2, Trash2 } from "lucide-react";

/**
 * Allocations — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function AllocationsSection(props) {
  const {
  allocFormVarId,
  allocFormWhId,
  allocations,
  handleDeleteAllocation,
  isAr,
  selectedWarehouseId,
  setAllocDialogOpen,
  setAllocFormVarId,
  setAllocFormWhId,
  variants,
  warehouses,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "تخصيص حصص المخزون لقنوات البيع (Channel Allocation)" : "Sales Channel Inventory Allocation"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "حجز كوتة مخصصة لكل قناة بيع (كاشير POS، متجر، واتساب) لضمان عدم استنفاد قناة لمخزون القنوات الأخرى"
                    : "Reserve dedicated inventory quotas per channel (POS, Online Store, WhatsApp) to prevent stockouts"}
                </p>
              </div>
              <Button
                size="sm"
                className="gap-1.5 bg-[#E8761A] text-xs text-white hover:bg-[#D1650F]"
                onClick={() => {
                  if (!allocFormWhId && warehouses.length > 0) {
                    setAllocFormWhId(selectedWarehouseId !== "all" ? selectedWarehouseId : warehouses[0].id);
                  }
                  if (!allocFormVarId && variants.length > 0) {
                    setAllocFormVarId(variants[0].id);
                  }
                  setAllocDialogOpen(true);
                }}
              >
                <Plus className="h-3.5 w-3.5" />
                {isAr ? "تخصيص كوتة جديدة" : "New Allocation"}
              </Button>
            </div>

            <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
              <div className="flex items-center justify-between pb-3">
                <div className="flex items-center gap-2">
                  <Share2 className="h-4 w-4 text-[#E8761A]" />
                  <h3 className="text-xs font-bold text-[#3B3A36]">
                    {isAr ? "قائمة تخصيصات القنوات النشطة" : "Active Channel Quotas & Allocations"}
                  </h3>
                </div>
                <Badge variant="outline" className="text-[11px] font-normal">
                  {allocations.length} {isAr ? "تخصيص" : "allocations"}
                </Badge>
              </div>

              <div className="overflow-hidden rounded-lg border border-[#EBE7DF]">
                <table className="w-full text-right text-xs">
                  <thead className="bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                    <tr>
                      <th className="p-3">{isAr ? "قناة البيع" : "Channel"}</th>
                      <th className="p-3">{isAr ? "المستودع" : "Warehouse"}</th>
                      <th className="p-3">{isAr ? "المنتج / الصنف" : "Product Variant"}</th>
                      <th className="p-3 text-center">{isAr ? "الكمية المخصصة (الكوتة)" : "Allocated Quota"}</th>
                      <th className="p-3 text-center">{isAr ? "المحجوز في القناة" : "Reserved"}</th>
                      <th className="p-3 text-center">{isAr ? "المتاح للقناة" : "Available to Channel"}</th>
                      <th className="p-3 text-center">{isAr ? "الإجراء" : "Action"}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EBE7DF]">
                    {allocations.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="p-8 text-center text-[#7A766C]">
                          <Share2 className="mx-auto mb-2 h-6 w-6 text-[#D6D1C7]" />
                          <p className="font-medium">
                            {isAr ? "لا توجد تخصيصات مسجلة حالياً." : "No channel allocations found."}
                          </p>
                          <p className="mt-1 text-[11px] text-[#A8A29E]">
                            {isAr
                              ? "اضغط على «تخصيص كوتة جديدة» لحجز رصيد لقناة معينة مثل الكاشير أو المتجر."
                              : "Click 'New Allocation' to reserve dedicated inventory for POS or other sales channels."}
                          </p>
                        </td>
                      </tr>
                    ) : (
                      allocations.map((alloc) => {
                        const wh = warehouses.find((w) => w.id === alloc.warehouse_id);
                        const vr = variants.find((v) => v.id === alloc.variant_id);
                        const availableInChan = Math.max(0, (alloc.allocated_quantity || 0) - (alloc.reserved_in_channel || 0));

                        return (
                          <tr key={alloc.id} className="hover:bg-[#FAF8F5]/60 transition-colors">
                            <td className="p-3 font-semibold">
                              <Badge
                                variant="secondary"
                                className={cn(
                                  "font-mono text-[11px] uppercase",
                                  alloc.channel === "pos" && "bg-purple-100 text-purple-700",
                                  alloc.channel === "whatsapp" && "bg-green-100 text-green-700",
                                  alloc.channel === "online_store" && "bg-blue-100 text-blue-700",
                                  alloc.channel === "instagram" && "bg-pink-100 text-pink-700",
                                  !["pos", "whatsapp", "online_store", "instagram"].includes(alloc.channel) &&
                                    "bg-amber-100 text-amber-800",
                                )}
                              >
                                {alloc.channel}
                              </Badge>
                            </td>
                            <td className="p-3 text-[#7A766C]">
                              {wh ? `${wh.name} (${wh.code})` : alloc.warehouse_id?.slice(0, 8)}
                            </td>
                            <td className="p-3 font-medium">
                              {vr ? vr.name : alloc.variant_id?.slice(0, 8)}
                              {vr?.sku && <span className="block text-[10px] text-[#7A766C] font-mono">{vr.sku}</span>}
                            </td>
                            <td className="p-3 text-center font-bold text-[#3B3A36]">
                              {alloc.allocated_quantity}
                            </td>
                            <td className="p-3 text-center font-medium text-amber-700">
                              {alloc.reserved_in_channel}
                            </td>
                            <td className="p-3 text-center">
                              <span
                                className={cn(
                                  "inline-flex items-center px-2 py-0.5 rounded text-xs font-bold",
                                  availableInChan > 0
                                    ? "bg-green-50 text-green-700"
                                    : "bg-red-50 text-red-600",
                                )}
                              >
                                {availableInChan}
                              </span>
                            </td>
                            <td className="p-3 text-center">
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 w-7 p-0 text-red-500 hover:bg-red-50 hover:text-red-700"
                                onClick={() => handleDeleteAllocation(alloc.id)}
                                title={isAr ? "حذف التخصيص" : "Delete Allocation"}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        
    </>
  );
}
