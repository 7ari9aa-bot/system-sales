import { describe, expect, it, vi } from "vitest";
import { createSaveGuard, saveButtonState } from "./saveOnce";

describe("createSaveGuard", () => {
  it("turns two quick presses into one save", async () => {
    let release;
    const save = vi.fn(() => new Promise((resolve) => { release = resolve; }));
    const guarded = createSaveGuard(save);

    const first = guarded({ name: "تيشيرت" });
    const second = guarded({ name: "تيشيرت" });
    expect(save).toHaveBeenCalledTimes(1);
    expect(second).toBe(first);

    release("ok");
    await expect(first).resolves.toBe("ok");
    await expect(second).resolves.toBe("ok");
  });

  it("saves again after the first one finished, so a real retry is not blocked", async () => {
    const save = vi.fn(async () => "ok");
    const guarded = createSaveGuard(save);
    await guarded();
    await guarded();
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("frees the guard when the save fails, so the merchant can try again", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce("ok");
    const guarded = createSaveGuard(save);
    await expect(guarded()).rejects.toThrow("offline");
    await expect(guarded()).resolves.toBe("ok");
  });
});

describe("saveButtonState", () => {
  it("locks the button while saving and says so", () => {
    expect(saveButtonState({ isSaving: true })).toEqual({ disabled: true, label: "جاري الحفظ…" });
  });
  it("keeps it locked when the form is not ready, and normal otherwise", () => {
    expect(saveButtonState({ canSave: false }).disabled).toBe(true);
    expect(saveButtonState({})).toEqual({ disabled: false, label: "حفظ المنتج" });
  });
});
