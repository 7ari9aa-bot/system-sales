import { beforeEach, describe, expect, it, vi } from "vitest";

const { pos, api } = vi.hoisted(() => ({
  pos: {
    listRegisters: vi.fn(),
    listProfiles: vi.fn(),
    listSessions: vi.fn(),
    getSession: vi.fn(),
  },
  api: vi.fn(),
}));
vi.mock("./posApi", () => ({ posApi: pos }));
vi.mock("@/lib/api", () => ({ api }));

import { bootstrapPos, pickMyShift, resolveShiftState } from "./shiftState";

const REG = { id: "r1", code: "MAIN", name: "Main", is_active: true, warehouse_id: "w1", profile_id: "p1" };
const SESSION = { id: "s1", register_id: "r1", status: "OPEN", opening_float: "100.00" };

beforeEach(() => {
  Object.values(pos).forEach((f) => f.mockReset());
  api.mockReset();
});

describe("resolveShiftState", () => {
  it("no register + cannot configure => needs_setup/ask_manager (a cashier cannot create one)", async () => {
    pos.listRegisters.mockResolvedValue([]);
    const s = await resolveShiftState({ canConfigure: false });
    expect(s).toMatchObject({ status: "needs_setup", who: "manager" });
  });

  it("no register + can configure => needs_setup/can_setup", async () => {
    pos.listRegisters.mockResolvedValue([]);
    const s = await resolveShiftState({ canConfigure: true });
    expect(s).toMatchObject({ status: "needs_setup", who: "self" });
  });

  it("only inactive registers count as not set up", async () => {
    pos.listRegisters.mockResolvedValue([{ ...REG, is_active: false }]);
    expect((await resolveShiftState({ canConfigure: false })).status).toBe("needs_setup");
  });

  it("register but no open session => no_open_shift, carries the register to open on", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.listSessions.mockResolvedValue([]);
    const s = await resolveShiftState({ canConfigure: false });
    expect(s).toMatchObject({ status: "no_open_shift", register: REG });
    expect(pos.listSessions).toHaveBeenCalledWith("status=OPEN&register_id=r1");
  });

  it("an OPEN session on the register => open, with that session", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.listSessions.mockResolvedValue([SESSION]);
    pos.getSession.mockResolvedValue({ ...SESSION, inflow: "0.00", outflow: "0.00", expected_now: "100.00" });
    const s = await resolveShiftState({ canConfigure: false });
    expect(s.status).toBe("open");
    expect(s.session.id).toBe("s1");
    expect(s.session.expected_now).toBe("100.00");
  });

  it("a CLOSED session is never treated as open", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.listSessions.mockResolvedValue([{ ...SESSION, status: "CLOSED" }]);
    expect((await resolveShiftState({ canConfigure: false })).status).toBe("no_open_shift");
  });

  it("only the session of THIS register counts", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.listSessions.mockResolvedValue([{ ...SESSION, register_id: "other" }]);
    expect((await resolveShiftState({ canConfigure: false })).status).toBe("no_open_shift");
  });

  it("a backend failure is an error state, never a silent 'no shift'", async () => {
    pos.listRegisters.mockRejectedValue(Object.assign(new Error("boom"), { status: 500 }));
    const s = await resolveShiftState({ canConfigure: false });
    expect(s).toMatchObject({ status: "error", retryable: true });
  });

  it("403 on reading registers => forbidden (not 'needs setup')", async () => {
    pos.listRegisters.mockRejectedValue(Object.assign(new Error("no"), { status: 403 }));
    expect((await resolveShiftState({ canConfigure: false })).status).toBe("forbidden");
  });
});

