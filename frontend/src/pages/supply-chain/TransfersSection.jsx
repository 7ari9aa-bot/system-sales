import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CheckCircle2, Plus, Truck } from "lucide-react";

/**
 * Transfers — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function TransfersSection(props) {
  const {
  handleReceiveTransfer,
  handleShipTransfer,
  isAr,
  setTransferDialogOpen,
  transfers,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "التحويلات بين المستودعات والفروع (D6 Lifecycle)" : "Stock Transfers Lifecycle (D6)"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "دورة حياة تحويل البضاعة: مسودة، تجهيز وشحن (مع عزل البضاعة المنقولة In-Transit)، ثم استلام فعلي"
                    : "Draft -> Shipped (in-transit) -> Received with strict line-level tracking"}
                </p>
              </div>

              <Button
                size="sm"
                className="h-9 gap-1.5 rounded-lg bg-[#E8761A] text-xs font-semibold text-white hover:bg-[#D1650F]"
                onClick={() => setTransferDialogOpen(true)}
              >
                <Plus className="h-4 w-4" />
                {isAr ? "طلب تحويل جديد" : "New Transfer Request"}
              </Button>
            </div>

            <div className="overflow-hidden rounded-xl border border-[#EBE7DF] bg-white shadow-sm">
              <table className="w-full text-right text-xs">
                <thead className="border-b border-[#EBE7DF] bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                  <tr>
                    <th className="p-3">{isAr ? "المصدر" : "From Warehouse"}</th>
                    <th className="p-3">{isAr ? "الوجهة" : "To Warehouse"}</th>
                    <th className="p-3">{isAr ? "الحالة" : "Status"}</th>
                    <th className="p-3">{isAr ? "الناقل والتتبع" : "Carrier / Tracking"}</th>
                    <th className="p-3">{isAr ? "تاريخ الإنشاء" : "Created At"}</th>
                    <th className="p-3 text-center">{isAr ? "الإجراءات" : "Actions"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EBE7DF]">
                  {transfers.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-6 text-center text-[#7A766C]">
                        {isAr ? "لا توجد عمليات تحويل مسجلة." : "No transfers recorded."}
                      </td>
                    </tr>
                  ) : (
                    transfers.map((tr) => (
                      <tr key={tr.id} className="hover:bg-[#FAF8F5]/50">
                        <td className="p-3 font-semibold">{tr.from_warehouse_name || tr.from_warehouse_id?.slice(0, 8)}</td>
                        <td className="p-3 font-semibold">{tr.to_warehouse_name || tr.to_warehouse_id?.slice(0, 8)}</td>
                        <td className="p-3">
                          <Badge
                            variant="secondary"
                            className={cn(
                              "text-[10px]",
                              tr.status === "draft" && "bg-gray-100 text-gray-700",
                              tr.status === "shipped" && "bg-amber-100 text-amber-800",
                              tr.status === "received" && "bg-green-100 text-green-700",
                            )}

                          >
                            {tr.status}
                          </Badge>
                        </td>
                        <td className="p-3 text-[#7A766C]">
                          {tr.carrier ? `${tr.carrier} (${tr.tracking_number || "—"})` : "—"}
                        </td>
                        <td className="p-3 text-[#7A766C]">{tr.created_at?.slice(0, 10)}</td>
                        <td className="p-3 text-center">
                          <div className="flex items-center justify-center gap-1.5">
                            {tr.status === "draft" && (
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 border-[#E8761A] text-[11px] text-[#E8761A] hover:bg-[#E8761A] hover:text-white"
                                onClick={() => handleShipTransfer(tr.id)}
                              >
                                <Truck className="h-3 w-3" />
                                {isAr ? "شحن التحويل" : "Ship Transfer"}
                              </Button>
                            )}

                            {tr.status === "shipped" && (
                              <Button
                                size="sm"
                                className="h-7 bg-[#1E7E34] text-[11px] text-white hover:bg-[#155d27]"
                                onClick={() => handleReceiveTransfer(tr.id)}
                              >
                                <CheckCircle2 className="h-3 w-3" />
                                {isAr ? "استلام وإيداع بالمخزن" : "Receive Stock"}
                              </Button>
                            )}

                            {tr.status === "received" && (
                              <span className="text-[11px] text-[#7A766C]">
                                {isAr ? "مكتمل ومودع" : "Completed"}
                              </span>
                            )}

                          </div>
                        </td>
                      </tr>
                    ))
                  )}

                </tbody>
              </table>
            </div>
          </div>
        
    </>
  );
}
