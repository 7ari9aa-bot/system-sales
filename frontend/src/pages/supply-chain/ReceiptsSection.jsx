import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CheckCircle2, ClipboardCheck, Plus } from "lucide-react";

/**
 * Receipts — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function ReceiptsSection(props) {
  const {
  handleCancelReceipt,
  handleOpenQcDialog,
  handleOpenReceiptDialog,
  handlePostReceipt,
  handleSelectPo,
  isAr,
  purchaseOrders,
  selectedPo,
  selectedPoReceipts,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "أذونات استلام البضائع وفحص الجودة" : "Goods Receipts & Quality Inspection"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "استلام البضائع من الموردين جزئياً أو كلياً مع فحص الجودة وعزل التالف قبل الترحيل للبيع"
                    : "Receive orders from suppliers with QC verdict before posting to sellable stock"}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* Purchase Orders List */}
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
                <h3 className="text-xs font-bold text-[#3B3A36]">
                  {isAr ? "أوامر الشراء الواردة (Purchase Orders)" : "Incoming Purchase Orders"}
                </h3>
                <p className="mt-1 text-[11px] text-[#7A766C]">
                  {isAr ? "اختر أمر شراء لإنشاء إذن استلام أو مراجعة أذونات الاستلام السابقة" : "Select PO to manage receipts"}
                </p>

                <div className="mt-4 overflow-hidden rounded-lg border border-[#EBE7DF]">
                  <table className="w-full text-right text-xs">
                    <thead className="bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                      <tr>
                        <th className="p-3">{isAr ? "رقم الطلب" : "PO #"}</th>
                        <th className="p-3">{isAr ? "المورد" : "Supplier"}</th>
                        <th className="p-3">{isAr ? "الحالة" : "Status"}</th>
                        <th className="p-3 text-center">{isAr ? "الإجراء" : "Action"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#EBE7DF]">
                      {purchaseOrders.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="p-6 text-center text-[#7A766C]">
                            {isAr ? "لا توجد أوامر شراء حالياً." : "No purchase orders found."}
                          </td>
                        </tr>
                      ) : (
                        purchaseOrders.map((po) => {
                          const isCurrent = selectedPo?.id === po.id;
                          return (
                            <tr
                              key={po.id}
                              onClick={() => handleSelectPo(po)}
                              className={cn(
                                "cursor-pointer transition-colors hover:bg-[#FAF8F5]/80",
                                isCurrent && "bg-[#E8761A]/5 font-semibold",
                              )}

                            >
                              <td className="p-3">{po.number}</td>
                              <td className="p-3 text-[#7A766C]">{po.supplier_name || po.supplier_id}</td>
                              <td className="p-3">
                                <Badge
                                  variant="secondary"
                                  className={cn(
                                    "text-[10px]",
                                    po.status === "received" && "bg-green-100 text-green-700",
                                    po.status === "partially_received" && "bg-blue-100 text-blue-700",
                                    po.status === "draft" && "bg-gray-100 text-gray-700",
                                  )}

                                >
                                  {po.status}
                                </Badge>
                              </td>
                              <td className="p-3 text-center">
                                {po.status !== "received" ? (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-7 border-[#E8761A] text-[11px] text-[#E8761A] hover:bg-[#E8761A] hover:text-white"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      handleOpenReceiptDialog(po);
                                    }}
                                  >
                                    <Plus className="h-3 w-3" />
                                    {isAr ? "إذن استلام" : "Receive"}
                                  </Button>
                                ) : (
                                  <span className="text-[10px] text-green-600 font-medium">
                                    <CheckCircle2 className="inline h-3 w-3" /> {isAr ? "مكتمل" : "Complete"}
                                  </span>
                                )}

                              </td>
                            </tr>
                          );
                        })
                      )}

                    </tbody>
                  </table>
                </div>
              </div>

              {/* Goods Receipts for Selected PO */}
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold text-[#3B3A36]">
                      {isAr ? "أذونات الاستلام وفحوص الجودة المرتبطة" : "Goods Receipts & QC for PO"}
                    </h3>
                    <p className="mt-1 text-[11px] text-[#7A766C]">
                      {selectedPo
                        ? isAr
                          ? `أذونات الاستلام الخاصة بأمر الشراء رقم: ${selectedPo.number}`
                          : `Receipts for PO ${selectedPo.number}`
                        : isAr
                        ? "اختر أمر شراء لعرض أذوناته"
                        : "Select a PO"}
                    </p>
                  </div>
                </div>

                <div className="mt-4 space-y-3">
                  {selectedPoReceipts.length === 0 ? (
                    <div className="rounded-lg border border-dashed border-[#D6D1C7] p-8 text-center text-xs text-[#7A766C]">
                      {isAr
                        ? "لا توجد أذونات استلام مسجلة لأمر الشراء المختار. اضغط 'إذن استلام' للبدء."
                        : "No goods receipts found for this PO."}
                    </div>
                  ) : (
                    selectedPoReceipts.map((rc) => (
                      <div
                        key={rc.id}
                        className="rounded-lg border border-[#EBE7DF] bg-[#FAF8F5] p-3.5 transition-all"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <ClipboardCheck className="h-4 w-4 text-[#E8761A]" />
                            <span className="text-xs font-bold">{rc.number}</span>
                            <Badge
                              variant="secondary"
                              className={cn(
                                "text-[10px]",
                                rc.status === "posted" && "bg-green-100 text-green-700",
                                rc.status === "draft" && "bg-amber-100 text-amber-800",
                                rc.status === "cancelled" && "bg-red-100 text-red-700",
                              )}

                            >
                              {rc.status}
                            </Badge>
                          </div>
                          <span className="text-[11px] text-[#7A766C]">
                            {rc.lines?.length || 0} {isAr ? "بنود" : "lines"}
                          </span>
                        </div>

                        {rc.note && (
                          <p className="mt-1.5 text-[11px] text-[#7A766C]">{rc.note}</p>
                        )}


                        <div className="mt-3 flex items-center justify-end gap-2 border-t border-[#EBE7DF] pt-2.5">
                          {rc.status === "draft" && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                className="h-7 text-[11px] text-[#0066CC] border-[#0066CC]"
                                onClick={() => handleOpenQcDialog(rc)}
                              >
                                {isAr ? "تسجيل فحص الجودة" : "QC Inspection"}
                              </Button>
                              <Button
                                size="sm"
                                className="h-7 bg-[#1E7E34] text-[11px] text-white hover:bg-[#155d27]"
                                onClick={() => handlePostReceipt(rc.id)}
                              >
                                {isAr ? "ترحيل للمخزن الفعلي" : "Post to Inventory"}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 text-[11px] text-[#C0392B]"
                                onClick={() => handleCancelReceipt(rc.id)}
                              >
                                {isAr ? "إلغاء" : "Cancel"}
                              </Button>
                            </>
                          )}

                          {rc.status === "posted" && (
                            <span className="text-[11px] font-medium text-green-700 flex items-center gap-1">
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              {isAr ? "تم الترحيل وتحديث طبقات FIFO" : "Posted to FIFO layers"}
                            </span>
                          )}

                        </div>
                      </div>
                    ))
                  )}

                </div>
              </div>
            </div>
          </div>
        
    </>
  );
}
