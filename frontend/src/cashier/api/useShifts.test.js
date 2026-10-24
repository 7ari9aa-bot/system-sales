import { describe, expect, it, vi, beforeEach } from "vitest";

const { pos, boot } = vi.hoisted(() => ({
  pos: { openDay: vi.fn(), closeSession: vi.fn(), listRegisters: vi.fn(), listSessions: vi.fn() },
  boot: vi.fn(),
}));
vi.mock("./posApi", () => ({ posApi: pos }));
// the pure rules (chooseRegister, startDay) stay REAL; only the network-touching bootstrap is replaced
vi.mock("./shiftState", async (orig) => ({ ...(await orig()), bootstrapPos: boot, resolveShiftState: vi.fn() }));

import { openShiftFlow } from "./useShifts";

const reg = (id, extra = {}) => ({ id, name: `Till ${id}`, code: id, is_active: true, ...extra });
// An open day carries no cashier: it belongs to the register.
const day = (id, registerId) => ({ id, register_id: registerId, cashier_user_id: null, status: "OPEN" });

beforeEach(() => {
  vi.clearAllMocks();
  pos.openDay.mockResolvedValue({ started: true, session: { id: "s-new" } });
});

describe("openShiftFlow (what the Start Day button does)", () => {
  it("brand-new shop: bootstraps the till FIRST, then starts the day on the register that bootstrap returned", async () => {
    pos.listRegisters.mockResolvedValue([]);
    pos.listSessions.mockResolvedValue([]);
    boot.mockResolvedValue({ id: "reg-new" });
    await openShiftFlow({ openingCash: "150" });
    expect(boot).toHaveBeenCalledTimes(1);
    expect(pos.openDay).toHaveBeenCalledWith("reg-new", "150");
  });

  it("one-till shop: starts the day on it without asking, and does not bootstrap again", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1")]);
    pos.listSessions.mockResolvedValue([]);
    await openShiftFlow({ openingCash: "0" });
    expect(boot).not.toHaveBeenCalled();
    expect(pos.openDay).toHaveBeenCalledWith("reg-1", "0");
  });

  it("the balance is REQUIRED: blank or invalid never reaches the server", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1")]);
    pos.listSessions.mockResolvedValue([]);
    for (const bad of [undefined, null, "", "  ", "-3", "abc"]) {
      await expect(openShiftFlow({ openingCash: bad })).rejects.toThrow(/رصيد الدرج/);
    }
    expect(pos.openDay).not.toHaveBeenCalled();
  });

  it("a register whose day is already running is not offered again; the free one is taken", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([day("s0", "reg-1")]);
    await openShiftFlow({ openingCash: "5" });
    expect(pos.openDay).toHaveBeenCalledWith("reg-2", "5");
  });

  it("two free registers and no pick: asks instead of guessing, backend untouched", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([]);
    await expect(openShiftFlow({ openingCash: "5" })).rejects.toMatchObject({ code: "register_required" });
    expect(pos.openDay).not.toHaveBeenCalled();
  });

  it("two free registers and an explicit pick: starts exactly the picked one", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([]);
    await openShiftFlow({ openingCash: "5", registerId: "reg-2" });
    expect(pos.openDay).toHaveBeenCalledWith("reg-2", "5");
  });

  it("a pick whose day started meanwhile is refused with a clear message", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1"), reg("reg-2")]);
    pos.listSessions.mockResolvedValue([day("s9", "reg-2")]);
    await expect(openShiftFlow({ openingCash: "5", registerId: "reg-2" })).rejects.toThrow("لم يعد متاحًا");
    expect(pos.openDay).not.toHaveBeenCalled();
  });

  it("every register already running a day: says so", async () => {
    pos.listRegisters.mockResolvedValue([reg("reg-1")]);
    pos.listSessions.mockResolvedValue([day("s9", "reg-1")]);
    await expect(openShiftFlow({ openingCash: "5" })).rejects.toThrow("كل أجهزة الكاشير");
    expect(pos.openDay).not.toHaveBeenCalled();
  });

  it("a forbidden read is surfaced, not turned into a blind attempt", async () => {
    pos.listRegisters.mockRejectedValue(Object.assign(new Error("nope"), { status: 403 }));
    pos.listSessions.mockResolvedValue([]);
    await expect(openShiftFlow({ openingCash: "10" })).rejects.toThrow("صلاحية");
    expect(pos.openDay).not.toHaveBeenCalled();
  });
});
