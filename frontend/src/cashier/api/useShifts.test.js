import { describe, expect, it, vi, beforeEach } from "vitest";

const { pos, state } = vi.hoisted(() => ({
  pos: { openSession: vi.fn(), closeSession: vi.fn() },
  state: { resolveShiftState: vi.fn(), bootstrapPos: vi.fn() },
}));
vi.mock("./posApi", () => ({ posApi: pos }));
vi.mock("./shiftState", () => state);

import { openShiftFlow } from "./useShifts";

beforeEach(() => vi.clearAllMocks());

describe("openShiftFlow (what the Open Shift button does)", () => {
  it("brand-new shop: bootstraps the till FIRST, then opens on the register that bootstrap returned", async () => {
    state.resolveShiftState.mockResolvedValue({ status: "needs_setup", who: "self" });
    state.bootstrapPos.mockResolvedValue({ id: "reg-new" }); // bootstrapPos returns the register itself
    pos.openSession.mockResolvedValue({ id: "s1" });
    await openShiftFlow({ openingCash: 150 });
    expect(state.bootstrapPos).toHaveBeenCalledTimes(1);
    expect(pos.openSession).toHaveBeenCalledWith("reg-new", { openingFloat: 150 });
  });

  it("configured shop: does not bootstrap again", async () => {
    state.resolveShiftState.mockResolvedValue({ status: "no_open_shift", register: { id: "reg-1" } });
    pos.openSession.mockResolvedValue({ id: "s1" });
    await openShiftFlow({ openingCash: 0 });
    expect(state.bootstrapPos).not.toHaveBeenCalled();
    expect(pos.openSession).toHaveBeenCalledWith("reg-1", { openingFloat: 0 });
  });

  it("refuses when a shift is already open, and never calls the backend", async () => {
    state.resolveShiftState.mockResolvedValue({ status: "open", register: { id: "reg-1" }, session: { id: "s0" } });
    await expect(openShiftFlow({ openingCash: 10 })).rejects.toThrow();
    expect(pos.openSession).not.toHaveBeenCalled();
  });

  it("a forbidden/error state is surfaced, not turned into a blind open attempt", async () => {
    state.resolveShiftState.mockResolvedValue({ status: "forbidden" });
    await expect(openShiftFlow({ openingCash: 10 })).rejects.toThrow();
    expect(pos.openSession).not.toHaveBeenCalled();
  });
});
