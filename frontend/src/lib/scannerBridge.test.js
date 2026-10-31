import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// بيئة الاختبار node بلا DOM، فيُبنى window وهمي بالحد الأدنى (addEventListener / removeEventListener)
// وُيلتقط المُستمع المسجّل لاستدعائه يدويًا بدل توزيع حدث حقيقي.
let addSpy;
let removeSpy;

beforeEach(() => {
  addSpy = vi.fn();
  removeSpy = vi.fn();
  globalThis.window = { addEventListener: addSpy, removeEventListener: removeSpy };
});

afterEach(() => {
  delete globalThis.window;
  vi.resetModules();
});

// كل اختبار يحصل على نسخة جديدة من الوحدة (singleton) حتى لا يتسرب تسجيل بين الاختبارات.
async function freshBridge() {
  vi.resetModules();
  return import("./scannerBridge");
}

// يستدعي مُستمع "fihrist:scan" المسجّل على window الوهمي بحدث يشبه ما يطلقه سكربت الصدفة.
function dispatchScan(addCalls, detail) {
  const entry = addCalls.find(([type]) => type === "fihrist:scan");
  expect(entry, "expected a registered fihrist:scan listener").toBeTruthy();
  entry[1]({ detail, type: "fihrist:scan" });
}

describe("scannerBridge", () => {
  it("invokes the handler with the trimmed value from the event detail", async () => {
    const { SCAN_EVENT_NAME, registerScanHandler } = await freshBridge();
    expect(SCAN_EVENT_NAME).toBe("fihrist:scan");
    const handler = vi.fn();
    registerScanHandler(handler);
    dispatchScan(addSpy.mock.calls, { value: "  6301001  ", durationMs: 42 });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith("6301001");
  });

  it("invokes every registered handler", async () => {
    const { registerScanHandler } = await freshBridge();
    const first = vi.fn();
    const second = vi.fn();
    registerScanHandler(first);
    registerScanHandler(second);
    dispatchScan(addSpy.mock.calls, { value: "6301002" });
    expect(first).toHaveBeenCalledWith("6301002");
    expect(second).toHaveBeenCalledWith("6301002");
  });

  it("registers the same fn only once", async () => {
    const { registerScanHandler } = await freshBridge();
    const handler = vi.fn();
    registerScanHandler(handler);
    registerScanHandler(handler);
    dispatchScan(addSpy.mock.calls, { value: "6301003" });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("stops invoking a handler after unregister", async () => {
    const { registerScanHandler, unregisterScanHandler } = await freshBridge();
    const kept = vi.fn();
    const removed = vi.fn();
    registerScanHandler(kept);
    registerScanHandler(removed);
    unregisterScanHandler(removed);
    dispatchScan(addSpy.mock.calls, { value: "6301004" });
    expect(kept).toHaveBeenCalledTimes(1);
    expect(removed).not.toHaveBeenCalled();
  });

  it("ignores empty and missing values", async () => {
    const { registerScanHandler } = await freshBridge();
    const handler = vi.fn();
    registerScanHandler(handler);
    dispatchScan(addSpy.mock.calls, { value: "   " });
    dispatchScan(addSpy.mock.calls, { value: "" });
    dispatchScan(addSpy.mock.calls, {});
    dispatchScan(addSpy.mock.calls, undefined);
    expect(handler).not.toHaveBeenCalled();
  });

  it("adds the window listener on first registration and removes it after the last unregister", async () => {
    const { SCAN_EVENT_NAME, registerScanHandler, unregisterScanHandler } = await freshBridge();
    const first = vi.fn();
    const second = vi.fn();
    registerScanHandler(first);
    expect(addSpy).toHaveBeenCalledTimes(1);
    expect(addSpy).toHaveBeenCalledWith(SCAN_EVENT_NAME, expect.any(Function));
    const listener = addSpy.mock.calls[0][1];

    registerScanHandler(second); // still one window listener for both handlers
    expect(addSpy).toHaveBeenCalledTimes(1);

    unregisterScanHandler(first);
    expect(removeSpy).not.toHaveBeenCalled(); // second handler still registered
    unregisterScanHandler(second);
    expect(removeSpy).toHaveBeenCalledTimes(1);
    expect(removeSpy).toHaveBeenCalledWith(SCAN_EVENT_NAME, listener);

    // حتى لو وصل حدث جديد، لا يوجد مُعالج مسجّل فلا يُستدعى أحد.
    listener({ detail: { value: "6301005" }, type: SCAN_EVENT_NAME });
    expect(first).not.toHaveBeenCalled();
    expect(second).not.toHaveBeenCalled();
  });

  it("does nothing when unregistering an unknown handler", async () => {
    const { registerScanHandler, unregisterScanHandler } = await freshBridge();
    const handler = vi.fn();
    registerScanHandler(handler);
    unregisterScanHandler(vi.fn());
    expect(removeSpy).not.toHaveBeenCalled();
    dispatchScan(addSpy.mock.calls, { value: "6301006" });
    expect(handler).toHaveBeenCalledTimes(1);
  });
});
