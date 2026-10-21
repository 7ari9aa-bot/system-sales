import { describe, expect, it, vi, beforeEach } from "vitest";

const { pos, boot } = vi.hoisted(() => ({
  pos: { openSession: vi.fn(), closeSession: vi.fn(), listRegisters: vi.fn(), listSessions: vi.fn() },
  boot: vi.fn(),
}));
vi.mock("./posApi", () => ({ posApi: pos }));
// the pure rules (chooseRegister, pickMyShift) stay REAL; only the network-touching bootstrap is replaced
vi.mock("./shiftState", async (orig) => ({ ...(await orig()), bootstrapPos: boot, resolveShiftState: vi.fn() }));

import { openShiftFlow } from "./useShifts";

const reg = (id, extra = {}) => ({ id, name: `Till ${id}`, code: id, is_active: true, ...extra });
const shift = (id, registerId, userId) => ({ id, register_id: registerId, cashier_user_id: userId, status: "OPEN" });

beforeEach(() => {
  vi.clearAllMocks();
  pos.openSession.mockResolvedValue({ id: "s-new" });
});

describe("openShiftFlow (what the Open Shift button does)", () => {
  it("brand-new shop: bootstraps the till FIRST, then opens on the register that bootstrap returned", async () => {
    pos.listRegisters.mockResolvedValue([]);
    pos.listSessions.mockResolvedValue([]);
    boot.mockResolvedValue({ id: "reg-new" });
    await openShiftFlow({ openingCash: 150, userId: "u1" });
    expect(boot).toHaveBeenCalledTimes(1);
    expect(pos.openSession).toHaveBeenCalledWith("reg-new", { openingFloat: 150 });
  });

  it("one-till shop: opens on it without asking, and does not bootstrap again", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1")]);
    pos.listSessions.mockResolvedValue([]);
    await openShiftFlow({ openingCash: 0, userId: "u1" });
    expect(boot).not.toHaveBeenCalled();
    expect(pos.openSession).toHaveBeenCalledWith("reg-1", { openingFloat: 0 });
  });

  it("refuses when THIS cashier already has a shift open, and never calls the backend", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([shift("s0", "reg-1", "u1")]);
    await expect(openShiftFlow({ openingCash: 10, userId: "u1" })).rejects.toThrow("هناك وردية مفتوحة");
    expect(pos.openSession).not.toHaveBeenCalled();
  });

  it("another cashier's open shift on the first drawer does NOT block me, I get the free one", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([shift("s0", "reg-1", "someone-else")]);
    await openShiftFlow({ openingCash: 5, userId: "u1" });
    expect(pos.openSession).toHaveBeenCalledWith("reg-2", { openingFloat: 5 });
  });

  it("two free drawers and no pick: asks instead of guessing, backend untouched", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([]);
    await expect(openShiftFlow({ openingCash: 5, userId: "u1" })).rejects.toMatchObject({ code: "register_required" });
    expect(pos.openSession).not.toHaveBeenCalled();
  });

  it("two free drawers and an explicit pick: opens exactly the picked one", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([]);
    await openShiftFlow({ openingCash: 5, userId: "u1", registerId: "reg-2" });
    expect(pos.openSession).toHaveBeenCalledWith("reg-2", { openingFloat: 5 });
  });

  it("a pick that became busy meanwhile is refused with a clear message", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([shift("s9", "reg-2", "other")]);
    await expect(openShiftFlow({ openingCash: 5, userId: "u1", registerId: "reg-2" })).rejects.toThrow("لم يعد متاحًا");
    expect(pos.openSession).not.toHaveBeenCalled();
  });

  it("every drawer busy: says so", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1")]);
    pos.listSessions.mockResolvedValue([shift("s9", "reg-1", "other")]);
    await expect(openShiftFlow({ openingCash: 5, userId: "u1" })).rejects.toThrow("كل أجهزة الكاشير");
    expect(pos.openSession).not.toHaveBeenCalled();
  });

  it("a forbidden read is surfaced, not turned into a blind open attempt", async () => {
    pos.listRegisters.mockRejectedValue(Object.assign(new Error("nope"), { status: 403 }));
    pos.listSessions.mockResolvedValue([]);
    await expect(openShiftFlow({ openingCash: 10, userId: "u1" })).rejects.toThrow("صلاحية");
    expect(pos.openSession).not.toHaveBeenCalled();
  });
});
