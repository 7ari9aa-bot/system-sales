import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";

/**
 * Valuation — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function ValuationSection(props) {
  const {
  deadStock,
  isAr,
  setLandedCostDialogOpen,
  valuationData,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "تقييم المخزون بطبقات FIFO وتكاليف الشحن (Landed Cost)" : "FIFO Valuation & Landed Cost"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "حساب دقيق لتكلفة البضاعة المباعة (COGS) وتوزيع مصاريف الشحن والجمارك على الطبقات النشطة"
                    : "Accurate First-In-First-Out layer valuation and freight allocation"}
                </p>
              </div>

              <Button
                size="sm"
                className="h-9 gap-1.5 rounded-lg bg-[#E8761A] text-xs font-semibold text-white hover:bg-[#D1650F]"
                onClick={() => setLandedCostDialogOpen(true)}
              >
                <Plus className="h-4 w-4" />
                {isAr ? "تسجيل تكاليف شحن أو جمارك" : "Add Landed Cost"}
              </Button>
            </div>

            {/* Valuation KPI Cards */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-4 shadow-sm">
                <span className="text-xs font-medium text-[#7A766C]">{isAr ? "إجمالي قيمة المخزون الحالي" : "Total Valuation"}</span>
                <div className="mt-1 text-2xl font-bold text-[#1E7E34]">
                  {valuationData?.total_value ? `${valuationData.total_value} ج.م` : "—"}
                </div>
              </div>
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-4 shadow-sm">
                <span className="text-xs font-medium text-[#7A766C]">{isAr ? "متوسط تكلفة الوحدة" : "Average Unit Cost"}</span>
                <div className="mt-1 text-2xl font-bold text-[#3B3A36]">
                  {valuationData?.average_unit_cost ? `${valuationData.average_unit_cost} ج.م` : "—"}
                </div>
              </div>
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-4 shadow-sm">
                <span className="text-xs font-medium text-[#7A766C]">{isAr ? "عدد طبقات التكلفة النشطة" : "Active FIFO Layers"}</span>
                <div className="mt-1 text-2xl font-bold text-[#0066CC]">
                  {valuationData?.layer_count ?? 0}
                </div>
              </div>
            </div>

            {/* Dead stock table */}
            <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
              <h3 className="text-xs font-bold text-[#C0392B]">
                {isAr ? "الأصناف الراكدة ورأس المال المجمد (Dead Stock)" : "Dead Stock Items"}
              </h3>
              <p className="mt-1 text-[11px] text-[#7A766C]">
                {isAr
                  ? "أصناف لم تسجل أي حركة بيع خلال آخر 90 يوماً ومخزونها مجمد في المستودع"
                  : "Items with no sales movements in the last 90 days"}
              </p>

              <div className="mt-4 overflow-hidden rounded-lg border border-[#EBE7DF]">
                <table className="w-full text-right text-xs">
                  <thead className="bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                    <tr>
                      <th className="p-3">{isAr ? "الصنف" : "Variant"}</th>
                      <th className="p-3">{isAr ? "الكمية الراكدة" : "Quantity"}</th>
                      <th className="p-3">{isAr ? "القيمة المجمدة" : "Frozen Capital"}</th>
                      <th className="p-3">{isAr ? "أيام الركود" : "Days Inactive"}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#EBE7DF]">
                    {deadStock.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="p-4 text-center text-[#7A766C]">
                          {isAr ? "لا توجد بضائع راكدة مسجلة. حركة المخزون نشطة." : "No dead stock detected."}
                        </td>
                      </tr>
                    ) : (
                      deadStock.map((item, idx) => (
                        <tr key={idx} className="hover:bg-[#FAF8F5]/50">
                          <td className="p-3 font-semibold">{item.variant_id}</td>
                          <td className="p-3 text-sm font-bold text-[#C0392B]">{item.on_hand}</td>
                          <td className="p-3 font-medium">{item.total_cost || "—"} ج.م</td>
                          <td className="p-3 text-[#7A766C]">{item.days_inactive || 90} يوم</td>
                        </tr>
                      ))
                    )}

                  </tbody>
                </table>
              </div>
            </div>
          </div>
        
    </>
  );
}
