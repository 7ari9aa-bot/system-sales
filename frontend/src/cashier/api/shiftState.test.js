import { beforeEach, describe, expect, it, vi } from "vitest";

const { pos, api } = vi.hoisted(() => ({
  pos: {
    listRegisters: vi.fn(),
    listProfiles: vi.fn(),
    listSessions: vi.fn(),
    getSession: vi.fn(),
    workingSession: vi.fn(),
    openDay: vi.fn(),
  },
  api: vi.fn(),
}));
vi.mock("./posApi", () => ({ posApi: pos }));
vi.mock("@/lib/api", () => ({ api }));

import { bootstrapPos, chooseRegister, parseOpeningBalance, pickMyShift, resolveShiftState, resolveWorkingSession, startDay } from "./shiftState";

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

  it("the till it sets up sells in cash only", async () => {
    pos.listProfiles.mockResolvedValue([]);
    pos.listRegisters.mockResolvedValue([]);
    api.mockImplementation(async (path, opts = {}) => {
      if (path === "/warehouses/ensure-default") return { id: "w1", is_active: true };
      if (path === "/pos/profiles" && opts.method === "POST") return { id: "p1" };
      if (path === "/pos/registers" && opts.method === "POST") return { ...REG };
      throw new Error(`unexpected ${path}`);
    });
    await bootstrapPos();
    const body = api.mock.calls.find(([p, o]) => p === "/pos/profiles" && o?.method === "POST")[1].body;
    expect(body.allowed_payment_methods).toEqual(["cash"]);
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

describe("chooseRegister (which drawer a cashier may open a shift on)", () => {
  const R = (id, extra = {}) => ({ id, is_active: true, ...extra });
  const S = (registerId, status = "OPEN") => ({ register_id: registerId, status });

  it("no active drawer", () => {
    expect(chooseRegister([], [])).toEqual({ status: "none", reason: "no_register" });
    expect(chooseRegister([R("a", { is_active: false })], [])).toEqual({ status: "none", reason: "no_register" });
    expect(chooseRegister(null, null)).toEqual({ status: "none", reason: "no_register" });
  });
  it("a single free drawer is taken without asking", () => {
    expect(chooseRegister([R("a")], [])).toMatchObject({ status: "ok", register: { id: "a" } });
  });
  it("busy drawers are skipped; the one free drawer is taken", () => {
    expect(chooseRegister([R("a"), R("b")], [S("a")])).toMatchObject({ status: "ok", register: { id: "b" } });
  });
  it("a closed shift does not make a drawer busy", () => {
    expect(chooseRegister([R("a")], [S("a", "CLOSED")])).toMatchObject({ status: "ok", register: { id: "a" } });
  });
  it("several free drawers: the cashier must choose, listing only the free ones", () => {
    const r = chooseRegister([R("a"), R("b"), R("c")], [S("b")]);
    expect(r.status).toBe("choose");
    expect(r.free.map((x) => x.id)).toEqual(["a", "c"]);
  });
  it("an explicit pick is honoured when free, refused when busy or unknown", () => {
    expect(chooseRegister([R("a"), R("b")], [], "b")).toMatchObject({ status: "ok", register: { id: "b" } });
    expect(chooseRegister([R("a"), R("b")], [S("b")], "b")).toEqual({ status: "none", reason: "picked_unavailable" });
    expect(chooseRegister([R("a"), R("b")], [], "zzz")).toEqual({ status: "none", reason: "picked_unavailable" });
  });
  it("every drawer busy", () => {
    expect(chooseRegister([R("a"), R("b")], [S("a"), S("b")])).toEqual({ status: "none", reason: "all_busy" });
  });
  it("an inactive drawer is never offered", () => {
    expect(chooseRegister([R("a", { is_active: false }), R("b")], [])).toMatchObject({ status: "ok", register: { id: "b" } });
  });
});

describe("resolveWorkingSession: the till without a shift", () => {
  it("one active register => its working session, asked from the server (never a shift screen)", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.workingSession.mockResolvedValue({ started: true, session: SESSION });
    const s = await resolveWorkingSession({ canConfigure: false });
    expect(s).toEqual({ status: "open", register: REG, session: SESSION });
    expect(pos.workingSession).toHaveBeenCalledWith("r1");
    expect(pos.listSessions).not.toHaveBeenCalled();
  });

  it("the day not started => needs_opening: looking at the till never opens it", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.workingSession.mockResolvedValue({ started: false, session: null });
    expect(await resolveWorkingSession({})).toEqual({ status: "needs_opening", register: REG });
    expect(pos.openDay).not.toHaveBeenCalled();
  });

  it("no register => needs_setup, and nothing is opened", async () => {
    pos.listRegisters.mockResolvedValue([]);
    expect(await resolveWorkingSession({ canConfigure: false })).toMatchObject({ status: "needs_setup", who: "manager" });
    expect(await resolveWorkingSession({ canConfigure: true })).toMatchObject({ status: "needs_setup", who: "self" });
    expect(pos.workingSession).not.toHaveBeenCalled();
  });

  it("several active registers => the cashier is asked to choose; the first one is NEVER guessed", async () => {
    const r2 = { ...REG, id: "r2", code: "B" };
    pos.listRegisters.mockResolvedValue([REG, r2]);
    const s = await resolveWorkingSession({});
    expect(s).toMatchObject({ status: "choose" });
    expect(s.registers.map((r) => r.id)).toEqual(["r1", "r2"]);
    expect(pos.workingSession).not.toHaveBeenCalled();
  });

  it("an explicit pick among several is honoured; an unknown pick is refused, not replaced", async () => {
    const r2 = { ...REG, id: "r2", code: "B" };
    pos.listRegisters.mockResolvedValue([REG, r2]);
    pos.workingSession.mockResolvedValue({ started: true, session: { ...SESSION, id: "s2", register_id: "r2" } });
    expect(await resolveWorkingSession({ registerId: "r2" })).toMatchObject({ status: "open", register: { id: "r2" } });
    expect(pos.workingSession).toHaveBeenCalledWith("r2");
    pos.workingSession.mockClear();
    expect(await resolveWorkingSession({ registerId: "gone" })).toMatchObject({ status: "choose" });
    expect(pos.workingSession).not.toHaveBeenCalled();
  });

  it("inactive registers are ignored", async () => {
    pos.listRegisters.mockResolvedValue([{ ...REG, id: "old", is_active: false }, REG]);
    pos.workingSession.mockResolvedValue({ started: true, session: SESSION });
    expect(await resolveWorkingSession({})).toMatchObject({ status: "open", register: { id: "r1" } });
  });

  it("403 => forbidden, 401 => unauthorized, network => retryable error", async () => {
    pos.listRegisters.mockResolvedValue([REG]);
    pos.workingSession.mockRejectedValueOnce(Object.assign(new Error("no"), { status: 403 }));
    expect(await resolveWorkingSession({})).toEqual({ status: "forbidden" });
    pos.workingSession.mockRejectedValueOnce(Object.assign(new Error("no"), { status: 401 }));
    expect(await resolveWorkingSession({})).toEqual({ status: "unauthorized" });
    pos.workingSession.mockRejectedValueOnce(Object.assign(new Error("down"), { status: 0 }));
    expect(await resolveWorkingSession({})).toMatchObject({ status: "error", retryable: true });
  });
});

