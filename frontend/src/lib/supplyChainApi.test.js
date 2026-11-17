import { describe, expect, it, vi } from "vitest";
import { supplyChainApi } from "./supplyChainApi";
import { api } from "./api";

vi.mock("./api", () => ({
  api: vi.fn(),
}));

describe("supplyChainApi client", () => {
  it("calls listWarehouses", async () => {
    vi.mocked(api).mockResolvedValueOnce([{ id: "wh1" }]);
    const res = await supplyChainApi.listWarehouses();
    expect(api).toHaveBeenCalledWith("/inventory/warehouses");
    expect(res).toEqual([{ id: "wh1" }]);
  });

  it("calls listLocations and createLocation", async () => {
    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listLocations("wh1");
    expect(api).toHaveBeenCalledWith("/inventory/warehouses/wh1/locations");

    vi.mocked(api).mockResolvedValueOnce({ id: "loc1" });
    await supplyChainApi.createLocation("wh1", { name: "Bin A" });
    expect(api).toHaveBeenCalledWith("/inventory/warehouses/wh1/locations", {
      method: "POST",
      body: { name: "Bin A" },
    });
  });

  it("calls relocate stock", async () => {
    vi.mocked(api).mockResolvedValueOnce({ success: true });
    await supplyChainApi.relocate({ warehouse_id: "wh1", quantity: 5 });
    expect(api).toHaveBeenCalledWith("/inventory/relocate", {
      method: "POST",
      body: { warehouse_id: "wh1", quantity: 5 },
    });
  });

  it("calls goods receipts endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listReceiptsForPo("po1");
    expect(api).toHaveBeenCalledWith("/purchase-orders/po1/receipts");

    vi.mocked(api).mockResolvedValueOnce({ id: "gr1" });
    await supplyChainApi.createReceipt("po1", { note: "test" });
    expect(api).toHaveBeenCalledWith("/purchase-orders/po1/receipts", {
      method: "POST",
      body: { note: "test" },
    });

    vi.mocked(api).mockResolvedValueOnce({ id: "gr1", status: "posted" });
    await supplyChainApi.postReceipt("gr1");
    expect(api).toHaveBeenCalledWith("/goods-receipts/gr1/post", { method: "POST" });
  });

  it("calls quality inspection endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce({ id: "insp1" });
    await supplyChainApi.createInspection({ source_type: "goods_receipt" });
    expect(api).toHaveBeenCalledWith("/inventory/inspections", {
      method: "POST",
      body: { source_type: "goods_receipt" },
    });

    vi.mocked(api).mockResolvedValueOnce({ id: "insp1" });
    await supplyChainApi.completeInspection("insp1", { verdict: "passed" });
    expect(api).toHaveBeenCalledWith("/inventory/inspections/insp1/complete", {
      method: "POST",
      body: { verdict: "passed" },
    });
  });

  it("calls transfers endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listTransfers("draft");
    expect(api).toHaveBeenCalledWith("/inventory/transfers?status=draft");

    vi.mocked(api).mockResolvedValueOnce({ id: "tr1" });
    await supplyChainApi.createTransfer({ from_warehouse_id: "w1" });
    expect(api).toHaveBeenCalledWith("/inventory/transfers", {
      method: "POST",
      body: { from_warehouse_id: "w1" },
    });

    vi.mocked(api).mockResolvedValueOnce({ id: "tr1", status: "shipped" });
    await supplyChainApi.shipTransfer("tr1", { carrier: "DHL" });
    expect(api).toHaveBeenCalledWith("/inventory/transfers/tr1/ship", {
      method: "POST",
      body: { carrier: "DHL" },
    });
  });

  it("calls replenishment endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listSuggestions("open");
    expect(api).toHaveBeenCalledWith("/inventory/replenishment/suggestions?status=open");

    vi.mocked(api).mockResolvedValueOnce({ generated_count: 3 });
    await supplyChainApi.generateSuggestions("wh1");
    expect(api).toHaveBeenCalledWith("/inventory/replenishment/generate?warehouse_id=wh1", {
      method: "POST",
    });

    vi.mocked(api).mockResolvedValueOnce({ status: "approved" });
    await supplyChainApi.approveSuggestion("sug1");
    expect(api).toHaveBeenCalledWith("/inventory/replenishment/suggestions/sug1/approve", {
      method: "POST",
    });
  });

  it("calls valuation and landed cost endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce({ total_value: "100.00" });
    await supplyChainApi.getValuation("wh1");
    expect(api).toHaveBeenCalledWith("/inventory/valuation?warehouse_id=wh1");

    vi.mocked(api).mockResolvedValueOnce({ id: "lc1" });
    await supplyChainApi.createLandedCost({ total: 50 });
    expect(api).toHaveBeenCalledWith("/inventory/landed-costs", {
      method: "POST",
      body: { total: 50 },
    });
  });

  it("calls traceability endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce({ mode: "batch" });
    await supplyChainApi.getTrackingPolicy("v1");
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/tracking-policy");

    vi.mocked(api).mockResolvedValueOnce({ mode: "batch" });
    await supplyChainApi.setTrackingPolicy("v1", { mode: "batch" });
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/tracking-policy", {
      method: "POST",
      body: { mode: "batch" },
    });

    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listLots("v1");
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/lots");

    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listSerials("v1");
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/serials");
  });

  it("calls reporting endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce({ on_hand: 50 });
    await supplyChainApi.getSummaryReport("wh1");
    expect(api).toHaveBeenCalledWith("/inventory/reports/summary?warehouse_id=wh1");

    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.getDeadStockReport(60, "wh1");
    expect(api).toHaveBeenCalledWith(
      "/inventory/reports/dead-stock?days_inactive=60&warehouse_id=wh1",
    );

    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.getLowStockAlerts("wh1");
    expect(api).toHaveBeenCalledWith("/inventory/reports/low-stock-alerts?warehouse_id=wh1");

    vi.mocked(api).mockResolvedValueOnce({});
    await supplyChainApi.getApparelInsights(45, "wh1");
    expect(api).toHaveBeenCalledWith(
      "/inventory/reports/apparel-insights?days=45&warehouse_id=wh1",
    );
  });

  it("calls channel allocations and checkout traceability endpoints", async () => {
    vi.mocked(api).mockResolvedValueOnce([]);
    await supplyChainApi.listChannelAllocations({ warehouseId: "wh1", channel: "pos" });
    expect(api).toHaveBeenCalledWith("/inventory/channel-allocations?warehouse_id=wh1&channel=pos");

    vi.mocked(api).mockResolvedValueOnce({ id: "ca1" });
    await supplyChainApi.setChannelAllocation({ warehouse_id: "wh1", variant_id: "v1", channel: "pos", quantity: 5 });
    expect(api).toHaveBeenCalledWith("/inventory/channel-allocations", {
      method: "POST",
      body: { warehouse_id: "wh1", variant_id: "v1", channel: "pos", quantity: 5 },
    });

    vi.mocked(api).mockResolvedValueOnce({ ok: true });
    await supplyChainApi.deleteChannelAllocation("ca1");
    expect(api).toHaveBeenCalledWith("/inventory/channel-allocations/ca1", { method: "DELETE" });

    vi.mocked(api).mockResolvedValueOnce({ available_quantity: 5 });
    await supplyChainApi.getChannelAvailability({ warehouseId: "wh1", variantId: "v1", channel: "pos" });
    expect(api).toHaveBeenCalledWith("/inventory/channel-availability?warehouse_id=wh1&variant_id=v1&channel=pos");

    vi.mocked(api).mockResolvedValueOnce({ mode: "serial", serials: [] });
    await supplyChainApi.getCheckoutTraceability("v1");
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/checkout-traceability");

    vi.mocked(api).mockResolvedValueOnce({ ok: true });
    await supplyChainApi.markSerialsSold("v1", ["SN1", "SN2"]);
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/serials/mark-sold", {
      method: "POST",
      body: { serial_codes: ["SN1", "SN2"] },
    });

    vi.mocked(api).mockResolvedValueOnce({ ok: true });
    await supplyChainApi.markSerialsReturned("v1", ["SN1"]);
    expect(api).toHaveBeenCalledWith("/inventory/variants/v1/serials/mark-returned", {
      method: "POST",
      body: { serial_codes: ["SN1"] },
    });
  });
});
