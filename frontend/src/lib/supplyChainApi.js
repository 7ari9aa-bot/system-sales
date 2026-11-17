import { api } from "./api";

export const supplyChainApi = {
  // Warehouses
  listWarehouses: () => api("/inventory/warehouses"),

  // Locations & Relocation
  listLocations: (warehouseId) => api(`/inventory/warehouses/${warehouseId}/locations`),
  createLocation: (warehouseId, body) =>
    api(`/inventory/warehouses/${warehouseId}/locations`, { method: "POST", body }),
  relocate: (body) => api("/inventory/relocate", { method: "POST", body }),

  // Goods Receipts
  listReceiptsForPo: (orderId) => api(`/purchase-orders/${orderId}/receipts`),
  createReceipt: (orderId, body) =>
    api(`/purchase-orders/${orderId}/receipts`, { method: "POST", body }),
  getReceipt: (receiptId) => api(`/goods-receipts/${receiptId}`),
  postReceipt: (receiptId) => api(`/goods-receipts/${receiptId}/post`, { method: "POST" }),
  cancelReceipt: (receiptId) => api(`/goods-receipts/${receiptId}/cancel`, { method: "POST" }),

  // Quality Inspections
  createInspection: (body) => api("/inventory/inspections", { method: "POST", body }),
  getInspection: (inspectionId) => api(`/inventory/inspections/${inspectionId}`),
  recordInspectionResult: (inspectionId, body) =>
    api(`/inventory/inspections/${inspectionId}/results`, { method: "POST", body }),
  completeInspection: (inspectionId, body) =>
    api(`/inventory/inspections/${inspectionId}/complete`, { method: "POST", body }),

  // Transfers
  listTransfers: (status = "") =>
    api(`/inventory/transfers${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  getTransfer: (transferId) => api(`/inventory/transfers/${transferId}`),
  createTransfer: (body) => api("/inventory/transfers", { method: "POST", body }),
  shipTransfer: (transferId, body) =>
    api(`/inventory/transfers/${transferId}/ship`, { method: "POST", body }),
  receiveTransfer: (transferId, body) =>
    api(`/inventory/transfers/${transferId}/receive`, { method: "POST", body }),

  // Replenishment
  listPolicies: (warehouseId = "") =>
    api(`/inventory/replenishment/policies${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  setPolicy: (body) => api("/inventory/replenishment/policies", { method: "POST", body }),
  listSuggestions: (status = "") =>
    api(`/inventory/replenishment/suggestions${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  generateSuggestions: (warehouseId = "") =>
    api(`/inventory/replenishment/generate${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`, {
      method: "POST",
    }),
  approveSuggestion: (id) =>
    api(`/inventory/replenishment/suggestions/${id}/approve`, { method: "POST" }),
  dismissSuggestion: (id) =>
    api(`/inventory/replenishment/suggestions/${id}/dismiss`, { method: "POST" }),

  // Valuation & Landed Cost
  getValuation: (warehouseId = "") =>
    api(`/inventory/valuation${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  createLandedCost: (body) => api("/inventory/landed-costs", { method: "POST", body }),
  postLandedCost: (costId) => api(`/inventory/landed-costs/${costId}/post`, { method: "POST" }),

  // Traceability
  getTrackingPolicy: (variantId) => api(`/inventory/variants/${variantId}/tracking-policy`),
  setTrackingPolicy: (variantId, body) =>
    api(`/inventory/variants/${variantId}/tracking-policy`, { method: "POST", body }),
  listLots: (variantId) => api(`/inventory/variants/${variantId}/lots`),
  createLot: (variantId, body) =>
    api(`/inventory/variants/${variantId}/lots`, { method: "POST", body }),
  listSerials: (variantId) => api(`/inventory/variants/${variantId}/serials`),
  createSerials: (variantId, body) =>
    api(`/inventory/variants/${variantId}/serials`, { method: "POST", body }),

  // Reports
  getSummaryReport: (warehouseId = "") =>
    api(`/inventory/reports/summary${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  getDeadStockReport: (days = 90, warehouseId = "") =>
    api(
      `/inventory/reports/dead-stock?days_inactive=${days}${warehouseId ? `&warehouse_id=${warehouseId}` : ""}`,
    ),
  getLowStockAlerts: (warehouseId = "") =>
    api(`/inventory/reports/low-stock-alerts${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  getApparelInsights: (days = 30, warehouseId = "") =>
    api(
      `/inventory/reports/apparel-insights?days=${days}${warehouseId ? `&warehouse_id=${warehouseId}` : ""}`,
    ),

  // Channel Allocation
  listChannelAllocations: ({ warehouseId = "", variantId = "", channel = "" } = {}) => {
    const params = new URLSearchParams();
    if (warehouseId) params.set("warehouse_id", warehouseId);
    if (variantId) params.set("variant_id", variantId);
    if (channel) params.set("channel", channel);
    const qs = params.toString();
    return api(`/inventory/channel-allocations${qs ? `?${qs}` : ""}`);
  },
  setChannelAllocation: (body) =>
    api("/inventory/channel-allocations", { method: "POST", body }),
  deleteChannelAllocation: (allocationId) =>
    api(`/inventory/channel-allocations/${allocationId}`, { method: "DELETE" }),
  getChannelAvailability: ({ warehouseId, variantId, channel }) =>
    api(
      `/inventory/channel-availability?warehouse_id=${warehouseId}&variant_id=${variantId}&channel=${encodeURIComponent(channel)}`,
    ),

  // Checkout Traceability
  getCheckoutTraceability: (variantId) =>
    api(`/inventory/variants/${variantId}/checkout-traceability`),
  markSerialsSold: (variantId, serialCodes) =>
    api(`/inventory/variants/${variantId}/serials/mark-sold`, {
      method: "POST",
      body: { serial_codes: serialCodes },
    }),
  markSerialsReturned: (variantId, serialCodes) =>
    api(`/inventory/variants/${variantId}/serials/mark-returned`, {
      method: "POST",
      body: { serial_codes: serialCodes },
    }),
};