describe("opening balance: required, and checked before any request", () => {
  it("accepts a cash amount in Western or Arabic digits and either decimal mark", () => {
    expect(parseOpeningBalance("250")).toBe("250");
    expect(parseOpeningBalance(" 250.50 ")).toBe("250.50");
    expect(parseOpeningBalance("250,5")).toBe("250.5");
    expect(parseOpeningBalance("٢٥٠٫٥٠")).toBe("250.50");
    expect(parseOpeningBalance("0")).toBe("0");
  });

  it("refuses blank, negative, text and too many decimals", () => {
    for (const bad of ["", "   ", null, undefined, "-5", "abc", "12.345", "1e3", "1,000.50", "--"]) {
      expect(parseOpeningBalance(bad)).toBeNull();
    }
  });

  it("startDay sends the cleaned balance and returns the session", async () => {
    pos.openDay.mockResolvedValue({ started: true, session: SESSION });
    expect(await startDay("r1", "٢٥٠٫٥٠")).toEqual(SESSION);
    expect(pos.openDay).toHaveBeenCalledWith("r1", "250.50");
  });

  it("startDay with no valid balance throws and makes NO request", async () => {
    pos.openDay.mockClear();
    await expect(startDay("r1", "")).rejects.toThrow(/رصيد الدرج/);
    await expect(startDay("r1", "-1")).rejects.toThrow();
    expect(pos.openDay).not.toHaveBeenCalled();
  });
});
