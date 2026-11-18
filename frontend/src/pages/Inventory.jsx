import React, { useEffect, useState } from "react";
import {
  Boxes,
  Truck,
  ClipboardCheck,
  ArrowLeftRight,
  TrendingUp,
  AlertTriangle,
  RotateCcw,
  Plus,
  RefreshCw,
  Search,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  MapPin,
  Calendar,
  Sparkles,
  Barcode,
  Tag,
  Share2,
  Trash2,
} from "lucide-react";
import { supplyChainApi } from "@/lib/supplyChainApi";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function InventoryPage() {
  const { lang } = useI18n();
  const isAr = lang === "ar";

  const [activeTab, setActiveTab] = useState("receipts"); // receipts | transfers | replenishment | locations | valuation | traceability
  const [warehouses, setWarehouses] = useState([]);
  const [selectedWarehouseId, setSelectedWarehouseId] = useState("all");
  const [loading, setLoading] = useState(true);
  const [refreshIndex, setRefreshIndex] = useState(0);

  // Summary Metrics
  const [summary, setSummary] = useState(null);

  // Tab Data States
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [selectedPoReceipts, setSelectedPoReceipts] = useState([]);
  const [selectedPo, setSelectedPo] = useState(null);

  const [transfers, setTransfers] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [lowStockAlerts, setLowStockAlerts] = useState([]);
  const [locations, setLocations] = useState([]);
  const [deadStock, setDeadStock] = useState([]);
  const [valuationData, setValuationData] = useState(null);

  // Traceability States
  const [traceVariantId, setTraceVariantId] = useState("");
  const [trackingPolicy, setTrackingPolicy] = useState({ mode: "none", expiry_required: false });
  const [lots, setLots] = useState([]);
  const [serials, setSerials] = useState([]);
  const [traceLoading, setTraceLoading] = useState(false);

  // Search Filter
  const [searchQuery, setSearchQuery] = useState("");

  // Dialog States
  const [transferDialogOpen, setTransferDialogOpen] = useState(false);
  const [receiptDialogOpen, setReceiptDialogOpen] = useState(false);
  const [qcDialogOpen, setQcDialogOpen] = useState(false);
  const [locationDialogOpen, setLocationDialogOpen] = useState(false);
  const [relocateDialogOpen, setRelocateDialogOpen] = useState(false);
  const [landedCostDialogOpen, setLandedCostDialogOpen] = useState(false);
  const [policyDialogOpen, setPolicyDialogOpen] = useState(false);
  const [lotDialogOpen, setLotDialogOpen] = useState(false);
  const [serialDialogOpen, setSerialDialogOpen] = useState(false);

  // Active items for modals
  const [activeReceipt, setActiveReceipt] = useState(null);
  const [activePoForReceipt, setActivePoForReceipt] = useState(null);

  // Form inputs
  const [fromWhId, setFromWhId] = useState("");
  const [toWhId, setToWhId] = useState("");
  const [transferVariantId, setTransferVariantId] = useState("");
  const [transferQty, setTransferQty] = useState("10");
  const [transferNotes, setTransferNotes] = useState("");

  const [receiptNotes, setReceiptNotes] = useState("");

  const [qcVerdict, setQcVerdict] = useState("passed");
  const [qcNote, setQcNote] = useState("");

  const [locCode, setLocCode] = useState("");
  const [locName, setLocName] = useState("");
  const [locKind, setLocKind] = useState("storage");

  const [relocVariantId, setRelocVariantId] = useState("");
  const [relocFromLocId, setRelocFromLocId] = useState("");
  const [relocToLocId, setRelocToLocId] = useState("");
  const [relocQty, setRelocQty] = useState("5");

  const [lcAmount, setLcAmount] = useState("");
  const [lcNote, setLcNote] = useState("");

  // Traceability Form Inputs
  const [formPolicyMode, setFormPolicyMode] = useState("none");
  const [formPolicyExpiry, setFormPolicyExpiry] = useState(false);

  const [lotCode, setLotCode] = useState("");
  const [lotExpiresAt, setLotExpiresAt] = useState("");
  const [lotUnitCost, setLotUnitCost] = useState("");

  const [serialWhId, setSerialWhId] = useState("");
  const [serialsText, setSerialsText] = useState("");

  // Catalog variants for selectors
  const [variants, setVariants] = useState([]);

  // Channel Allocation state
  const [allocations, setAllocations] = useState([]);
  const [allocDialogOpen, setAllocDialogOpen] = useState(false);
  const [allocFormWhId, setAllocFormWhId] = useState("");
  const [allocFormVarId, setAllocFormVarId] = useState("");
  const [allocFormChannel, setAllocFormChannel] = useState("pos");
  const [allocFormQty, setAllocFormQty] = useState("10");
  const [allocSaveLoading, setAllocSaveLoading] = useState(false);

  // Fetch initial data
  useEffect(() => {
    let alive = true;
    async function init() {
      try {
        setLoading(true);
        const [whList, sumRes, catRes] = await Promise.all([
          supplyChainApi.listWarehouses().catch(() => []),
          supplyChainApi
            .getSummaryReport(selectedWarehouseId === "all" ? "" : selectedWarehouseId)
            .catch(() => null),
          api("/products?limit=200").catch(() => ({ items: [] })),
        ]);
        if (!alive) return;
        setWarehouses(whList || []);
        if (whList?.length > 0 && !fromWhId) {
          setFromWhId(whList[0].id);
          if (whList.length > 1) setToWhId(whList[1].id);
          setSerialWhId(whList[0].id);
          if (!allocFormWhId) setAllocFormWhId(whList[0].id);
        }
        setSummary(sumRes);

        // Extract variants
        const vars = [];
        const productList = Array.isArray(catRes) ? catRes : (catRes?.items || []);
        productList.forEach((prod) => {
          (prod.variants || []).forEach((v) => {
            vars.push({
              id: v.id,
              name: `${prod.title} (${v.title || v.sku})`,
              sku: v.sku,
            });
          });
        });
        setVariants(vars);
        if (vars.length > 0) {
          if (!transferVariantId) setTransferVariantId(vars[0].id);
          if (!relocVariantId) setRelocVariantId(vars[0].id);
          if (!traceVariantId) setTraceVariantId(vars[0].id);
          if (!allocFormVarId) setAllocFormVarId(vars[0].id);
        }
      } catch (e) {
        console.error(e);
      } finally {
        if (alive) setLoading(false);
      }
    }
    init();
    return () => {
      alive = false;
    };
  }, [refreshIndex, selectedWarehouseId]);

  // Tab-specific data loader
  useEffect(() => {
    let alive = true;
    const whId = selectedWarehouseId === "all" ? "" : selectedWarehouseId;

    async function loadTabData() {
      try {
        if (activeTab === "receipts") {
          const pos = await api("/purchase-orders?limit=100").catch(() => []);
          if (alive) {
            setPurchaseOrders(pos || []);
            if (pos?.length > 0 && !selectedPo) {
              setSelectedPo(pos[0]);
              const rcs = await supplyChainApi.listReceiptsForPo(pos[0].id).catch(() => []);
              if (alive) setSelectedPoReceipts(rcs || []);
            }
          }
        } else if (activeTab === "transfers") {
          const trs = await supplyChainApi.listTransfers().catch(() => []);
          if (alive) setTransfers(trs || []);
        } else if (activeTab === "replenishment") {
          const [suggs, alerts] = await Promise.all([
            supplyChainApi.listSuggestions().catch(() => []),
            supplyChainApi.getLowStockAlerts(whId).catch(() => []),
          ]);
          if (alive) {
            setSuggestions(suggs || []);
            setLowStockAlerts(alerts || []);
          }
        } else if (activeTab === "locations") {
          const targetWh = whId || (warehouses[0]?.id ?? "");
          if (targetWh) {
            const locs = await supplyChainApi.listLocations(targetWh).catch(() => []);
            if (alive) setLocations(locs || []);
          }
        } else if (activeTab === "valuation") {
          const [val, dead] = await Promise.all([
            supplyChainApi.getValuation(whId).catch(() => null),
            supplyChainApi.getDeadStockReport(90, whId).catch(() => []),
          ]);
          if (alive) {
            setValuationData(val);
            setDeadStock(dead || []);
          }
        } else if (activeTab === "traceability") {
          if (traceVariantId) {
            loadTraceability(traceVariantId);
          }
        } else if (activeTab === "allocations") {
          const allocs = await supplyChainApi
            .listChannelAllocations({ warehouseId: whId })
            .catch(() => []);
          if (alive) setAllocations(allocs || []);
        }
      } catch (err) {
        console.error(err);
      }
    }

    loadTabData();
    return () => {
      alive = false;
    };
  }, [activeTab, selectedWarehouseId, refreshIndex, warehouses, traceVariantId]);

  // Load Traceability for a variant
  async function loadTraceability(variantId) {
    if (!variantId) return;
    try {
      setTraceLoading(true);
      const [pol, lotList, serialList] = await Promise.all([
        supplyChainApi.getTrackingPolicy(variantId).catch(() => ({ mode: "none", expiry_required: false })),
        supplyChainApi.listLots(variantId).catch(() => []),
        supplyChainApi.listSerials(variantId).catch(() => []),
      ]);
      setTrackingPolicy(pol);
      setFormPolicyMode(pol.mode || "none");
      setFormPolicyExpiry(Boolean(pol.expiry_required));
      setLots(lotList || []);
      setSerials(serialList || []);
    } catch (e) {
      console.error(e);
    } finally {
      setTraceLoading(false);
    }
  }

  // Load receipts for a selected PO
  async function handleSelectPo(po) {
    setSelectedPo(po);
    try {
      const rcs = await supplyChainApi.listReceiptsForPo(po.id).catch(() => []);
      setSelectedPoReceipts(rcs || []);
    } catch (e) {
      console.error(e);
      setSelectedPoReceipts([]);
    }
  }

  // Actions
  async function handleCreateTransfer(e) {
    e.preventDefault();
    try {
      if (!fromWhId || !toWhId || fromWhId === toWhId) {
        toast.error(isAr ? "يجب اختيار مستودعين مختلفين." : "Select two different warehouses.");
        return;
      }
      await supplyChainApi.createTransfer({
        from_warehouse_id: fromWhId,
        to_warehouse_id: toWhId,
        lines: [{ variant_id: transferVariantId, quantity: parseInt(transferQty, 10) || 1 }],
        note: transferNotes,
      });
      toast.success(isAr ? "تم إنشاء طلب التحويل بنجاح." : "Transfer created successfully.");
      setTransferDialogOpen(false);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل إنشاء التحويل." : "Failed to create transfer."));
    }
  }

  async function handleShipTransfer(trId) {
    try {
      await supplyChainApi.shipTransfer(trId, {
        carrier: "الناقل الداخلي",
        tracking_number: `TRK-${Date.now().toString().slice(-6)}`,
      });
      toast.success(isAr ? "تم شحن ونقل البضاعة بنجاح." : "Transfer shipped successfully.");
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل شحن التحويل." : "Failed to ship transfer."));
    }
  }

  async function handleReceiveTransfer(trId) {
    try {
      await supplyChainApi.receiveTransfer(trId, {});
      toast.success(
        isAr ? "تم استلام التحويل وإيداع البضاعة بالمخزن." : "Transfer received successfully.",
      );
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل استلام التحويل." : "Failed to receive transfer."));
    }
  }

  async function handleApproveSuggestion(suggId) {
    try {
      await supplyChainApi.approveSuggestion(suggId);
      toast.success(
        isAr
          ? "تم اعتماد المقترح وإنشاء أمر الشراء بنجاح."
          : "Suggestion approved and PO created.",
      );
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل اعتماد المقترح." : "Failed to approve suggestion."));
    }
  }

  async function handleDismissSuggestion(suggId) {
    try {
      await supplyChainApi.dismissSuggestion(suggId);
      toast.success(isAr ? "تم تجاهل المقترح." : "Suggestion dismissed.");
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل تجاهل المقترح." : "Failed to dismiss suggestion."));
    }
  }

  async function handleGenerateSuggestions() {
    try {
      const whId = selectedWarehouseId === "all" ? "" : selectedWarehouseId;
      const res = await supplyChainApi.generateSuggestions(whId);
      toast.success(
        isAr
          ? `تم حساب وتحديث المقترحات (${res.generated_count || 0} مقترح جديد).`
          : `Generated ${res.generated_count || 0} suggestions.`,
      );
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل حساب المقترحات." : "Failed to generate."));
    }
  }

  function handleOpenReceiptDialog(po) {
    setActivePoForReceipt(po);
    setReceiptNotes(isAr ? `استلام أمر شراء ${po.number}` : `Receipt for PO ${po.number}`);
    setReceiptDialogOpen(true);
  }

  async function handleConfirmCreateReceipt(e) {
    e.preventDefault();
    if (!activePoForReceipt) return;
    try {
      const lines = (activePoForReceipt.lines || []).map((l) => ({
        purchase_order_line_id: l.id,
        variant_id: l.variant_id,
        quantity: l.quantity,
        unit_cost: l.unit_cost,
        condition: "good",
      }));
      const gr = await supplyChainApi.createReceipt(activePoForReceipt.id, {
        lines,
        note: receiptNotes,
      });
      toast.success(
        isAr
          ? `تم إنشاء إذن الاستلام ${gr.number} بنجاح كمسودة.`
          : `Goods Receipt ${gr.number} created.`,
      );
      setReceiptDialogOpen(false);
      handleSelectPo(activePoForReceipt);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل إنشاء إذن الاستلام." : "Failed to create receipt."));
    }
  }

  async function handlePostReceipt(receiptId) {
    try {
      await supplyChainApi.postReceipt(receiptId);
      toast.success(
        isAr ? "تم ترحيل إذن الاستلام وتحديث أرصدة المخزن." : "Receipt posted to inventory.",
      );
      if (selectedPo) handleSelectPo(selectedPo);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل ترحيل الاستلام." : "Failed to post receipt."));
    }
  }

  async function handleCancelReceipt(receiptId) {
    try {
      await supplyChainApi.cancelReceipt(receiptId);
      toast.success(isAr ? "تم إلغاء إذن الاستلام." : "Receipt cancelled.");
      if (selectedPo) handleSelectPo(selectedPo);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل إلغاء الاستلام." : "Failed to cancel receipt."));
    }
  }

  function handleOpenQcDialog(receipt) {
    setActiveReceipt(receipt);
    setQcVerdict("passed");
    setQcNote("");
    setQcDialogOpen(true);
  }

  async function handleCompleteQC() {
    try {
      if (!activeReceipt) return;
      const targetWh = activeReceipt.warehouse_id || (warehouses[0]?.id ?? "");
      // create inspection
      const insp = await supplyChainApi.createInspection({
        source_type: "goods_receipt",
        source_id: activeReceipt.id,
        warehouse_id: targetWh,
        note: qcNote,
      });
      // record result for lines
      for (const ln of activeReceipt.lines || []) {
        await supplyChainApi.recordInspectionResult(insp.id, {
          variant_id: ln.variant_id,
          quantity: ln.quantity,
          verdict: qcVerdict === "passed" ? "pass" : "reject",
        });
      }
      // complete
      await supplyChainApi.completeInspection(insp.id, {
        note: qcNote,
      });
      toast.success(isAr ? "تم إكمال فحص الجودة بنجاح." : "Quality inspection completed.");
      setQcDialogOpen(false);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل تسجيل فحص الجودة." : "Failed QC inspection."));
    }
  }

  async function handleCreateLocation(e) {
    e.preventDefault();
    try {
      const targetWh =
        selectedWarehouseId !== "all" ? selectedWarehouseId : warehouses[0]?.id;
      if (!targetWh) return;
      await supplyChainApi.createLocation(targetWh, {
        code: locCode,
        name: locName,
        kind: locKind,
      });
      toast.success(isAr ? "تم إضافة موقع التخزين بنجاح." : "Location added successfully.");
      setLocationDialogOpen(false);
      setLocCode("");
      setLocName("");
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل إنشاء الموقع." : "Failed to create location."));
    }
  }

  async function handleRelocateStock(e) {
    e.preventDefault();
    try {
      const targetWh =
        selectedWarehouseId !== "all" ? selectedWarehouseId : warehouses[0]?.id;
      if (!targetWh) return;
      await supplyChainApi.relocate({
        warehouse_id: targetWh,
        variant_id: relocVariantId,
        from_location_id: relocFromLocId,
        to_location_id: relocToLocId,
        quantity: parseInt(relocQty, 10) || 1,
      });
      toast.success(
        isAr ? "تم نقل البضاعة بين الرفوف بنجاح." : "Stock relocated successfully.",
      );
      setRelocateDialogOpen(false);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل نقل البضاعة." : "Failed to relocate stock."));
    }
  }

  async function handleCreateLandedCost(e) {
    e.preventDefault();
    try {
      const targetWh =
        selectedWarehouseId !== "all" ? selectedWarehouseId : warehouses[0]?.id;
      if (!targetWh) return;
      await supplyChainApi.createLandedCost({
        warehouse_id: targetWh,
        total: parseFloat(lcAmount) || 0,
        note: lcNote,
      });
      toast.success(
        isAr ? "تم تسجيل وثيقة التكاليف الإضافية بنجاح." : "Landed cost document created.",
      );
      setLandedCostDialogOpen(false);
      setLcAmount("");
      setLcNote("");
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل تسجيل التكلفة." : "Failed to create landed cost."));
    }
  }

  // Traceability Handlers
  async function handleSaveTrackingPolicy(e) {
    e.preventDefault();
    if (!traceVariantId) return;
    try {
      await supplyChainApi.setTrackingPolicy(traceVariantId, {
        mode: formPolicyMode,
        expiry_required: formPolicyExpiry,
      });
      toast.success(isAr ? "تم تحديث سياسة التتبع بنجاح." : "Tracking policy updated.");
      setPolicyDialogOpen(false);
      loadTraceability(traceVariantId);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل تحديث السياسة." : "Failed to update policy."));
    }
  }

  async function handleCreateLot(e) {
    e.preventDefault();
    if (!traceVariantId || !lotCode) return;
    try {
      await supplyChainApi.createLot(traceVariantId, {
        lot_code: lotCode,
        expires_at: lotExpiresAt ? new Date(lotExpiresAt).toISOString() : null,
        unit_cost: lotUnitCost ? parseFloat(lotUnitCost) : null,
      });
      toast.success(isAr ? "تم إنشاء رقم التشغيلة/الدفعة بنجاح." : "Lot created successfully.");
      setLotDialogOpen(false);
      setLotCode("");
      setLotExpiresAt("");
      setLotUnitCost("");
      loadTraceability(traceVariantId);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل إنشاء الدفعة." : "Failed to create lot."));
    }
  }

  async function handleRegisterSerials(e) {
    e.preventDefault();
    if (!traceVariantId || !serialWhId) return;
    const serialNumbers = serialsText
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (serialNumbers.length === 0) {
      toast.error(isAr ? "أدخل رقماً تسلسلياً واحداً على الأقل." : "Enter at least one serial number.");
      return;
    }
    try {
      const res = await supplyChainApi.createSerials(traceVariantId, {
        warehouse_id: serialWhId,
        serial_numbers: serialNumbers,
      });
      toast.success(
        isAr
          ? `تم تسجيل ${res.registered_count || serialNumbers.length} رقم تسلسلي بنجاح.`
          : `Registered ${res.registered_count || serialNumbers.length} serials.`,
      );
      setSerialDialogOpen(false);
      setSerialsText("");
      loadTraceability(traceVariantId);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل تسجيل الأرقام التسلسلية." : "Failed to register serials."));
    }
  }

  async function handleCreateAllocation(e) {
    e.preventDefault();
    if (!allocFormVarId || !allocFormWhId || !allocFormChannel) {
      toast.error(isAr ? "يرجى تعبئة كافة الحقول المطلوبة." : "Please fill all required fields.");
      return;
    }
    try {
      setAllocSaveLoading(true);
      await supplyChainApi.setChannelAllocation({
        warehouse_id: allocFormWhId,
        variant_id: allocFormVarId,
        channel: allocFormChannel.trim().toLowerCase(),
        quantity: parseInt(allocFormQty, 10) || 0,
      });
      toast.success(isAr ? "تم حفظ تخصيص القناة بنجاح." : "Channel allocation saved.");
      setAllocDialogOpen(false);
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل حفظ التخصيص." : "Failed to save allocation."));
    } finally {
      setAllocSaveLoading(false);
    }
  }

  async function handleDeleteAllocation(allocId) {
    try {
      await supplyChainApi.deleteChannelAllocation(allocId);
      toast.success(isAr ? "تم حذف التخصيص." : "Allocation deleted.");
      setRefreshIndex((n) => n + 1);
    } catch (err) {
      toast.error(err?.message || (isAr ? "فشل حذف التخصيص." : "Failed to delete allocation."));
    }
  }

  // Filtered variants
  const filteredVariants = variants.filter(
    (v) =>
      v.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      v.sku.toLowerCase().includes(searchQuery.toLowerCase()),
  );

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
          {[
            { id: "receipts", label: isAr ? "أذونات الاستلام والجودة" : "Goods Receipts & QC", icon: ClipboardCheck },
            { id: "transfers", label: isAr ? "التحويلات بين المستودعات (D6)" : "Stock Transfers (D6)", icon: ArrowLeftRight },
            { id: "replenishment", label: isAr ? "محرك التجديد وإعادة الشراء" : "Replenishment Engine", icon: TrendingUp },
            { id: "locations", label: isAr ? "المواقع والرفوف الداخلية" : "Locations & Bins", icon: MapPin },
            { id: "valuation", label: isAr ? "تقييم FIFO والتكاليف" : "Valuation & Landed Cost", icon: Layers },
            { id: "traceability", label: isAr ? "التتبع والدفعات والسيريال" : "Traceability & Serials", icon: Barcode },
            { id: "allocations", label: isAr ? "تخصيص القنوات" : "Channel Allocations", icon: Share2 },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
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
        )}


        {/* TAB 2: STOCK TRANSFERS */}
        {activeTab === "transfers" && (
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
        )}


        {/* TAB 3: REPLENISHMENT */}
        {activeTab === "replenishment" && (
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
        )}


        {/* TAB 4: LOCATIONS & BINS */}
        {activeTab === "locations" && (
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
        )}


        {/* TAB 5: VALUATION & LANDED COST */}
        {activeTab === "valuation" && (
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
        )}


        {/* TAB 6: TRACEABILITY (LOTS & SERIALS) */}
        {activeTab === "traceability" && (
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
        )}

        {/* TAB 7: CHANNEL ALLOCATIONS */}
        {activeTab === "allocations" && (
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
