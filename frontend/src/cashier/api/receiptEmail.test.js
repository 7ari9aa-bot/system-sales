import { beforeEach, describe, expect, it, vi } from "vitest";

const calls = [];
vi.mock("@/lib/api", () => ({
  api: vi.fn(async (path, opts = {}) => {
    calls.push({ path, ...opts });
    return { receipt_id: "r1", status: "queued" };
  }),
}));

import { posApi } from "./posApi";
import { receiptEmailProblem, validReceiptEmail } from "./receiptEmail";

beforeEach(() => {
  calls.length = 0;
});

describe("emailing a receipt", () => {
  it("posts the trimmed address to the receipt's email route", async () => {
    await posApi.emailReceipt("rc-1", "  buyer@example.com ");
    expect(calls[0].path).toBe("/pos/receipts/rc-1/email");
    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toEqual({ email: "buyer@example.com" });
  });

  it("refuses an address that is not one address, before any request", async () => {
    for (const bad of ["", "   ", "a@b", "no-at.com", "a@b.com,c@d.com", "a,b@c.com", "a;b@c.com", "a b@c.com", "x@y.com\nBcc: z@w.com"]) {
      expect(() => posApi.emailReceipt("rc-1", bad), bad).toThrow(/email/i);
    }
    expect(calls).toHaveLength(0);
  });

  it("validReceiptEmail accepts ordinary addresses only", () => {
    expect(validReceiptEmail("ali.hassan+shop@mail.example.com")).toBe(true);
    expect(validReceiptEmail("a@b")).toBe(false);
    expect(validReceiptEmail("a@b.com,c@d.com")).toBe(false);
  });
});

describe("what the cashier reads when it does not work", () => {
  it("names the shop-level cause in Arabic, never the server's English", () => {
    expect(receiptEmailProblem({ message: "email delivery is not configured on this deployment" })).toMatch(/غير مفعّل/);
    expect(receiptEmailProblem({ status: 429, message: "too many" })).toMatch(/بكرة/);
    expect(receiptEmailProblem({ status: 429, message: "too many" })).not.toMatch(/بعد شوية/);
    expect(receiptEmailProblem({ message: "whatever else" })).toMatch(/تعذّر/);
    for (const m of ["email delivery is not configured", "x", ""]) {
      expect(receiptEmailProblem({ message: m })).not.toMatch(/[A-Za-z]{4,}/);
    }
  });
});

import { submitReceiptEmail } from "./receiptEmail";

describe("submitReceiptEmail", () => {
  it("sends once and says it was sent", async () => {
    const send = vi.fn().mockResolvedValue({});
    const out = await submitReceiptEmail(send, "rc-1", " a@b.com ");
    expect(send).toHaveBeenCalledExactlyOnceWith("rc-1", "a@b.com");
    expect(out).toEqual({ ok: true, message: "اتبعت الإيصال للإيميل." });
  });

  it("does not call the server for a bad address or an unsaved receipt", async () => {
    const send = vi.fn();
    expect((await submitReceiptEmail(send, "rc-1", "a@b")).ok).toBe(false);
    expect((await submitReceiptEmail(send, "", "a@b.com")).ok).toBe(false);
    expect(send).not.toHaveBeenCalled();
  });

  it("turns a server refusal into the Arabic cause and never throws", async () => {
    const send = vi.fn().mockRejectedValue(Object.assign(new Error("email delivery is not configured on this deployment"), { status: 422 }));
    const out = await submitReceiptEmail(send, "rc-1", "a@b.com");
    expect(out.ok).toBe(false);
    expect(out.message).toMatch(/غير مفعّل/);
  });
});
