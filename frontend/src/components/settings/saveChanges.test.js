import { describe, expect, test, vi } from "vitest";
import { applySave } from "@/components/settings/saveChanges";

/**
 * One Save, two requests, two independent outcomes.
 *
 * The bug this pins: the bulk write landed, the change-request call then failed, and the
 * screen reported "could not save" — for an edit that was stored — while the saved keys stayed
 * dirty and a retry re-sent them with stale revisions and got a 409.
 */
const okBulk = () => vi.fn().mockResolvedValue({});
const failOn = (path, error) =>
  vi.fn().mockImplementation((calledPath) =>
    calledPath === path ? Promise.reject(error) : Promise.resolve({ id: "req-1" })
  );

describe("applySave", () => {
  test("both halves land: saved and pending, no error", async () => {
    const api = vi.fn().mockResolvedValue({ id: "req-1" });
    const result = await applySave({
      api,
      direct: { "business.phone": "0100" },
      needsApproval: { "pos.return_max_days": 14 },
      scope: "tenant",
    });

    expect(result.saved).toEqual(["business.phone"]);
    expect(result.pending).toEqual(["pos.return_max_days"]);
    expect(result.failed).toEqual([]);
    expect(result.error).toBeNull();
    expect(api).toHaveBeenCalledTimes(2);
    // The direct write carries the scope, so a branch save cannot land tenant-wide.
    expect(api.mock.calls[0][1].body.scope).toBe("tenant");
  });

  test("the request half failing does NOT undo the saved half", async () => {
    const error = new Error("change request refused");
    const api = failOn("/settings/change-requests", error);
    const result = await applySave({
      api,
      direct: { "business.phone": "0100" },
      needsApproval: { "pos.return_max_days": 14 },
      scope: "tenant",
    });

    expect(result.saved).toEqual(["business.phone"]);
    expect(result.pending).toEqual([]);
    expect(result.failed).toEqual(["pos.return_max_days"]);
    expect(result.errorPhase).toBe("request");
    expect(result.error).toBe(error);
  });

  test("the direct half failing stops before filing a request for values nobody saved", async () => {
    const error = new Error("409 conflict");
    const api = failOn("/settings/bulk", error);
    const result = await applySave({
      api,
      direct: { "business.phone": "0100" },
      needsApproval: { "pos.return_max_days": 14 },
      scope: "tenant",
    });

    expect(result.saved).toEqual([]);
    expect(result.failed).toEqual(["business.phone"]);
    expect(result.errorPhase).toBe("direct");
    // Only the bulk call was attempted: a change request would have approved a screen that
    // never stored its direct edits.
    expect(api).toHaveBeenCalledTimes(1);
  });

  test("expected revisions travel with the direct write, including the null of a fresh key", async () => {
    const api = okBulk();
    await applySave({
      api,
      direct: { "business.phone": "0100" },
      scope: "branch",
      scopeId: "b-1",
      expectedIds: { "business.phone": null },
    });

    const body = api.mock.calls[0][1].body;
    expect(body.scope_id).toBe("b-1");
    expect(body.expected_history_ids).toEqual({ "business.phone": null });
  });
});
