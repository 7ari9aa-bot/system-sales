import { describe, expect, it, vi } from "vitest";
import { approvalFailure, approvalReason, needsApproval, pinProblem, runWithApproval } from "./approval";
import { newIntent } from "./posApi";

const asked = Object.assign(new Error("x"), { code: "approval_required", details: { limit: "refund", ceiling: "40.00" } });

describe("needsApproval", () => {
  it("goes by the code, never by the wording", () => {
    expect(needsApproval(asked)).toBe(true);
    expect(needsApproval(Object.assign(new Error("needs a manager's approval"), { code: "validation_error" }))).toBe(false);
    expect(needsApproval(null)).toBe(false);
  });
});

describe("approvalReason", () => {
  it("names the limit and the amount", () => {
    expect(approvalReason(asked)).toBe("المرتجع أكبر من الحد المسموح للكاشير (40.00)");
    expect(approvalReason({ details: { limit: "discount", ceiling: "10.00" } })).toContain("(10.00%)");
  });
  it("falls back to the server's message for a limit it does not know", () => {
    expect(approvalReason({ message: "no", details: { limit: "future" } })).toBe("no");
  });
});

describe("pinProblem", () => {
  it("accepts 4-8 ascii digits only", () => {
    expect(pinProblem("4821")).toBeNull();
    expect(pinProblem("")).toMatch(/اكتب/);
    expect(pinProblem("123")).not.toBeNull();
    expect(pinProblem("123456789")).not.toBeNull();
    expect(pinProblem("٤٨٢١")).not.toBeNull(); // Arabic-Indic digits are refused, like the server
    expect(pinProblem("48 21")).not.toBeNull();
  });
});

describe("runWithApproval", () => {
  it("passes a success straight through", async () => {
    const call = vi.fn(async () => ({ id: 1 }));
    expect(await runWithApproval(call, newIntent())).toEqual({ ok: true, data: { id: 1 } });
  });

  it("reports needsApproval instead of throwing, so the screen can open the dialog", async () => {
    const call = vi.fn(async () => { throw asked; });
    const r = await runWithApproval(call, newIntent());
    expect(r).toMatchObject({ ok: false, needsApproval: true });
    expect(r.error).toBe(asked);
  });

  it("the retry carries the PIN on the SAME idempotency key", async () => {
    const seen = [];
    const call = vi.fn(async (intent) => {
      seen.push(intent);
      if (!intent.approval) throw asked;
      return { ok: 1 };
    });
    const intent = newIntent();
    await runWithApproval(call, intent);
    const done = await runWithApproval(call, intent, { managerId: "m1", pin: "4821" });
    expect(done.ok).toBe(true);
    expect(seen[1].key).toBe(seen[0].key);
    expect(seen[1].approval).toEqual({ managerId: "m1", pin: "4821" });
  });

  it("does not ask twice: a refusal even WITH a PIN is a real error", async () => {
    const call = vi.fn(async () => { throw asked; });
    await expect(runWithApproval(call, newIntent(), { managerId: "m", pin: "4821" })).rejects.toBe(asked);
  });

  it("any other error is thrown untouched", async () => {
    const boom = Object.assign(new Error("boom"), { code: "conflict" });
    await expect(runWithApproval(async () => { throw boom; }, newIntent())).rejects.toBe(boom);
  });
});

describe("approvalFailure", () => {
  it("never says WHY the manager was refused", () => {
    const m = approvalFailure({ status: 403, message: "manager approval refused" });
    expect(m).toContain("PIN");
    expect(m).not.toMatch(/صلاحية|locked|مقفول/);
  });
  it("tells a locked-out cashier to wait, and passes other errors through", () => {
    expect(approvalFailure({ status: 429 })).toMatch(/انتظر/);
    expect(approvalFailure({ status: 500, message: "boom" })).toBe("boom");
  });
});