describe("bootstrapPos (manager only, idempotent)", () => {
  it("creates warehouse-bound profile then register with fixed codes", async () => {
    pos.listProfiles.mockResolvedValue([]);
    pos.listRegisters.mockResolvedValue([]);
    api.mockImplementation(async (path, opts = {}) => {
      if (path === "/warehouses/ensure-default") return { id: "w1", is_active: true };
      if (path === "/pos/profiles" && opts.method === "POST") return { id: "p1" };
      if (path === "/pos/registers" && opts.method === "POST") return { ...REG };
      throw new Error(`unexpected ${path}`);
    });
    const reg = await bootstrapPos();
    expect(reg.id).toBe("r1");
    const bodyOf = (path) => api.mock.calls.find(([p, o]) => p === path && o?.method === "POST")[1].body;
    expect(bodyOf("/pos/profiles")).toMatchObject({ code: "MAIN", warehouse_id: "w1" });
    expect(bodyOf("/pos/registers")).toMatchObject({ code: "MAIN", warehouse_id: "w1", profile_id: "p1" });
  });

  it("works on a brand-new shop: the warehouse comes from ensure-default, not from a list", async () => {
    pos.listRegisters.mockResolvedValue([]);
    pos.listProfiles.mockResolvedValue([]);
    api.mockImplementation(async (path, opts = {}) => {
      if (path === "/warehouses/ensure-default" && opts.method === "POST") return { id: "w-new", is_active: true };
      if (path === "/pos/profiles") return { id: "p1" };
      if (path === "/pos/registers") return { ...REG, warehouse_id: "w-new" };
      throw new Error(`unexpected ${path}`);
    });
    await bootstrapPos();
    expect(api.mock.calls[0][0]).toBe("/warehouses/ensure-default");
    expect(api.mock.calls.some(([p]) => p === "/warehouses")).toBe(false);
  });

  it("surfaces a clear error if the warehouse cannot be prepared", async () => {
    pos.listRegisters.mockResolvedValue([]);
    api.mockResolvedValue({});
    await expect(bootstrapPos()).rejects.toThrow(/warehouse/i);
  });

  it("is a no-op when a register already exists (safe to click twice)", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    const reg = await bootstrapPos();
    expect(reg).toEqual(REG);
    expect(api).not.toHaveBeenCalled();
  });

  it("reuses an existing MAIN profile instead of creating a duplicate", async () => {
    pos.listRegisters.mockResolvedValue([]);
    pos.listProfiles.mockResolvedValue([{ id: "p9", code: "MAIN", is_active: true }]);
    api.mockImplementation(async (path, opts = {}) => {
      if (path === "/warehouses/ensure-default") return { id: "w1", is_active: true };
      if (path === "/pos/registers" && opts.method === "POST") return { ...REG, profile_id: "p9" };
      throw new Error(`unexpected ${path}`);
    });
    await bootstrapPos();
    expect(api.mock.calls.some(([p, o]) => p === "/pos/profiles" && o?.method === "POST")).toBe(false);
    const regPost = api.mock.calls.find(([p, o]) => p === "/pos/registers" && o?.method === "POST");
    expect(regPost[1].body.profile_id).toBe("p9");
  });
});

describe("a drawer per cashier", () => {
  const REG2 = { ...REG, id: "r2", code: "SECOND" };
  const mine = { id: "s-mine", register_id: "r2", status: "OPEN", cashier_user_id: "u-me" };
  const theirs = { id: "s-theirs", register_id: "r1", status: "OPEN", cashier_user_id: "u-other" };

  it("pickMyShift never returns somebody else's shift", () => {
    expect(pickMyShift([theirs, mine], "u-me")).toBe(mine);
    expect(pickMyShift([theirs], "u-me")).toBeNull();
    expect(pickMyShift([mine], null)).toBeNull();
    expect(pickMyShift([{ ...mine, status: "CLOSED" }], "u-me")).toBeNull();
  });

  it("lands on MY open drawer even when another cashier's register comes first", async () => {
    pos.listRegisters.mockResolvedValue([REG, REG2]);
    pos.listSessions.mockResolvedValue([theirs, mine]);
    pos.getSession.mockResolvedValue({ ...mine, expected_now: "0.00" });
    const s = await resolveShiftState({ userId: "u-me" });
    expect(s).toMatchObject({ status: "open", register: { id: "r2" }, session: { id: "s-mine" } });
    expect(pos.getSession).toHaveBeenCalledWith("s-mine");
  });

  it("with no shift of my own it falls back to the first register, as before", async () => {
    pos.listRegisters.mockResolvedValue([REG, REG2]);
    pos.listSessions.mockResolvedValueOnce([theirs]).mockResolvedValueOnce([]);
    const s = await resolveShiftState({ userId: "u-me" });
    expect(s).toMatchObject({ status: "no_open_shift", register: { id: "r1" } });
  });
});
