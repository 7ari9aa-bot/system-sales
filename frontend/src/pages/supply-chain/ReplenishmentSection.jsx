import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AlertTriangle, Sparkles } from "lucide-react";

/**
 * Replenishment — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function ReplenishmentSection(props) {
  const {
  handleApproveSuggestion,
  handleDismissSuggestion,
  handleGenerateSuggestions,
  isAr,
  lowStockAlerts,
  suggestions,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "محرك تجديد المخزون ومقترحات إعادة الشراء" : "Replenishment Engine & Suggestions"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "مقترحات حسابية دقيقة تفضل التحويل من فائض الفروع قبل الشراء، وتوضح الحسبة بالكامل"
                    : "Deterministic suggestions preferring transfers over purchases with complete arithmetic reasons"}
                </p>
              </div>

              <Button
                size="sm"
                variant="outline"
                className="h-9 gap-1.5 rounded-lg border-[#D6D1C7] text-xs font-semibold"
                onClick={handleGenerateSuggestions}
              >
                <Sparkles className="h-4 w-4 text-[#E8761A]" />
                {isAr ? "إعادة حساب المقترحات الآن" : "Run Calculation Engine"}
              </Button>
            </div>

            {/* Low stock alert banner */}
            {lowStockAlerts.length > 0 && (
              <div className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
                <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
                <div className="flex-1 text-xs">
                  <span className="font-bold">
                    {isAr
                      ? `يوجد ${lowStockAlerts.length} صنف وصل إلى حد الخطر أو أقل من نقطة إعادة الطلب!`
                      : `${lowStockAlerts.length} items reached low stock or safety threshold!`}
                  </span>
                  <p className="text-[11px] text-amber-700 mt-0.5">
                    {isAr
                      ? "قام المحرك بتوليد مقترحات تلقائية لتفادي انقطاع البضاعة وتغطية فترة التوريد."
                      : "Automatic replenishment suggestions were generated to avoid stockouts."}
                  </p>
                </div>
              </div>
            )}


            <div className="overflow-hidden rounded-xl border border-[#EBE7DF] bg-white shadow-sm">
              <table className="w-full text-right text-xs">
                <thead className="border-b border-[#EBE7DF] bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                  <tr>
                    <th className="p-3">{isAr ? "الصنف" : "Variant"}</th>
                    <th className="p-3">{isAr ? "المصدر المقترح" : "Source"}</th>
                    <th className="p-3">{isAr ? "الكمية المقترحة" : "Suggested Qty"}</th>
                    <th className="p-3">{isAr ? "سبب واحتساب المقترح" : "Reason & Arithmetic"}</th>
                    <th className="p-3">{isAr ? "الحالة" : "Status"}</th>
                    <th className="p-3 text-center">{isAr ? "الإجراءات" : "Actions"}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#EBE7DF]">
                  {suggestions.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="p-6 text-center text-[#7A766C]">
                        {isAr
                          ? "لا توجد مقترحات إعادة شراء معلقة حالياً. المخزون متوازن."
                          : "No open replenishment suggestions. Stock is healthy."}
                      </td>
                    </tr>
                  ) : (
                    suggestions.map((sug) => (
                      <tr key={sug.id} className="hover:bg-[#FAF8F5]/50">
                        <td className="p-3 font-semibold">{sug.variant_id?.slice(0, 8)}...</td>
                        <td className="p-3">
                          <Badge variant="outline" className="text-[10px]">
                            {sug.source === "transfer" ? (isAr ? "تحويل" : "Transfer") : (isAr ? "شراء" : "Purchase")}
                          </Badge>
                        </td>
                        <td className="p-3 text-sm font-bold text-[#E8761A]">{sug.suggested_quantity}</td>
                        <td className="p-3 text-[11px] text-[#7A766C]">
                          {typeof sug.reason === "object" ? JSON.stringify(sug.reason) : sug.reason}
                        </td>
                        <td className="p-3">
                          <Badge
                            variant="secondary"
                            className={cn(
                              "text-[10px]",
                              sug.status === "accepted" && "bg-green-100 text-green-700",
                              sug.status === "open" && "bg-blue-100 text-blue-700",
                              sug.status === "dismissed" && "bg-gray-100 text-gray-700",
                            )}

                          >
                            {sug.status}
                          </Badge>
                        </td>
                        <td className="p-3 text-center">
                          {sug.status === "open" && (
                            <div className="flex items-center justify-center gap-1.5">
                              <Button
                                size="sm"
                                className="h-7 bg-[#1E7E34] text-[11px] text-white hover:bg-[#155d27]"
                                onClick={() => handleApproveSuggestion(sug.id)}
                              >
                                {isAr ? "اعتماد المقترح" : "Approve & Order"}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className="h-7 text-[11px] text-[#C0392B]"
                                onClick={() => handleDismissSuggestion(sug.id)}
                              >
                                {isAr ? "تجاهل" : "Dismiss"}
                              </Button>
                            </div>
                          )}

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
