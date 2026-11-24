import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { AlertTriangle, Barcode, Calendar, CheckCircle2, Clock, Plus, RefreshCw, Search, Tag, XCircle } from "lucide-react";

/**
 * Traceability — one supply-chain screen, on its own route.
 *
 * Extracted from the single 2,416-line stock page so this screen owns nothing else: the data and
 * the handlers still live in ``pages/Inventory.jsx`` and arrive as props.
 */
export default function TraceabilitySection(props) {
  const {
  filteredVariants,
  isAr,
  loadTraceability,
  lots,
  searchQuery,
  serials,
  setLotDialogOpen,
  setPolicyDialogOpen,
  setSearchQuery,
  setSerialDialogOpen,
  setTraceVariantId,
  traceLoading,
  traceVariantId,
  trackingPolicy,
  warehouses,
  } = props;

  return (
    <>

          <div className="space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-base font-bold">
                  {isAr ? "تتبع الدفعات (Lots) والأرقام التسلسلية وتواريخ الصلاحية (FEFO)" : "Traceability: Lots, Serials & Expiry"}
                </h2>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "إدارة سياسات التتبع، تشغيلات الدفعات وتواريخ الصلاحية والصرف حسب الأسبق انتهاءً (FEFO)"
                    : "Variant tracking policies, batch lot codes, expiry dates, and unique serial numbers"}
                </p>
              </div>

              {/* Variant Picker with Search */}
              <div className="flex flex-wrap items-center gap-2">
                <div className="relative">
                  <Search className="absolute right-2.5 top-2.5 h-4 w-4 text-[#7A766C]" />
                  <Input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={isAr ? "بحث بالاسم أو SKU…" : "Search variant…"}
                    className="h-9 w-48 pr-8 text-xs bg-[#FAF8F5] border-[#D6D1C7]"
                  />
                </div>
                <Select
                  value={traceVariantId}
                  onValueChange={(val) => {
                    setTraceVariantId(val);
                    loadTraceability(val);
                  }}
                >
                  <SelectTrigger className="h-9 w-64 rounded-lg border-[#D6D1C7] bg-[#FAF8F5] text-xs">
                    <SelectValue placeholder={isAr ? "اختر صنفاً…" : "Choose variant…"} />
                  </SelectTrigger>
                  <SelectContent>
                    {filteredVariants.map((v) => (
                      <SelectItem key={v.id} value={v.id}>
                        {v.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Tracking Policy Banner */}
            <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#0066CC]/10 text-[#0066CC]">
                    <Barcode className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-bold text-[#3B3A36]">
                        {isAr ? "سياسة تتبع هذا الصنف:" : "Tracking Policy:"}
                      </span>
                      <Badge
                        variant="secondary"
                        className={cn(
                          "text-[10px]",
                          trackingPolicy.mode === "batch" && "bg-blue-100 text-blue-700",
                          trackingPolicy.mode === "serial" && "bg-purple-100 text-purple-700",
                          trackingPolicy.mode === "none" && "bg-gray-100 text-gray-700",
                        )}

                      >
                        {trackingPolicy.mode === "batch"
                          ? isAr ? "تتبع برقم التشغيلة / الدفعة (Batch)" : "Batch / Lot"
                          : trackingPolicy.mode === "serial"
                          ? isAr ? "تتبع برقم تسلسلي فريد (Serial)" : "Serial Number"
                          : isAr ? "بدون تتبع خاص (None)" : "Standard (None)"}
                      </Badge>
                      {trackingPolicy.expiry_required && (
                        <Badge variant="outline" className="border-amber-400 bg-amber-50 text-[10px] text-amber-800">
                          <Clock className="mr-1 h-3 w-3" />
                          {isAr ? "تاريخ الصلاحية إلزامي" : "Expiry Required"}
                        </Badge>
                      )}

                    </div>
                    <p className="mt-0.5 text-[11px] text-[#7A766C]">
                      {trackingPolicy.mode === "batch"
                        ? isAr
                          ? "يتم صرف البضاعة وفق أسبقية انتهاء الصلاحية FEFO وتتبع كل دفعة برقمها"
                          : "Dispensed via First-Expired-First-Out (FEFO) rules"
                        : trackingPolicy.mode === "serial"
                        ? isAr
                          ? "كل قطعة تملك رقماً تسلسلياً فريداً يتابع حركتها من الاستلام للبيع أو الصيانة"
                          : "Each individual unit is tracked with a unique serial number"
                        : isAr
                        ? "المخزون يتم حسابه ككميات عددية مجمعة"
                        : "Tracked by aggregate quantity"}
                    </p>
                  </div>
                </div>

                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs font-semibold border-[#D6D1C7]"
                  onClick={() => setPolicyDialogOpen(true)}
                >
                  <Tag className="h-3.5 w-3.5" />
                  {isAr ? "تعديل سياسة التتبع" : "Change Policy"}
                </Button>
              </div>
            </div>

            {/* Tab Body: Lots and/or Serials */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              {/* LOTS SECTION */}
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Calendar className="h-4 w-4 text-[#E8761A]" />
                    <h3 className="text-xs font-bold text-[#3B3A36]">
                      {isAr ? "دفعات التشغيل وتواريخ الصلاحية (Lots & Expiry)" : "Lots & Expiry Dates"}
                    </h3>
                  </div>
                  <Button
                    size="sm"
                    className="h-7 gap-1 bg-[#E8761A] text-[11px] text-white hover:bg-[#D1650F]"
                    onClick={() => setLotDialogOpen(true)}
                  >
                    <Plus className="h-3 w-3" />
                    {isAr ? "دفعة جديدة" : "New Lot"}
                  </Button>
                </div>

                <div className="mt-4 overflow-hidden rounded-lg border border-[#EBE7DF]">
                  <table className="w-full text-right text-xs">
                    <thead className="bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                      <tr>
                        <th className="p-2.5">{isAr ? "رقم الدفعة" : "Lot Code"}</th>
                        <th className="p-2.5">{isAr ? "تاريخ الصلاحية" : "Expiry Date"}</th>
                        <th className="p-2.5">{isAr ? "التكلفة" : "Unit Cost"}</th>
                        <th className="p-2.5">{isAr ? "الحالة" : "Status"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#EBE7DF]">
                      {traceLoading ? (
                        <tr>
                          <td colSpan={4} className="p-4 text-center text-[#7A766C]">
                            <RefreshCw className="inline h-4 w-4 animate-spin text-[#E8761A]" />
                          </td>
                        </tr>
                      ) : lots.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="p-6 text-center text-[#7A766C]">
                            {isAr ? "لا توجد دفعات تشغيل مسجلة لهذا الصنف." : "No lots registered."}
                          </td>
                        </tr>
                      ) : (
                        lots.map((lot) => {
                          const isExpired = lot.expires_at && new Date(lot.expires_at) < new Date();
                          const isNearExpiry =
                            lot.expires_at &&
                            !isExpired &&
                            new Date(lot.expires_at).getTime() - Date.now() < 30 * 24 * 3600 * 1000;
                          return (
                            <tr key={lot.id} className="hover:bg-[#FAF8F5]/50">
                              <td className="p-2.5 font-mono font-semibold">{lot.lot_code}</td>
                              <td className="p-2.5">
                                {lot.expires_at ? lot.expires_at.slice(0, 10) : (isAr ? "غير محدد" : "None")}
                              </td>
                              <td className="p-2.5 font-medium">{lot.unit_cost ? `${lot.unit_cost} ج.م` : "—"}</td>
                              <td className="p-2.5">
                                {isExpired ? (
                                  <Badge className="bg-red-100 text-[10px] text-red-700">
                                    <XCircle className="inline h-3 w-3" /> {isAr ? "منتهية" : "Expired"}
                                  </Badge>
                                ) : isNearExpiry ? (
                                  <Badge className="bg-amber-100 text-[10px] text-amber-800">
                                    <AlertTriangle className="inline h-3 w-3" /> {isAr ? "قريبة الانتهاء" : "Near"}
                                  </Badge>
                                ) : (
                                  <Badge className="bg-green-100 text-[10px] text-green-700">
                                    <CheckCircle2 className="inline h-3 w-3" /> {isAr ? "سارية" : "Valid"}
                                  </Badge>
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

              {/* SERIALS SECTION */}
              <div className="rounded-xl border border-[#EBE7DF] bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Barcode className="h-4 w-4 text-[#0066CC]" />
                    <h3 className="text-xs font-bold text-[#3B3A36]">
                      {isAr ? "الأرقام التسلسلية الفردية (Unit Serials)" : "Registered Serial Numbers"}
                    </h3>
                  </div>
                  <Button
                    size="sm"
                    className="h-7 gap-1 bg-[#0066CC] text-[11px] text-white hover:bg-[#0052a3]"
                    onClick={() => setSerialDialogOpen(true)}
                  >
                    <Plus className="h-3 w-3" />
                    {isAr ? "تسجيل أرقام" : "Add Serials"}
                  </Button>
                </div>

                <div className="mt-4 overflow-hidden rounded-lg border border-[#EBE7DF]">
                  <table className="w-full text-right text-xs">
                    <thead className="bg-[#FAF8F5] text-[11px] font-semibold text-[#7A766C]">
                      <tr>
                        <th className="p-2.5">{isAr ? "الرقم التسلسلي" : "Serial #"}</th>
                        <th className="p-2.5">{isAr ? "المستودع" : "Warehouse"}</th>
                        <th className="p-2.5">{isAr ? "الحالة" : "Status"}</th>
                        <th className="p-2.5">{isAr ? "تاريخ التسجيل" : "Date"}</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#EBE7DF]">
                      {traceLoading ? (
                        <tr>
                          <td colSpan={4} className="p-4 text-center text-[#7A766C]">
                            <RefreshCw className="inline h-4 w-4 animate-spin text-[#0066CC]" />
                          </td>
                        </tr>
                      ) : serials.length === 0 ? (
                        <tr>
                          <td colSpan={4} className="p-6 text-center text-[#7A766C]">
                            {isAr ? "لا توجد أرقام تسلسلية مسجلة لهذا الصنف." : "No serial numbers found."}
                          </td>
                        </tr>
                      ) : (
                        serials.map((s) => (
                          <tr key={s.id} className="hover:bg-[#FAF8F5]/50">
                            <td className="p-2.5 font-mono font-semibold">{s.serial_number}</td>
                            <td className="p-2.5 text-[#7A766C]">
                              {warehouses.find((w) => w.id === s.warehouse_id)?.name || s.warehouse_id?.slice(0, 8)}
                            </td>
                            <td className="p-2.5">
                              <Badge
                                variant="secondary"
                                className={cn(
                                  "text-[10px]",
                                  s.status === "in_stock" && "bg-green-100 text-green-700",
                                  s.status === "reserved" && "bg-amber-100 text-amber-800",
                                  s.status === "sold" && "bg-blue-100 text-blue-700",
                                  s.status === "defective" && "bg-red-100 text-red-700",
                                )}

                              >
                                {s.status}
                              </Badge>
                            </td>
                            <td className="p-2.5 text-[#7A766C]">{s.registered_at?.slice(0, 10)}</td>
                          </tr>
                        ))
                      )}

                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        
    </>
  );
}
