import AllocationsSection from "@/pages/supply-chain/AllocationsSection";
import LocationsSection from "@/pages/supply-chain/LocationsSection";
import ReceiptsSection from "@/pages/supply-chain/ReceiptsSection";
import ReplenishmentSection from "@/pages/supply-chain/ReplenishmentSection";
import TraceabilitySection from "@/pages/supply-chain/TraceabilitySection";
import TransfersSection from "@/pages/supply-chain/TransfersSection";
import ValuationSection from "@/pages/supply-chain/ValuationSection";
import { Boxes, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useSupplyChain } from "@/pages/supply-chain/useSupplyChain";

export default function InventoryPage() {
  const {
    activePoForReceipt,
    activeTab,
    allocDialogOpen,
    allocFormChannel,
    allocFormQty,
    allocFormVarId,
    allocFormWhId,
    allocSaveLoading,
    allocations,
    deadStock,
    filteredVariants,
    formPolicyExpiry,
    formPolicyMode,
    fromWhId,
    handleApproveSuggestion,
    handleCancelReceipt,
    handleCompleteQC,
    handleConfirmCreateReceipt,
    handleCreateAllocation,
    handleCreateLandedCost,
    handleCreateLocation,
    handleCreateLot,
    handleCreateTransfer,
    handleDeleteAllocation,
    handleDismissSuggestion,
    handleGenerateSuggestions,
    handleOpenQcDialog,
    handleOpenReceiptDialog,
    handlePostReceipt,
    handleReceiveTransfer,
    handleRegisterSerials,
    handleRelocateStock,
    handleSaveTrackingPolicy,
    handleSelectPo,
    handleShipTransfer,
    isAr,
    landedCostDialogOpen,
    lcAmount,
    lcNote,
    loadTraceability,
    loading,
    locCode,
    locKind,
    locName,
    locationDialogOpen,
    locations,
    lotCode,
    lotDialogOpen,
    lotExpiresAt,
    lotUnitCost,
    lots,
    lowStockAlerts,
    navigate,
    policyDialogOpen,
    purchaseOrders,
    qcDialogOpen,
    qcNote,
    qcVerdict,
    receiptDialogOpen,
    receiptNotes,
    relocFromLocId,
    relocQty,
    relocToLocId,
    relocVariantId,
    relocateDialogOpen,
    searchQuery,
    selectedPo,
    selectedPoReceipts,
    selectedWarehouseId,
    serialDialogOpen,
    serialWhId,
    serials,
    serialsText,
    setAllocDialogOpen,
    setAllocFormChannel,
    setAllocFormQty,
    setAllocFormVarId,
    setAllocFormWhId,
    setFormPolicyExpiry,
    setFormPolicyMode,
    setFromWhId,
    setLandedCostDialogOpen,
    setLcAmount,
    setLcNote,
    setLocCode,
    setLocKind,
    setLocName,
    setLocationDialogOpen,
    setLotCode,
    setLotDialogOpen,
    setLotExpiresAt,
    setLotUnitCost,
    setPolicyDialogOpen,
    setQcDialogOpen,
    setQcNote,
    setQcVerdict,
    setReceiptDialogOpen,
    setReceiptNotes,
    setRefreshIndex,
    setRelocFromLocId,
    setRelocQty,
    setRelocToLocId,
    setRelocVariantId,
    setRelocateDialogOpen,
    setSearchQuery,
    setSelectedWarehouseId,
    setSerialDialogOpen,
    setSerialWhId,
    setSerialsText,
    setToWhId,
    setTraceVariantId,
    setTransferDialogOpen,
    setTransferNotes,
    setTransferQty,
    setTransferVariantId,
    shownTabs,
    suggestions,
    summary,
    toWhId,
    traceLoading,
    traceVariantId,
    trackingPolicy,
    transferDialogOpen,
    transferNotes,
    transferQty,
    transferVariantId,
    transfers,
    valuationData,
    variants,
    warehouses,
  } = useSupplyChain();

  return (
    <div className="flex min-h-screen flex-col bg-[#FBFAF7] text-[#3B3A36]" dir={isAr ? "rtl" : "ltr"}>
      {/* Top Header */}
      <div className="border-b border-[#EBE7DF] bg-white px-6 py-5 sm:px-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5">
              <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#E8761A]/10 text-[#E8761A]">
                <Boxes className="h-5 w-5" />
              </div>
              <div>
                <h1 className="font-heading text-2xl font-bold tracking-tight">
                  {isAr ? "منظومة المخزون وسلاسل الإمداد المتقدمة" : "Advanced Supply Chain & Inventory Platform"}
                </h1>
                <p className="text-xs text-[#7A766C]">
                  {isAr
                    ? "أذونات الاستلام، فحص الجودة، دورة التحويلات D6، محرك التجديد، مواقع الرفوف، وتقييم FIFO والتتبع"
                    : "Goods Receipts, QC, D6 Transfers, Replenishment, Warehouse Locations, FIFO Valuation & Traceability"}
                </p>
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Warehouse Filter */}
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-[#7A766C]">{isAr ? "المستودع:" : "Warehouse:"}</span>
              <Select value={selectedWarehouseId} onValueChange={setSelectedWarehouseId}>
                <SelectTrigger className="h-9 w-44 rounded-lg border-[#D6D1C7] bg-[#FAF8F5] text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{isAr ? "جميع المستودعات والفروع" : "All Warehouses"}</SelectItem>
                  {warehouses.map((w) => (
                    <SelectItem key={w.id} value={w.id}>
                      {w.name} ({w.code})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <Button
              variant="outline"
              size="sm"
              disabled={loading}
              onClick={() => {
                setRefreshIndex((n) => n + 1);
                toast.info(isAr ? "جارٍ تحديث البيانات…" : "Refreshing data…");
              }}
              className="h-9 rounded-lg border-[#D6D1C7] text-xs text-[#3B3A36]"
            >
              <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
              {isAr ? "تحديث" : "Refresh"}
            </Button>
          </div>
        </div>

        {/* Global Stock Stats Cards */}
        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
          <div className="rounded-xl border border-[#EBE7DF] bg-[#FAF8F5] p-3.5">
            <span className="text-[11px] font-medium text-[#7A766C]">
              {isAr ? "المتاح للبيع الفعلي" : "Sellable Stock"}
            </span>
            <div className="mt-1 text-lg font-bold text-[#1E7E34]">
              {summary?.sellable ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-[#EBE7DF] bg-[#FAF8F5] p-3.5">
            <span className="text-[11px] font-medium text-[#7A766C]">
              {isAr ? "المحجوز للطلبات" : "Reserved Orders"}
            </span>
            <div className="mt-1 text-lg font-bold text-[#E8761A]">
              {summary?.allocated ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-[#EBE7DF] bg-[#FAF8F5] p-3.5">
            <span className="text-[11px] font-medium text-[#7A766C]">
              {isAr ? "قيد فحص الجودة" : "Quality Inspection"}
            </span>
            <div className="mt-1 text-lg font-bold text-[#0066CC]">
              {summary?.quality_check ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-[#EBE7DF] bg-[#FAF8F5] p-3.5">
            <span className="text-[11px] font-medium text-[#7A766C]">
              {isAr ? "الحجر الصحي والمعزول" : "Quarantine Stock"}
            </span>
            <div className="mt-1 text-lg font-bold text-[#8E44AD]">
              {summary?.quarantine ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-[#EBE7DF] bg-[#FAF8F5] p-3.5">
            <span className="text-[11px] font-medium text-[#7A766C]">
              {isAr ? "التالف ومرفوض الجودة" : "Damaged / Rejected"}
            </span>
            <div className="mt-1 text-lg font-bold text-[#C0392B]">
              {summary?.damaged ?? 0}
            </div>
          </div>
          <div className="rounded-xl border border-[#EBE7DF] bg-[#FAF8F5] p-3.5">
            <span className="text-[11px] font-medium text-[#7A766C]">
              {isAr ? "الرصيد الفعلي الإجمالي" : "Physical On-Hand"}
            </span>
            <div className="mt-1 text-lg font-bold text-[#3B3A36]">
              {summary?.on_hand ?? 0}
            </div>
          </div>
        </div>
      </div>

      {/* Workspace Tabs Navigation */}
      <div className="border-b border-[#EBE7DF] bg-white px-6 sm:px-8">
        <div className="flex gap-2 overflow-x-auto">
          {shownTabs.map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => navigate(`/cashier/supply-chain/${tab.id}`)}
                className={cn(
                  "flex items-center gap-2 border-b-2 py-3.5 px-3 text-xs font-semibold transition-all whitespace-nowrap",
                  active
                    ? "border-[#E8761A] text-[#E8761A]"
                    : "border-transparent text-[#7A766C] hover:border-[#D6D1C7] hover:text-[#3B3A36]",
                )}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Main Tab Content */}
      <div className="flex-1 p-6 sm:p-8">
        {/* TAB 1: GOODS RECEIPTS & QC */}
        {activeTab === "receipts" && (
        <ReceiptsSection {...{ handleCancelReceipt, handleOpenQcDialog, handleOpenReceiptDialog, handlePostReceipt, handleSelectPo, isAr, purchaseOrders, selectedPo, selectedPoReceipts }} />
      )}


        {/* TAB 2: STOCK TRANSFERS */}
        {activeTab === "transfers" && (
        <TransfersSection {...{ handleReceiveTransfer, handleShipTransfer, isAr, setTransferDialogOpen, transfers }} />
      )}


        {/* TAB 3: REPLENISHMENT */}
        {activeTab === "replenishment" && (
        <ReplenishmentSection {...{ handleApproveSuggestion, handleDismissSuggestion, handleGenerateSuggestions, isAr, lowStockAlerts, suggestions }} />
      )}


        {/* TAB 4: LOCATIONS & BINS */}
        {activeTab === "locations" && (
        <LocationsSection {...{ isAr, locations, setLocationDialogOpen, setRelocateDialogOpen }} />
      )}


        {/* TAB 5: VALUATION & LANDED COST */}
        {activeTab === "valuation" && (
        <ValuationSection {...{ deadStock, isAr, setLandedCostDialogOpen, valuationData }} />
      )}


        {/* TAB 6: TRACEABILITY (LOTS & SERIALS) */}
        {activeTab === "traceability" && (
        <TraceabilitySection {...{ filteredVariants, isAr, loadTraceability, lots, searchQuery, serials, setLotDialogOpen, setPolicyDialogOpen, setSearchQuery, setSerialDialogOpen, setTraceVariantId, traceLoading, traceVariantId, trackingPolicy, warehouses }} />
      )}

        {/* TAB 7: CHANNEL ALLOCATIONS */}
        {activeTab === "allocations" && (
        <AllocationsSection {...{ allocFormVarId, allocFormWhId, allocations, handleDeleteAllocation, isAr, selectedWarehouseId, setAllocDialogOpen, setAllocFormVarId, setAllocFormWhId, variants, warehouses }} />
      )}

      </div>

      {/* DIALOG: CREATE GOODS RECEIPT */}
      <Dialog open={receiptDialogOpen} onOpenChange={setReceiptDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إنشاء إذن استلام بضائع من مورد" : "Create Goods Receipt"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleConfirmCreateReceipt} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "أمر الشراء" : "Purchase Order"}</Label>
              <Input
                value={activePoForReceipt?.number || ""}
                disabled
                className="mt-1 h-9 bg-[#FAF8F5]"
              />
            </div>
            <div>
              <Label className="text-xs">{isAr ? "ملاحظات إذن الاستلام" : "Receipt Notes"}</Label>
              <Input
                value={receiptNotes}
                onChange={(e) => setReceiptNotes(e.target.value)}
                placeholder={isAr ? "مثال: استلام دفعة أولى بحالة سليمة" : "Receipt notes"}
                className="mt-1 h-9"
              />
            </div>
            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "تأكيد وإنشاء الإذن" : "Confirm Receipt"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DIALOG: CREATE TRANSFER */}
      <Dialog open={transferDialogOpen} onOpenChange={setTransferDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "طلب تحويل مخزون جديد" : "New Stock Transfer"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateTransfer} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "من مستودع (المصدر)" : "From Warehouse"}</Label>
              <Select value={fromWhId} onValueChange={setFromWhId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر المستودع" : "Select warehouse"} />
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
              <Label className="text-xs">{isAr ? "إلى مستودع (الهدف)" : "To Warehouse"}</Label>
              <Select value={toWhId} onValueChange={setToWhId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر المستودع" : "Select warehouse"} />
                </SelectTrigger>
                <SelectContent>
                  {warehouses
                    .filter((w) => w.id !== fromWhId)
                    .map((w) => (
                      <SelectItem key={w.id} value={w.id}>
                        {w.name} ({w.code})
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">{isAr ? "الصنف المراد نقله" : "Product Variant"}</Label>
              <Select value={transferVariantId} onValueChange={setTransferVariantId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر الصنف" : "Select variant"} />
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
              <Label className="text-xs">{isAr ? "الكمية" : "Quantity"}</Label>
              <Input
                type="number"
                min="1"
                value={transferQty}
                onChange={(e) => setTransferQty(e.target.value)}
                className="mt-1 h-9"
              />
            </div>

            <div>
              <Label className="text-xs">{isAr ? "ملاحظات التحويل" : "Notes"}</Label>
              <Input
                value={transferNotes}
                onChange={(e) => setTransferNotes(e.target.value)}
                placeholder={isAr ? "سبب النقل أو توجيهات الشحن" : "Reason or instructions"}
                className="mt-1 h-9"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "إنشاء طلب التحويل" : "Create Transfer"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DIALOG: QC INSPECTION */}
      <Dialog open={qcDialogOpen} onOpenChange={setQcDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "فحص جودة استلام البضائع" : "Quality Inspection"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "قرار الفحص الإجمالي" : "Verdict"}</Label>
              <Select value={qcVerdict} onValueChange={setQcVerdict}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="passed">{isAr ? "سليم ومقبول للبيع (Pass)" : "Passed"}</SelectItem>
                  <SelectItem value="quarantined">{isAr ? "عزل وحجر صحي (Quarantine)" : "Quarantined"}</SelectItem>
                  <SelectItem value="rejected">{isAr ? "مرفوض وتالف (Reject)" : "Rejected"}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">{isAr ? "تقرير وملاحظات الفاحص" : "Inspector Note"}</Label>
              <Input
                value={qcNote}
                onChange={(e) => setQcNote(e.target.value)}
                placeholder={isAr ? "سليم بالكامل أو تفاصيل التلف" : "Details or notes"}
                className="mt-1 h-9"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button onClick={handleCompleteQC} className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "تأكيد نتيجة الفحص" : "Submit Verdict"}
              </Button>
            </DialogFooter>
          </div>
        </DialogContent>
      </Dialog>

      {/* DIALOG: CREATE LOCATION */}
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

      {/* DIALOG: RELOCATE STOCK */}
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

      {/* DIALOG: CREATE LANDED COST */}
      <Dialog open={landedCostDialogOpen} onOpenChange={setLandedCostDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إضافة مصاريف شحن أو جمارك" : "Add Landed Cost"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateLandedCost} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "المبلغ الإجمالي (ج.م)" : "Total Amount"}</Label>
              <Input
                type="number"
                step="0.01"
                min="0"
                value={lcAmount}
                onChange={(e) => setLcAmount(e.target.value)}
                placeholder="1500.00"
                required
                className="mt-1 h-9"
              />
            </div>
            <div>
              <Label className="text-xs">{isAr ? "بيان المصروف" : "Note / Description"}</Label>
              <Input
                value={lcNote}
                onChange={(e) => setLcNote(e.target.value)}
                placeholder={isAr ? "مصاريف تخليص جمركي أو شحن بحري" : "Customs clearance, freight"}
                className="mt-1 h-9"
              />
            </div>
            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ التكلفة" : "Save Landed Cost"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DIALOG: EDIT TRACKING POLICY */}
      <Dialog open={policyDialogOpen} onOpenChange={setPolicyDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "تحديد سياسة تتبع الصنف" : "Set Tracking Policy"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSaveTrackingPolicy} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "نوع التتبع" : "Tracking Mode"}</Label>
              <Select value={formPolicyMode} onValueChange={setFormPolicyMode}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">{isAr ? "بدون تتبع إضافي (None)" : "Standard (None)"}</SelectItem>
                  <SelectItem value="batch">{isAr ? "تتبع برقم الدفعة/التشغيلة (Batch/Lot)" : "Batch / Lot"}</SelectItem>
                  <SelectItem value="serial">{isAr ? "تتبع بالأرقام التسلسلية (Serial Number)" : "Serial Number"}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="flex items-center gap-2 pt-1">
              <input
                type="checkbox"
                id="policyExpiry"
                checked={formPolicyExpiry}
                onChange={(e) => setFormPolicyExpiry(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-[#E8761A] focus:ring-[#E8761A]"
              />
              <Label htmlFor="policyExpiry" className="cursor-pointer text-xs">
                {isAr ? "إلزامية تسجيل تاريخ انتهاء الصلاحية للدفعة" : "Require Expiry Date for Lots"}
              </Label>
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ السياسة" : "Save Policy"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DIALOG: CREATE LOT */}
      <Dialog open={lotDialogOpen} onOpenChange={setLotDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إضافة دفعة تشغيل / تاريخ صلاحية" : "Create New Lot / Batch"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateLot} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "رمز الدفعة (Lot Code)" : "Lot Code"}</Label>
              <Input
                value={lotCode}
                onChange={(e) => setLotCode(e.target.value)}
                placeholder="LOT-2026-B01"
                required
                className="mt-1 h-9"
              />
            </div>

            <div>
              <Label className="text-xs">{isAr ? "تاريخ انتهاء الصلاحية" : "Expiry Date"}</Label>
              <Input
                type="date"
                value={lotExpiresAt}
                onChange={(e) => setLotExpiresAt(e.target.value)}
                className="mt-1 h-9"
              />
            </div>

            <div>
              <Label className="text-xs">{isAr ? "تكلفة الوحدة في هذه الدفعة (اختياري)" : "Unit Cost (Optional)"}</Label>
              <Input
                type="number"
                step="0.01"
                value={lotUnitCost}
                onChange={(e) => setLotUnitCost(e.target.value)}
                placeholder="25.00"
                className="mt-1 h-9"
              />
            </div>

            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "حفظ الدفعة" : "Create Lot"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* DIALOG: REGISTER SERIALS */}
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
      {/* DIALOG: CREATE CHANNEL ALLOCATION */}
      <Dialog open={allocDialogOpen} onOpenChange={setAllocDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>
              {isAr ? "تخصيص كوتة مخزون لقناة بيع" : "Allocate Stock to Channel"}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleCreateAllocation} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "المستودع" : "Warehouse"}</Label>
              <Select value={allocFormWhId} onValueChange={setAllocFormWhId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر المستودع" : "Select warehouse"} />
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
              <Label className="text-xs">{isAr ? "المنتج / الصنف" : "Product Variant"}</Label>
              <Select value={allocFormVarId} onValueChange={setAllocFormVarId}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue placeholder={isAr ? "اختر الصنف" : "Select variant"} />
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
              <Label className="text-xs">{isAr ? "قناة البيع المستهدفة" : "Target Sales Channel"}</Label>
              <Select value={allocFormChannel} onValueChange={setAllocFormChannel}>
                <SelectTrigger className="mt-1 h-9">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pos">
                    {isAr ? "الكاشير ونقطة البيع (POS)" : "Point of Sale (POS)"}
                  </SelectItem>
                  <SelectItem value="whatsapp">
                    {isAr ? "واتساب (WhatsApp)" : "WhatsApp"}
                  </SelectItem>
                  <SelectItem value="online_store">
                    {isAr ? "المتجر الإلكتروني (Online Store)" : "Online Store"}
                  </SelectItem>
                  <SelectItem value="instagram">
                    {isAr ? "إنستغرام (Instagram)" : "Instagram"}
                  </SelectItem>
                  <SelectItem value="telegram">
                    {isAr ? "تيليجرام (Telegram)" : "Telegram"}
                  </SelectItem>
                  <SelectItem value="messenger">
                    {isAr ? "ماسنجر (Messenger)" : "Messenger"}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div>
              <Label className="text-xs">
                {isAr ? "الكمية المخصصة (الكوتة)" : "Allocated Quantity (Quota)"}
              </Label>
              <Input
                type="number"
                min="0"
                value={allocFormQty}
                onChange={(e) => setAllocFormQty(e.target.value)}
                placeholder="10"
                required
                className="mt-1 h-9"
              />
              <p className="mt-1 text-[11px] text-[#7A766C]">
                {isAr
                  ? "القناة لا يمكنها بيع أو حجز أكثر من هذه الكمية ما لم تتم زيادة الكوتة."
                  : "The channel cannot sell or reserve more than this allocated quota."}
              </p>
            </div>

            <DialogFooter className="mt-4">
              <Button
                type="submit"
                disabled={allocSaveLoading}
                className="bg-[#E8761A] text-white hover:bg-[#D1650F]"
              >
                {allocSaveLoading ? (
                  <RefreshCw className="h-4 w-4 animate-spin" />
                ) : isAr ? (
                  "حفظ التخصيص"
                ) : (
                  "Save Allocation"
                )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
