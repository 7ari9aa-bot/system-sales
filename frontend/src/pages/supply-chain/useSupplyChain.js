/**
 * حالة صفحة سلاسل الإمداد وبياناتها — مسؤولية واحدة.
 *
 * الوعاء كان 1441 سطر: 157 اسم حالة ومعالج فوق الـJSX. كلهم اتنقلوا هنا، والصفحة بقت
 * بتعرض بس. نفس النداءات ونفس الحقول زي ما كانت، فالمكوّنات السبع ماحستش بفرق.
 */
import { ArrowLeftRight, Barcode, ClipboardCheck, Layers, MapPin, Share2, TrendingUp } from "lucide-react";
import { activeOrFirst, visibleTabs } from "@/cashier/lib/stockScreens";
import { api } from "@/lib/api";
import { supplyChainApi } from "@/lib/supplyChainApi";
import { toast } from "sonner";
import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { useNavigate, useParams } from "react-router-dom";
import { useStockScreens } from "@/cashier/api/useShopOptions";

export function useSupplyChain() {
  const { lang } = useI18n();
  const isAr = lang === "ar";

  // Every module has its own URL (/cashier/supply-chain/<section>): the page never stacks seven
  // workspaces behind a tab strip that a refresh or a shared link cannot reproduce.
  const { section } = useParams();
  const navigate = useNavigate();
  const [activeTabRaw, setActiveTab] = useState(section || "receipts"); // receipts | transfers | replenishment | locations | valuation | traceability | allocations
  useEffect(() => {
    if (section && section !== activeTabRaw) setActiveTab(section);
  }, [section, activeTabRaw]);
  // The owner can hide the transfers and online-allocation tabs; nothing is removed, so turning one back on restores it.
  const screens = useStockScreens();

  const allTabs = [
    { id: "receipts", label: isAr ? "أذونات الاستلام والجودة" : "Goods Receipts & QC", icon: ClipboardCheck },
    { id: "transfers", label: isAr ? "التحويلات بين المستودعات (D6)" : "Stock Transfers (D6)", icon: ArrowLeftRight },
    { id: "replenishment", label: isAr ? "محرك التجديد وإعادة الشراء" : "Replenishment Engine", icon: TrendingUp },
    { id: "locations", label: isAr ? "المواقع والرفوف الداخلية" : "Locations & Bins", icon: MapPin },
    { id: "valuation", label: isAr ? "تقييم FIFO والتكاليف" : "Valuation & Landed Cost", icon: Layers },
    { id: "traceability", label: isAr ? "التتبع والدفعات والسيريال" : "Traceability & Serials", icon: Barcode },
    { id: "allocations", label: isAr ? "تخصيص القنوات" : "Channel Allocations", icon: Share2 },
  ];
  const shownTabs = visibleTabs(allTabs, screens);
  // If the tab being viewed was just hidden, show the first one still shown.
  const activeTab = activeOrFirst(activeTabRaw, shownTabs);
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


  return {
    activePoForReceipt,
    activeReceipt,
    activeTab,
    activeTabRaw,
    allTabs,
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
    refreshIndex,
    relocFromLocId,
    relocQty,
    relocToLocId,
    relocVariantId,
    relocateDialogOpen,
    screens,
    searchQuery,
    selectedPo,
    selectedPoReceipts,
    selectedWarehouseId,
    serialDialogOpen,
    serialWhId,
    serials,
    serialsText,
    setActivePoForReceipt,
    setActiveReceipt,
    setActiveTab,
    setAllocDialogOpen,
    setAllocFormChannel,
    setAllocFormQty,
    setAllocFormVarId,
    setAllocFormWhId,
    setAllocSaveLoading,
    setAllocations,
    setDeadStock,
    setFormPolicyExpiry,
    setFormPolicyMode,
    setFromWhId,
    setLandedCostDialogOpen,
    setLcAmount,
    setLcNote,
    setLoading,
    setLocCode,
    setLocKind,
    setLocName,
    setLocationDialogOpen,
    setLocations,
    setLotCode,
    setLotDialogOpen,
    setLotExpiresAt,
    setLotUnitCost,
    setLots,
    setLowStockAlerts,
    setPolicyDialogOpen,
    setPurchaseOrders,
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
    setSelectedPo,
    setSelectedPoReceipts,
    setSelectedWarehouseId,
    setSerialDialogOpen,
    setSerialWhId,
    setSerials,
    setSerialsText,
    setSuggestions,
    setSummary,
    setToWhId,
    setTraceLoading,
    setTraceVariantId,
    setTrackingPolicy,
    setTransferDialogOpen,
    setTransferNotes,
    setTransferQty,
    setTransferVariantId,
    setTransfers,
    setValuationData,
    setVariants,
    setWarehouses,
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
  };
}
