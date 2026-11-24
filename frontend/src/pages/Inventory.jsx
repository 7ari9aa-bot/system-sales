import AllocationsSection from "@/pages/supply-chain/AllocationsSection";
import LocationsSection from "@/pages/supply-chain/LocationsSection";
import ReceiptsSection from "@/pages/supply-chain/ReceiptsSection";
import ReplenishmentSection from "@/pages/supply-chain/ReplenishmentSection";
import TraceabilitySection from "@/pages/supply-chain/TraceabilitySection";
import TransfersSection from "@/pages/supply-chain/TransfersSection";
import ValuationSection from "@/pages/supply-chain/ValuationSection";
import { Boxes, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { useSupplyChain } from "@/pages/supply-chain/useSupplyChain";
import ReceiptDialog from "@/pages/supply-chain/dialogs/ReceiptDialog";
import TransferDialog from "@/pages/supply-chain/dialogs/TransferDialog";
import QcDialog from "@/pages/supply-chain/dialogs/QcDialog";
import LocationDialog from "@/pages/supply-chain/dialogs/LocationDialog";
import RelocateDialog from "@/pages/supply-chain/dialogs/RelocateDialog";
import LandedCostDialog from "@/pages/supply-chain/dialogs/LandedCostDialog";
import TrackingPolicyDialog from "@/pages/supply-chain/dialogs/TrackingPolicyDialog";
import LotDialog from "@/pages/supply-chain/dialogs/LotDialog";
import SerialDialog from "@/pages/supply-chain/dialogs/SerialDialog";
import AllocationDialog from "@/pages/supply-chain/dialogs/AllocationDialog";

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
      <ReceiptDialog {...{ activePoForReceipt, handleConfirmCreateReceipt, isAr, receiptDialogOpen, receiptNotes, setReceiptDialogOpen, setReceiptNotes }} />

      {/* DIALOG: CREATE TRANSFER */}
      <TransferDialog {...{ fromWhId, handleCreateTransfer, isAr, setFromWhId, setToWhId, setTransferDialogOpen, setTransferNotes, setTransferQty, setTransferVariantId, toWhId, transferDialogOpen, transferNotes, transferQty, transferVariantId, variants, warehouses }} />

      {/* DIALOG: QC INSPECTION */}
      <QcDialog {...{ handleCompleteQC, isAr, qcDialogOpen, qcNote, qcVerdict, setQcDialogOpen, setQcNote, setQcVerdict }} />

      {/* DIALOG: CREATE LOCATION */}
      <LocationDialog {...{ handleCreateLocation, isAr, locCode, locKind, locName, locationDialogOpen, setLocCode, setLocKind, setLocName, setLocationDialogOpen }} />

      {/* DIALOG: RELOCATE STOCK */}
      <RelocateDialog {...{ handleRelocateStock, isAr, locations, relocFromLocId, relocQty, relocToLocId, relocVariantId, relocateDialogOpen, setRelocFromLocId, setRelocQty, setRelocToLocId, setRelocVariantId, setRelocateDialogOpen, variants }} />

      {/* DIALOG: CREATE LANDED COST */}
      <LandedCostDialog {...{ handleCreateLandedCost, isAr, landedCostDialogOpen, lcAmount, lcNote, setLandedCostDialogOpen, setLcAmount, setLcNote }} />

      {/* DIALOG: EDIT TRACKING POLICY */}
      <TrackingPolicyDialog {...{ formPolicyExpiry, formPolicyMode, handleSaveTrackingPolicy, isAr, policyDialogOpen, setFormPolicyExpiry, setFormPolicyMode, setPolicyDialogOpen }} />

      {/* DIALOG: CREATE LOT */}
      <LotDialog {...{ handleCreateLot, isAr, lotCode, lotDialogOpen, lotExpiresAt, lotUnitCost, setLotCode, setLotDialogOpen, setLotExpiresAt, setLotUnitCost }} />

      {/* DIALOG: REGISTER SERIALS */}
      <SerialDialog {...{ handleRegisterSerials, isAr, serialDialogOpen, serialWhId, serialsText, setSerialDialogOpen, setSerialWhId, setSerialsText, warehouses }} />
      {/* DIALOG: CREATE CHANNEL ALLOCATION */}
      <AllocationDialog {...{ allocDialogOpen, allocFormChannel, allocFormQty, allocFormVarId, allocFormWhId, allocSaveLoading, handleCreateAllocation, isAr, setAllocDialogOpen, setAllocFormChannel, setAllocFormQty, setAllocFormVarId, setAllocFormWhId, variants, warehouses }} />
    </div>
  );
}
